import asyncio
import json
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from personal_markets.agents.graph import LangGraphAgentWorkflow
from personal_markets.agents.state import AgentDependencies, redact
from personal_markets.core.config import Settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.service import GoalService
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.integrations.research import (
    CompositeResearchProvider,
    FrozenReferenceProvider,
    MonidResearchProvider,
)
from personal_markets.persistence.agent_store import (
    InMemoryAgentRunStore,
    InMemoryEvidenceRepository,
)
from personal_markets.ports import ResumePayload, WorkflowRequest

RUNS = [
    (
        "create_clear",
        WorkflowRequest(kind="create_goal", intent="Receive an SWE/FDE offer by August 2027."),
    ),
    ("create_rich", WorkflowRequest(kind="create_goal", intent="I want to get rich.")),
]


async def _run() -> list[dict[str, object]]:
    runs = InMemoryAgentRunStore()
    deps = AgentDependencies(
        settings=Settings(environment="test"),
        inference=ScriptedInferenceProvider(),
        research=CompositeResearchProvider(
            FrozenReferenceProvider(), MonidResearchProvider(False, None, None)
        ),
        goals=GoalService(InMemoryGoalRepository()),
        evidence=EvidenceService(InMemoryEvidenceRepository()),
        run_store=runs,
    )
    workflow = LangGraphAgentWorkflow(deps, MemorySaver())
    exported: list[dict[str, object]] = []
    for name, request in RUNS:
        snapshot = await workflow.start(request)
        if snapshot.interrupt and snapshot.interrupt.type == "confirm_contract":
            snapshot = await workflow.resume(snapshot.thread_id, ResumePayload(confirmed=True))
        if snapshot.interrupt and snapshot.interrupt.type == "clarification":
            snapshot = await workflow.resume(
                snapshot.thread_id,
                ResumePayload(
                    answers={"rich_definition": "net worth 1000000", "deadline": "2035-12-31"}
                ),
            )
        exported.append(
            {
                "name": name,
                "status": snapshot.status,
                "progress": snapshot.progress,
                "interrupt": snapshot.interrupt.model_dump(mode="json")
                if snapshot.interrupt
                else None,
                "critic": snapshot.critic.model_dump(mode="json") if snapshot.critic else None,
                "pricing_priced": snapshot.pricing.priced if snapshot.pricing else False,
                "agent_run_ids": snapshot.agent_run_ids,
                "runs": redact(await runs.list_for_thread(snapshot.thread_id)),
            }
        )
    return exported


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    directory = root / "benchmarks" / "agent_trajectories"
    directory.mkdir(parents=True, exist_ok=True)
    payload = asyncio.run(_run())
    path = directory / "representative.json"
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {path} ({len(payload)} trajectories)")


if __name__ == "__main__":
    main()
