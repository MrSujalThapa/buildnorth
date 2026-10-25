"""Owner+goal scoped last quantitative What If. Not a general chat memory."""

from __future__ import annotations

import time
from uuid import UUID

from personal_markets.what_if.intervention_models import InterventionChangeResponse


class LastInterventionStore:
    def __init__(self, ttl_seconds: float = 1800) -> None:
        self._ttl = ttl_seconds
        self._rows: dict[
            tuple[UUID, UUID], tuple[float, str, list[InterventionChangeResponse]]
        ] = {}

    def put(
        self,
        user_id: UUID,
        goal_id: UUID,
        text: str,
        changes: list[InterventionChangeResponse],
    ) -> None:
        if not changes:
            return
        self._rows[(user_id, goal_id)] = (time.monotonic(), text, list(changes))

    def get(
        self, user_id: UUID, goal_id: UUID
    ) -> tuple[str, list[InterventionChangeResponse]] | None:
        row = self._rows.get((user_id, goal_id))
        if row is None:
            return None
        stamped, text, changes = row
        if time.monotonic() - stamped > self._ttl:
            self._rows.pop((user_id, goal_id), None)
            return None
        return text, list(changes)


def relative_scale(text: str) -> float | None:
    lowered = text.strip().lower()
    if "half as" in lowered:
        return 0.5
    if "twice as" in lowered or "double" in lowered:
        return 2.0
    return None
