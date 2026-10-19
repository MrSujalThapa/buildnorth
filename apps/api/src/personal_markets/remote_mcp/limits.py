from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Callable


class SlidingWindowLimiter:
    """Per-key request windows held in this process.

    Limits are per API process and are not shared across workers. Deploy a
    single Uvicorn/Gunicorn worker until these counters move to Postgres.
    Running several workers multiplies the effective limit. Hosted spend
    budgets are enforced separately and atomically in the database.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, bucket: str, key: str, limit: int, window_seconds: float) -> bool:
        now = self._clock()
        async with self._lock:
            events = self._events[(bucket, key)]
            while events and events[0] <= now - window_seconds:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True


class KeyedLocks:
    """Serialize evidence writes per goal so check-then-insert dedup cannot race.

    Locks live in this process only. Multi-worker deployments can race across
    processes; keep a single worker for current MCP write serialization.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get(self, key: str) -> asyncio.Lock:
        return self._locks[key]
