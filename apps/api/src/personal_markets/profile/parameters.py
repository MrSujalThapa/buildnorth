"""Measured Profile parameters, separate from behavioral execution estimates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Literal

from pydantic import BaseModel, Field

from personal_markets.evidence.domain import NormalizedEvidence

Aggregation = Literal["latest_period", "sum_increments"]


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    id: str
    name: str
    metric: str
    unit: str
    window_days: int
    aggregation: Aggregation
    scale_max: float
    aliases: tuple[str, ...] = ()


PRESETS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        "weekly_applications",
        "Applications / week",
        "applications_per_week",
        "applications/week",
        56,
        "latest_period",
        20,
        ("weekly_application_rate", "applications_submitted"),
    ),
    ParameterSpec(
        "weekly_study_hours",
        "Study hours / week",
        "study_hours_per_week",
        "hours/week",
        56,
        "latest_period",
        30,
        ("focused_hours_per_week", "hours_per_week", "study_hours", "practice_hours"),
    ),
    ParameterSpec(
        "monthly_savings",
        "Monthly savings",
        "monthly_contribution",
        "currency/month",
        120,
        "latest_period",
        5000,
        ("contribution_per_month",),
    ),
    ParameterSpec(
        "weekly_running_km",
        "Running / week",
        "weekly_distance_km",
        "km/week",
        56,
        "latest_period",
        60,
        ("weekly_running_km",),
    ),
    ParameterSpec(
        "reading_minutes",
        "Reading time",
        "reading_minutes",
        "minutes/30 days",
        30,
        "sum_increments",
        1200,
        ("minutes_read",),
    ),
)
BY_ID = {spec.id: spec for spec in PRESETS}
DEFAULT_IDS = [spec.id for spec in PRESETS]
_CURRENCY_CODES = frozenset(
    {
        "aed",
        "aud",
        "brl",
        "cad",
        "chf",
        "cny",
        "dkk",
        "eur",
        "gbp",
        "hkd",
        "inr",
        "jpy",
        "krw",
        "mxn",
        "nok",
        "nzd",
        "sar",
        "sek",
        "sgd",
        "usd",
        "zar",
    }
)


def _currency_unit(unit: str, *, period: bool) -> bool:
    normalized = unit.lower().replace(" ", "")
    if period:
        match = re.fullmatch(r"([a-z]{3}|currency)/(?:month|mo)", normalized)
        return match is not None and (
            match.group(1) == "currency" or match.group(1) in _CURRENCY_CODES
        )
    return normalized in _CURRENCY_CODES


class ParameterEstimate(BaseModel):
    id: str
    name: str
    metric: str
    unit: str
    window_days: int
    aggregation: Aggregation
    normalization: str
    raw_value: float | None = None
    value: float | None = Field(default=None, ge=0, le=1)
    observation_count: int = 0
    source_types: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    last_observed_at: datetime | None = None
    status: Literal["measured", "insufficient"] = "insufficient"
    cohort: Literal["authentic", "workspace_seed"] = "authentic"


class ParameterProfile(BaseModel):
    version: str = "measured_parameters@2.0.0"
    as_of: datetime
    parameters: list[ParameterEstimate]
    evidence_count: int
    synthetic: bool = False


def _compatible(row: NormalizedEvidence, spec: ParameterSpec, *, synthetic: bool) -> bool:
    if row.metric not in (spec.metric, *spec.aliases) or row.numeric_value is None:
        return False
    if not isfinite(row.numeric_value) or row.numeric_value < 0:
        return False
    if row.provenance.parsing_status != "ok" or row.provenance.conflict_status != "none":
        return False
    if not synthetic and row.source_quality in {"demo_fixture", "synthetic_demo"}:
        return False
    kind = row.provenance.observation_kind
    if spec.aggregation == "sum_increments":
        return kind in {"increment", "event"} and (row.unit or "").lower() in {
            "minute",
            "minutes",
            "min",
            "mins",
        }
    if kind not in {"period", "snapshot"}:
        return False
    unit = (row.unit or "").lower().replace(" ", "")
    if spec.id == "monthly_savings":
        return _currency_unit(unit, period=True)
    allowed = {
        "weekly_applications": {
            "applications/week",
            "applicationsperweek",
            "count/week",
            "perweek",
        },
        "weekly_study_hours": {"hours/week", "hour/week", "hr/week", "hrs/week"},
        "weekly_running_km": {"km/week", "kilometers/week", "kilometres/week"},
    }
    return unit in allowed.get(spec.id, set())


def _increment_compatible(row: NormalizedEvidence, spec: ParameterSpec, *, synthetic: bool) -> bool:
    """Recognize dated activity without treating a cumulative snapshot as a weekly event."""
    if row.numeric_value is None or not isfinite(row.numeric_value) or row.numeric_value < 0:
        return False
    if row.provenance.parsing_status != "ok" or row.provenance.conflict_status != "none":
        return False
    if not synthetic and row.source_quality in {"demo_fixture", "synthetic_demo"}:
        return False
    if row.provenance.observation_kind not in {"increment", "event"}:
        return False
    unit = (row.unit or "").lower().replace(" ", "")
    if spec.id == "weekly_applications":
        return row.metric == "applications_submitted" and unit in {
            "count",
            "application",
            "applications",
        }
    if spec.id == "weekly_study_hours":
        return row.metric in {"study_hours", "practice_hours", "focused_hours"} and unit in {
            "hour",
            "hours",
            "hr",
            "hrs",
        }
    if spec.id == "weekly_running_km":
        return row.metric == "weekly_distance_km" and unit in {
            "km",
            "kilometer",
            "kilometers",
            "kilometre",
            "kilometres",
        }
    if spec.id == "monthly_savings":
        return row.metric == "monthly_contribution" and _currency_unit(unit, period=False)
    return False


def parameter_profile(
    evidence: list[NormalizedEvidence],
    *,
    selected_ids: list[str] | None = None,
    as_of: datetime | None = None,
    synthetic: bool = False,
) -> ParameterProfile:
    stamp = as_of or datetime.now(UTC)
    wanted = selected_ids if selected_ids is not None else DEFAULT_IDS
    estimates: list[ParameterEstimate] = []
    used: set[str] = set()
    for identifier in wanted:
        spec = BY_ID.get(identifier)
        if spec is None:
            continue
        cutoff = stamp - timedelta(days=spec.window_days)
        period_rows = [
            row
            for row in evidence
            if _compatible(row, spec, synthetic=synthetic)
            and row.observed_at is not None
            and cutoff <= row.observed_at <= stamp
        ]
        increment_window = 30 if spec.id == "monthly_savings" else 7
        increment_cutoff = stamp - timedelta(days=increment_window)
        increment_rows = [
            row
            for row in evidence
            if _increment_compatible(row, spec, synthetic=synthetic)
            and row.observed_at is not None
            and increment_cutoff <= row.observed_at <= stamp
        ]
        # A later period reading supersedes component activity. Otherwise use
        # the explicitly dated increments in the corresponding rolling window.
        latest_period = max(
            (row.observed_at for row in period_rows if row.observed_at is not None),
            default=None,
        )
        latest_increment = max(
            (row.observed_at for row in increment_rows if row.observed_at is not None),
            default=None,
        )
        use_increments = bool(increment_rows) and (
            latest_period is None
            or latest_increment is not None
            and latest_increment > latest_period
        )
        rows = increment_rows if use_increments else period_rows
        # One normalized observation may be linked to multiple owned goals.
        distinct = {
            str(row.provenance.event_identity or row.evidence_id or row.fingerprint): row
            for row in rows
        }
        rows = sorted(distinct.values(), key=lambda row: (row.observed_at, str(row.evidence_id)))
        if (
            spec.id == "monthly_savings"
            and len({(row.unit or "").split("/")[0].upper() for row in rows}) > 1
        ):
            rows = []  # CAD and USD are not interchangeable.
        used.update(str(row.evidence_id or row.fingerprint) for row in rows)
        effective_aggregation: Aggregation = (
            "sum_increments" if use_increments else spec.aggregation
        )
        raw = (
            sum(row.numeric_value or 0 for row in rows)
            if effective_aggregation == "sum_increments" and rows
            else rows[-1].numeric_value
            if rows
            else None
        )
        estimates.append(
            ParameterEstimate(
                id=spec.id,
                name=spec.name,
                metric=spec.metric,
                unit=(
                    f"{rows[-1].unit}/30 days"
                    if spec.id == "monthly_savings" and rows and use_increments
                    else rows[-1].unit
                    if spec.id == "monthly_savings" and rows
                    else spec.unit
                )
                or spec.unit,
                window_days=increment_window if use_increments else spec.window_days,
                aggregation=effective_aggregation,
                normalization=(
                    f"clamp(value / {spec.scale_max:g}, 0, 1); display scale, not goal odds"
                ),
                raw_value=raw,
                value=min(1.0, max(0.0, raw / spec.scale_max)) if raw is not None else None,
                observation_count=len(rows),
                source_types=sorted({row.provenance.source_type for row in rows}),
                evidence_ids=[str(row.evidence_id or row.fingerprint) for row in rows],
                last_observed_at=rows[-1].observed_at if rows else None,
                status="measured" if rows else "insufficient",
            )
        )
    return ParameterProfile(
        as_of=stamp, parameters=estimates, evidence_count=len(used), synthetic=synthetic
    )


def merge_parameter_profiles(
    authentic: ParameterProfile, seed: ParameterProfile | None
) -> ParameterProfile:
    """Authentic measurements win per parameter; seeded ones fill only empty axes."""
    if seed is None:
        return authentic
    by_id = {item.id: item for item in seed.parameters}
    merged: list[ParameterEstimate] = []
    filled = 0
    for item in authentic.parameters:
        fallback = by_id.get(item.id)
        if item.status != "measured" and fallback is not None and fallback.status == "measured":
            merged.append(fallback.model_copy(update={"cohort": "workspace_seed"}))
            filled += fallback.observation_count
        else:
            merged.append(item)
    return authentic.model_copy(
        update={
            "parameters": merged,
            "evidence_count": authentic.evidence_count + filled,
            "synthetic": filled > 0,
        }
    )
