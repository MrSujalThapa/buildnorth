"""Scripted intervention-agent verification for Pass 6 example prompts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from personal_markets.agents.intervention_service import InterventionAgentService
from personal_markets.core.config import Settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.integrations.research import (
    CompositeResearchProvider,
    FrozenReferenceProvider,
    MonidResearchProvider,
)
from personal_markets.persistence.agent_store import InMemoryAgentRunStore, InMemoryEvidenceRepository


async def main() -> None:
    cases = [
        (
            "career",
            GoalType.DEADLINE_EVENT,
            "Receive SWE offer",
            ["applications_submitted"],
            [
                "What if I start posting on LinkedIn 4 times a week?",
                "What if I do 3 mock interviews per week?",
                "What if I sleep 2 extra hours?",
                "What if I send 15 more applications per week?",
            ],
        ),
        (
            "startup",
            GoalType.MULTI_OUTCOME,
            "Launch startup",
            ["runway_months"],
            [
                "What if I talk to 10 users every week?",
                "What if I go full time?",
                "What if I hire a salesperson?",
            ],
        ),
        (
            "running",
            GoalType.THRESHOLD,
            "Break 45 min 10K",
            ["weekly_distance_km"],
            [
                "What if I run 4 days a week?",
                "What if I increase to 40 km/week?",
                "What if I sleep more?",
            ],
        ),
        (
            "finance",
            GoalType.CONTINUOUS_TARGET,
            "Reach net worth target",
            ["net_worth_usd"],
            [
                "What if I invest $1500/month?",
                "What if my rent drops $500?",
            ],
        ),
    ]
    service = InterventionAgentService(
        settings=Settings(
            environment="test",
            intervention_agent_enabled=True,
            intervention_regex_fallback=False,
        ),
        inference=ScriptedInferenceProvider(),
        research=CompositeResearchProvider(
            FrozenReferenceProvider(), MonidResearchProvider(False, None, None)
        ),
        goals=GoalService(InMemoryGoalRepository()),
        evidence=EvidenceService(InMemoryEvidenceRepository()),
        run_store=InMemoryAgentRunStore(),
    )
    for label, gtype, title, dims, prompts in cases:
        goal = GoalContract(
            goal_id=uuid4(),
            title=title,
            goal_type=gtype,
            success_definition={"metric": "x", "target": "y"},
            deadline=datetime.now(UTC) + timedelta(days=180),
            state_dimensions=dims,
        )
        await service._goals._repository.create(goal, uuid4())
        print(f"== {label} ==")
        for prompt in prompts:
            parsed = await service.parse(str(goal.goal_id), prompt)
            metrics = [item.metric for item in parsed.changes]
            tail = metrics or parsed.unsupported[:1]
            print(f"  {prompt[:52]:52} -> {parsed.pricing_status:20} {tail}")


if __name__ == "__main__":
    asyncio.run(main())
