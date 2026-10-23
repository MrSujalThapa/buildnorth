from datetime import UTC, datetime
from uuid import uuid4

import pytest

from personal_markets.evidence.service import EvidenceService
from personal_markets.persistence.agent_store import InMemoryEvidenceRepository
from personal_markets.ports import EvidenceEventProposal


@pytest.mark.asyncio
async def test_list_for_goals_groups_each_goals_evidence_and_keeps_empty_goals() -> None:
    with_events, without_events = uuid4(), uuid4()
    repository = InMemoryEvidenceRepository({with_events: True, without_events: True})
    for value in (1.0, 2.0):
        await repository.insert(
            uuid4(),
            with_events,
            EvidenceEventProposal.model_validate(
                {
                    "source_type": "manual",
                    "event_type": "observation",
                    "domain": "reading",
                    "metric": "books_read",
                    "numeric_value": value,
                    "unit": "books",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "summary": f"books={value}",
                }
            ),
            fingerprint=f"books-{value}",
            agent_run_id=None,
            conflict="none",
        )

    grouped = await EvidenceService(repository).list_for_goals([with_events, without_events])

    assert [event.numeric_value for event in grouped[with_events]] == [1.0, 2.0]
    assert grouped[without_events] == []
    assert grouped == {
        goal_id: await repository.list_for_goal(goal_id)
        for goal_id in (with_events, without_events)
    }
