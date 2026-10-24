"""Evidence-learning contracts. Synthetic rows only; they are not OULAD results."""

import math

import numpy as np
import pandas as pd
import pytest

from personal_markets.evaluation.evidence_learning import (
    DOMAIN,
    EvidenceState,
    applies_to,
    assert_group_separation,
    assert_unique_checkpoints,
    evidence_state,
    explain_forecast,
    learning_curve,
    shrink_toward_prior,
)
from personal_markets.forecasting.models import feature_columns


def test_zero_evidence_is_absence_not_a_skill_estimate() -> None:
    state = evidence_state(math.nan, math.nan)
    assert state == EvidenceState(0, 0.0, "population_only")
    assert shrink_toward_prior(0.9, 0.4, state.effective_sample_size, 8.0) == pytest.approx(0.4)


def test_shrinkage_moves_toward_the_model_only_as_evidence_grows() -> None:
    sparse = shrink_toward_prior(0.9, 0.4, 0.5, 8.0)
    rich = shrink_toward_prior(0.9, 0.4, 40.0, 8.0)
    assert 0.4 < sparse < rich < 0.9


def test_shrinkage_rejects_bad_bounds() -> None:
    with pytest.raises(ValueError, match="positive"):
        shrink_toward_prior(0.2, 0.4, 1.0, 0.0)
    with pytest.raises(ValueError, match="negative"):
        evidence_state(-1, 0)


def test_explanation_matches_the_formula_and_makes_no_causal_claim() -> None:
    state = evidence_state(0, 0)
    explained = explain_forecast(
        prior=0.42,
        model_probability=0.8,
        shrunk_probability=0.42,
        state=state,
        strength=8.0,
    )
    assert explained["causal_claim"] is None
    assert explained["data_sufficiency"] == "population_only"
    assert "not automatically" in explained["limitations"][2]
    assert explained["evidence_weight"] == 0.0
    assert explained["domain"] == DOMAIN
    with pytest.raises(ValueError, match="does not match"):
        explain_forecast(
            prior=0.42,
            model_probability=0.8,
            shrunk_probability=0.1,
            state=state,
            strength=8.0,
        )


def test_applicability_stays_inside_oulad_completion() -> None:
    assert applies_to(DOMAIN) is True
    assert applies_to("hiring") is False
    assert applies_to("running") is False


def test_duplicate_and_overlapping_students_are_rejected() -> None:
    frame = _frame()
    with pytest.raises(ValueError, match="duplicate"):
        assert_unique_checkpoints(pd.concat([frame, frame.iloc[[0]]], ignore_index=True))
    leaked = frame.copy()
    train_id = int(frame.loc[frame.split == "train", "id_student"].iloc[0])
    leaked.loc[leaked.split == "test", "id_student"] = train_id
    with pytest.raises(ValueError, match="both train and test"):
        assert_group_separation(leaked)


def test_learning_curve_is_reproducible_and_uses_later_evidence() -> None:
    frame = _frame()
    first = learning_curve(frame)
    second = learning_curve(frame)
    assert first["checkpoints"] == second["checkpoints"]
    by_day = {row["checkpoint_day"]: row for row in first["checkpoints"]}
    early = by_day[14]["models"]
    late = by_day[105]["models"]
    assert early["shrunk_evidence"]["brier"] == pytest.approx(early["population_prior"]["brier"])
    assert late["evidence_logistic"]["brier"] < late["population_prior"]["brier"]
    assert late["shrunk_evidence"]["brier"] < early["shrunk_evidence"]["brier"]
    assert set(by_day[14]["by_sufficiency"]) == {"population_only"}
    absent = by_day[14]["by_sufficiency"]["population_only"]["models"]
    assert absent["shrunk_evidence"]["brier"] == pytest.approx(absent["population_prior"]["brier"])
    late_groups = by_day[105]["by_sufficiency"]
    assert late_groups["population_only"]["models"]["population_prior"]["roc_auc"] is None
    assert len(first["validation_strength_brier"]) == 6
    assert first["example_explanation"]["snapshots"][0]["causal_claim"] is None
    basis = first["example_explanation"]["snapshots"][0]["log_odds_basis"]
    assert basis == "pre_calibration_logistic"
    assert first["not_applicable_to"] == ["hiring", "running", "finance", "startup"]


def test_outcome_columns_cannot_enter_the_fit() -> None:
    frame = _frame()
    frame["final_result"] = "Pass"
    with pytest.raises(ValueError, match="outcome columns"):
        learning_curve(frame)


def test_constant_prior_does_not_invent_an_auc() -> None:
    report = learning_curve(_frame())
    early = report["checkpoints"][0]["models"]["population_prior"]
    assert early["roc_auc"] is None
    assert "undefined" in early["roc_auc_note"]


def _frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    columns = feature_columns(14)
    for student in range(80):
        if student < 40:
            split = "train"
        elif student < 55:
            split = "validation"
        elif student < 70:
            split = "calibration"
        else:
            split = "test"
        outcome = student % 2
        for day in (14, 105):
            row: dict[str, object] = {column: 0.0 for column in columns}
            row.update(
                {
                    "code_module": "AAA",
                    "code_presentation": "2013J",
                    "id_student": student,
                    "split": split,
                    "checkpoint_day": day,
                    "outcome": outcome,
                    "num_of_prev_attempts": 0,
                    "studied_credits": 60,
                    "module_presentation_length": 260,
                }
            )
            if day == 105 and outcome == 1:
                row["vle_active_days"] = 20
                row["vle_total_clicks"] = 400
                row["assessment_submissions"] = 3
                row["assessment_mean_score"] = 80
            rows.append(row)
    frame = pd.DataFrame(rows)
    for column in frame.columns:
        if column not in {"code_module", "code_presentation", "split"}:
            frame[column] = pd.to_numeric(frame[column])
    return frame


def test_metric_identity_on_a_known_pair() -> None:
    from personal_markets.evaluation.metrics import brier_score

    probability = shrink_toward_prior(1.0, 0.0, 1.0, 1.0)
    assert probability == pytest.approx(0.5)
    assert brier_score([1], [probability]) == pytest.approx(0.25)
    assert np.isfinite(probability)
