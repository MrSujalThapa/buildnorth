"""Estimate primitive parameters from user evidence. Never invent population priors."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import numpy as np

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.evidence.metrics import (
    canonicalize_metric,
    observation_kind,
    reduce_stock_value,
)

SourceKind = Literal[
    "observed", "inferred", "estimated", "prior", "user_assumption", "research_candidate"
]


@dataclass(frozen=True, slots=True)
class EstimatedParameter:
    name: str
    value: float | None
    unit: str | None
    estimator: str
    source_kind: SourceKind
    n_observations: int = 0
    std_error: float | None = None
    usable: bool = False
    limitations: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


def evidence_series(
    evidence: list[NormalizedEvidence],
    metric: str,
    aliases: tuple[str, ...] = (),
) -> list[tuple[datetime, float, str]]:
    wanted = {canonicalize_metric(metric), *(canonicalize_metric(alias) for alias in aliases)}
    series: list[tuple[datetime, float, str]] = []
    for item in evidence:
        if canonicalize_metric(item.metric) not in wanted:
            continue
        if item.numeric_value is None or item.observed_at is None:
            continue
        kind = observation_kind(
            item.metric,
            item.event_type,
            item.provenance.observation_kind,
        )
        series.append((item.observed_at, float(item.numeric_value), kind))
    series.sort(key=lambda row: row[0])
    return series


def current_stock(
    evidence: list[NormalizedEvidence],
    metric: str,
    aliases: tuple[str, ...] = (),
) -> float | None:
    series = evidence_series(evidence, metric, aliases)
    if not series:
        return None
    return reduce_stock_value([(stamp, value, kind) for stamp, value, kind in series])  # type: ignore[arg-type]


def estimate_rate(
    evidence: list[NormalizedEvidence],
    metric: str,
    *,
    now: datetime,
    horizon_start: datetime | None = None,
    aliases: tuple[str, ...] = (),
    time_unit_days: float = 7.0,
) -> EstimatedParameter:
    """MLE additions per time unit from dated increments, or snapshot deltas."""
    series = evidence_series(evidence, metric, aliases)
    increments = [
        (stamp, value) for stamp, value, kind in series if kind == "increment" and value >= 0
    ]
    snapshots = [(stamp, value) for stamp, value, kind in series if kind in {"snapshot", "period"}]
    if len(increments) >= 2:
        first, last = increments[0][0], max(increments[-1][0], now)
        span_days = max((last - first).total_seconds() / 86400.0, time_unit_days / 8.0)
        total = sum(value for _, value in increments)
        rate = total / (span_days / time_unit_days)
        return EstimatedParameter(
            name="rate",
            value=rate,
            unit=f"count/{'week' if time_unit_days == 7 else 'period'}",
            estimator="increment_mle",
            source_kind="estimated",
            n_observations=len(increments),
            std_error=math.sqrt(max(total, 1.0)) / (span_days / time_unit_days),
            usable=len(increments) >= 2,
            provenance={"first": first.isoformat(), "last": last.isoformat(), "total": total},
        )
    if len(snapshots) >= 2:
        ordered = sorted(snapshots, key=lambda row: row[0])
        first_t, first_v = ordered[0]
        last_t, last_v = ordered[-1]
        span_days = max((last_t - first_t).total_seconds() / 86400.0, time_unit_days / 8.0)
        delta = last_v - first_v
        if delta < 0:
            return EstimatedParameter(
                name="rate",
                value=None,
                unit="count/period",
                estimator="snapshot_delta",
                source_kind="estimated",
                n_observations=len(snapshots),
                usable=False,
                limitations=["Stock declined; a non-negative addition rate cannot be inferred."],
            )
        rate = delta / (span_days / time_unit_days)
        return EstimatedParameter(
            name="rate",
            value=rate,
            unit="count/period",
            estimator="snapshot_delta",
            source_kind="estimated",
            n_observations=len(snapshots),
            usable=len(snapshots) >= 2,
            provenance={"first": first_t.isoformat(), "last": last_t.isoformat(), "delta": delta},
        )
    _ = horizon_start
    return EstimatedParameter(
        name="rate",
        value=None,
        unit="count/period",
        estimator="insufficient",
        source_kind="estimated",
        n_observations=len(series),
        usable=False,
        limitations=[
            "Need dated increments or at least two snapshots to estimate an addition rate. "
            "No population prior was substituted."
        ],
    )


def estimate_log_growth(
    evidence: list[NormalizedEvidence],
    metric: str,
    *,
    aliases: tuple[str, ...] = (),
    time_unit_days: float = 7.0,
) -> EstimatedParameter:
    """OLS of log(x) on time in periods. Requires ≥3 positive snapshots."""
    series = [
        (stamp, value)
        for stamp, value, kind in evidence_series(evidence, metric, aliases)
        if kind in {"snapshot", "period"} and value > 0
    ]
    if len(series) < 3:
        return EstimatedParameter(
            name="mu",
            value=None,
            unit="log-change/period",
            estimator="log_ols",
            source_kind="estimated",
            n_observations=len(series),
            usable=False,
            limitations=[
                "Growth needs at least three positive dated measurements. "
                "A platform-wide average was not used as a prior."
            ],
        )
    origin = series[0][0]
    times = np.array(
        [(stamp - origin).total_seconds() / 86400.0 / time_unit_days for stamp, _ in series],
        dtype=float,
    )
    logs = np.log(np.array([value for _, value in series], dtype=float))
    slope, intercept = np.polyfit(times, logs, 1)
    fitted = intercept + slope * times
    residual = logs - fitted
    df = max(len(series) - 2, 1)
    sigma = float(np.sqrt(np.sum(residual**2) / df))
    return EstimatedParameter(
        name="mu",
        value=float(slope),
        unit="log-change/period",
        estimator="log_ols",
        source_kind="estimated",
        n_observations=len(series),
        std_error=sigma,
        usable=True,
        provenance={"sigma": sigma, "intercept": float(intercept), "n": len(series)},
    )


def estimate_linear_trend(
    evidence: list[NormalizedEvidence],
    metric: str,
    *,
    aliases: tuple[str, ...] = (),
    time_unit_days: float = 7.0,
) -> EstimatedParameter:
    series = [
        (stamp, value)
        for stamp, value, _kind in evidence_series(evidence, metric, aliases)
        if value is not None
    ]
    if len(series) < 2:
        return EstimatedParameter(
            name="trend",
            value=None,
            unit="units/period",
            estimator="ols",
            source_kind="estimated",
            n_observations=len(series),
            usable=False,
            limitations=["A performance trend needs at least two dated measurements."],
        )
    origin = series[0][0]
    times = np.array(
        [(stamp - origin).total_seconds() / 86400.0 / time_unit_days for stamp, _ in series],
        dtype=float,
    )
    values = np.array([value for _, value in series], dtype=float)
    slope, intercept = np.polyfit(times, values, 1)
    fitted = intercept + slope * times
    df = max(len(series) - 2, 1)
    sigma = float(np.sqrt(np.sum((values - fitted) ** 2) / df))
    return EstimatedParameter(
        name="trend",
        value=float(slope),
        unit="units/period",
        estimator="ols",
        source_kind="estimated",
        n_observations=len(series),
        std_error=max(sigma, 1e-6),
        usable=True,
        provenance={"sigma": sigma, "n": len(series)},
    )


def periods_until(deadline: datetime, now: datetime, *, days_per_period: float = 7.0) -> float:
    seconds = (deadline - now).total_seconds()
    return max(seconds / (days_per_period * 86400.0), 1.0 / days_per_period)
