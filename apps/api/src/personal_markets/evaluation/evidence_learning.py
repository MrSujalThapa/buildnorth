"""How forecast quality changes as a person's own evidence arrives.

Models are fit on train rows only. Shrinkage strength is chosen on validation.
The calibration split fits probability calibration. Test rows are scored once.

Activity features must already be limited to events at or before `checkpoint_day`.
This module does not read raw event logs and cannot see a later checkpoint's clicks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from personal_markets.evaluation.metrics import brier_score, expected_calibration_error, log_loss
from personal_markets.forecasting.models import (
    CATEGORICAL,
    ProbabilityCalibrator,
    build_model,
    feature_columns,
    logistic_contributions,
    split_xy,
)

SEED = 20260828
HALF_LIFE_DAYS = 14
MODEL_VERSION = "evidence-learning-v1"
DATASET_ID = "oulad_completion_v1"
DOMAIN = "oulad_module_completion"
PRIOR_STRENGTHS = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
# Exposure score below this, and above zero, is labeled sparse. It is not a sample-size estimate.
SPARSE_EFFECTIVE_BELOW = 2.0
STATIC_COLUMNS = [
    *CATEGORICAL,
    "num_of_prev_attempts",
    "studied_credits",
    "module_presentation_length",
]
Sufficiency = Literal["population_only", "sparse", "adequate"]
CalibrationStatus = Literal["not_applicable", "uncalibrated", "calibration_split"]


@dataclass(frozen=True, slots=True)
class EvidenceState:
    n_observations: int
    effective_sample_size: float
    sufficiency: Sufficiency


def evidence_state(submissions: float, active_days: float) -> EvidenceState:
    """Count recorded activity. Missing values count as no observation, not as zero skill."""
    if math.isnan(submissions):
        submissions = 0.0
    if math.isnan(active_days):
        active_days = 0.0
    if submissions < 0 or active_days < 0:
        raise ValueError("evidence counts cannot be negative")
    observed = int(submissions) + int(active_days)
    effective = float(submissions) + math.log1p(active_days)
    if observed == 0:
        sufficiency: Sufficiency = "population_only"
    elif effective < SPARSE_EFFECTIVE_BELOW:
        sufficiency = "sparse"
    else:
        sufficiency = "adequate"
    return EvidenceState(observed, effective, sufficiency)


def shrink_toward_prior(
    probability: float, prior: float, effective_n: float, strength: float
) -> float:
    """Evidence-weighted average of a model probability and the train base rate.

    `strength` is pseudo-counts of the prior. At zero evidence the result is the prior.
    """
    if strength <= 0:
        raise ValueError("prior strength must be positive")
    if not 0 <= probability <= 1 or not 0 <= prior <= 1:
        raise ValueError("probabilities must be in [0, 1]")
    if effective_n < 0:
        raise ValueError("effective sample size cannot be negative")
    weight = effective_n / (effective_n + strength)
    blended = weight * probability + (1.0 - weight) * prior
    return float(min(max(blended, 0.0), 1.0))


def applies_to(domain: str) -> bool:
    return domain == DOMAIN


def assert_group_separation(frame: pd.DataFrame) -> None:
    train_ids = set(frame.loc[frame.split == "train", "id_student"])
    test_ids = set(frame.loc[frame.split == "test", "id_student"])
    overlap = train_ids & test_ids
    if overlap:
        raise ValueError(f"{len(overlap)} students appear in both train and test")


def assert_unique_checkpoints(frame: pd.DataFrame) -> None:
    keys = ["code_module", "code_presentation", "id_student", "checkpoint_day"]
    sizes = frame.groupby(keys, observed=True).size()
    if int(sizes.max()) > 1:
        raise ValueError("duplicate student-module-checkpoint rows")


def assert_no_outcome_leak_columns(frame: pd.DataFrame) -> None:
    banned = {"final_result", "date_unregistration"}
    present = banned & set(frame.columns)
    if present:
        raise ValueError(f"outcome columns cannot be model inputs: {sorted(present)}")


def _clip_metrics(outcomes: np.ndarray, probability: np.ndarray) -> dict[str, Any]:
    y = outcomes.astype(int).tolist()
    p = probability.astype(float).tolist()
    unique = np.unique(np.round(probability.astype(float), 8))
    auc = None
    auc_note = None
    if len(unique) < 2 or len(set(y)) < 2:
        auc_note = "AUC is undefined when the score or the outcome does not vary"
    else:
        auc = float(roc_auc_score(outcomes, probability))
    return {
        "n": int(len(outcomes)),
        "positive_rate": float(np.mean(outcomes)),
        "brier": brier_score(y, p),
        "log_loss": log_loss(y, p),
        "roc_auc": auc,
        "roc_auc_note": auc_note,
        "ece_10": expected_calibration_error(y, p),
    }


def _fit_calibrated(
    family: str,
    columns: list[str],
    train: pd.DataFrame,
    calibration: pd.DataFrame,
) -> tuple[Any, ProbabilityCalibrator, str]:
    model = build_model(family, columns)
    model.fit(*split_xy(train, columns))
    raw_cal = model.predict_proba(calibration[columns])[:, 1]
    method = _select_calibrator(raw_cal, calibration.outcome.to_numpy(dtype=int))
    calibrator = ProbabilityCalibrator.fit(
        method, raw_cal, calibration.outcome.to_numpy(dtype=int)
    )
    return model, calibrator, method


def _select_calibrator(raw: np.ndarray, outcomes: np.ndarray) -> str:
    """Pick Platt or isotonic on an even/odd hash of row order, not on the test set."""
    selector = np.arange(len(raw)) % 2 == 0
    if selector.sum() == 0 or (~selector).sum() == 0 or len(np.unique(outcomes[selector])) < 2:
        return "platt"
    scores: dict[str, float] = {}
    for method in ("platt", "isotonic"):
        calibrator = ProbabilityCalibrator.fit(method, raw[selector], outcomes[selector])
        held = calibrator.predict(raw[~selector])
        scores[method] = brier_score(outcomes[~selector].astype(int).tolist(), held.tolist())
    return min(scores, key=scores.__getitem__)


def _predict(
    model: Any, calibrator: ProbabilityCalibrator, frame: pd.DataFrame, columns: list[str]
) -> np.ndarray:
    raw = model.predict_proba(frame[columns])[:, 1]
    calibrated = calibrator.predict(raw)
    values = [float(np.clip(value, 0.0, 1.0)) for value in calibrated]
    return np.asarray(values, dtype=float)


def _states(frame: pd.DataFrame) -> list[EvidenceState]:
    submissions = frame.get("assessment_submissions", pd.Series(0.0, index=frame.index))
    active = frame.get("vle_active_days", pd.Series(0.0, index=frame.index))
    submitted = submissions.to_numpy(dtype=float)
    active_days = active.to_numpy(dtype=float)
    return [
        evidence_state(float(sub), float(act))
        for sub, act in zip(submitted, active_days, strict=True)
    ]


def select_prior_strength(
    probability: np.ndarray,
    prior: float,
    states: list[EvidenceState],
    outcomes: np.ndarray,
) -> tuple[float, list[dict[str, float]]]:
    best_strength = PRIOR_STRENGTHS[0]
    best_score = math.inf
    table: list[dict[str, float]] = []
    y = outcomes.astype(int).tolist()
    for strength in PRIOR_STRENGTHS:
        shrunk = [
            shrink_toward_prior(float(prob), prior, state.effective_sample_size, strength)
            for prob, state in zip(probability, states, strict=True)
        ]
        score = brier_score(y, shrunk)
        table.append({"prior_strength": strength, "validation_brier": score})
        if score < best_score:
            best_score = score
            best_strength = strength
    return best_strength, table


def explain_forecast(
    *,
    prior: float,
    model_probability: float,
    shrunk_probability: float,
    state: EvidenceState,
    strength: float,
    contributions: list[dict[str, float | str]] | None = None,
) -> dict[str, Any]:
    """Describe the forecast from its inputs. No causal claim is attached."""
    weight = state.effective_sample_size / (state.effective_sample_size + strength)
    expected = shrink_toward_prior(
        model_probability, prior, state.effective_sample_size, strength
    )
    if abs(shrunk_probability - expected) > 1e-9:
        raise ValueError("explanation probability does not match the shrinkage formula")
    return {
        "domain": DOMAIN,
        "applies_outside_domain": False,
        "population_prior": prior,
        "evidence_model_probability": model_probability,
        "shrunk_probability": shrunk_probability,
        "prior_weight": 1.0 - weight,
        "evidence_weight": weight,
        "n_observations": state.n_observations,
        "effective_sample_size": state.effective_sample_size,
        "prior_strength": strength,
        "data_sufficiency": state.sufficiency,
        "calibration_status": "calibration_split",
        "model_version": MODEL_VERSION,
        "training_dataset": DATASET_ID,
        "top_log_odds": (contributions or [])[:5],
        "causal_claim": None,
        "limitations": [
            "Click and assessment associations are not effects of an intervention.",
            "A forecast from this fit applies only to OULAD module completion.",
            "Zero activity is still a model input. It is not automatically the population prior.",
            "Listed log-odds are pre-calibration contributions, not the calibrated probability.",
        ],
    }


def learning_curve(frame: pd.DataFrame) -> dict[str, Any]:
    """Score held-out students at each checkpoint against a frozen train fit."""
    required = {"id_student", "split", "checkpoint_day", "outcome", *STATIC_COLUMNS}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"frame is missing {sorted(missing)}")
    assert_no_outcome_leak_columns(frame)
    assert_group_separation(frame)
    assert_unique_checkpoints(frame)
    evidence_columns = feature_columns(HALF_LIFE_DAYS)
    missing_evidence = [column for column in evidence_columns if column not in frame.columns]
    if missing_evidence:
        raise ValueError(f"frame is missing evidence columns {missing_evidence}")

    train = frame[frame.split == "train"].copy()
    validation = frame[frame.split == "validation"].copy()
    calibration = frame[frame.split == "calibration"].copy()
    test = frame[frame.split == "test"].copy()
    if train.empty or validation.empty or calibration.empty or test.empty:
        raise ValueError("train, validation, calibration, and test splits are all required")

    prior = float(train.outcome.mean())
    static_model, static_cal, static_method = _fit_calibrated(
        "logistic_regression", STATIC_COLUMNS, train, calibration
    )
    evidence_model, evidence_cal, evidence_method = _fit_calibrated(
        "logistic_regression", evidence_columns, train, calibration
    )
    tree_model, tree_cal, tree_method = _fit_calibrated(
        "hist_gradient_boosting", evidence_columns, train, calibration
    )

    validation_probability = _predict(evidence_model, evidence_cal, validation, evidence_columns)
    strength, strength_table = select_prior_strength(
        validation_probability,
        prior,
        _states(validation),
        validation.outcome.to_numpy(),
    )

    checkpoints = sorted(int(value) for value in test.checkpoint_day.unique())
    rows: list[dict[str, Any]] = []
    for checkpoint in checkpoints:
        held = test[test.checkpoint_day == checkpoint]
        outcomes = held.outcome.to_numpy(dtype=int)
        states = _states(held)
        population = np.full(len(held), prior)
        static = _predict(static_model, static_cal, held, STATIC_COLUMNS)
        logistic = _predict(evidence_model, evidence_cal, held, evidence_columns)
        boosted = _predict(tree_model, tree_cal, held, evidence_columns)
        shrunk = np.asarray(
            [
                shrink_toward_prior(float(prob), prior, state.effective_sample_size, strength)
                for prob, state in zip(logistic, states, strict=True)
            ]
        )
        scored = {
            "population_prior": _clip_metrics(outcomes, population),
            "static_covariates": _clip_metrics(outcomes, static),
            "evidence_logistic": _clip_metrics(outcomes, logistic),
            "shrunk_evidence": _clip_metrics(outcomes, shrunk),
            "hist_gradient_boosting": _clip_metrics(outcomes, boosted),
        }
        prior_brier = scored["population_prior"]["brier"]
        for payload in scored.values():
            payload["brier_improvement_vs_prior"] = prior_brier - payload["brier"]
        rows.append(
            {
                "checkpoint_day": checkpoint,
                "models": scored,
                "by_sufficiency": _by_sufficiency(
                    outcomes,
                    states,
                    {
                        "population_prior": population,
                        "evidence_logistic": logistic,
                        "shrunk_evidence": shrunk,
                    },
                ),
                "mean_effective_sample_size": float(
                    np.mean([state.effective_sample_size for state in states])
                ),
                "fraction_population_only": float(
                    np.mean([state.sufficiency == "population_only" for state in states])
                ),
            }
        )

    example = _example_explanation(
        test, evidence_model, evidence_columns, prior, strength, evidence_cal
    )
    return {
        "benchmark": DATASET_ID,
        "experiment": "evidence_learning_v1",
        "seed": SEED,
        "model_version": MODEL_VERSION,
        "domain": DOMAIN,
        "not_applicable_to": ["hiring", "running", "finance", "startup"],
        "half_life_days": HALF_LIFE_DAYS,
        "half_life_source": "reused from oulad_completion_v1 selection; not re-tuned on test",
        "prior_strength": strength,
        "prior_strength_selection": "minimum validation Brier of shrunk calibrated logistic",
        "validation_strength_brier": strength_table,
        "calibration_methods": {
            "static_covariates": static_method,
            "evidence_logistic": evidence_method,
            "hist_gradient_boosting": tree_method,
        },
        "train_positive_rate": prior,
        "n_train_rows": int(len(train)),
        "n_validation_rows": int(len(validation)),
        "n_calibration_rows": int(len(calibration)),
        "n_test_rows": int(len(test)),
        "n_test_students": int(test.id_student.nunique()),
        "checkpoints": rows,
        "example_explanation": example,
        "limitations": [
            "One completion label is shared across checkpoints; later rows are not new outcomes.",
            "Test students are held out. Training still sees other students' later checkpoints.",
            "Shrinkage is a regularizer, not a posterior from a fully specified Bayesian model.",
            "Pulling a zero-activity row to the base rate can drop a real association.",
            "Pooled OULAD Brier numbers are a different experiment and are not this result.",
        ],
    }


def _by_sufficiency(
    outcomes: np.ndarray,
    states: list[EvidenceState],
    probabilities: dict[str, np.ndarray],
) -> dict[str, Any]:
    labels = np.asarray([state.sufficiency for state in states])
    groups: dict[str, Any] = {}
    for label in ("population_only", "sparse", "adequate"):
        mask = labels == label
        if not bool(mask.any()):
            continue
        groups[label] = {
            "n": int(mask.sum()),
            "models": {
                name: _clip_metrics(outcomes[mask], values[mask])
                for name, values in probabilities.items()
            },
        }
    return groups


def _example_explanation(
    test: pd.DataFrame,
    model: Any,
    columns: list[str],
    prior: float,
    strength: float,
    calibrator: ProbabilityCalibrator,
) -> dict[str, Any]:
    ordered = test.sort_values(["id_student", "checkpoint_day"])
    identity = ordered.iloc[0]
    person = ordered[
        (ordered.id_student == identity.id_student)
        & (ordered.code_module == identity.code_module)
        & (ordered.code_presentation == identity.code_presentation)
    ]
    snapshots = []
    for _, row in person.iterrows():
        single = person.loc[[row.name]]
        probability = float(_predict(model, calibrator, single, columns)[0])
        state = _states(single)[0]
        shrunk = shrink_toward_prior(probability, prior, state.effective_sample_size, strength)
        contributions: list[dict[str, float | str]] | None = None
        if model.named_steps["model"].__class__.__name__ == "LogisticRegression":
            contributions = logistic_contributions(model, single[columns])
        snapshots.append(
            {
                "checkpoint_day": int(row.checkpoint_day),
            **explain_forecast(
                prior=prior,
                model_probability=probability,
                shrunk_probability=shrunk,
                state=state,
                strength=strength,
                contributions=contributions,
            ),
            "log_odds_basis": "pre_calibration_logistic" if contributions is not None else None,
            }
        )
    return {
        "id_student": "redacted",
        "snapshots": snapshots,
        "note": "Student id is omitted. These probabilities are not a published goal.",
    }
