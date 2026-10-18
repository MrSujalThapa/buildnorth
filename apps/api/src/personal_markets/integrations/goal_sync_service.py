from __future__ import annotations

from personal_markets.integrations.mcp_domain import RawSourceRecord
from personal_markets.ports import WorkflowRequest


class GoalSyncService:
    def __init__(
        self,
        settings,
        gateway,
        repository,
        goals,
        workflow,
        evidence,
        owner_id=None,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._repository = repository
        self._goals = goals
        self._workflow = workflow
        self._evidence = evidence
        self._owner_id = owner_id

    async def sync_goal_sources(self, goal_id: str):
        goal = await self._goals.get_goal_by_string(goal_id, owner_id=self._owner_id)
        recipes = await self._repository.list_goal_recipes(goal.goal_id)
        approved = [item for item in recipes if item.approved]
        if not approved:
            return {"status": "no_recipes", "message": "No approved goal-specific sync recipes."}

        new_records: list[RawSourceRecord] = []
        for recipe in approved:
            result = await self._gateway.sync(recipe.plugin_id, steps=recipe.steps)
            for row in result.get("new_records") or []:
                if isinstance(row, dict):
                    new_records.append(RawSourceRecord.model_validate(row))

        if not new_records:
            return {"status": "no_new_records", "records_synced": 0}

        return await self._workflow.start(
            WorkflowRequest(
                kind="add_evidence",
                goal_id=goal.goal_id,
                evidence_text=f"Synced {len(new_records)} records from approved integrations.",
                mcp_records=[record.model_dump(mode="json") for record in new_records],
                user_id=self._owner_id,
            )
        )
