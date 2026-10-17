from datetime import UTC, datetime
from uuid import uuid4

import pytest

from personal_markets.core.config import DEFAULT_USER_ID
from personal_markets.evidence.metrics import canonicalize_metric, observation_kind
from personal_markets.evidence.service import EvidenceService, evidence_fingerprint
from personal_markets.persistence.agent_store import InMemoryEvidenceRepository
from personal_markets.ports import EvidenceEventProposal


def _event(**overrides: object) -> EvidenceEventProposal:
    payload: dict[str, object] = {
        "event_type": "manual_state_entry",
        "domain": "user_state",
        "metric": "applications",
        "numeric_value": 12,
        "unit": "count",
        "observed_at": datetime.now(UTC).isoformat(),
        "source_type": "manual",
        "summary": "Applications submitted so far",
    }
    payload.update(overrides)
    return EvidenceEventProposal.model_validate(payload)


def test_application_aliases_share_one_canonical_metric() -> None:
    assert canonicalize_metric("applications") == "applications_submitted"
    assert canonicalize_metric("job_applications_submitted") == "applications_submitted"
    assert canonicalize_metric("applications_submitted") == "applications_submitted"


def test_equivalent_application_observations_share_fingerprint() -> None:
    goal = uuid4()
    manual = _event()
    natural_language = _event(
        event_type="observation",
        metric="job_applications_submitted",
        source_type="mcp_sync",
        summary="I sent 12 job applications this week.",
        observed_at="2026-01-01T00:00:00Z",
    )
    assert evidence_fingerprint(DEFAULT_USER_ID, manual, goal_id=goal) == evidence_fingerprint(
        DEFAULT_USER_ID, natural_language, goal_id=goal
    )


def test_different_application_counts_are_distinct_events() -> None:
    goal = uuid4()
    first = _event(numeric_value=6)
    second = _event(numeric_value=18)
    assert evidence_fingerprint(DEFAULT_USER_ID, first, goal_id=goal) != evidence_fingerprint(
        DEFAULT_USER_ID, second, goal_id=goal
    )


def test_snapshots_ignore_timestamp_in_fingerprint() -> None:
    goal = uuid4()
    morning = _event(observed_at="2026-03-02T08:00:00Z")
    evening = _event(observed_at="2026-03-02T20:00:00Z")
    assert observation_kind(morning.metric, morning.event_type) == "snapshot"
    assert evidence_fingerprint(DEFAULT_USER_ID, morning, goal_id=goal) == evidence_fingerprint(
        DEFAULT_USER_ID, evening, goal_id=goal
    )


def test_identical_increments_on_different_days_have_distinct_fingerprints() -> None:
    goal = uuid4()
    monday = _event(
        event_type="increment",
        metric="applications_submitted",
        numeric_value=1,
        observed_at="2026-03-02T12:00:00Z",
        summary="Sent one application",
    )
    tuesday = _event(
        event_type="increment",
        metric="applications_submitted",
        numeric_value=1,
        observed_at="2026-03-03T12:00:00Z",
        summary="Sent one application",
    )
    assert observation_kind(monday.metric, monday.event_type) == "increment"
    assert evidence_fingerprint(DEFAULT_USER_ID, monday, goal_id=goal) != evidence_fingerprint(
        DEFAULT_USER_ID, tuesday, goal_id=goal
    )


def test_same_weekly_distance_in_different_weeks_have_distinct_fingerprints() -> None:
    goal = uuid4()
    week_one = _event(
        event_type="observation",
        metric="weekly_distance_km",
        numeric_value=32,
        unit="km",
        observed_at="2026-03-02T12:00:00Z",
        summary="Weekly mileage",
    )
    week_two = _event(
        event_type="observation",
        metric="weekly_distance_km",
        numeric_value=32,
        unit="km",
        observed_at="2026-03-09T12:00:00Z",
        summary="Weekly mileage",
    )
    assert observation_kind(week_one.metric, week_one.event_type) == "period"
    assert evidence_fingerprint(DEFAULT_USER_ID, week_one, goal_id=goal) != evidence_fingerprint(
        DEFAULT_USER_ID, week_two, goal_id=goal
    )


@pytest.mark.asyncio
async def test_identical_increments_on_different_days_are_not_deduplicated() -> None:
    goal_id = uuid4()
    service = EvidenceService(InMemoryEvidenceRepository({goal_id: True}))
    monday = _event(
        event_type="increment",
        metric="applications_submitted",
        numeric_value=1,
        observed_at="2026-03-02T12:00:00Z",
        summary="Sent one application",
    )
    tuesday = _event(
        event_type="increment",
        metric="applications_submitted",
        numeric_value=1,
        observed_at="2026-03-03T12:00:00Z",
        summary="Sent one application",
    )
    await service.commit(DEFAULT_USER_ID, goal_id, [monday], None, [])
    await service.commit(DEFAULT_USER_ID, goal_id, [tuesday], None, [])
    rows = await service.list_for_goal(goal_id)
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_cross_source_dedup_keeps_primary_and_corroborating_provenance() -> None:
    goal_id = uuid4()
    service = EvidenceService(InMemoryEvidenceRepository({goal_id: True}))
    manual = _event(
        numeric_value=12,
        source_type="manual",
        summary="Applications submitted so far",
    )
    imported = _event(
        event_type="observation",
        metric="job_applications_submitted",
        numeric_value=12,
        source_type="mcp_sync",
        summary="I sent 12 job applications this week.",
        observed_at="2026-01-01T00:00:00Z",
    )
    await service.commit(DEFAULT_USER_ID, goal_id, [manual], None, [])
    await service.commit(DEFAULT_USER_ID, goal_id, [imported], None, [])
    rows = await service.list_for_goal(goal_id)
    assert len(rows) == 1
    assert rows[0].provenance.source_type == "manual"
    assert rows[0].summary == "Applications submitted so far"
    assert len(rows[0].provenance.corroborating_sources) == 1
    extra = rows[0].provenance.corroborating_sources[0]
    assert extra.source_type == "mcp_sync"
    assert extra.summary == "I sent 12 job applications this week."
