"""Explicit observed trials for habit forecasts, separate from execution traits."""

from __future__ import annotations

from datetime import datetime

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.evidence.metrics import canonicalize_metric


def habit_trials(
    evidence: list[NormalizedEvidence], metric: str, now: datetime
) -> list[tuple[str, bool]]:
    wanted = canonicalize_metric(metric)
    rows: list[tuple[datetime, str, bool]] = []
    for item in evidence:
        if canonicalize_metric(item.metric) != wanted or item.observed_at is None:
            continue
        if item.observed_at > now:
            continue
        status = (item.categorical_value or item.event_type).lower()
        if status in {"completed", "completed_session", "session_completed"}:
            completed = True
        elif status in {"missed", "missed_session", "session_missed"}:
            completed = False
        else:
            continue
        rows.append((item.observed_at, str(item.evidence_id or ""), completed))
    rows.sort()
    return [(evidence_id, completed) for _, evidence_id, completed in rows]
