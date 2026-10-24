"""Measured Profile parameters, separate from behavioral execution estimates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
        ("weekly_application_rate",),
    ),
    ParameterSpec(
        "weekly_study_hours",
        "Study hours / week",
        "study_hours_per_week",
        "hours/week",
        56,
        "latest_period",
        30,
        ("focused_hours_per_week", "hours_per_week"),
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
    status: Literal["measured", "insufficient"] = "insufficient"


class ParameterProfile(BaseModel):
    version: str = "measured_parameters@2.0.0"
    as_of: datetime
    parameters: list[ParameterEstimate]
    evidence_count: int
    synthetic: bool = False


def _compatible(row: NormalizedEvidence, spec: ParameterSpec, *, synthetic: bool) -> bool:
    if row.metric not in (spec.metric, *spec.aliases) or row.numeric_value is None:
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
        return unit.endswith("/month") or unit.endswith("/mo")
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
        rows = [
            row
            for row in evidence
            if _compatible(row, spec, synthetic=synthetic)
            and row.observed_at is not None
            and cutoff <= row.observed_at <= stamp
        ]
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
        raw = (
            sum(row.numeric_value or 0 for row in rows)
            if spec.aggregation == "sum_increments" and rows
            else rows[-1].numeric_value
            if rows
            else None
        )
        estimates.append(
            ParameterEstimate(
                id=spec.id,
                name=spec.name,
                metric=spec.metric,
                unit=(rows[-1].unit if spec.id == "monthly_savings" and rows else spec.unit)
                or spec.unit,
                window_days=spec.window_days,
                aggregation=spec.aggregation,
                normalization=(
                    f"clamp(value / {spec.scale_max:g}, 0, 1); display scale, not goal odds"
                ),
                raw_value=raw,
                value=min(1.0, max(0.0, raw / spec.scale_max)) if raw is not None else None,
                observation_count=len(rows),
                source_types=sorted({row.provenance.source_type for row in rows}),
                evidence_ids=[str(row.evidence_id or row.fingerprint) for row in rows],
                status="measured" if rows else "insufficient",
            )
        )
    return ParameterProfile(
        as_of=stamp, parameters=estimates, evidence_count=len(used), synthetic=synthetic
    )
