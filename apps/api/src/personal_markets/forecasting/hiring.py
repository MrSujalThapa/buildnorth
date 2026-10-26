from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.evidence.metrics import ObservationKind, observation_kind, reduce_stock_value
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.goals.domain import GoalContract
from personal_markets.ports import GoalArchitectProposal

REFERENCE_ID = "hiring_funnel_rates.json"
STAGE_CHAIN = (
    "application_to_response",
    "response_to_phone_screen",
    "phone_screen_to_oa",
    "oa_to_technical",
    "technical_to_final",
    "final_to_offer",
)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[5]


@dataclass(frozen=True, slots=True)
class HiringFunnelState:
    applications: int = 0
    responses: int = 0
    phone_screens: int = 0
    oas: int = 0
    technicals: int = 0
    finals: int = 0
    offers: int = 0
    rejections: dict[str, int] = field(default_factory=dict)
    practice_hours: float = 0.0
    last_activity_at: datetime | None = None
    resolved_cohort_validated: bool = False


@dataclass(frozen=True, slots=True)
class HiringReferenceRates:
    stage_rates: dict[str, float]
    weekly_application_rate: float
    recency_half_life_days: float
    recency_floor: float
    resolved_outcome_pseudo_counts: float
    reference_id: str
    version: str
    limitations: tuple[str, ...]


def load_hiring_reference(root: Path | None = None) -> HiringReferenceRates:
    path = (root or _repo_root() / "data" / "reference") / REFERENCE_ID
    payload = json.loads(path.read_text(encoding="utf-8"))
    defaults = payload.get("defaults") or {}
    rates = payload.get("stage_rates") or {}
    for key in STAGE_CHAIN:
        if key not in rates:
            raise ValueError(f"{REFERENCE_ID} missing stage rate {key!r}")
    return HiringReferenceRates(
        stage_rates={key: float(rates[key]) for key in STAGE_CHAIN},
        weekly_application_rate=float(defaults.get("weekly_application_rate", 2.0)),
        recency_half_life_days=float(defaults.get("recency_half_life_days", 21.0)),
        recency_floor=float(defaults.get("recency_floor", 0.65)),
        resolved_outcome_pseudo_counts=float(
            defaults.get("resolved_outcome_pseudo_counts", 8.0)
        ),
        reference_id=REFERENCE_ID,
        version=str(payload.get("version") or "unknown"),
        limitations=tuple(payload.get("limitations") or []),
    )


def is_hiring_goal(goal: GoalContract, proposal: GoalArchitectProposal | None = None) -> bool:
    blob = " ".join(
        [
            goal.title,
            str(goal.success_definition),
            " ".join(goal.state_dimensions),
            proposal.model_family_compatibility if proposal else "",
            proposal.success_metric if proposal else "",
        ]
    ).lower()
    tokens = (
        "offer",
        "interview",
        "hiring",
        "swe",
        "fde",
        "recruiter",
        "application_pipeline",
        "applications_submitted",
        "technical_interview",
    )
    return any(token in blob for token in tokens)


def aggregate_funnel_from_evidence(
    evidence: list[NormalizedEvidence],
    *,
    now: datetime | None = None,
) -> HiringFunnelState:
    clock = now or datetime.now(UTC)
    last_activity: datetime | None = None
    practice_hours = 0.0
    rejection_rows: dict[str, list[tuple[datetime, float, ObservationKind]]] = {}
    stocks: dict[str, list[tuple[datetime, float, ObservationKind]]] = {
        "application": [],
        "response": [],
        "phone_screen": [],
        "oa": [],
        "technical": [],
        "final": [],
        "offer": [],
    }

    for item in evidence:
        metric = item.metric.lower()
        event_type = item.event_type.lower()
        category = (item.categorical_value or "").lower()
        summary = item.summary.lower()
        observed = item.observed_at or clock
        if last_activity is None or observed > last_activity:
            last_activity = observed

        count = float(_event_count(item))
        kind = observation_kind(
            item.metric, item.event_type, item.provenance.observation_kind, item.unit
        )
        if kind == "period":
            continue
        stage = _resolve_stage(metric, event_type, category, summary, item.unit or "")
        if stage == "rejection":
            rejection_stage = _rejection_stage(metric, event_type, category, summary)
            rejection_rows.setdefault(rejection_stage, []).append((observed, count, kind))
            continue
        if stage == "practice":
            practice_hours += float(item.numeric_value or 0.0)
            continue
        if stage in stocks:
            stocks[stage].append((observed, count, kind))

    rejections = {
        stage: int(round(reduce_stock_value(rows)))
        for stage, rows in rejection_rows.items()
    }
    rejections = {stage: count for stage, count in rejections.items() if count > 0}

    return HiringFunnelState(
        applications=int(round(reduce_stock_value(stocks["application"]))),
        responses=int(round(reduce_stock_value(stocks["response"]))),
        phone_screens=int(round(reduce_stock_value(stocks["phone_screen"]))),
        oas=int(round(reduce_stock_value(stocks["oa"]))),
        technicals=int(round(reduce_stock_value(stocks["technical"]))),
        finals=int(round(reduce_stock_value(stocks["final"]))),
        offers=int(round(reduce_stock_value(stocks["offer"]))),
        rejections=rejections,
        practice_hours=practice_hours,
        last_activity_at=last_activity,
    )


def apply_funnel_overrides(
    state: HiringFunnelState, overrides: dict[str, Any] | None
) -> HiringFunnelState:
    if not overrides:
        return state
    updated = state
    if "applications" in overrides:
        updated = replace(updated, applications=int(overrides["applications"]))
    if "responses" in overrides:
        updated = replace(updated, responses=int(overrides["responses"]))
    if "phone_screens" in overrides:
        updated = replace(updated, phone_screens=int(overrides["phone_screens"]))
    if "oas" in overrides:
        updated = replace(updated, oas=int(overrides["oas"]))
    if "technicals" in overrides:
        updated = replace(updated, technicals=int(overrides["technicals"]))
    if "finals" in overrides:
        updated = replace(updated, finals=int(overrides["finals"]))
    if "offers" in overrides:
        updated = replace(updated, offers=int(overrides["offers"]))
    if "practice_hours" in overrides:
        updated = replace(updated, practice_hours=float(overrides["practice_hours"]))
    if "rejections" in overrides and isinstance(overrides["rejections"], dict):
        merged = dict(updated.rejections)
        merged.update({str(k): int(v) for k, v in overrides["rejections"].items()})
        updated = replace(updated, rejections=merged)
    return updated


def funnel_state_to_numeric_inputs(
    goal: GoalContract,
    state: HiringFunnelState,
    *,
    rates: HiringReferenceRates | None = None,
    weekly_application_rate: float | None = None,
    stage_rate_overrides: dict[str, float] | None = None,
    now: datetime | None = None,
) -> NumericInputs | None:
    reference = rates or load_hiring_reference()
    stage_rates = dict(reference.stage_rates)
    if stage_rate_overrides:
        for key, value in stage_rate_overrides.items():
            if key in stage_rates:
                stage_rates[key] = float(value)
    clock = now or datetime.now(UTC)
    if not _has_funnel_signal(state):
        return None

    if state.offers >= 1:
        return _priced_inputs(
            goal=goal,
            state=state,
            reference=reference,
            probability=0.995,
            transforms={"offer_already_received": True},
            clock=clock,
        )

    periods = max(1, math.ceil((goal.deadline - clock).total_seconds() / 604800))
    weekly_rate = (
        weekly_application_rate
        if weekly_application_rate is not None
        else reference.weekly_application_rate
    )
    p_current = _pipeline_offer_probability(state, stage_rates)
    p_current *= _recency_factor(state, reference, clock)
    p_new = _expected_new_pipeline_offers(weekly_rate, periods, stage_rates)
    p_total = _combine_independent([p_current, p_new])
    p_total = min(max(p_total, 1e-6), 1 - 1e-6)
    hazard = 1.0 - (1.0 - p_total) ** (1.0 / periods)
    hazard = min(max(hazard, 1e-6), 1 - 1e-6)
    logit = math.log(hazard / (1.0 - hazard))

    active = _active_counts(state)
    rate_source = "REFERENCE" if weekly_application_rate is None else "USER_ASSUMPTION"
    transforms: dict[str, Any] = {
        "funnel_state": active,
        "periods_remaining": periods,
        "pipeline_offer_probability": p_current,
        "current_pipeline_offer_probability": p_current,
        "expected_new_pipeline_offer_probability": p_new,
        "future_applications_offer_probability": p_new,
        "combined_offer_probability": p_total,
        "weekly_application_rate": weekly_rate,
        "future_application_rate": {
            "applications_per_week": weekly_rate,
            "source": rate_source,
            "reference_default_per_week": reference.weekly_application_rate,
            "applies_to": "expected future applications, not the current pipeline",
        },
        "reference_version": reference.version,
        "stage_rates": stage_rates,
        "practice_hours_observed": state.practice_hours,
    }
    inconsistent = active.get("stage_count_inconsistencies") or []
    if inconsistent:
        transforms["count_consistency"] = {
            "stages": inconsistent,
            "note": (
                "Passes plus rejections exceed the reported stock. The active count is "
                "zero. Extra rejections were not assigned to another stage."
            ),
        }
    if state.practice_hours:
        transforms["practice_note"] = (
            "Practice volume is activity evidence only; it does not map to a strength score."
        )

    return NumericInputs(
        state={
            "baseline_logits": [logit] * periods,
            "periods_remaining": periods,
            "funnel": active,
            "pricing_transforms": transforms,
        },
        assumptions={"weekly_application_rate": weekly_rate},
        assumption_sources={
            "baseline_logits": "REFERENCE",
            "weekly_application_rate": "REFERENCE"
            if weekly_application_rate is None
            else "USER_ASSUMPTION",
        },
    )


_REJECTION_STAGE = {
    "application": "application_to_response",
    "response": "response_to_phone_screen",
    "phone_screen": "phone_screen_to_oa",
    "oa": "oa_to_technical",
    "technical": "technical_to_final",
    "final": "final_to_offer",
}
_STAGE_SUCCESS_FIELD = {
    "application_to_response": "responses",
    "response_to_phone_screen": "phone_screens",
    "phone_screen_to_oa": "oas",
    "oa_to_technical": "technicals",
    "technical_to_final": "finals",
    "final_to_offer": "offers",
}


def fit_resolved_stage_rates(
    state: HiringFunnelState, reference: HiringReferenceRates
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Shrink a stage rate toward the reference using resolved passes and rejections.

    In-flight applications are not failures. A stage is fit only when that stage has
    at least one recorded rejection. Successes are the count observed at the next
    stage, which is a different set of people from the rejections.
    """
    pseudo = reference.resolved_outcome_pseudo_counts
    if pseudo <= 0:
        raise ValueError("resolved outcome pseudo-counts must be positive")
    overrides: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    for rejection_stage, stage in _REJECTION_STAGE.items():
        failures = float(state.rejections.get(rejection_stage, 0))
        if failures <= 0:
            continue
        successes = float(getattr(state, _STAGE_SUCCESS_FIELD[stage]))
        prior = float(reference.stage_rates[stage])
        trials = successes + failures
        fitted = (successes + pseudo * prior) / (trials + pseudo)
        overrides[stage] = fitted
        rows.append(
            {
                "stage": stage,
                "successes": successes,
                "failures": failures,
                "trials": trials,
                "prior_rate": prior,
                "fitted_rate": fitted,
                "pseudo_counts": pseudo,
                "estimator": "resolved_outcomes_shrunk_to_reference",
            }
        )
    return overrides, rows


def build_hiring_numeric_inputs(
    goal: GoalContract,
    proposal: GoalArchitectProposal | None,
    evidence: list[NormalizedEvidence],
    *,
    overrides: dict[str, Any] | None = None,
    now: datetime | None = None,
    validated_resolved_cohort: bool = False,
) -> NumericInputs | None:
    if not is_hiring_goal(goal, proposal):
        return None
    state = aggregate_funnel_from_evidence(evidence, now=now)
    state = apply_funnel_overrides(state, overrides)
    state = replace(state, resolved_cohort_validated=validated_resolved_cohort)
    reference = load_hiring_reference()
    personal_rates, fits = (
        fit_resolved_stage_rates(state, reference)
        if validated_resolved_cohort else ({}, [])
    )
    weekly_rate = None
    explicit_rates: dict[str, float] = {}
    if overrides:
        if "weekly_application_rate" in overrides:
            weekly_rate = float(overrides["weekly_application_rate"])
        explicit_rates = {
            key: float(value) for key, value in overrides.items() if key in STAGE_CHAIN
        }
    merged_rates = {**personal_rates, **explicit_rates}
    numeric = funnel_state_to_numeric_inputs(
        goal,
        state,
        rates=reference,
        weekly_application_rate=weekly_rate,
        stage_rate_overrides=merged_rates or None,
        now=now,
    )
    if numeric is None:
        return None
    return _annotate_hiring_prediction(
        numeric,
        reference=reference,
        fits=fits,
        explicit_rates=explicit_rates,
        weekly_rate_is_user=weekly_rate is not None,
    )


def _annotate_hiring_prediction(
    numeric: NumericInputs,
    *,
    reference: HiringReferenceRates,
    fits: list[dict[str, Any]],
    explicit_rates: dict[str, float],
    weekly_rate_is_user: bool,
) -> NumericInputs:
    from personal_markets.forecasting.selection import hiring_prediction_block

    offer_observed = bool(
        (numeric.state.get("pricing_transforms") or {}).get("offer_already_received")
    )
    method: Literal["DETERMINISTIC", "FITTED_STATISTICAL", "REFERENCE_MODEL"]
    if offer_observed:
        method = "DETERMINISTIC"
        sufficiency = "observed_success"
    elif fits:
        method = "FITTED_STATISTICAL"
        sufficiency = "resolved_stage_outcomes"
    else:
        method = "REFERENCE_MODEL"
        sufficiency = "reference_only"
    fitted_stages = {row["stage"] for row in fits}
    missing = [stage for stage in STAGE_CHAIN if stage not in fitted_stages and not offer_observed]
    updated_state = dict(numeric.state)
    transforms = dict(updated_state.get("pricing_transforms") or {})
    future = transforms.get("future_application_rate") or {}
    weekly_rate = float(future.get("applications_per_week") or reference.weekly_application_rate)
    block = hiring_prediction_block(
        method=method,
        sufficiency=sufficiency,
        fits=fits,
        missing_stages=missing,
        reference_version=reference.version,
        pseudo_counts=reference.resolved_outcome_pseudo_counts,
        weekly_rate_source="USER_ASSUMPTION" if weekly_rate_is_user else "REFERENCE",
        weekly_rate=weekly_rate,
    )
    notes = list(block["limitations"])
    active = updated_state.get("funnel") or {}
    if active.get("stage_count_inconsistencies"):
        notes.append(
            "Passes plus rejections exceed the reported stock. Active count is zero. "
            "Extra rejections were not assigned to another stage."
        )
    if active.get("unassigned_rejections"):
        notes.append(
            "Rejections that named no stage stay out of every active count."
        )
    if not offer_observed and not fits:
        notes.append(
            "Resolved-stage fitting requires outcomes linked to a validated application cohort; "
            "aggregate stage counts alone retain the reference model."
        )
    block["limitations"] = notes
    transforms["prediction_method"] = method
    transforms["stage_rate_fits"] = fits
    updated_state["pricing_transforms"] = transforms
    updated_state["prediction"] = block
    sources = dict(numeric.assumption_sources)
    if method == "FITTED_STATISTICAL" and not explicit_rates:
        sources["baseline_logits"] = "FITTED"
    elif explicit_rates:
        sources["baseline_logits"] = "USER_ASSUMPTION"
    return replace(numeric, state=updated_state, assumption_sources=sources)


def _priced_inputs(
    *,
    goal: GoalContract,
    state: HiringFunnelState,
    reference: HiringReferenceRates,
    probability: float,
    transforms: dict[str, Any],
    clock: datetime,
) -> NumericInputs:
    periods = max(1, math.ceil((goal.deadline - clock).total_seconds() / 604800))
    hazard = 1.0 - (1.0 - probability) ** (1.0 / periods)
    hazard = min(max(hazard, 1e-6), 1 - 1e-6)
    logit = math.log(hazard / (1.0 - hazard))
    merged = {
        "funnel_state": _active_counts(state),
        "periods_remaining": periods,
        "combined_offer_probability": probability,
        "reference_version": reference.version,
        **transforms,
    }
    return NumericInputs(
        state={
            "baseline_logits": [logit] * periods,
            "periods_remaining": periods,
            "funnel": merged["funnel_state"],
            "pricing_transforms": merged,
        },
        assumptions={},
        assumption_sources={"baseline_logits": "REAL_USER_EVIDENCE"},
    )


def _has_funnel_signal(state: HiringFunnelState) -> bool:
    totals = (
        state.applications,
        state.responses,
        state.phone_screens,
        state.oas,
        state.technicals,
        state.finals,
        state.offers,
    )
    if any(value > 0 for value in totals):
        return True
    return any(count > 0 for count in state.rejections.values())


def _active_counts(state: HiringFunnelState) -> dict[str, Any]:
    """People still waiting at a stage.

    The live path subtracts only observed advances. Rejections are subtracted
    only for a separately validated resolved cohort; aggregate stage totals do
    not establish that they belong to the same applications.
    """
    stages = (
        ("applications", state.applications, state.responses, "application"),
        ("responses", state.responses, state.phone_screens, "response"),
        ("phone_screens", state.phone_screens, state.oas, "phone_screen"),
        ("oas", state.oas, state.technicals, "oa"),
        ("technicals", state.technicals, state.finals, "technical"),
        ("finals", state.finals, state.offers, "final"),
    )
    active: dict[str, Any] = {}
    inconsistent: list[str] = []
    for name, stock, advanced, rejection_key in stages:
        rejected = (
            int(state.rejections.get(rejection_key, 0))
            if state.resolved_cohort_validated else 0
        )
        remaining = stock - advanced - rejected
        if remaining < 0:
            inconsistent.append(name)
        active[name] = max(0, remaining)
    active["offers"] = state.offers
    active["rejections"] = dict(state.rejections)
    active["practice_hours"] = state.practice_hours
    if inconsistent:
        active["stage_count_inconsistencies"] = inconsistent
    unassigned = int(state.rejections.get("unassigned", 0))
    if unassigned:
        active["unassigned_rejections"] = unassigned
    return active


def _pipeline_offer_probability(state: HiringFunnelState, rates: dict[str, float]) -> float:
    active = _active_counts(state)
    stage_entries = (
        ("applications", active["applications"], 0),
        ("responses", active["responses"], 1),
        ("phone_screens", active["phone_screens"], 2),
        ("oas", active["oas"], 3),
        ("technicals", active["technicals"], 4),
        ("finals", active["finals"], 5),
    )
    survival = 1.0
    for _, count, start_index in stage_entries:
        if count <= 0:
            continue
        p_one = _stage_to_offer(rates, start_index)
        survival *= (1.0 - p_one) ** count
    return 1.0 - survival


def _expected_new_pipeline_offers(
    weekly_rate: float, periods: int, rates: dict[str, float]
) -> float:
    if weekly_rate <= 0 or periods <= 0:
        return 0.0
    expected_apps = weekly_rate * periods
    p_one = _stage_to_offer(rates, 0)
    # Poisson-style approximation for many small independent attempts.
    return float(1.0 - (1.0 - p_one) ** expected_apps)


def _stage_to_offer(rates: dict[str, float], start_index: int) -> float:
    prob = 1.0
    for key in STAGE_CHAIN[start_index:]:
        prob *= float(rates[key])
    return float(prob)


def _combine_independent(probabilities: list[float]) -> float:
    survival = 1.0
    for value in probabilities:
        survival *= 1.0 - min(max(value, 0.0), 1.0)
    return 1.0 - survival


def _recency_factor(
    state: HiringFunnelState, reference: HiringReferenceRates, now: datetime
) -> float:
    if state.last_activity_at is None:
        return 1.0
    days = max(0.0, (now - state.last_activity_at).total_seconds() / 86400.0)
    if days <= 0:
        return 1.0
    decay = 0.5 ** (days / reference.recency_half_life_days)
    return float(reference.recency_floor + (1.0 - reference.recency_floor) * decay)


def _event_count(item: NormalizedEvidence) -> int:
    if item.numeric_value is not None and item.numeric_value >= 0:
        return int(round(item.numeric_value))
    return 1


# A free-text summary can name a stage only when the metric is not itself a distinct activity.
_GENERIC_METRICS = frozenset(
    {
        "",
        "activity",
        "count",
        "event",
        "interview_stage",
        "note",
        "notes",
        "observation",
        "outcome",
        "stage",
        "update",
    }
)


def _resolve_stage(
    metric: str, event_type: str, category: str, summary: str, unit: str = ""
) -> str:
    structured = " ".join(part for part in (metric, event_type, category, unit) if part)
    stage = _classify_stage(structured)
    if stage != "unrelated":
        return stage
    if metric.strip() in {"stage", "interview_stage"} and category:
        mapping = {
            "application": "application",
            "response": "response",
            "phone_screen": "phone_screen",
            "technical_screen": "technical",
            "technical": "technical",
            "onsite": "final",
            "final": "final",
            "offer": "offer",
        }
        return mapping.get(category, "technical")
    if metric.strip() in _GENERIC_METRICS:
        return _classify_stage(" ".join(part for part in (summary, unit) if part))
    return "unrelated"


def _classify_stage(blob: str) -> str:
    if _matches(blob, ("offer_received", "signed_offer", "offer", "received offer")):
        return "offer"
    if _matches(blob, ("reject", "rejected", "declined", "failed screen", "no offer")):
        return "rejection"
    if _matches(
        blob,
        (
            "application",
            "applications_submitted",
            "applied",
            "submitted application",
        ),
    ):
        return "application"
    if _matches(blob, ("recruiter", "response", "reply", "callback")):
        return "response"
    if _matches(blob, ("phone screen", "phone_screen", "recruiter screen", "initial screen")):
        return "phone_screen"
    if _matches(blob, ("online assessment", "online_assessment", "oa", "hackerrank", "codesignal")):
        return "oa"
    if _matches(
        blob,
        ("technical", "technical_screen", "technical interview", "coding interview", "onsite"),
    ):
        if "final" in blob or "onsite" in blob:
            return "final"
        return "technical"
    if _matches(blob, ("final round", "final_round", "final interview", "onsite loop")):
        return "final"
    if _matches(blob, ("practice_hours", "prep_hours", "study_hours")) or (
        _matches(blob, ("practice", "study", "prep")) and "hour" in blob
    ):
        return "practice"
    if "interview" in blob:
        return "technical"
    return "unrelated"


def _rejection_stage(metric: str, event_type: str, category: str, summary: str) -> str:
    """Name the stage that rejected the opportunity. Unknown text stays unassigned."""
    blob = " ".join([metric, event_type, category, summary])
    if _matches(blob, ("final", "onsite")):
        return "final"
    if _matches(blob, ("technical", "coding")):
        return "technical"
    if metric.strip() in {"oa", "online_assessment", "hackerrank", "codesignal"}:
        return "oa"
    if _matches(blob, ("online assessment", "online_assessment", "hackerrank", "codesignal")):
        return "oa"
    if _matches(blob, ("phone screen", "phone_screen", "recruiter screen")):
        return "phone_screen"
    if _matches(blob, ("application", "resume", "applied")):
        return "application"
    if _matches(blob, ("response", "reply", "callback")):
        return "response"
    if _matches(blob, ("phone",)):
        return "phone_screen"
    return "unassigned"


def _matches(blob: str, tokens: tuple[str, ...]) -> bool:
    return any(token in blob for token in tokens)
