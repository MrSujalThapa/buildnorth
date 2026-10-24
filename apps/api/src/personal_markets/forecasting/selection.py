"""Choose how a goal is priced. A classifier runs only when its outcome and features match.

No trained artifact in this repository has inputs a live goal can collect. OULAD, JTH,
SHED, and the running-pace classifier stay documented rejections. Hiring, finance, and
running keep the statistical or reference models that already consume user evidence.
"""

from __future__ import annotations

from typing import Any, Literal

from personal_markets.forecasting.engine import NumericInputs
from personal_markets.goals.domain import GoalContract
from personal_markets.ports import GoalArchitectProposal

PredictionMethod = Literal[
    "TRAINED_ML",
    "FITTED_STATISTICAL",
    "REFERENCE_MODEL",
    "DETERMINISTIC",
    "NOT_PRICED",
]

_CLASSIFIERS: tuple[dict[str, str], ...] = (
    {
        "model_id": "oulad_completion_v1",
        "domain": "education",
        "outcome": "OULAD module Pass or Distinction versus Fail or Withdrawn",
        "feature_schema": "oulad-temporal-v1",
        "reason": (
            "Requires Open University VLE click totals and assessment rows censored at "
            "checkpoint days 14, 35, 70, or 105. A personal goal does not collect that schema."
        ),
    },
    {
        "model_id": "jth_offer_v1",
        "domain": "hiring",
        "outcome": "This JTH application row receives an offer",
        "feature_schema": "jth-offer-temporal-v1",
        "reason": (
            "Requires JTH candidate and job fields (skill counts, diploma and seniority "
            "ordinals, salary, company size) plus that dataset's stage dates. A PlayItOut "
            "hiring goal is the user's own funnel counts, which is a different outcome. "
            "The source is CC BY-NC. The classifier is not applied."
        ),
    },
    {
        "model_id": "shed_emergency_savings_v1",
        "domain": "finance",
        "outcome": "SHED EF1 is Yes in the 2023 wave",
        "feature_schema": "shed-ef1-2022to2023-v1",
        "reason": (
            "Requires 2022 SHED survey codes such as income band, age, and household size. "
            "A savings goal is a balance, a contribution, and a deadline. Those are not the "
            "SHED feature schema, and no model artifact is shipped."
        ),
    },
    {
        "model_id": "running_pace_improve_2019_v1",
        "domain": "running",
        "outcome": "July-December 2019 mean pace is at least 5% faster than January-June",
        "feature_schema": "running-pace-improve-2019-v1",
        "reason": (
            "The label is a half-year pace change for athletes in one public training log. "
            "A race-time goal is a threshold on the user's own timed efforts. The live path "
            "fits that trend from the user's runs instead of loading this classifier."
        ),
    },
)


def hiring_prediction_block(
    *,
    method: PredictionMethod,
    sufficiency: str,
    fits: list[dict[str, Any]],
    missing_stages: list[str],
    reference_version: str,
    pseudo_counts: float,
    weekly_rate_source: str,
    weekly_rate: float,
) -> dict[str, Any]:
    calibration_reason = (
        "Resolved stage rates are shrunk toward the mechanistic hiring prior. "
        "That is not an empirically calibrated probability for this person."
    )
    if method == "DETERMINISTIC":
        calibration_reason = (
            "An offer was observed. The published value is the existing observed-offer "
            "ceiling, not a new claim of certainty."
        )
    elif method == "REFERENCE_MODEL":
        calibration_reason = (
            "Stage rates are the frozen hiring reference. No resolved pass/rejection "
            "pair was available to update them. This is not personal calibration."
        )
    return {
        "method": method,
        "trained_classifier": None,
        "model_family": "deadline_event_hazard",
        "model_version": reference_version,
        "applicable_domain": "hiring_funnel",
        "required_features": [
            "applications",
            "resolved passes and rejections at a stage",
        ],
        "evidence_sources": ["user_evidence"],
        "missing_inputs": missing_stages,
        "statistical_assumptions": [
            "Parallel applications are treated as independent.",
            "In-flight applications are not counted as failures.",
            "A rejection is removed only from the stage it names.",
            "Practice volume does not change the probability.",
            (
                f"Future applications use {weekly_rate:g} per week ({weekly_rate_source}). "
                "The reference default is 2 per week. This rate is not the current pipeline."
            ),
        ],
        "calibration": {
            "applied": False,
            "status": "not_empirically_calibrated",
            "reason": calibration_reason,
        },
        "uncertainty": {
            "representation": "pseudo_count_shrinkage",
            "pseudo_counts": pseudo_counts,
            "fitted_stages": fits,
            "interval": None,
        },
        "data_sufficiency": sufficiency,
        "limitations": [
            "JTH, OULAD, SHED, and the running-pace classifier do not apply to this goal.",
            "No population model is claimed to be individually calibrated.",
        ],
    }


def rejected_classifiers(
    goal: GoalContract, proposal: GoalArchitectProposal | None
) -> list[dict[str, str]]:
    """Classifiers whose domain is adjacent to this goal, and why they stay off."""
    from personal_markets.forecasting.finance import is_finance_goal
    from personal_markets.forecasting.hiring import is_hiring_goal
    from personal_markets.forecasting.running import is_running_goal

    metric = str(goal.success_definition.get("metric") or "")
    wanted: set[str] = set()
    if metric == "course_completion":
        wanted.add("education")
    if is_hiring_goal(goal, proposal):
        wanted.add("hiring")
    if is_finance_goal(goal, proposal):
        wanted.add("finance")
    if is_running_goal(goal, proposal):
        wanted.add("running")
    if not wanted:
        return []
    return [dict(row) for row in _CLASSIFIERS if row["domain"] in wanted]


def attach_prediction(
    goal: GoalContract,
    proposal: GoalArchitectProposal | None,
    inputs: NumericInputs | None,
    *,
    priced: bool,
    model_family: str,
    model_version: str,
) -> dict[str, Any]:
    existing = inputs.state.get("prediction") if inputs is not None else None
    if isinstance(existing, dict):
        block = dict(existing)
    else:
        block = _infer_block(
            goal, inputs, priced=priced, model_family=model_family, model_version=model_version
        )
    block["trained_classifier"] = None
    block["rejected_classifiers"] = rejected_classifiers(goal, proposal)
    block.setdefault("calibration", _uncalibrated("No calibrator was applied."))
    return block


def _infer_block(
    goal: GoalContract,
    inputs: NumericInputs | None,
    *,
    priced: bool,
    model_family: str,
    model_version: str,
) -> dict[str, Any]:
    if not priced or inputs is None:
        return {
            "method": "NOT_PRICED",
            "model_family": model_family,
            "model_version": model_version,
            "applicable_domain": goal.goal_type.value,
            "required_features": [],
            "evidence_sources": [],
            "missing_inputs": ["numeric inputs required by the selected family"],
            "statistical_assumptions": [],
            "calibration": _uncalibrated("The goal was not priced, so nothing was calibrated."),
            "uncertainty": {"interval": None},
            "data_sufficiency": "insufficient",
            "limitations": ["Missing evidence was not invented."],
        }
    sources = inputs.assumption_sources
    fitted = any(source in {"FITTED", "REAL_USER_EVIDENCE"} for source in sources.values())
    reference = any(source == "REFERENCE" for source in sources.values())
    if fitted and _running_trend_fitted(sources):
        method: PredictionMethod = "FITTED_STATISTICAL"
        sufficiency = "personal_observations"
        reason = (
            "The pace trend is fit from this user's timed efforts. "
            "It is not the 2019 pace-improvement classifier, and it is not calibrated."
        )
    elif fitted and not reference:
        method = "FITTED_STATISTICAL"
        sufficiency = "personal_observations"
        reason = "Parameters come from this user's evidence. No held-out calibrator was applied."
    else:
        method = "REFERENCE_MODEL"
        sufficiency = "reference_with_observed_state" if fitted else "reference_only"
        reason = (
            "The probability uses a documented reference distribution or rate. "
            "Observed balances or counts are inputs, not a trained classifier, "
            "and the result is not personally calibrated."
        )
    return {
        "method": method,
        "model_family": model_family,
        "model_version": model_version,
        "applicable_domain": goal.goal_type.value,
        "required_features": sorted(inputs.assumptions.keys()),
        "evidence_sources": sorted({source for source in sources.values()}),
        "missing_inputs": [],
        "statistical_assumptions": [reason],
        "calibration": _uncalibrated(reason),
        "uncertainty": {"interval": None},
        "data_sufficiency": sufficiency,
        "limitations": [reason],
    }


def _running_trend_fitted(sources: dict[str, str]) -> bool:
    return sources.get("trend") == "REAL_USER_EVIDENCE"


def _uncalibrated(reason: str) -> dict[str, Any]:
    return {"applied": False, "status": "not_empirically_calibrated", "reason": reason}
