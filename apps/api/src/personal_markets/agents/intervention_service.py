from __future__ import annotations

from uuid import UUID, uuid4

from personal_markets.agents.intervention_critic import critique_intervention
from personal_markets.agents.json_schema import strict_json_schema
from personal_markets.agents.completion import complete_validated
from personal_markets.agents.models import estimate_cost_usd, ladders
from personal_markets.agents.prompts import load_prompt
from personal_markets.agents.state import redact, stable_run_id
from personal_markets.core.config import Settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService
from personal_markets.ports import (
    InferenceProvider,
    InferenceRequest,
    InterventionAgentProposal,
    ResearchProvider,
    ResearchQuery,
)
from personal_markets.what_if.baseline_state import build_baseline_state
from personal_markets.what_if.intervention_models import InterventionChangeResponse, ParseInterventionResponse
from personal_markets.what_if.intervention_parser import parse_intervention_text
from personal_markets.what_if.intervention_registry import allowed_metrics, goal_domain


class InterventionAgentService:
    def __init__(
        self,
        settings: Settings,
        inference: InferenceProvider,
        research: ResearchProvider,
        goals: GoalService,
        evidence: EvidenceService,
        run_store: object,
        owner_id=None,
    ) -> None:
        self._settings = settings
        self._inference = inference
        self._research = research
        self._goals = goals
        self._evidence = evidence
        self._run_store = run_store
        self._owner_id = owner_id
        self._ladders = ladders(settings)

    async def parse(self, goal_id: str, text: str) -> ParseInterventionResponse:
        goal = await self._goals.get_goal_by_string(goal_id, owner_id=self._owner_id)
        evidence = await self._evidence.list_for_goal(UUID(goal_id))
        baseline = build_baseline_state(goal, evidence)
        thread_id = uuid4()

        if not self._settings.intervention_agent_enabled:
            return self._regex_response(text, fallback_note="Intervention agent disabled.")

        proposal, critic, agent_run_id = await self._run_agent(
            thread_id, goal, baseline.model_dump(mode="json"), text
        )
        changes = [
            InterventionChangeResponse(
                metric=item.metric,
                operation=item.operation,
                value=item.value,
                unit=item.unit,
                frequency=item.frequency,
                scope=item.scope,
                provenance=item.provenance,
            )
            for item in critic.validated_changes
        ]

        if not changes and self._settings.intervention_regex_fallback:
            regex = parse_intervention_text(text)
            if regex.changes:
                return ParseInterventionResponse(
                    raw_text=text,
                    changes=[
                        InterventionChangeResponse(
                            metric=item.metric,
                            operation=item.operation,
                            value=item.value,
                            unit=item.unit,
                            frequency=item.frequency,
                            scope=item.scope,
                            provenance=item.provenance,
                        )
                        for item in regex.changes
                    ],
                    unsupported=list(regex.unsupported),
                    effect_assigned=False,
                    understood_action=text,
                    mechanism=[],
                    pricing_status="PRICED",
                    agent_run_id=None,
                    limitations=["Regex fast-path used after agent returned no defensible changes."],
                    research_claims=[],
                )

        return ParseInterventionResponse(
            raw_text=text,
            changes=changes,
            unsupported=list(proposal.unsupported) + critic.issues,
            effect_assigned=False,
            understood_action=proposal.understood_action,
            mechanism=[step.model_dump() for step in proposal.mechanism],
            pricing_status=critic.pricing_status,
            agent_run_id=agent_run_id,
            limitations=critic.limitations,
            research_claims=proposal.research_claims,
        )

    async def _run_agent(
        self,
        thread_id: UUID,
        goal: GoalContract,
        baseline: dict[str, object],
        text: str,
    ) -> tuple[InterventionAgentProposal, object, str | None]:
        research = await self._research.search(
            ResearchQuery(
                query=f"What If intervention effect pathways for: {text}",
                as_of=goal.deadline,
                goal_type=goal.goal_type.value,
            )
        )
        payload = {
            "intervention_text": text,
            "goal": goal.model_dump(mode="json"),
            "baseline_state": baseline,
            "allowed_metrics": sorted(allowed_metrics(goal)),
            "goal_domain": goal_domain(goal),
            "research": research.model_dump(mode="json"),
            "state_dimensions": goal.state_dimensions,
        }
        prompt = load_prompt("intervention")
        ladder = self._ladders["intervention"]
        run_id = stable_run_id(str(thread_id), "intervention", 0)
        request = InferenceRequest(
            instructions=prompt.text,
            input=redact(payload),
            output_schema=strict_json_schema(InterventionAgentProposal),
            model=None,
            fallback_models=[],
            pool=ladder.pool,  # type: ignore[arg-type]
            agent_name="intervention",
            user_id=self._owner_id,
        )
        proposal, response = await complete_validated(
            self._inference, request, InterventionAgentProposal,
            timeout_seconds=self._settings.inference_run_timeout_seconds,
        )
        critic = critique_intervention(goal, proposal)
        await self._run_store.record(  # type: ignore[attr-defined]
            {
                "id": run_id,
                "thread_id": thread_id,
                "agent_type": "intervention",
                "agent_version": prompt.version,
                "model_provider": response.provider,
                "model_name": response.model,
                "prompt_version": prompt.version,
                "prompt_checksum": prompt.checksum,
                "input_refs": list(payload.keys()),
                "output": {
                    "proposal": proposal.model_dump(mode="json"),
                    "critic": critic.model_dump(mode="json"),
                },
                "validation_status": "ok" if critic.approved else "rejected",
                "retry_count": response.retries,
                "duration_ms": response.latency_ms,
                "token_usage": response.usage,
                "estimated_cost": estimate_cost_usd(
                    response.model,
                    int(response.usage.get("input_tokens", 0)),
                    int(response.usage.get("output_tokens", 0)),
                ),
                "tool_trace": [],
                "status": "completed",
            }
        )
        return proposal, critic, str(run_id)

    @staticmethod
    def _regex_response(text: str, *, fallback_note: str) -> ParseInterventionResponse:
        parsed = parse_intervention_text(text)
        return ParseInterventionResponse(
            raw_text=text,
            changes=[
                InterventionChangeResponse(
                    metric=item.metric,
                    operation=item.operation,
                    value=item.value,
                    unit=item.unit,
                    frequency=item.frequency,
                    scope=item.scope,
                    provenance=item.provenance,
                )
                for item in parsed.changes
            ],
            unsupported=list(parsed.unsupported),
            effect_assigned=False,
            understood_action=text,
            mechanism=[],
            pricing_status="NOT_PRICED" if not parsed.changes else "PRICED",
            agent_run_id=None,
            limitations=[fallback_note],
            research_claims=[],
        )
