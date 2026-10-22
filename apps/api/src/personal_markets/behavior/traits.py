"""Person-level execution traits estimated from planned-versus-observed behavior.

Traits describe how someone pursues goals (follow-through, plan realism, focus,
time management, consistency, recovery). They are not activity quantities such
as applications per week or kilometres run; those stay goal evidence.

Every trait is a pure function of commitment trials and typed evidence. A trait
without enough comparable observations returns no value rather than a default.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, field_validator

from personal_markets.behavior.domain import CommitmentTrial, Confidence
from personal_markets.behavior.model import beta_posterior, credible_interval, recency_weights
from personal_markets.evidence.domain import NormalizedEvidence

TRAIT_ESTIMATOR_VERSION = "behavior_traits_v1"

# Recency half-life for trait evidence (days). Shared with the execution model default.
TRAIT_HALF_LIFE_DAYS = 21.0
# Window used for the "change" readout on each trait.
TRAIT_CHANGE_WINDOW_DAYS = 28
# Pseudo-observations that shrink ratio-based traits toward an uninformative 0.5.
RATIO_SHRINKAGE_K = 4.0
# Comparable weeks needed before week-to-week consistency is meaningful.
MIN_CONSISTENCY_WEEKS = 4
# A commitment counts as on time when it was resolved within this many days of its window.
ON_TIME_TOLERANCE_DAYS = 1.0
# A context series is drawn only with at least this many trials in that context.
MIN_CONTEXT_TRIALS = 6

ForecastUse = Literal["execution_probability", "exploratory"]
Context = Literal["career", "personal", "relationships"]

CONTEXT_LABELS: dict[str, str] = {
    "overall": "Overall",
    "career": "Career",
    "personal": "Personal",
    "relationships": "Relationships",
}

_CONTEXT_DOMAINS: dict[str, frozenset[str]] = {
    "career": frozenset(
        {
            "career",
            "hiring",
            "job",
            "work",
            "startup",
            "fundraising",
            "engineering",
            "coding",
            "project",
            "technical",
            "interview",
            "business",
        }
    ),
    "relationships": frozenset(
        {"relationships", "relationship", "family", "friends", "social", "partner", "community"}
    ),
    "personal": frozenset(
        {
            "personal",
            "health",
            "fitness",
            "running",
            "reading",
            "learning",
            "finance",
            "savings",
            "sleep",
            "wellbeing",
            "creative",
            "music",
        }
    ),
}


def context_for_domain(domain: str | None) -> Context | None:
    token = (domain or "").strip().lower()
    for context, members in _CONTEXT_DOMAINS.items():
        if token in members or any(part in members for part in re.split(r"[_\-\s/]+", token)):
            return context  # type: ignore[return-value]
    return None


@dataclass(frozen=True, slots=True)
class TraitSpec:
    id: str
    name: str
    description: str
    measurement: str
    evidence: tuple[str, ...]
    forecast_use: ForecastUse
    min_observations: float


BUILT_IN_TRAITS: tuple[TraitSpec, ...] = (
    TraitSpec(
        id="discipline",
        name="Discipline",
        description="How reliably you carry out actions you committed to.",
        measurement="Recency-weighted share of committed actions completed.",
        evidence=("Planned commitments and their observed outcomes",),
        forecast_use="execution_probability",
        min_observations=4,
    ),
    TraitSpec(
        id="realism",
        name="Goal realism",
        description="How closely what you plan matches what you actually deliver.",
        measurement="Typical gap between planned and delivered amounts, in either direction.",
        evidence=("Planned versus delivered quantities", "Estimated versus actual durations"),
        forecast_use="exploratory",
        min_observations=4,
    ),
    TraitSpec(
        id="focus",
        name="Focus",
        description="How much of a scheduled work block turns into on-task work.",
        measurement="Recency-weighted on-task share of scheduled focus sessions.",
        evidence=("Focus sessions with on-task share",),
        forecast_use="exploratory",
        min_observations=4,
    ),
    TraitSpec(
        id="time_management",
        name="Time management",
        description="Whether your commitments fit your available time and land on schedule.",
        measurement="On-time completion rate, discounted when committed hours exceed capacity.",
        evidence=("Commitment completion dates", "Available versus committed weekly hours"),
        forecast_use="exploratory",
        min_observations=4,
    ),
    TraitSpec(
        id="consistency",
        name="Consistency",
        description="How steady your follow-through is from week to week.",
        measurement="One minus the spread of weekly completion rates.",
        evidence=("Commitments across at least four weeks",),
        forecast_use="exploratory",
        min_observations=MIN_CONSISTENCY_WEEKS,
    ),
    TraitSpec(
        id="recovery",
        name="Recovery",
        description="How quickly you get back on track after missing a commitment.",
        measurement="Share of misses followed by a completed commitment within seven days.",
        evidence=("Missed commitments and what happened next",),
        forecast_use="exploratory",
        min_observations=3,
    ),
)

BUILT_IN_BY_ID = {item.id: item for item in BUILT_IN_TRAITS}
DEFAULT_TRAIT_IDS: tuple[str, ...] = (
    "discipline",
    "realism",
    "focus",
    "time_management",
    "consistency",
)
CUSTOM_PREFIX = "custom:"
CUSTOM_METRIC_PREFIX = "trait_"


class CustomTraitDefinition(BaseModel):
    """A user-defined trait. It is scored only from evidence on its own metric."""

    id: str = Field(min_length=8, max_length=48)
    name: str = Field(min_length=2, max_length=32)
    description: str = Field(min_length=4, max_length=160)
    metric: str = Field(min_length=7, max_length=48)
    scale_min: float = 0.0
    scale_max: float = 1.0

    @field_validator("id")
    @classmethod
    def _custom_id(cls, value: str) -> str:
        if not value.startswith(CUSTOM_PREFIX):
            raise ValueError("custom trait ids start with 'custom:'")
        return value

    @field_validator("metric")
    @classmethod
    def _metric(cls, value: str) -> str:
        if not value.startswith(CUSTOM_METRIC_PREFIX) or not re.fullmatch(r"[a-z0-9_]+", value):
            raise ValueError("custom trait metrics are lowercase and start with 'trait_'")
        return value


def custom_trait_from_name(name: str, description: str) -> CustomTraitDefinition:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")[:36] or "trait"
    return CustomTraitDefinition(
        id=f"{CUSTOM_PREFIX}{slug}",
        name=name.strip(),
        description=description.strip(),
        metric=f"{CUSTOM_METRIC_PREFIX}{slug}",
    )


class TraitScore(BaseModel):
    value: float | None = Field(default=None, ge=0, le=1)
    interval: tuple[float, float] | None = None
    n_eff: float = 0.0
    observations: int = 0
    confidence: Confidence = "insufficient"


class TraitEstimate(BaseModel):
    id: str
    name: str
    description: str
    measurement: str
    evidence: list[str]
    custom: bool = False
    forecast_use: ForecastUse = "exploratory"
    value: float | None = Field(default=None, ge=0, le=1)
    interval: tuple[float, float] | None = None
    n_eff: float = 0.0
    observations: int = 0
    confidence: Confidence = "insufficient"
    previous_value: float | None = Field(default=None, ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    window_days: float | None = None


class TraitSeries(BaseModel):
    id: str
    label: str
    values: dict[str, float | None]


class TraitProfile(BaseModel):
    estimator_version: str = TRAIT_ESTIMATOR_VERSION
    as_of: datetime
    traits: list[TraitEstimate]
    series: list[TraitSeries]
    trial_count: int
    evidence_count: int


def _confidence(n_eff: float, minimum: float) -> Confidence:
    if n_eff < minimum:
        return "insufficient"
    if n_eff < minimum * 2:
        return "low"
    if n_eff < minimum * 4:
        return "medium"
    return "high"


def _stamp(value: datetime | None, fallback: datetime) -> datetime:
    stamp = value or fallback
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def _weights(stamps: list[datetime], as_of: datetime) -> np.ndarray:
    ages = np.array([max(0.0, (as_of - item).total_seconds() / 86400) for item in stamps])
    return recency_weights(ages, TRAIT_HALF_LIFE_DAYS)


def _beta_score(
    outcomes: list[float], stamps: list[datetime], as_of: datetime, minimum: float
) -> TraitScore:
    if not outcomes:
        return TraitScore()
    weights = _weights(stamps, as_of)
    post = beta_posterior(np.array(outcomes, dtype=float), weights)
    confidence = _confidence(post.n_eff, minimum)
    if confidence == "insufficient":
        return TraitScore(n_eff=post.n_eff, observations=len(outcomes))
    return TraitScore(
        value=post.mean,
        interval=credible_interval(post.alpha, post.beta),
        n_eff=post.n_eff,
        observations=len(outcomes),
        confidence=confidence,
    )


def _shrunk_mean_score(values: list[float], minimum: float) -> TraitScore:
    """Mean of [0, 1] scores shrunk toward 0.5 with a normal-approximation interval."""
    n = len(values)
    confidence = _confidence(float(n), minimum)
    if confidence == "insufficient":
        return TraitScore(n_eff=float(n), observations=n)
    arr = np.clip(np.array(values, dtype=float), 0.0, 1.0)
    lam = n / (n + RATIO_SHRINKAGE_K)
    mean = float(lam * arr.mean() + (1 - lam) * 0.5)
    spread = float(arr.std(ddof=1)) if n > 1 else 0.25
    width = 1.28155 * max(spread, 0.05) / math.sqrt(n)
    return TraitScore(
        value=mean,
        interval=(max(0.0, mean - width), min(1.0, mean + width)),
        n_eff=float(n),
        observations=n,
        confidence=confidence,
    )


def discipline_score(trials: list[CommitmentTrial], as_of: datetime) -> TraitScore:
    return _beta_score(
        [item.outcome for item in trials],
        [item.observed_at for item in trials],
        as_of,
        BUILT_IN_BY_ID["discipline"].min_observations,
    )


def realism_score(trials: list[CommitmentTrial]) -> TraitScore:
    """exp(-|log(delivered / planned)|): 1 when plans match delivery, lower for any gap.

    Over-delivery also lowers the score, so this measures calibration, not effort.
    Missed commitments with no delivered quantity are follow-through evidence and
    are excluded here.
    """
    values = []
    for item in trials:
        if not item.planned_amount or item.planned_amount <= 0:
            continue
        if item.realized_amount is None or item.realized_amount <= 0:
            continue
        values.append(math.exp(-abs(math.log(item.realized_amount / item.planned_amount))))
    return _shrunk_mean_score(values, BUILT_IN_BY_ID["realism"].min_observations)


FOCUS_METRICS = frozenset({"focus_ratio", "on_task_share", "deep_work_ratio"})
CAPACITY_METRIC = "available_hours_per_week"
COMMITTED_HOURS_METRIC = "committed_hours_per_week"


def focus_score(evidence: list[NormalizedEvidence], as_of: datetime) -> TraitScore:
    rows = [
        (item, float(item.numeric_value))
        for item in evidence
        if item.metric in FOCUS_METRICS and item.numeric_value is not None
    ]
    if not rows:
        return TraitScore()
    shares = [min(1.0, max(0.0, value if value <= 1 else value / 100.0)) for _, value in rows]
    return _beta_score(
        shares,
        [_stamp(item.observed_at, as_of) for item, _ in rows],
        as_of,
        BUILT_IN_BY_ID["focus"].min_observations,
    )


def capacity_fit(evidence: list[NormalizedEvidence]) -> float | None:
    """Latest available/committed hours ratio, capped at 1. None without both readings."""

    def latest(metric: str) -> float | None:
        rows = [
            item
            for item in evidence
            if item.metric == metric and item.numeric_value is not None and item.observed_at
        ]
        if not rows:
            return None
        newest = max(rows, key=lambda item: item.observed_at or datetime.min.replace(tzinfo=UTC))
        return float(newest.numeric_value or 0.0)

    available = latest(CAPACITY_METRIC)
    committed = latest(COMMITTED_HOURS_METRIC)
    if available is None or committed is None or committed <= 0:
        return None
    return min(1.0, max(0.0, available / committed))


def time_management_score(
    trials: list[CommitmentTrial], evidence: list[NormalizedEvidence], as_of: datetime
) -> TraitScore:
    resolved = [item for item in trials if item.delay_days is not None]
    on_time = [
        1.0 if item.outcome >= 0.5 and (item.delay_days or 0.0) <= ON_TIME_TOLERANCE_DAYS else 0.0
        for item in resolved
    ]
    score = _beta_score(
        on_time,
        [item.observed_at for item in resolved],
        as_of,
        BUILT_IN_BY_ID["time_management"].min_observations,
    )
    fit = capacity_fit(evidence)
    if score.value is None or fit is None:
        return score
    low, high = score.interval or (score.value, score.value)
    return score.model_copy(
        update={"value": score.value * fit, "interval": (low * fit, high * fit)}
    )


def consistency_score(trials: list[CommitmentTrial]) -> TraitScore:
    weekly: dict[str, list[float]] = defaultdict(list)
    for item in trials:
        year, week, _ = item.observed_at.astimezone(UTC).isocalendar()
        weekly[f"{year}-{week:02d}"].append(item.outcome)
    rates = [float(np.mean(values)) for values in weekly.values()]
    n = len(rates)
    confidence = _confidence(float(n), BUILT_IN_BY_ID["consistency"].min_observations)
    if confidence == "insufficient":
        return TraitScore(n_eff=float(n), observations=n)
    # Max std of [0,1] rates is 0.5, so 2*std maps spread onto [0, 1].
    spread = min(1.0, 2.0 * float(np.std(rates)))
    raw = 1.0 - spread
    lam = n / (n + RATIO_SHRINKAGE_K)
    value = lam * raw + (1 - lam) * 0.5
    width = 1.28155 * 0.5 / math.sqrt(n)
    return TraitScore(
        value=value,
        interval=(max(0.0, value - width), min(1.0, value + width)),
        n_eff=float(n),
        observations=n,
        confidence=confidence,
    )


def recovery_score(trials: list[CommitmentTrial], horizon_days: float = 7.0) -> TraitScore:
    ordered = sorted(trials, key=lambda item: item.observed_at)
    outcomes: list[float] = []
    stamps: list[datetime] = []
    for index, item in enumerate(ordered):
        if item.outcome >= 0.5:
            continue
        resumed = 0.0
        for later in ordered[index + 1 :]:
            if (later.observed_at - item.observed_at).total_seconds() / 86400 > horizon_days:
                break
            if later.outcome >= 0.5:
                resumed = 1.0
                break
        outcomes.append(resumed)
        stamps.append(item.observed_at)
    if not outcomes:
        return TraitScore()
    return _beta_score(outcomes, stamps, max(stamps), BUILT_IN_BY_ID["recovery"].min_observations)


def custom_score(
    definition: CustomTraitDefinition, evidence: list[NormalizedEvidence], as_of: datetime
) -> TraitScore:
    span = definition.scale_max - definition.scale_min
    rows = [
        item
        for item in evidence
        if item.metric == definition.metric and item.numeric_value is not None
    ]
    if not rows or span <= 0:
        return TraitScore()
    shares = [
        min(1.0, max(0.0, (float(item.numeric_value or 0.0) - definition.scale_min) / span))
        for item in rows
    ]
    return _beta_score(shares, [_stamp(item.observed_at, as_of) for item in rows], as_of, 4)


def _score_for(
    trait_id: str,
    trials: list[CommitmentTrial],
    evidence: list[NormalizedEvidence],
    as_of: datetime,
    custom: dict[str, CustomTraitDefinition],
) -> TraitScore:
    if trait_id in custom:
        return custom_score(custom[trait_id], evidence, as_of)
    scorers: dict[str, Callable[[], TraitScore]] = {
        "discipline": lambda: discipline_score(trials, as_of),
        "realism": lambda: realism_score(trials),
        "focus": lambda: focus_score(evidence, as_of),
        "time_management": lambda: time_management_score(trials, evidence, as_of),
        "consistency": lambda: consistency_score(trials),
        "recovery": lambda: recovery_score(trials),
    }
    scorer = scorers.get(trait_id)
    return scorer() if scorer else TraitScore()


def _sources(
    trait_id: str,
    trials: list[CommitmentTrial],
    evidence: list[NormalizedEvidence],
    custom: dict[str, CustomTraitDefinition],
) -> list[str]:
    if trait_id in custom:
        metric = custom[trait_id].metric
        return sorted({item.provenance.source_type for item in evidence if item.metric == metric})
    if trait_id == "focus":
        return sorted(
            {item.provenance.source_type for item in evidence if item.metric in FOCUS_METRICS}
        )
    return sorted({item.source for item in trials})


def _before(
    trials: list[CommitmentTrial], evidence: list[NormalizedEvidence], cutoff: datetime
) -> tuple[list[CommitmentTrial], list[NormalizedEvidence]]:
    return (
        [item for item in trials if item.observed_at <= cutoff],
        [
            item
            for item in evidence
            if item.observed_at is not None and _stamp(item.observed_at, cutoff) <= cutoff
        ],
    )


def estimate_traits(
    trials: Iterable[CommitmentTrial],
    evidence: Iterable[NormalizedEvidence],
    *,
    selected: list[str] | None = None,
    custom: list[CustomTraitDefinition] | None = None,
    as_of: datetime | None = None,
) -> TraitProfile:
    stamp = as_of or datetime.now(UTC)
    trial_rows = [item for item in trials if item.observed_at <= stamp]
    evidence_rows = [
        item
        for item in evidence
        if item.observed_at is None or _stamp(item.observed_at, stamp) <= stamp
    ]
    custom_by_id = {item.id: item for item in custom or []}
    wanted = [
        item
        for item in (selected or list(DEFAULT_TRAIT_IDS))
        if item in BUILT_IN_BY_ID or item in custom_by_id
    ]
    earlier = stamp - timedelta(days=TRAIT_CHANGE_WINDOW_DAYS)
    prior_trials, prior_evidence = _before(trial_rows, evidence_rows, earlier)
    window = None
    if trial_rows:
        window = max(
            1.0, (stamp - min(item.observed_at for item in trial_rows)).total_seconds() / 86400
        )

    traits: list[TraitEstimate] = []
    for trait_id in wanted:
        score = _score_for(trait_id, trial_rows, evidence_rows, stamp, custom_by_id)
        previous = _score_for(trait_id, prior_trials, prior_evidence, earlier, custom_by_id)
        if trait_id in custom_by_id:
            definition = custom_by_id[trait_id]
            name = definition.name
            description = definition.description
            measurement = f"Recency-weighted score from '{definition.metric}' observations."
            sources_text = [f"Observations recorded as {definition.metric}"]
            is_custom = True
            forecast_use: ForecastUse = "exploratory"
        else:
            spec = BUILT_IN_BY_ID[trait_id]
            name = spec.name
            description = spec.description
            measurement = spec.measurement
            sources_text = list(spec.evidence)
            is_custom = False
            forecast_use = spec.forecast_use
        traits.append(
            TraitEstimate(
                id=trait_id,
                name=name,
                description=description,
                measurement=measurement,
                evidence=sources_text,
                custom=is_custom,
                forecast_use=forecast_use,
                value=score.value,
                interval=score.interval,
                n_eff=score.n_eff,
                observations=score.observations,
                confidence=score.confidence,
                previous_value=previous.value if score.value is not None else None,
                sources=_sources(trait_id, trial_rows, evidence_rows, custom_by_id),
                window_days=round(window, 1) if window is not None else None,
            )
        )

    series = [
        TraitSeries(
            id="overall",
            label=CONTEXT_LABELS["overall"],
            values={item.id: item.value for item in traits},
        )
    ]
    by_context: dict[str, list[CommitmentTrial]] = defaultdict(list)
    for trial in trial_rows:
        trial_context = context_for_domain(trial.domain)
        if trial_context is not None:
            by_context[trial_context].append(trial)
    evidence_by_context: dict[str, list[NormalizedEvidence]] = defaultdict(list)
    for observation in evidence_rows:
        evidence_context = context_for_domain(observation.domain)
        if evidence_context is not None:
            evidence_by_context[evidence_context].append(observation)
    contextual: list[TraitSeries] = []
    for context in ("career", "personal", "relationships"):
        rows = by_context.get(context, [])
        if len(rows) < MIN_CONTEXT_TRIALS:
            continue
        values = {
            item.id: _score_for(
                item.id, rows, evidence_by_context.get(context, []), stamp, custom_by_id
            ).value
            for item in traits
        }
        if sum(value is not None for value in values.values()) < 3:
            continue
        contextual.append(TraitSeries(id=context, label=CONTEXT_LABELS[context], values=values))
    if len(contextual) >= 2:
        series = contextual

    return TraitProfile(
        as_of=stamp,
        traits=traits,
        series=series,
        trial_count=len(trial_rows),
        evidence_count=len(evidence_rows),
    )


def available_traits(custom: list[CustomTraitDefinition] | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "measurement": item.measurement,
            "evidence": list(item.evidence),
            "custom": False,
            "forecast_use": item.forecast_use,
        }
        for item in BUILT_IN_TRAITS
    ]
    for item in custom or []:
        rows.append(
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "measurement": f"Recency-weighted score from '{item.metric}' observations.",
                "evidence": [f"Observations recorded as {item.metric}"],
                "custom": True,
                "forecast_use": "exploratory",
                "metric": item.metric,
            }
        )
    return rows
