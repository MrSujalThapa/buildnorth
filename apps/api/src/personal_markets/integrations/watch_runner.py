"""Run due watches and persisted sync jobs from an external scheduled process.

Configure a Render Cron Job to run `python -m personal_markets.integrations.watch_runner`
on a 15-minute schedule. This entry point never reads sources outside explicit
active watch allowlists; manual sync jobs already queued by users remain eligible.
"""

from __future__ import annotations

import asyncio
import os
import time

import structlog

from personal_markets.integrations.goal_sync_jobs import get_goal_sync_job_store
from personal_markets.integrations.goal_sync_worker import execute_goal_sync_job
from personal_markets.integrations.source_watches import get_source_watch_store
from personal_markets.main import app


async def run_once(max_jobs: int = 1) -> None:
    """Bound each invocation to at most one billable sync job by default."""
    if not 1 <= max_jobs <= 5:
        raise ValueError("max_jobs must be between 1 and 5")
    os.environ["PLAYITOUT_WATCH_RUNNER"] = "1"
    log = structlog.get_logger(__name__)
    started = time.monotonic()
    async with app.router.lifespan_context(app):
        # A goal may have several due resources but still needs one sync job.
        scheduled = await get_source_watch_store().enqueue_due(limit=max_jobs * 5)
        log.info("source_watches_scheduled", count=scheduled)
        jobs = get_goal_sync_job_store()
        await jobs.expire_stranded()
        processed = 0
        while processed < max_jobs:
            job = await jobs.claim(include_watches=True)
            if job is None:
                break
            await execute_goal_sync_job(app, job)
            processed += 1
        log.info(
            "source_watch_runner_finished",
            scheduled=scheduled,
            processed=processed,
            duration_seconds=round(time.monotonic() - started, 3),
        )


if __name__ == "__main__":
    asyncio.run(run_once())
