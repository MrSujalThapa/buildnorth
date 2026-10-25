"""One-source GitHub watch acceptance with the existing evidence workflow."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from personal_markets.agents.goal_mapping import proposal_to_contract
from personal_markets.agents.model_planner import refine_architect_proposal
from personal_markets.core.errors import ResourceNotFoundError
from personal_markets.integrations.composio_normalizer import normalize_tool_result
from personal_markets.integrations.goal_sync_service import GoalSyncService
from personal_markets.integrations.mcp_domain import (
    GoalSyncRecipeRecord,
    RawSourceRecord,
    SyncRecipeStep,
)
from personal_markets.integrations.source_watches import InMemorySourceWatchStore, SourceWatch
from personal_markets.ports import GoalArchitectProposal
from remote_mcp_support import McpHarness


@pytest.mark.asyncio
async def test_github_commit_watch_normalizes_and_reprices_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with McpHarness() as harness:
        owner = harness.owner.user_id
        proposal = refine_architect_proposal(GoalArchitectProposal.model_validate({
            "ready_to_commit": True,
            "title": "Ship 10 commits to my project",
            "goal_type": "threshold",
            "success_metric": "commits_pushed",
            "success_operator": ">=",
            "success_target": "10",
            "success_unit": "count",
            "deadline": (datetime.now(UTC) + timedelta(days=90)).date().isoformat(),
            "primitive_kind": "cumulative_count",
            "state_dimensions": ["commits_pushed"],
            "current_state_known": {"commits_pushed": "0"},
            "model_family_compatibility": "deadline_event_hazard",
        }))
        deps = harness.app.state.agent_workflow._inner._deps
        goal = await deps.goals.create_goal(proposal_to_contract(proposal), owner)
        connection_id = uuid4()
        resource_id = "MrSujalThapa/buildnorth"
        resource_uri = f"composio://github/{resource_id}"
        step = SyncRecipeStep(
            capability_id="github-commits", tool_name="GITHUB_LIST_COMMITS",
            resource_uri=resource_uri,
            arguments={"owner": "MrSujalThapa", "repo": "buildnorth"},
        )
        recipe = GoalSyncRecipeRecord(
            goal_id=goal.goal_id, plugin_connection_id=connection_id,
            plugin_id="github", label="Project commits", approved=True, steps=[step],
        )
        watches = InMemorySourceWatchStore()
        await watches.save(SourceWatch(
            owner_id=owner, goal_id=goal.goal_id,
            plugin_connection_id=connection_id,
            plugin_id="github", resource_id=resource_id,
        ))
        monkeypatch.setattr(
            "personal_markets.integrations.goal_sync_service.get_source_watch_store",
            lambda: watches,
        )
        def source_record(sha: str, observed_at: str) -> RawSourceRecord:
            return normalize_tool_result(
                plugin_id="github", plugin_connection_id=connection_id,
                sync_run_id=uuid4(), tool_name="GITHUB_LIST_COMMITS",
                user_id=str(owner), recipe_step=step,
                payload={"commits": [{
                    "sha": sha,
                    "commit": {"message": "Implement feature", "author": {
                        "date": observed_at,
                    }},
                }]},
            )[0]

        first_record = source_record("test-commit-1", "2026-10-01T00:00:00Z")
        second_record = source_record("test-commit-2", "2026-10-24T00:00:00Z")
        assert first_record.payload["events"][0]["metric"] == "commits_pushed"
        assert first_record.payload["promotes_to_verified_outcome"] is False

        gateway = SimpleNamespace(sync=AsyncMock(side_effect=[
            {"records_read": 1, "records_new": 1,
             "new_records": [first_record.model_dump(mode="json")]},
            {"records_read": 1, "records_new": 1,
             "new_records": [second_record.model_dump(mode="json")]},
            {"records_read": 1, "records_new": 0, "new_records": []},
        ]))
        repository = SimpleNamespace(
            list_goal_recipes=AsyncMock(return_value=[recipe]),
            get_connection=AsyncMock(return_value=SimpleNamespace(
                id=connection_id, status="connected"
            )),
        )
        service = GoalSyncService(
            settings=None, gateway=gateway, repository=repository,
            goals=deps.goals, workflow=harness.app.state.agent_workflow,
            evidence=deps.evidence, owner_id=owner,
            watch_resource_uris=[resource_uri],
        )
        first = await service.sync_goal_sources(str(goal.goal_id))
        assert first.status == "withheld"
        assert first.pricing is not None and not first.pricing.priced
        second = await service.sync_goal_sources(str(goal.goal_id))
        assert second.status in {"completed", "unchanged"}
        events = await deps.evidence.list_for_goal(goal.goal_id)
        assert len([event for event in events if event.metric == "commits_pushed"]) == 2
        history = await deps.baseline_forecasts.published_history(goal.goal_id)
        assert len(history) >= 1
        before = len(history)
        repeat = await service.sync_goal_sources(str(goal.goal_id))
        assert repeat["status"] == "no_new_records"
        assert len(await deps.baseline_forecasts.published_history(goal.goal_id)) == before
        assert len(await deps.evidence.list_for_goal(goal.goal_id)) == len(events)
        await watches.set_status(owner, goal.goal_id, (
            await watches.list_for_goal(owner, goal.goal_id)
        )[0].id, "revoked")
        gateway.sync.reset_mock()
        assert (await service.sync_goal_sources(str(goal.goal_id)))["status"] == "no_recipes"
        gateway.sync.assert_not_awaited()
        with pytest.raises(ResourceNotFoundError):
            await deps.goals.get_goal(UUID(str(goal.goal_id)), owner_id=uuid4())
