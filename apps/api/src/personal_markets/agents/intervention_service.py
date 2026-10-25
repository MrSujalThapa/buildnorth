# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID, uuid4

from personal_markets.agents.completion import complete_validated
from personal_markets.agents.intervention_critic import critique_intervention
from personal_markets.agents.json_schema import strict_json_schema
from personal_markets.agents.models import estimate_cost_usd, ladders
from personal_markets.agents.prompts import load_prompt
from personal_markets.agents.state import redact, stable_run_id
from personal_markets.core.config import Settings
from personal_markets.core.errors import (
    ProviderBudgetExceededError,
    SemanticProviderError,
    TransientProviderError,
)
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.service import BaselineForecastService
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
from personal_markets.what_if.domain import WhatIfBaselineState
from personal_markets.what_if.intervention_models import (
    InterventionChangeResponse,
    ParseInterventionResponse,
)
from personal_markets.what_if.intervention_parser import parse_intervention_text
from personal_markets.what_if.intervention_registry import (
    allowed_metrics,
    composed_metric_units,
    goal_domain,
)
from personal_markets.what_if.request_intent import ClassifiedRequest, classify_what_if_request
from personal_markets.what_if.strategy_insights import (
    STRATEGY_KINDS,
    StrategyProposal,
    consumer_summary,
    validate_strategy_proposal,
)


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
        forecasts: BaselineForecastService | None = None,
    ) -> None:
        self._settings = settings
        self._inference = inference
        self._research = research
        self._goals = goals
        self._evidence = evidence
        self._run_store = run_store
        self._owner_id = owner_id
        self._forecasts = forecasts
        self._ladders = ladders(settings)

    async def parse(self, goal_id: str, text: str) -> ParseInterventionResponse:
        goal = await self._goals.get_goal_by_string(goal_id, owner_id=self._owner_id)
        evidence = await self._evidence.list_for_goal(UUID(goal_id))
        baseline = build_baseline_state(goal, evidence)
        baseline = await self._with_published(goal.goal_id, baseline)
        classified = classify_what_if_request(text)
        summaries = [item.summary for item in evidence if item.summary]
        if classified.kind in STRATEGY_KINDS:
            return await self._parse_strategy(goal, baseline, text, classified, summaries)
        if classified.kind != "quantitative_scenario":
            return self._factual_response(text, classified, baseline, summaries, evidence)
        return await self._parse_quantitative(goal, baseline, text, classified, summaries)

    async def _with_published(
        self, goal_id: UUID, baseline: WhatIfBaselineState
    ) -> WhatIfBaselineState:
        if self._forecasts is None:
            return baseline
        history = await self._forecasts.published_history(goal_id)
        if not history:
            return baseline
        latest = history[-1]
        return baseline.model_copy(
            update={
                "published_probability": latest.probability,
                "published_model_version": latest.model_version,
                "published_evidence_watermark": latest.evidence_watermark,
            }
        )

    async def _parse_quantitative(
        self,
        goal: GoalContract,
        baseline: WhatIfBaselineState,
        text: str,
        classified: ClassifiedRequest,
        summaries: list[str],
    ) -> ParseInterventionResponse:
        thread_id = uuid4()
        if not self._settings.intervention_agent_enabled:
            return self._with_routing(
                text,
                self._regex_response(text, fallback_note="Intervention agent disabled."),
                classified,
                baseline,
            )

        proposal, critic, agent_run_id = await self._run_intervention_agent(
            thread_id, goal, baseline.model_dump(mode="json"), text, summaries, classified.kind
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
                return self._with_routing(
                    text,
                    ParseInterventionResponse(
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
                        limitations=[
                            "Regex fast-path used after agent returned no defensible changes."
                        ],
                        research_claims=[],
                    ),
                    classified,
                    baseline,
                )
        return self._with_routing(
            text,
            ParseInterventionResponse(
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
            ),
            classified,
            baseline,
        )

    async def _parse_strategy(
        self,
        goal: GoalContract,
        baseline: WhatIfBaselineState,
        text: str,
        classified: ClassifiedRequest,
        summaries: list[str],
    ) -> ParseInterventionResponse:
        if not self._settings.intervention_agent_enabled:
            return self._unavailable_strategy(
                text,
                classified,
                baseline,
                "Strategic recommendations need the inference agent, which is disabled.",
            )
        thread_id = uuid4()
        research = await self._research.search(
            ResearchQuery(
                query=f"{goal.title}: {text}",
                as_of=goal.deadline,
                goal_type=goal.goal_type.value,
                external_required=False,
                user_id=self._owner_id,
            )
        )
        research_payload = research.model_dump(mode="json")
        claims = [
            str(claim.get("claim") or "")
            for claim in research.claims
            if str(claim.get("claim") or "").strip()
            and "placeholder" not in str(claim.get("claim") or "").lower()
        ]
        sources = [
            str(claim.get("source") or "")
            for claim in research.claims
            if str(claim.get("source") or "").strip()
        ]
        payload = {
            "question": text,
            "goal": goal.model_dump(mode="json"),
            "baseline_state": {
                "priced": baseline.priced,
                "status": baseline.status,
                "current_probability": baseline.current_probability,
                "published_probability": baseline.published_probability,
                "resource_constraints": baseline.resource_constraints.model_dump(mode="json"),
                "limitations": baseline.limitations,
            },
            "authorized_evidence_summaries": summaries[:20],
            "allowed_metrics": sorted(allowed_metrics(goal)),
            "goal_domain": goal_domain(goal),
            "research": research_payload,
            "request_kind": classified.kind,
        }
        prompt = load_prompt("strategy")
        ladder = self._ladders["strategy"]
        run_id = stable_run_id(str(thread_id), "strategy", 0)
        request = InferenceRequest(
            instructions=prompt.text,
            input=redact(payload),
            output_schema=strict_json_schema(StrategyProposal),
            model=None,
            fallback_models=[],
            pool=ladder.pool,  # type: ignore[arg-type]
            agent_name="strategy",
            user_id=self._owner_id,
            max_output_tokens=self._settings.intervention_max_output_tokens,
        )
        try:
            proposal, response = await complete_validated(
                self._inference,
                request,
                StrategyProposal,
                timeout_seconds=self._settings.inference_run_timeout_seconds,
            )
        except (
            SemanticProviderError,
            TransientProviderError,
            ProviderBudgetExceededError,
        ) as error:
            return self._unavailable_strategy(
                text,
                classified,
                baseline,
                f"Strategic inference is unavailable: {error}",
            )
        insights, issues = validate_strategy_proposal(
            proposal,
            goal=goal,
            question=text,
            evidence_summaries=summaries,
            research_sources=sources + claims,
            allowed_metrics=allowed_metrics(goal),
        )
        await self._run_store.record(  # type: ignore[attr-defined]
            {
                "id": run_id,
                "thread_id": thread_id,
                "agent_type": "strategy",
                "agent_version": prompt.version,
                "model_provider": response.provider,
                "model_name": response.model,
                "prompt_version": prompt.version,
                "prompt_checksum": prompt.checksum,
                "input_refs": list(payload.keys()),
                "output": {
                    "proposal": proposal.model_dump(mode="json"),
                    "validated": [item.model_dump(mode="json") for item in insights],
                },
                "validation_status": "ok" if insights else "rejected",
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
        return ParseInterventionResponse(
            raw_text=text,
            changes=[],
            unsupported=issues,
            effect_assigned=False,
            understood_action=proposal.understood_question or text,
            mechanism=[],
            pricing_status="NOT_PRICED",
            agent_run_id=str(run_id),
            limitations=proposal.limitations + issues,
            research_claims=proposal.research_claims or claims[:4],
            request_kind=classified.kind,
            confirmation_needed=False,
            insights=insights,
            consumer_summary=consumer_summary(
                kind=classified.kind,
                published_odds=baseline.published_probability,
                comparison_odds=baseline.current_probability,
                scenario_odds=None,
                improvement_pp=None,
                question=text,
            ),
        )

    def _factual_response(
        self,
        text: str,
        classified: ClassifiedRequest,
        baseline: WhatIfBaselineState,
        summaries: list[str],
        evidence: list[NormalizedEvidence],
    ) -> ParseInterventionResponse:
        diagnostic = None
        if classified.kind == "diagnostic":
            recent = "; ".join(summaries[:3]) or "no recent evidence summaries"
            if not baseline.priced:
                diagnostic = (
                    "This forecast is not priced, so there is no published movement to explain. "
                    f"Recent evidence: {recent}."
                )
            else:
                current = baseline.current_probability
                published = baseline.published_probability
                diagnostic = (
                    "I will not invent a reason the receipt does not support. "
                    f"Priced comparison baseline is "
                    f"{None if current is None else round(current * 100, 2)}%. "
                    f"Published odds are "
                    f"{None if published is None else round(published * 100, 2)}%. "
                    f"Recent evidence: {recent}."
                )
        del evidence
        unsupported: list[str] = []
        if classified.kind == "evidence_report":
            unsupported = [
                classified.reason
                or "This looks like observed progress. Confirm it if you want it stored as evidence."
            ]
        elif classified.kind in {"follow_up", "clarification_needed"}:
            unsupported = [
                "This follow-up is missing the original action or baseline. Restate the full change."
            ]
        elif classified.kind == "current_odds":
            unsupported = ["Showing published odds only; no scenario was run."]
        return ParseInterventionResponse(
            raw_text=text,
            changes=[],
            unsupported=unsupported,
            effect_assigned=False,
            understood_action=text,
            mechanism=[],
            pricing_status="NOT_PRICED",
            agent_run_id=None,
            limitations=[],
            research_claims=[],
            request_kind=classified.kind,
            confirmation_needed=classified.needs_confirmation,
            insights=[],
            consumer_summary=consumer_summary(
                kind=classified.kind,
                published_odds=baseline.published_probability,
                comparison_odds=baseline.current_probability,
                scenario_odds=None,
                improvement_pp=None,
                question=text,
                diagnostic_note=diagnostic,
            ),
        )

    def _unavailable_strategy(
        self,
        text: str,
        classified: ClassifiedRequest,
        baseline: WhatIfBaselineState,
        reason: str,
    ) -> ParseInterventionResponse:
        return ParseInterventionResponse(
            raw_text=text,
            changes=[],
            unsupported=[reason],
            effect_assigned=False,
            understood_action=text,
            mechanism=[],
            pricing_status="NOT_PRICED",
            agent_run_id=None,
            limitations=[reason, "No template recommendations were substituted."],
            research_claims=[],
            request_kind=classified.kind,
            confirmation_needed=False,
            insights=[],
            consumer_summary=(
                "Strategic recommendations are unavailable right now. "
                "I will not substitute generic advice as if it were personalized."
            ),
        )

    async def _run_intervention_agent(
        self,
        thread_id: UUID,
        goal: GoalContract,
        baseline: dict[str, object],
        text: str,
        summaries: list[str],
        request_kind: str,
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
            "allowed_metric_units": composed_metric_units(goal),
            "goal_domain": goal_domain(goal),
            "research": research.model_dump(mode="json"),
            "state_dimensions": goal.state_dimensions,
            "authorized_evidence_summaries": summaries[:20],
            "request_kind": request_kind,
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
            max_output_tokens=self._settings.intervention_max_output_tokens,
        )
        proposal, response = await complete_validated(
            self._inference,
            request,
            InterventionAgentProposal,
            timeout_seconds=self._settings.inference_run_timeout_seconds,
        )
        critic = critique_intervention(goal, proposal, text)
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

    @staticmethod
    def _with_routing(
        text: str,
        parsed: ParseInterventionResponse,
        classified: ClassifiedRequest,
        baseline: WhatIfBaselineState,
    ) -> ParseInterventionResponse:
        return parsed.model_copy(
            update={
                "request_kind": classified.kind,
                "confirmation_needed": False,
                "insights": [],
                "consumer_summary": consumer_summary(
                    kind=classified.kind,
                    published_odds=baseline.published_probability,
                    comparison_odds=baseline.current_probability,
                    scenario_odds=None,
                    improvement_pp=None,
                    question=text,
                ),
            }
        )
