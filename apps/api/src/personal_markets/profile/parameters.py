from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from personal_markets.behavior.domain import (
    BehaviorDimension,
    BehaviorProfile,
    DimensionProvenance,
    ExecutionEstimate,
)
from personal_markets.evidence.domain import NormalizedEvidence, Provenance

ESTIMATOR_VERSION = "parameter_profile@1.0.0"


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    id: str
    name: str
    meaning: str
    measurement: str
    metric_keys: tuple[str, ...]
    unit: str
    scale_min: float
    scale_max: float
    horizon_days: int = 90


# Measurable presets. These are not the rejected six execution traits
# and are not life-area or goal-name labels.
PARAMETER_PRESETS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        id="weekly_applications",
        name="Weekly applications",
        meaning="How many targeted applications you send in a typical week.",
        measurement="Average applications per week in the selected window",
        metric_keys=("applications_per_week", "weekly_application_rate", "applications_submitted"),
        unit="per week",
        scale_min=0,
        scale_max=20,
    ),
    ParameterSpec(
        id="weekly_focus_hours",
        name="Focused hours",
        meaning="Hours each week spent in deliberate practice on the tracked goal.",
        measurement="Average focused hours per week",
        metric_keys=("hours_per_week", "focused_hours", "hours_on_startup_per_week"),
        unit="hours/week",
        scale_min=0,
        scale_max=20,
    ),
    ParameterSpec(
        id="monthly_savings",
        name="Monthly savings",
        meaning="Cash you add toward the financial target each month.",
        measurement="Average monthly contribution",
        metric_keys=("monthly_contribution", "contribution_per_month", "flow"),
        unit="currency/month",
        scale_min=0,
        scale_max=5000,
    ),
    ParameterSpec(
        id="weekly_running_km",
        name="Weekly running",
        meaning="Distance you run in a typical week.",
        measurement="Average weekly distance",
        metric_keys=("weekly_distance_km", "weekly_running_km", "weekly_distance"),
        unit="km/week",
        scale_min=0,
        scale_max=60,
    ),
    ParameterSpec(
        id="books_per_month",
        name="Books finished",
        meaning="How many books you complete in a month.",
        measurement="Average books finished per month",
        metric_keys=("books_read", "books_per_month", "reading_pace"),
        unit="books/month",
        scale_min=0,
        scale_max=6,
    ),
    ParameterSpec(
        id="sleep_hours",
        name="Sleep",
        meaning="Typical nightly sleep, when you have recorded it.",
        measurement="Average sleep hours per night",
        metric_keys=("sleep_hours_per_night", "sleep_hours"),
        unit="hours/night",
        scale_min=4,
        scale_max=9,
    ),
)


def _normalize(value: float, spec: ParameterSpec) -> float:
    span = spec.scale_max - spec.scale_min
    if span <= 0:
        return 0.0
    return max(0.0, min(1.0, (value - spec.scale_min) / span))


def _observations(
    spec: ParameterSpec,
    evidence: list[NormalizedEvidence],
    *,
    as_of: datetime,
) -> list[tuple[datetime, float]]:
    cutoff = as_of - timedelta(days=spec.horizon_days)
    rows: list[tuple[datetime, float]] = []
    for item in evidence:
        if item.numeric_value is None:
            continue
        if item.metric not in spec.metric_keys:
            continue
        stamp = item.observed_at or as_of
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        if stamp < cutoff:
            continue
        rows.append((stamp, float(item.numeric_value)))
    return rows


def _dimension_from_spec(
    spec: ParameterSpec,
    evidence: list[NormalizedEvidence],
    *,
    as_of: datetime,
) -> BehaviorDimension:
    rows = _observations(spec, evidence, as_of=as_of)
    n = len(rows)
    limited = n < 2
    mean = sum(value for _, value in rows) / n if n else None
    normalized = _normalize(mean, spec) if mean is not None else None
    sources = sorted(
        {
            item.provenance.source_type
            for item in evidence
            if item.metric in spec.metric_keys and item.numeric_value is not None
        }
    )
    confidence = "insufficient" if limited else "low" if n < 4 else "medium" if n < 8 else "high"
    return BehaviorDimension(
        key=spec.id,
        label=spec.name,
        value=None if limited else normalized,
        display_percent=None if limited or normalized is None else int(round(normalized * 100)),
        limited_evidence=limited,
        confidence=confidence,  # type: ignore[arg-type]
        provenance=DimensionProvenance(
            comparable_commitments=n,
            completed=n,
            recency_weighted_completion=mean,
            evidence_window_days=float(spec.horizon_days),
            sources=sources,
            n_eff=float(n),
            formula=spec.measurement,
            details=[
                spec.meaning,
                f"Scale {spec.scale_min:g}–{spec.scale_max:g} {spec.unit}",
                f"{n} observations in the last {spec.horizon_days} days",
                *(
                    [f"Current average {mean:.2f} {spec.unit}"]
                    if mean is not None
                    else ["No measured value yet"]
                ),
            ],
        ),
    )


def build_parameter_profile(
    evidence: list[NormalizedEvidence],
    *,
    selected_ids: list[str] | None = None,
    as_of: datetime | None = None,
    demo: bool = False,
) -> BehaviorProfile:
    stamp = as_of or datetime.now(UTC)
    wanted = set(selected_ids) if selected_ids else {item.id for item in PARAMETER_PRESETS}
    specs = [item for item in PARAMETER_PRESETS if item.id in wanted]
    dimensions = [_dimension_from_spec(item, evidence, as_of=stamp) for item in specs]
    if not demo:
        dimensions = [item for item in dimensions if item.provenance.comparable_commitments]
    measured = [item for item in dimensions if not item.limited_evidence and item.value is not None]
    n_eff = sum(item.provenance.n_eff for item in dimensions)
    sufficiency = "high" if len(measured) >= 3 else "low" if measured else "insufficient"
    return BehaviorProfile(
        estimator_version=ESTIMATOR_VERSION,
        as_of=stamp,
        execution=ExecutionEstimate(
            probability=0.0,
            interval=(0.0, 0.0),
            n_eff=n_eff,
            n_raw=int(n_eff),
            confidence=sufficiency,
            source="PRIOR" if demo else "FITTED",
            half_life_days=float(max((item.horizon_days for item in specs), default=90)),
            global_mean=0.0,
            domain_mean=0.0,
            action_mean=0.0,
            usable=bool(measured),
            notes=["Demonstration data. This is not your profile."] if demo else [],
        ),
        dimensions=dimensions,
        disclaimer=(
            "Demonstration profile computed from isolated fixture observations."
            if demo
            else (
                "Axes are measurable parameters you selected, "
                "not personality traits or goal names."
            )
        ),
        evidence_sufficiency=sufficiency,
        n_raw=sum(item.provenance.comparable_commitments for item in dimensions),
        n_eff=n_eff,
    )


def flatten_goal_evidence(
    evidence_by_goal: dict[str, list[NormalizedEvidence]],
) -> list[NormalizedEvidence]:
    rows: list[NormalizedEvidence] = []
    for items in evidence_by_goal.values():
        rows.extend(items)
    return rows


def _event(
    metric: str,
    value: float,
    *,
    days_ago: int,
    domain: str,
    unit: str,
    as_of: datetime,
) -> NormalizedEvidence:
    observed = as_of - timedelta(days=days_ago)
    return NormalizedEvidence(
        evidence_id=uuid4(),
        event_type="observation",
        domain=domain,
        metric=metric,
        numeric_value=value,
        unit=unit,
        observed_at=observed,
        source_quality="demo_fixture",
        provenance=Provenance(
            source_type="manual",
            source_authority="self_report",
            observed_vs_entered="user_entered",
            parsing_status="ok",
            completeness="complete",
            conflict_status="none",
        ),
        summary=f"{metric}={value}",
        fingerprint=f"demo:{metric}:{days_ago}:{value}",
    )


def demo_parameter_evidence(*, as_of: datetime | None = None) -> list[NormalizedEvidence]:
    """Isolated synthetic observations. Never write these onto a real user."""
    stamp = as_of or datetime.now(UTC)
    rows: list[NormalizedEvidence] = []
    applications = [14, 12, 16, 9, 18, 15, 11, 17]
    for index, value in enumerate(applications):
        rows.append(
            _event(
                "applications_per_week",
                value,
                days_ago=7 * (len(applications) - index),
                domain="career",
                unit="per week",
                as_of=stamp,
            )
        )
    hours = [6.0, 8.5, 7.0, 5.5, 9.0, 8.0]
    for index, value in enumerate(hours):
        rows.append(
            _event(
                "hours_per_week",
                value,
                days_ago=10 * (len(hours) - index),
                domain="career",
                unit="hours/week",
                as_of=stamp,
            )
        )
    savings = [900, 1100, 800, 1400, 1250]
    for index, value in enumerate(savings):
        rows.append(
            _event(
                "monthly_contribution",
                value,
                days_ago=20 * (len(savings) - index),
                domain="finance",
                unit="CAD/month",
                as_of=stamp,
            )
        )
    running = [18.0, 22.0, 12.0, 28.0, 24.0, 30.0, 21.0]
    for index, value in enumerate(running):
        rows.append(
            _event(
                "weekly_distance_km",
                value,
                days_ago=8 * (len(running) - index),
                domain="running",
                unit="km/week",
                as_of=stamp,
            )
        )
    books = [1.0, 2.0, 1.0, 3.0]
    for index, value in enumerate(books):
        rows.append(
            _event(
                "books_read",
                value,
                days_ago=21 * (len(books) - index),
                domain="learning",
                unit="books/month",
                as_of=stamp,
            )
        )
    # Sparse sleep: a single point is not enough to score the axis.
    rows.append(
        _event(
            "sleep_hours_per_night",
            6.4,
            days_ago=12,
            domain="health",
            unit="hours",
            as_of=stamp,
        )
    )
    return rows


def demo_parameter_profile(*, as_of: datetime | None = None) -> BehaviorProfile:
    stamp = as_of or datetime.now(UTC)
    return build_parameter_profile(demo_parameter_evidence(as_of=stamp), as_of=stamp, demo=True)
