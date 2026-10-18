from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from personal_markets.agents.critic import merge_critic_decision
from personal_markets.agents.goal_mapping import proposal_to_contract, validation_errors
from personal_markets.agents.pricing import needs_research
from personal_markets.agents.state import (
    MAX_SEMANTIC_RETRIES,
    AgentDependencies,
    AgentGraphState,
    complete_agent,
    mark_progress,
    snapshot_from_state,
    stable_goal_id,
)
from personal_markets.core.errors import ResourceNotFoundError
from personal_markets.ports import (
    CriticArtifact,
    EvidenceAgentProposal,
    GoalArchitectProposal,
    InterruptPayload,
    ResearchArtifact,
    ResearchClaim,
    ResearchQuery,
    ResumePayload,
    WorkflowRequest,
    WorkflowSnapshot,
)


class LangGraphAgentWorkflow:
    def __init__(self, deps: AgentDependencies, checkpointer: BaseCheckpointSaver[Any]) -> None:
        self._deps = deps
        self._checkpointer = checkpointer
        self._graph = self._build()

    def _build(self) -> Any:
        graph = StateGraph(AgentGraphState)
        graph.add_node("parse_request", self._parse_request)
        graph.add_node("architect_goal", self._architect_goal)
        graph.add_node("validate_goal", self._validate_goal)
        graph.add_node("interrupt_goal", self._interrupt_goal)
        graph.add_node("confirm_goal", self._confirm_goal)
        graph.add_node("commit_goal", self._commit_goal)
        graph.add_node("collect_evidence", self._collect_evidence)
        graph.add_node("normalize_evidence", self._normalize_evidence)
        graph.add_node("validate_evidence", self._validate_evidence)
        graph.add_node("interrupt_evidence", self._interrupt_evidence)
        graph.add_node("commit_evidence", self._commit_evidence)
        graph.add_node("decide_research", self._decide_research)
        graph.add_node("research_agent", self._research_agent)
        graph.add_node("compute_forecast", self._compute_forecast)
        graph.add_node("critique", self._critique)
        graph.add_node("publish", self._publish)
        graph.add_edge(START, "parse_request")
        graph.add_conditional_edges("parse_request", self._after_parse)
        graph.add_edge("architect_goal", "validate_goal")
        graph.add_conditional_edges("validate_goal", self._after_validate_goal)
        graph.add_conditional_edges("interrupt_goal", self._after_interrupt_goal)
        graph.add_conditional_edges("confirm_goal", self._after_confirm_goal)
        graph.add_edge("commit_goal", "collect_evidence")
        graph.add_conditional_edges("collect_evidence", self._after_collect_evidence)
        graph.add_edge("normalize_evidence", "validate_evidence")
        graph.add_conditional_edges("validate_evidence", self._after_validate_evidence)
        graph.add_conditional_edges("interrupt_evidence", self._after_interrupt_evidence)
        graph.add_edge("commit_evidence", "decide_research")
        graph.add_conditional_edges("decide_research", self._after_decide_research)
        graph.add_edge("research_agent", "compute_forecast")
        graph.add_edge("compute_forecast", "critique")
        graph.add_edge("critique", "publish")
        graph.add_edge("publish", END)
        return graph.compile(checkpointer=self._checkpointer)

    async def start(self, request: WorkflowRequest) -> WorkflowSnapshot:
        thread_id = request.thread_id or uuid4()
        user_id = request.user_id
        if user_id is None:
            if self._deps.settings.environment in {"test", "pytest"}:
                user_id = self._deps.settings.default_user_id
            else:
                from personal_markets.core.errors import UnauthorizedError

                raise UnauthorizedError("authenticated user required")
        initial: AgentGraphState = {
            "thread_id": str(thread_id),
            "user_id": str(user_id),
            "kind": request.kind,
            "intent": request.intent or "",
            "evidence_text": request.evidence_text or "",
            "github_login": request.github_login or "",
            "goal_id": str(request.goal_id) if request.goal_id else "",
            "current_step": "parse_request",
            "status": "running",
            "progress": [],
            "agent_run_ids": {},
            "validation_errors": [],
            "architect_retries": 0,
            "evidence_retries": 0,
            "research_needed": False,
            "resume_answers": {},
            "cancelled": False,
            "committed_evidence_ids": [],
            "debug": {
                "user_id": str(user_id),
                "structured_evidence": bool(request.evidence_events),
            },
            "github_records": [],
            "mcp_records": list(request.mcp_records or []),
            "evidence_proposal": {
                "events": [item.model_dump(mode="json") for item in request.evidence_events],
                "ambiguities": [],
                "conflicts": [],
            }
            if request.evidence_events
            else {},
        }
        result = await self._graph.ainvoke(initial, self._config(thread_id))
        return await self._to_snapshot(thread_id, result)

    async def resume(self, thread_id: UUID, payload: ResumePayload) -> WorkflowSnapshot:
        resume_value: dict[str, object]
        if payload.cancelled:
            resume_value = {"cancelled": True}
        elif payload.answers:
            resume_value = dict(payload.answers)
        else:
            resume_value = {"confirmed": bool(payload.confirmed)}
        result = await self._graph.ainvoke(Command(resume=resume_value), self._config(thread_id))
        return await self._to_snapshot(thread_id, result)

    async def snapshot(self, thread_id: UUID) -> WorkflowSnapshot:
        state = await self._graph.aget_state(self._config(thread_id))
        if not state.values:
            raise ResourceNotFoundError(f"Workflow thread {thread_id} was not found")
        return await self._to_snapshot(thread_id, dict(state.values), state)

    def _config(self, thread_id: UUID) -> dict[str, Any]:
        return {"configurable": {"thread_id": str(thread_id)}}

    async def _to_snapshot(
        self, thread_id: UUID, values: dict[str, Any], raw_state: Any | None = None
    ) -> WorkflowSnapshot:
        state: AgentGraphState = values  # type: ignore[assignment]
        interrupt_payload = None
        graph_state = raw_state or await self._graph.aget_state(self._config(thread_id))
        interrupts = getattr(graph_state, "interrupts", ()) or ()
        if interrupts:
            payload = interrupts[0].value
            interrupt_payload = InterruptPayload.model_validate(payload)
        goal = None
        goal_id = state.get("committed_goal_id") or state.get("goal_id")
        if goal_id:
            try:
                goal = await self._deps.goals.get_goal(
                    UUID(goal_id), owner_id=UUID(state["user_id"])
                )
            except ResourceNotFoundError:
                goal = None
            if (
                goal is None
                and state.get("goal_proposal")
                and state.get("status") in {"needs_input", "running"}
            ):
                try:
                    goal = proposal_to_contract(
                        GoalArchitectProposal.model_validate(state["goal_proposal"]),
                        stable_goal_id(str(thread_id)),
                    )
                except Exception:
                    goal = None
        snapshot = snapshot_from_state(state, interrupt_payload, goal)
        snapshot.debug = {
            **snapshot.debug,
            "user_id": state.get("user_id"),
            "steps": list(state.get("progress") or []),
        }
        return snapshot

    async def _parse_request(self, state: AgentGraphState) -> dict[str, Any]:
        return {"current_step": "parse_request", "status": "running"}

    def _after_parse(self, state: AgentGraphState) -> str:
        if state.get("cancelled"):
            return END
        kind = state.get("kind")
        if kind == "add_evidence":
            return "collect_evidence"
        if kind == "reprice":
            return "decide_research"
        return "architect_goal"

    async def _architect_goal(self, state: AgentGraphState) -> dict[str, Any]:
        payload = {
            "intent": state.get("intent"),
            "user_answers": state.get("resume_answers") or {},
            "previous_validation_errors": state.get("validation_errors") or [],
        }
        attempt = int(state.get("architect_retries") or 0)
        proposal, run_id = await complete_agent(
            self._deps, state, "goal_architect", GoalArchitectProposal, payload, attempt
        )
        ids = dict(state.get("agent_run_ids") or {})
        ids["goal_architect"] = run_id
        debug = dict(state.get("debug") or {})
        debug["goal_architect"] = {"model": "see agent_runs", "run_id": run_id}
        return {
            "goal_proposal": proposal,
            "current_step": "architect_goal",
            "progress": mark_progress(state, "architect_goal"),
            "agent_run_ids": ids,
            "debug": debug,
        }

    async def _validate_goal(self, state: AgentGraphState) -> dict[str, Any]:
        proposal = GoalArchitectProposal.model_validate(state["goal_proposal"])
        errors = validation_errors(proposal)
        retries = int(state.get("architect_retries") or 0)
        if errors:
            retries += 1
        return {
            "validation_errors": errors,
            "architect_retries": retries,
            "current_step": "validate_goal",
        }

    def _after_validate_goal(self, state: AgentGraphState) -> str:
        errors = state.get("validation_errors") or []
        retries = int(state.get("architect_retries") or 0)
        proposal = GoalArchitectProposal.model_validate(state.get("goal_proposal") or {})
        if errors and retries < MAX_SEMANTIC_RETRIES:
            return "architect_goal"
        if proposal.clarifications_required and not proposal.ready_to_commit:
            return "interrupt_goal"
        if errors:
            return "interrupt_goal"
        return "confirm_goal"

    async def _interrupt_goal(self, state: AgentGraphState) -> dict[str, Any]:
        proposal = GoalArchitectProposal.model_validate(state["goal_proposal"])
        payload = InterruptPayload(
            type="clarification",
            questions=proposal.clarifications_required,
            proposal=proposal.model_dump(mode="json"),
            message="A few details are needed before this can become a market.",
        )
        answers = interrupt(payload.model_dump(mode="json"))
        if isinstance(answers, dict) and answers.get("cancelled"):
            return {"cancelled": True, "status": "cancelled", "current_step": "interrupt_goal"}
        retries = int(state.get("architect_retries") or 0) + 1
        merged = dict(state.get("resume_answers") or {})
        if isinstance(answers, dict):
            merged.update(
                {str(key): str(value) for key, value in answers.items() if key != "cancelled"}
            )
        return {
            "resume_answers": merged,
            "architect_retries": retries,
            "current_step": "interrupt_goal",
        }

    def _after_interrupt_goal(self, state: AgentGraphState) -> str:
        if state.get("cancelled"):
            return END
        return "architect_goal"

    async def _confirm_goal(self, state: AgentGraphState) -> dict[str, Any]:
        proposal = GoalArchitectProposal.model_validate(state["goal_proposal"])
        payload = InterruptPayload(
            type="confirm_contract",
            questions=[],
            proposal=proposal.model_dump(mode="json"),
            message="Confirm this goal contract to create the market.",
        )
        result = interrupt(payload.model_dump(mode="json"))
        if isinstance(result, dict) and (
            result.get("cancelled") or result.get("confirmed") is False
        ):
            return {"cancelled": True, "status": "cancelled", "current_step": "confirm_goal"}
        return {"current_step": "confirm_goal"}

    def _after_confirm_goal(self, state: AgentGraphState) -> str:
        if state.get("cancelled"):
            return END
        return "commit_goal"

    async def _commit_goal(self, state: AgentGraphState) -> dict[str, Any]:
        if state.get("committed_goal_id"):
            return {"current_step": "commit_goal"}
        proposal = GoalArchitectProposal.model_validate(state["goal_proposal"])
        goal_id = stable_goal_id(state["thread_id"])
        contract = proposal_to_contract(proposal, goal_id)
        created = await self._deps.goals.create_goal(contract, UUID(state["user_id"]))
        await self._deps.evidence.watch_goal(created.goal_id)
        return {
            "committed_goal_id": str(created.goal_id),
            "goal_id": str(created.goal_id),
            "current_step": "commit_goal",
        }

    async def _collect_evidence(self, state: AgentGraphState) -> dict[str, Any]:
        text = (state.get("evidence_text") or "").strip()
        records = list(state.get("github_records") or [])
        progress = list(state.get("progress") or [])
        if text or records or (state.get("evidence_proposal") or {}).get("events") or state.get("mcp_records"):
            progress = mark_progress(state, "normalize_evidence")
        return {
            "current_step": "collect_evidence",
            "evidence_text": text,
            "github_records": records,
            "progress": progress,
        }

    def _after_collect_evidence(self, state: AgentGraphState) -> str:
        if (state.get("evidence_proposal") or {}).get("events"):
            return "validate_evidence"
        if (state.get("evidence_text") or "").strip() or state.get("github_records") or state.get("mcp_records"):
            return "normalize_evidence"
        return "decide_research"

    async def _normalize_evidence(self, state: AgentGraphState) -> dict[str, Any]:
        payload = {
            "evidence_text": state.get("evidence_text"),
            "github_records": state.get("github_records") or [],
            "mcp_records": state.get("mcp_records") or [],
            "goal_id": state.get("goal_id"),
        }
        attempt = int(state.get("evidence_retries") or 0)
        proposal, run_id = await complete_agent(
            self._deps, state, "evidence", EvidenceAgentProposal, payload, attempt
        )
        ids = dict(state.get("agent_run_ids") or {})
        ids["evidence"] = run_id
        return {
            "evidence_proposal": proposal,
            "current_step": "normalize_evidence",
            "progress": mark_progress(state, "normalize_evidence"),
            "agent_run_ids": ids,
        }

    async def _validate_evidence(self, state: AgentGraphState) -> dict[str, Any]:
        proposal = EvidenceAgentProposal.model_validate(
            state.get("evidence_proposal") or {"events": []}
        )
        errors: list[str] = []
        for event in proposal.events:
            if event.numeric_value is None and not event.categorical_value:
                errors.append(f"Event {event.summary} needs a numeric or categorical value.")
        retries = int(state.get("evidence_retries") or 0)
        structured = bool((state.get("debug") or {}).get("structured_evidence"))
        if errors and not structured:
            retries += 1
        status = "failed" if errors and structured else state.get("status")
        payload: dict[str, Any] = {
            "validation_errors": errors,
            "evidence_retries": retries,
            "current_step": "validate_evidence",
        }
        if status:
            payload["status"] = status
        return payload

    def _after_validate_evidence(self, state: AgentGraphState) -> str:
        errors = state.get("validation_errors") or []
        retries = int(state.get("evidence_retries") or 0)
        proposal = EvidenceAgentProposal.model_validate(
            state.get("evidence_proposal") or {"events": []}
        )
        if errors and (state.get("debug") or {}).get("structured_evidence"):
            return END
        if errors and retries < MAX_SEMANTIC_RETRIES:
            return "normalize_evidence"
        if proposal.ambiguities:
            return "interrupt_evidence"
        return "commit_evidence"

    async def _interrupt_evidence(self, state: AgentGraphState) -> dict[str, Any]:
        proposal = EvidenceAgentProposal.model_validate(
            state.get("evidence_proposal") or {"events": []}
        )
        payload = InterruptPayload(
            type="confirm_evidence",
            questions=proposal.ambiguities,
            proposal=proposal.model_dump(mode="json"),
            message="Review the recognized evidence before it is committed.",
        )
        result = interrupt(payload.model_dump(mode="json"))
        if isinstance(result, dict) and result.get("cancelled"):
            return {"cancelled": True, "status": "cancelled"}
        retries = int(state.get("evidence_retries") or 0) + 1
        answers = dict(state.get("resume_answers") or {})
        if isinstance(result, dict):
            answers.update({str(key): str(value) for key, value in result.items()})
        return {
            "resume_answers": answers,
            "evidence_retries": retries,
            "current_step": "interrupt_evidence",
        }

    def _after_interrupt_evidence(self, state: AgentGraphState) -> str:
        if state.get("cancelled"):
            return END
        proposal = EvidenceAgentProposal.model_validate(
            state.get("evidence_proposal") or {"events": []}
        )
        if proposal.ambiguities and int(state.get("evidence_retries") or 0) <= MAX_SEMANTIC_RETRIES:
            return "normalize_evidence"
        return "commit_evidence"

    async def _commit_evidence(self, state: AgentGraphState) -> dict[str, Any]:
        if state.get("committed_evidence_ids"):
            return {"current_step": "commit_evidence"}
        proposal = EvidenceAgentProposal.model_validate(
            state.get("evidence_proposal") or {"events": []}
        )
        goal_id = UUID(state["goal_id"])
        run_id = state.get("agent_run_ids", {}).get("evidence")
        committed = await self._deps.evidence.commit(
            user_id=UUID(state["user_id"]),
            goal_id=goal_id,
            events=proposal.events,
            agent_run_id=UUID(run_id) if run_id else None,
            conflicts=proposal.conflicts,
        )
        ids = [str(item.evidence_id) for item in committed.events if item.evidence_id]
        return {"committed_evidence_ids": ids, "current_step": "commit_evidence"}

    async def _decide_research(self, state: AgentGraphState) -> dict[str, Any]:
        if not state.get("goal_proposal"):
            goal = await self._deps.goals.get_goal(
                UUID(state["goal_id"]), owner_id=UUID(state["user_id"])
            )
            proposal = GoalArchitectProposal(
                ready_to_commit=True,
                title=goal.title,
                goal_type=goal.goal_type.value,
                success_metric=str(goal.success_definition.get("metric") or "unspecified"),
                success_operator=str(goal.success_definition.get("operator") or "=="),
                success_target=str(goal.success_definition.get("target") or ""),
                deadline=goal.deadline.date().isoformat(),
                state_dimensions=goal.state_dimensions,
                hours_per_week=goal.resource_constraints.hours_per_week,
                model_family_compatibility=str(
                    goal.model_requirements.get("compatibility") or "none"
                ),
            )
            needed = needs_research(proposal)
            return {
                "goal_proposal": proposal.model_dump(mode="json"),
                "research_needed": needed,
                "current_step": "decide_research",
            }
        proposal = GoalArchitectProposal.model_validate(state["goal_proposal"])
        return {"research_needed": needs_research(proposal), "current_step": "decide_research"}

    def _after_decide_research(self, state: AgentGraphState) -> str:
        if state.get("research_needed"):
            return "research_agent"
        return "compute_forecast"

    async def _research_agent(self, state: AgentGraphState) -> dict[str, Any]:
        proposal = GoalArchitectProposal.model_validate(state["goal_proposal"])
        query = ResearchQuery(
            query=f"{proposal.title} {proposal.success_metric} {proposal.success_target}",
            as_of=datetime.now(UTC),
            allowed_domains=["admissions", "hiring", "academic"],
            goal_type=proposal.goal_type,
        )
        retrieved = await self._deps.research.search(query)
        claims: list[dict[str, Any]] = []
        for item in retrieved.claims:
            payload = dict(item)
            payload.setdefault("retrieved_at", datetime.now(UTC).isoformat())
            payload.setdefault("source_type", "frozen")
            payload.setdefault("evidence_class", "mechanistic")
            try:
                claims.append(ResearchClaim.model_validate(payload).model_dump(mode="json"))
            except Exception:
                continue
        limitations = [
            item.get("detail") or item.get("status")
            for item in retrieved.provenance
            if item.get("status") == "not_configured" or item.get("detail")
        ]
        artifact = ResearchArtifact(
            claims=claims,
            reference_class_candidates=[
                item.get("source", "") for item in retrieved.provenance if item.get("source")
            ],
            limitations=limitations or ["Frozen reference artifacts only."],
        )
        return {
            "research": artifact.model_dump(mode="json"),
            "current_step": "research_agent",
            "progress": mark_progress(state, "research_agent"),
            "agent_run_ids": dict(state.get("agent_run_ids") or {}),
        }

    async def _compute_forecast(self, state: AgentGraphState) -> dict[str, Any]:
        from personal_markets.forecasting.inputs_builder import build_numeric_inputs

        proposal = GoalArchitectProposal.model_validate(state["goal_proposal"])
        goal_id = UUID(state["goal_id"])
        goal = await self._deps.goals.get_goal(goal_id, owner_id=UUID(state["user_id"]))
        evidence = await self._deps.evidence.list_for_goal(goal_id)
        evidence_ids = [str(item.evidence_id) for item in evidence if item.evidence_id]
        numeric = build_numeric_inputs(goal, proposal, evidence)
        research_ids = [
            claim.get("source", "")
            for claim in (state.get("research") or {}).get("claims") or []
        ]
        if numeric is not None and "hiring_funnel_rates.json" not in research_ids:
            research_ids = [*research_ids, "hiring_funnel_rates.json"]
        from personal_markets.forecasting.finance import is_finance_goal

        if numeric is not None and is_finance_goal(goal, proposal):
            if "net_worth_assumptions.json" not in research_ids:
                research_ids = [*research_ids, "net_worth_assumptions.json"]
        from personal_markets.forecasting.running import is_running_goal

        if numeric is not None and is_running_goal(goal, proposal):
            if "running_performance_assumptions.json" not in research_ids:
                research_ids = [*research_ids, "running_performance_assumptions.json"]
        from personal_markets.forecasting.startup import is_startup_goal

        if numeric is not None and is_startup_goal(goal, proposal):
            if "startup_outcome_priors.json" not in research_ids:
                research_ids = [*research_ids, "startup_outcome_priors.json"]
        pricing = self._deps.baseline_forecasts.compute(
            goal,
            proposal,
            evidence_ids,
            dict(state.get("agent_run_ids") or {}),
            research_ids,
            numeric,
        )
        return {
            "pricing": pricing.model_dump(mode="json"),
            "current_step": "compute_forecast",
            "progress": mark_progress(state, "compute_forecast"),
        }

    async def _critique(self, state: AgentGraphState) -> dict[str, Any]:
        from personal_markets.ports import EvidenceEventProposal, PricingResult

        events = [
            EvidenceEventProposal.model_validate(item)
            for item in (state.get("evidence_proposal") or {}).get("events") or []
        ]
        pricing = PricingResult.model_validate(state["pricing"])
        issues = self._deps.baseline_forecasts.deterministic_issues(
            events, list(state.get("committed_evidence_ids") or []), pricing
        )
        from personal_markets.agents.critic import deterministic_critic_decision

        deterministic = deterministic_critic_decision(issues, pricing)
        if deterministic is None:
            # Match BaselineRepriceService: a priced mathematical forecast does not
            # wait on an LLM critic to persist a receipt.
            deterministic = CriticArtifact(
                decision="publish",
                issues=[],
                limitations=pricing.limitations,
                required_actions=[],
            )
        if deterministic is not None:
            receipt = dict(pricing.receipt)
            receipt["critic_decision"] = deterministic.decision
            receipt["critic_run_id"] = None
            receipt["critic_mode"] = "deterministic"
            receipt["llm_used_for_critic"] = False
            pricing_dump = pricing.model_dump(mode="json")
            pricing_dump["receipt"] = receipt
            return {
                "critic": deterministic.model_dump(mode="json"),
                "pricing": pricing_dump,
                "current_step": "critique",
                "progress": mark_progress(state, "critique"),
                "agent_run_ids": dict(state.get("agent_run_ids") or {}),
            }
        payload = {
            "goal": state.get("goal_proposal"),
            "pricing": pricing.model_dump(mode="json"),
            "research": state.get("research"),
            "deterministic_issues": issues,
            "evidence_ids": state.get("committed_evidence_ids") or [],
        }
        artifact, run_id = await complete_agent(
            self._deps, state, "critic", CriticArtifact, payload, 0
        )
        merged = merge_critic_decision(
            issues, CriticArtifact.model_validate(artifact), pricing.priced
        )
        ids = dict(state.get("agent_run_ids") or {})
        ids["critic"] = run_id
        receipt = dict(pricing.receipt)
        receipt["critic_decision"] = merged.decision
        receipt["critic_run_id"] = run_id
        receipt["agent_run_ids"] = ids
        pricing_dump = pricing.model_dump(mode="json")
        pricing_dump["receipt"] = receipt
        return {
            "critic": merged.model_dump(mode="json"),
            "pricing": pricing_dump,
            "current_step": "critique",
            "progress": mark_progress(state, "critique"),
            "agent_run_ids": ids,
        }

    async def _publish(self, state: AgentGraphState) -> dict[str, Any]:
        critic = CriticArtifact.model_validate(state["critic"])
        from personal_markets.ports import PricingResult

        goal = await self._deps.goals.get_goal(
            UUID(state["goal_id"]), owner_id=UUID(state["user_id"])
        )
        pricing = PricingResult.model_validate(state["pricing"])
        status = await self._deps.baseline_forecasts.publish(goal, pricing, critic)
        return {"status": status, "current_step": "publish"}
