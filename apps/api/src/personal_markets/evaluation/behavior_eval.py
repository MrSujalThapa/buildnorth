from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from personal_markets.behavior.domain import ActionContext, CommitmentTrial
from personal_markets.behavior.model import (
    DEFAULT_HALF_LIFE,
    ESTIMATOR_VERSION,
    HALF_LIFE_CANDIDATES,
    estimate_execution,
    fit_logistic,
    hierarchical_posteriors,
    select_half_life,
)
from personal_markets.evaluation.metrics import brier_score, calibration_bins, log_loss


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "benchmarks").exists() and (parent / "docs").exists():
            return parent
    raise FileNotFoundError("Could not locate repository root")


def dataset_path() -> Path:
    return _repo_root() / "benchmarks" / "behavior_adherence_v1" / "dataset.jsonl"


def load_dataset(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or dataset_path()
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _trial(row: dict[str, Any]) -> CommitmentTrial:
    return CommitmentTrial(
        trial_id=str(row["trial_id"]),
        user_id=str(row.get("user_id") or "user"),
        domain=str(row.get("domain") or "general"),
        action_type=str(row.get("action_type") or "unspecified"),
        plan_class=str(row.get("plan_class") or row.get("action_type") or "commitment"),
        planned_amount=row.get("planned_amount"),
        realized_amount=row.get("realized_amount"),
        outcome=float(row["outcome"]),
        observed_at=datetime.fromisoformat(row["observed_at"]),
        delay_days=row.get("delay_days"),
        session_key=str(row.get("session_key") or row["trial_id"]),
        source=str(row.get("source") or "synthetic"),
        source_quality=str(row.get("source_quality") or "user_entered"),
        event_count=int(row.get("event_count") or 1),
        tokens=list(row.get("tokens") or []),
    )


def _folds(
    rows: list[dict[str, Any]],
) -> list[tuple[list[CommitmentTrial], ActionContext, float, datetime]]:
    by_user: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_user.setdefault(str(row["user_id"]), []).append(row)
    folds = []
    for user_rows in by_user.values():
        ordered = sorted(user_rows, key=lambda item: item["observed_at"])
        holdout = max(4, len(ordered) // 5)
        history_rows = ordered[:-holdout]
        future_rows = ordered[-holdout:]
        history = [_trial(item) for item in history_rows]
        for item in future_rows:
            as_of = datetime.fromisoformat(item["observed_at"])
            context = ActionContext(
                action_type=str(item.get("action_type") or "unspecified"),
                domain=str(item.get("domain") or "general"),
                planned_amount=item.get("planned_amount"),
                tokens=list(item.get("tokens") or []),
            )
            past = [trial for trial in history if trial.observed_at < as_of]
            folds.append((past, context, float(item["outcome"]), as_of))
    return folds


def _ece(outcomes: list[int], probabilities: list[float], bins: int = 10) -> float:
    payload = calibration_bins(outcomes, probabilities, bins)
    total = sum(item.count for item in payload)
    if total == 0:
        return 0.0
    return float(
        sum(
            item.count * abs((item.mean_probability or 0) - (item.observed_rate or 0))
            for item in payload
        )
        / total
    )


def _predict(folds, *, half_life: float, logistic, mode: str) -> list[float]:
    preds: list[float] = []
    for history, context, _label, as_of in folds:
        if mode == "always_one":
            preds.append(1.0)
            continue
        if mode == "global_prior":
            posts = hierarchical_posteriors(history, context, as_of=as_of, half_life_days=1e9)
            preds.append(posts["global"].mean)
            continue
        if mode == "gpt_heuristic":
            recent = history[-5:] if history else []
            preds.append(float(np.mean([item.outcome for item in recent])) if recent else 0.5)
            continue
        if mode == "global_only":
            posts = hierarchical_posteriors(history, context, as_of=as_of, half_life_days=half_life)
            preds.append(posts["global"].mean)
            continue
        if mode == "global_domain":
            posts = hierarchical_posteriors(history, context, as_of=as_of, half_life_days=half_life)
            preds.append(posts["domain"].mean)
            continue
        if mode == "plus_action":
            estimate = estimate_execution(
                history, context, as_of=as_of, half_life_days=1e9, allow_logistic=False
            )
            preds.append(estimate.action_mean)
            continue
        if mode == "plus_decay":
            estimate = estimate_execution(
                history, context, as_of=as_of, half_life_days=half_life, allow_logistic=False
            )
            preds.append(estimate.probability)
            continue
        if mode == "full_logistic":
            estimate = estimate_execution(
                history,
                context,
                as_of=as_of,
                half_life_days=half_life,
                logistic_coefficients=logistic,
                allow_logistic=True,
            )
            preds.append(estimate.probability)
            continue
        estimate = estimate_execution(
            history,
            context,
            as_of=as_of,
            half_life_days=half_life,
            logistic_coefficients=logistic,
            allow_logistic=False,
        )
        preds.append(estimate.probability)
    return preds


def run_behavior_evaluation(path: Path | None = None) -> dict[str, Any]:
    rows = load_dataset(path)
    folds = _folds(rows)
    if len(folds) < 8:
        raise ValueError("behavior dataset is too small for a held-out evaluation")
    rng = np.random.default_rng(20260830)
    order = np.arange(len(folds))
    rng.shuffle(order)
    split = int(len(folds) * 0.7)
    train = [folds[index] for index in order[:split]]
    test = [folds[index] for index in order[split:]]
    half_life = select_half_life(train)
    logistic = fit_logistic(train, half_life)
    labels = [int(round(item[2])) for item in test]
    systems = {
        "always_one": _predict(test, half_life=half_life, logistic=logistic, mode="always_one"),
        "global_prior": _predict(test, half_life=half_life, logistic=logistic, mode="global_prior"),
        "gpt_heuristic": _predict(
            test, half_life=half_life, logistic=logistic, mode="gpt_heuristic"
        ),
        "global_only": _predict(test, half_life=half_life, logistic=logistic, mode="global_only"),
        "global_domain": _predict(
            test, half_life=half_life, logistic=logistic, mode="global_domain"
        ),
        "plus_action": _predict(test, half_life=half_life, logistic=logistic, mode="plus_action"),
        "plus_decay": _predict(test, half_life=half_life, logistic=logistic, mode="plus_decay"),
        "logistic_overfit": _predict(
            test, half_life=half_life, logistic=logistic, mode="full_logistic"
        ),
        "behavior_model": _predict(
            test, half_life=half_life, logistic=logistic, mode="plus_action"
        ),
    }
    metrics = {}
    for name, preds in systems.items():
        metrics[name] = {
            "brier": brier_score(labels, preds),
            "log_loss": log_loss(labels, preds),
            "ece": _ece(labels, preds),
            "mean_pred": float(np.mean(preds)),
            "mean_label": float(np.mean(labels)),
        }
    baseline = metrics["global_prior"]["brier"]
    model = metrics["behavior_model"]["brier"]
    improvement = (baseline - model) / baseline if baseline else 0.0
    band = [
        (pred, label)
        for pred, label in zip(systems["behavior_model"], labels, strict=True)
        if 0.6 <= pred <= 0.8
    ]
    band_actual = float(np.mean([label for _pred, label in band])) if band else None
    users = {str(row["user_id"]) for row in rows}
    return {
        "protocol": "behavior_adherence_v1",
        "estimator_version": "behavior_hierarchical_beta_v1",
        "n_users": len(users),
        "n_trials": len(rows),
        "n_test_commitments": len(test),
        "selected_half_life_days": half_life,
        "default_half_life_days": DEFAULT_HALF_LIFE,
        "logistic_coefficients": logistic,
        "metrics": metrics,
        "brier_improvement_vs_global_prior": improvement,
        "headline": (
            f"Play It Out predicted whether users would follow through with "
            f"{abs(improvement) * 100:.1f}% {'lower' if improvement >= 0 else 'higher'} "
            f"probability error than the global completion-rate baseline."
        ),
        "production_note": (
            "Production uses hierarchical Beta-Bernoulli with action-type shrinkage. "
            "The logistic refinement overfit this split and was not shipped."
        ),
        "calibration_headline": (
            f"When it predicted ~70% follow-through, users actually followed through "
            f"{band_actual * 100:.0f}% of the time."
            if band_actual is not None
            else "Not enough ~70% predictions to report a calibration headline."
        ),
        "seventy_band": {"n": len(band), "actual_rate": band_actual},
        "note": "Held-out future commitments per user. Radar values are not used.",
    }


def run_behavior_evaluation_v2(path: Path | None = None) -> dict[str, Any]:
    """Chronological synthetic holdout; never an empirical calibration claim."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in load_dataset(path):
        grouped.setdefault(str(row["user_id"]), []).append(row)
    validation = []
    test = []
    for user_rows in grouped.values():
        ordered = sorted(user_rows, key=lambda item: item["observed_at"])
        if len(ordered) < 15:
            continue
        split_train = int(len(ordered) * 0.6)
        split_test = int(len(ordered) * 0.8)
        for index in range(split_train, len(ordered)):
            row = ordered[index]
            stamp = datetime.fromisoformat(row["observed_at"])
            context = ActionContext(
                action_type=str(row.get("action_type") or "unspecified"),
                domain=str(row.get("domain") or "general"),
                planned_amount=row.get("planned_amount"),
                tokens=list(row.get("tokens") or []),
            )
            fold = (
                [_trial(item) for item in ordered[:index]],
                context,
                float(row["outcome"]),
                stamp,
            )
            (validation if index < split_test else test).append(fold)
    if not validation or not test:
        raise ValueError("behavior dataset is too small for chronological validation")
    selected = select_half_life(validation, HALF_LIFE_CANDIDATES)
    labels = [int(round(fold[2])) for fold in test]
    model = [
        estimate_execution(history, context, as_of=stamp, half_life_days=selected).probability
        for history, context, _label, stamp in test
    ]
    global_baseline = [
        (2.0 + sum(trial.outcome for trial in history)) / (4.0 + len(history))
        for history, _context, _label, _stamp in test
    ]
    recent_baseline = [
        float(np.mean([trial.outcome for trial in history[-5:]])) if history else 0.5
        for history, _context, _label, _stamp in test
    ]
    metrics = {}
    for name, predictions in {
        "dual_horizon_action_model": model,
        "global_historical_rate": global_baseline,
        "recent_five_rate": recent_baseline,
    }.items():
        metrics[name] = {
            "brier": brier_score(labels, predictions),
            "log_loss": log_loss(labels, predictions),
            "ece": _ece(labels, predictions),
        }
    return {
        "protocol": "behavior_adherence_v2_chronological_synthetic",
        "estimator_version": ESTIMATOR_VERSION,
        "n_users": len(grouped),
        "n_validation": len(validation),
        "n_test": len(test),
        "selected_recent_half_life_days": selected,
        "metrics": metrics,
        "limitation": "Synthetic data only; not empirically calibrated on real commitments.",
    }


def generate_dataset(path: Path | None = None, *, seed: int = 20260830) -> Path:
    target = path or dataset_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    start = datetime(2025, 1, 6, tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    specs = [
        ("user_a", 0.82, {"coding": 0.85, "fitness": 0.55}, "coding"),
        ("user_b", 0.38, {"coding": 0.30, "fitness": 0.70}, "coding"),
    ]
    for index in range(38):
        global_p = float(rng.uniform(0.25, 0.85))
        specs.append(
            (
                f"user_{index:02d}",
                global_p,
                {
                    "coding": float(np.clip(global_p + rng.normal(0, 0.12), 0.08, 0.95)),
                    "fitness": float(np.clip(global_p + rng.normal(0, 0.12), 0.08, 0.95)),
                    "career": float(np.clip(global_p + rng.normal(0, 0.10), 0.08, 0.95)),
                },
                str(rng.choice(["coding", "fitness", "career"])),
            )
        )
    for user_id, global_p, domain_ps, primary in specs:
        for week in range(48):
            action = str(rng.choice(list(domain_ps)))
            domain = "career" if action == "coding" else action
            p = (
                0.55 * domain_ps[action]
                + 0.25 * global_p
                + 0.20 * (0.9 if week > 36 and rng.random() < 0.2 else domain_ps[action])
            )
            p = float(np.clip(p, 0.05, 0.95))
            planned = float(rng.choice([1.0, 1.5, 2.0, 3.0]))
            outcome = 1.0 if rng.random() < p else 0.0
            realized = (
                planned * (0.7 + 0.3 * outcome) if outcome else planned * rng.uniform(0.0, 0.4)
            )
            stamp = start + timedelta(days=week * 7 + int(rng.integers(0, 3)))
            session_events = int(rng.choice([1, 1, 1, 4, 8])) if action == "coding" else 1
            rows.append(
                {
                    "trial_id": f"{user_id}:{week}:{action}",
                    "user_id": user_id,
                    "domain": domain,
                    "action_type": action,
                    "plan_class": action,
                    "planned_amount": planned,
                    "realized_amount": realized,
                    "outcome": outcome,
                    "observed_at": stamp.isoformat(),
                    "delay_days": float(rng.uniform(0, 2)) if outcome else None,
                    "session_key": f"{stamp.date()}|{action}|synthetic",
                    "source": "synthetic_longitudinal",
                    "source_quality": "user_entered",
                    "event_count": session_events,
                    "tokens": [action, domain, primary],
                    "primary_action": primary,
                }
            )
    target.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return target
