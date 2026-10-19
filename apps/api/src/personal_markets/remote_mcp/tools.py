"""Application adapter behind the remote MCP tools.

Every operation delegates to the services the REST API uses: GoalService for ownership,
EvidenceService.commit plus BaselineRepriceService for evidence and publication, and
WhatIfService for scenarios. Nothing here computes a probability.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, Field

from personal_markets.agents.state import AgentDependencies, AgentGraphState, complete_agent
from personal_markets.core.config import Settings
from personal_markets.core.errors import (
    DomainError,
    ForbiddenError,
    ProviderBudgetExceededError,
    ProviderNotConfiguredError,
    ResourceNotFoundError,
    SemanticProviderError,
    TransientProviderError,
)
from personal_markets.evidence.domain import NormalizedEvidence, SubmissionContext
from personal_markets.evidence.metrics import anchor_reported_today_increment
from personal_markets.forecasting.inputs_builder import proposal_from_goal
from personal_markets.forecasting.priceability import requirements_for
from personal_markets.forecasting.reprice import BaselineRepriceService, RepriceResult
from personal_markets.forecasting.requirements import resolve_state
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService
from personal_markets.identity.domain import Principal
from personal_markets.ports import EvidenceAgentProposal, EvidenceEventProposal
from personal_markets.remote_mcp.limits import KeyedLocks, SlidingWindowLimiter
from personal_markets.remote_mcp.policy import (
    IDEMPOTENCY_KEY,
    MetricPolicy,
    ObservationPolicy,
    match_metric,
    observation_policy,
    resolve_observed_at,
    unit_matches,
)
from personal_markets.remote_mcp.scopes import EVIDENCE_WRITE, INFERENCE, READ, SIMULATE
from personal_markets.remote_mcp.store import AuditRecord, RemoteMcpStore, SubmissionRecord, digest
from personal_markets.what_if.domain import InterventionChangeInput, WhatIfRequest, WhatIfResult
from personal_markets.what_if.intervention_overrides import unmapped_change_metrics

log = structlog.get_logger("personal_markets.remote_mcp")

_MAX_LIST = 25
_MAX_TEXT = 400
_MAX_VECTOR = 6
_PUBLISHED_STATUSES = {"completed", "limited", "unchanged"}
_SUPPORTED_EFFECT_SOURCES = {"FITTED", "REFERENCE"}


class ToolFailure(Exception):
    """A deliberate tool failure reported to the client as an MCP `isError` result."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                **({"details": self.details} if self.details else {}),
            }
        }


@dataclass(frozen=True, slots=True)
class Caller:
    principal: Principal
    connection_id: UUID
    client_id: str
    client_name: str | None
    scopes: frozenset[str]

    @property
    def user_id(self) -> UUID:
        return self.principal.user_id


def _clip(value: Any, limit: int = _MAX_TEXT) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 1] + "…"
    return value


def _compact(value: Any, depth: int = 0) -> Any:
    """Bound nested output so a receipt cannot balloon an agent's context window."""
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, list):
        if depth >= 2:
            return f"[{len(value)} items]"
        head = [_compact(item, depth + 1) for item in value[:_MAX_VECTOR]]
        if len(value) > _MAX_VECTOR:
            head.append(f"... {len(value) - _MAX_VECTOR} more")
        return head
    if isinstance(value, dict):
        if depth >= 2:
            return "{...}"
        return {
            str(key): _compact(item, depth + 1) for key, item in list(value.items())[:_MAX_LIST]
        }
    return value


def _clip_list(values: Any, limit: int = _MAX_LIST) -> list[Any]:
    if not isinstance(values, list):
        return []
    return [_compact(item) for item in values[:limit]]


def _scalars(values: Any) -> dict[str, Any]:
    if not isinstance(values, dict):
        return {}
    return {
        str(key): value
        for key, value in list(values.items())[:_MAX_LIST]
        if isinstance(value, (int, float, str, bool)) or value is None
    }


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# --- output models -------------------------------------------------------------


class GoalSummary(BaseModel):
    goal_id: str
    title: str
    goal_type: str
    deadline: str
    forecast_status: str
    success_metric: str | None = None
    success_target: str | None = None


class GoalList(BaseModel):
    goals: list[GoalSummary]
    total: int
    next_cursor: str | None = None


class GoalDetail(GoalSummary):
    success_definition: dict[str, Any]
    state_dimensions: list[str]
    contract_version: int
    model_family: str | None = None
    model_version: str | None = None
    compiler_version: str | None = None
    observable_inputs: list[dict[str, Any]] = Field(default_factory=list)


class ForecastView(BaseModel):
    goal_id: str
    status: Literal["PUBLISHED", "NOT_PUBLISHED"]
    probability: float | None = None
    probability_basis: str | None = None
    forecast_status: str | None = None
    model_family: str | None = None
    model_version: str | None = None
    compiler_version: str | None = None
    published_at: str | None = None
    evidence_watermark: str | None = None
    assumptions: list[Any] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    llm_used_for_probability: bool = False
    published_points: int = 0
    message: str | None = None
    missing_inputs: list[dict[str, Any]] = Field(default_factory=list)


class HistoryPoint(BaseModel):
    probability: float
    forecast_status: str
    model_family: str
    model_version: str
    evidence_watermark: str
    published_at: str | None = None


class ForecastHistory(BaseModel):
    goal_id: str
    points: list[HistoryPoint]
    total: int


class EvidenceItem(BaseModel):
    evidence_id: str | None
    metric: str
    value: float | None
    categorical_value: str | None = None
    unit: str | None
    observation_kind: str | None
    observed_at: str | None
    source_type: str
    verification_status: str | None
    corroborating_sources: int = 0
    submitted_by_connection: str | None = None


class EvidenceSummary(BaseModel):
    goal_id: str
    total: int
    items: list[EvidenceItem]
    by_verification_status: dict[str, int]


class InterventionRanking(BaseModel):
    goal_id: str
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    reason: str
    ranked: list[dict[str, Any]] = Field(default_factory=list)
    excluded: list[dict[str, Any]] = Field(default_factory=list)
    next_step: str | None = None


class PublicationView(BaseModel):
    status: str
    priced: bool
    probability: float | None = None
    reason: str | None = None


class SubmissionResult(BaseModel):
    status: Literal["committed", "replayed", "needs_clarification", "in_progress"]
    goal_id: str
    idempotency_key: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    dedup: list[str] = Field(default_factory=list)
    publication: PublicationView | None = None
    questions: list[str] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    llm_calls: int = 0
    message: str | None = None


class ChangeInput(BaseModel):
    metric: str = Field(min_length=1, max_length=80)
    operation: Literal["set", "add", "subtract"]
    value: float = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=40)


class SimulationView(BaseModel):
    goal_id: str
    status: str
    priced: bool
    causal_status: str | None = None
    published_baseline: ForecastView
    scenario_baseline_probability: float | None = None
    scenario_probability: float | None = None
    delta_pp: float | None = None
    uplift_interval_pp: list[float] | None = None
    mapped_changes: list[str] = Field(default_factory=list)
    unmapped_changes: list[str] = Field(default_factory=list)
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None
    hypothetical: bool = True
    writes_published_history: bool = False


# --- service -----------------------------------------------------------------------


class RemoteMcpTools:
    def __init__(
        self,
        *,
        settings: Settings,
        store: RemoteMcpStore,
        deps: Callable[[], AgentDependencies],
        goals: GoalService | None = None,
        what_if: Callable[[Principal], Any],
        limiter: SlidingWindowLimiter | None = None,
        locks: KeyedLocks | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._goal_override = goals
        self._deps = deps
        self._what_if = what_if
        self._limiter = limiter or SlidingWindowLimiter()
        self._locks = locks or KeyedLocks()

    @property
    def _goals(self) -> GoalService:
        return self._goal_override or self._deps().goals

    # --- guards ---------------------------------------------------------------------

    @staticmethod
    def require_scope(caller: Caller, *scopes: str) -> None:
        missing = [scope for scope in scopes if scope not in caller.scopes]
        if missing:
            raise ToolFailure(
                "insufficient_scope",
                f"This connection was not granted {', '.join(missing)}. Reconnect and approve "
                "that permission in PlayItOut.",
            )

    async def rate_limit(self, caller: Caller, tool: str, *, write: bool, inference: bool) -> None:
        key = str(caller.connection_id)
        settings = self._settings
        if not await self._limiter.allow("tools", key, settings.mcp_tool_calls_per_minute, 60):
            raise ToolFailure("rate_limited", "Too many tool calls. Wait a minute.", retryable=True)
        if write and not await self._limiter.allow(
            "writes", key, settings.mcp_writes_per_minute, 60
        ):
            raise ToolFailure("rate_limited", "Too many writes. Wait a minute.", retryable=True)
        if inference:
            user = str(caller.user_id)
            minute = await self._limiter.allow(
                "inference", user, settings.mcp_inference_calls_per_minute, 60
            )
            day = minute and await self._limiter.allow(
                "inference_day", user, settings.mcp_inference_calls_per_day, 86_400
            )
            if not (minute and day):
                raise ToolFailure(
                    "rate_limited",
                    "Natural-language submissions are rate limited. Use "
                    "submit_structured_evidence, which needs no model call.",
                    retryable=True,
                )
        del tool

    async def audit(self, caller: Caller, tool: str, outcome: str, **detail: Any) -> None:
        try:
            await self._store.audit(
                AuditRecord(
                    event="tool.call",
                    outcome=outcome,
                    user_id=caller.user_id,
                    connection_id=caller.connection_id,
                    client_id=caller.client_id,
                    tool_name=tool,
                    detail=detail,
                )
            )
        except Exception:
            log.warning("mcp_audit_failed", tool=tool)

    async def _goal(self, caller: Caller, goal_id: str) -> GoalContract:
        try:
            parsed = UUID(goal_id)
        except ValueError:
            raise ToolFailure("invalid_argument", "goal_id must be a UUID") from None
        try:
            return await self._goals.get_goal(parsed, owner_id=caller.user_id)
        except ResourceNotFoundError:
            # Same answer for missing and not-owned goals, so ids cannot be probed.
            raise ToolFailure("not_found", "Goal not found") from None

    # --- read tools ---------------------------------------------------------------

    @staticmethod
    def _summary(goal: GoalContract) -> GoalSummary:
        success = goal.success_definition or {}
        return GoalSummary(
            goal_id=str(goal.goal_id),
            title=_clip(goal.title, 200),
            goal_type=goal.goal_type.value,
            deadline=goal.deadline.isoformat(),
            forecast_status=str(getattr(goal.forecast_status, "value", goal.forecast_status)),
            success_metric=_clip(str(success.get("metric")), 120)
            if success.get("metric")
            else None,
            success_target=_clip(str(success.get("target")), 120)
            if success.get("target") is not None
            else None,
        )

    async def list_goals(self, caller: Caller, limit: int, cursor: str | None) -> GoalList:
        self.require_scope(caller, READ)
        goals = await self._goals.list_goals(owner_id=caller.user_id)
        try:
            offset = int(cursor) if cursor else 0
        except ValueError:
            raise ToolFailure("invalid_argument", "cursor is invalid") from None
        offset = max(offset, 0)
        page = goals[offset : offset + limit]
        following = offset + limit
        return GoalList(
            goals=[self._summary(goal) for goal in page],
            total=len(goals),
            next_cursor=str(following) if following < len(goals) else None,
        )

    async def get_goal(self, caller: Caller, goal_id: str) -> GoalDetail:
        self.require_scope(caller, READ)
        goal = await self._goal(caller, goal_id)
        spec = goal.model_requirements.get("forecast_spec") or {}
        return GoalDetail(
            **self._summary(goal).model_dump(),
            success_definition=_scalars(goal.success_definition),
            state_dimensions=[str(item) for item in goal.state_dimensions[:_MAX_LIST]],
            contract_version=goal.version,
            model_family=spec.get("family"),
            model_version=spec.get("model_version"),
            compiler_version=spec.get("compiler_version"),
            observable_inputs=[
                _scalars(item)
                for item in (spec.get("observable_inputs") or [])[:_MAX_LIST]
                if isinstance(item, dict)
            ],
        )

    async def _published(self, goal: GoalContract) -> list[Any]:
        return await self._deps().baseline_forecasts.published_history(goal.goal_id)

    async def _forecast(self, caller: Caller, goal: GoalContract) -> ForecastView:
        history = await self._published(goal)
        if not history:
            return await self._unpublished(goal)
        latest = history[-1]
        receipt = latest.receipt or {}
        calibrated = receipt.get("calibrated_probability")
        return ForecastView(
            goal_id=str(goal.goal_id),
            status="PUBLISHED",
            probability=latest.probability,
            probability_basis="calibrated" if calibrated is not None else "raw_model",
            forecast_status=latest.forecast_status,
            model_family=latest.model_family,
            model_version=latest.model_version,
            compiler_version=receipt.get("compiler_version"),
            published_at=latest.published_at.isoformat() if latest.published_at else None,
            evidence_watermark=latest.evidence_watermark,
            assumptions=_clip_list(receipt.get("assumptions")),
            limitations=_clip_list(receipt.get("limitations")),
            diagnostics={
                **_scalars(receipt.get("feature_transforms")),
                "calibration_applied": bool((receipt.get("calibration") or {}).get("applied")),
                "critic_decision": receipt.get("critic_decision"),
            },
            llm_used_for_probability=bool(receipt.get("llm_used_for_probability", False)),
            published_points=len(history),
        )

    async def _unpublished(self, goal: GoalContract) -> ForecastView:
        base = (
            "No forecast has been published for this goal. PlayItOut does not report a "
            "probability until its model can price the goal."
        )
        match = requirements_for(goal, proposal_from_goal(goal))
        if match is None:
            return ForecastView(
                goal_id=str(goal.goal_id),
                status="NOT_PUBLISHED",
                message=base + " No numerical model family covers this goal yet.",
            )
        family, requirements = match
        events = await self._deps().evidence.list_for_goal(goal.goal_id)
        resolution = resolve_state(requirements, events)
        missing = [
            {"key": item.key, "label": item.label, "unit": item.unit} for item in resolution.missing
        ][:_MAX_LIST]
        if missing:
            detail = " Still needed: " + ", ".join(item["label"] for item in missing) + "."
        else:
            detail = " The inputs are present; the latest publication attempt did not complete."
        return ForecastView(
            goal_id=str(goal.goal_id),
            status="NOT_PUBLISHED",
            model_family=family,
            message=base + detail,
            missing_inputs=missing,
        )

    async def get_forecast(self, caller: Caller, goal_id: str) -> ForecastView:
        self.require_scope(caller, READ)
        goal = await self._goal(caller, goal_id)
        return await self._forecast(caller, goal)

    async def get_forecast_history(
        self, caller: Caller, goal_id: str, limit: int
    ) -> ForecastHistory:
        self.require_scope(caller, READ)
        goal = await self._goal(caller, goal_id)
        history = await self._published(goal)
        points = [
            HistoryPoint(
                probability=item.probability,
                forecast_status=item.forecast_status,
                model_family=item.model_family,
                model_version=item.model_version,
                evidence_watermark=item.evidence_watermark,
                published_at=item.published_at.isoformat() if item.published_at else None,
            )
            for item in history[-limit:]
        ]
        return ForecastHistory(goal_id=goal_id, points=points, total=len(history))

    @staticmethod
    def _evidence_item(item: NormalizedEvidence) -> EvidenceItem:
        provenance = item.provenance
        return EvidenceItem(
            evidence_id=str(item.evidence_id) if item.evidence_id else None,
            metric=item.metric,
            value=item.numeric_value,
            categorical_value=_clip(item.categorical_value, 120),
            unit=item.unit,
            observation_kind=provenance.observation_kind,
            observed_at=item.observed_at.isoformat() if item.observed_at else None,
            source_type=provenance.source_type,
            verification_status=provenance.verification_status,
            corroborating_sources=len(provenance.corroborating_sources),
            submitted_by_connection=provenance.submission.connection_id
            if provenance.submission
            else None,
        )

    async def get_evidence_summary(
        self, caller: Caller, goal_id: str, limit: int
    ) -> EvidenceSummary:
        self.require_scope(caller, READ)
        goal = await self._goal(caller, goal_id)
        events = await self._deps().evidence.list_for_goal(goal.goal_id)
        counts: dict[str, int] = {}
        for item in events:
            status = item.provenance.verification_status or "unclassified"
            counts[status] = counts.get(status, 0) + 1
        return EvidenceSummary(
            goal_id=goal_id,
            total=len(events),
            items=[self._evidence_item(item) for item in events[-limit:]],
            by_verification_status=counts,
        )

    async def get_observation_policy(self, caller: Caller, goal_id: str) -> ObservationPolicy:
        self.require_scope(caller, READ)
        return observation_policy(await self._goal(caller, goal_id))

    async def get_best_interventions(self, caller: Caller, goal_id: str) -> InterventionRanking:
        self.require_scope(caller, READ)
        goal = await self._goal(caller, goal_id)
        baseline = await self._what_if(caller.principal).baseline_state(str(goal.goal_id))
        if not baseline.priced:
            return InterventionRanking(
                goal_id=goal_id,
                status="UNAVAILABLE",
                reason="The goal is not priced yet, so no intervention can be compared.",
                next_step="Submit the inputs listed by get_observation_policy.",
            )
        supported, excluded = [], []
        for candidate in baseline.compare_candidates:
            source = candidate.intervention.effect_source
            if (
                candidate.intervention.effect_per_unit is not None
                and str(getattr(source, "value", source)) in _SUPPORTED_EFFECT_SOURCES
            ):
                supported.append(candidate)
            else:
                excluded.append(
                    {
                        "id": candidate.id,
                        "title": candidate.title,
                        "reason": "Its effect size is an exploration assumption, not a fitted "
                        "or reference-derived estimate.",
                    }
                )
        if not supported:
            return InterventionRanking(
                goal_id=goal_id,
                status="UNAVAILABLE",
                reason=(
                    "No candidate intervention has a quantitatively supported effect for this "
                    "goal, so PlayItOut will not rank them."
                ),
                excluded=excluded[:_MAX_LIST],
                next_step=(
                    "Use simulate_intervention with a specific parameter change to explore a "
                    "hypothetical. Results are labeled as hypothetical."
                ),
            )
        service = self._what_if(caller.principal)
        ranked = []
        for candidate in supported[:5]:
            request = WhatIfRequest(
                goal_id=goal_id,
                current_value=baseline.current_value or 0,
                target_value=baseline.target_value or 1,
                periods=baseline.periods or 8,
                direction=baseline.direction,
                assumptions=baseline.assumptions,
                intervention=candidate.intervention,
                config=baseline.config,
            )
            result = await service.fast_reprice(request)
            if result.priced and result.expected_uplift_pp is not None:
                ranked.append(
                    {
                        "id": candidate.id,
                        "title": candidate.title,
                        "expected_uplift_pp": result.expected_uplift_pp,
                        "uplift_interval_pp": list(result.uplift_interval_pp or []),
                        "effect_source": str(candidate.intervention.effect_source),
                    }
                )
        ranked.sort(key=lambda item: item["expected_uplift_pp"], reverse=True)
        return InterventionRanking(
            goal_id=goal_id,
            status="AVAILABLE" if ranked else "UNAVAILABLE",
            reason="Ranked by simulated uplift in percentage points."
            if ranked
            else "Supported candidates could not be priced.",
            ranked=ranked,
            excluded=excluded[:_MAX_LIST],
        )

    # --- writes -------------------------------------------------------------------------

    def _submission(
        self,
        caller: Caller,
        source_category: str,
        source_identifier: str | None,
        supporting_reference: str | None,
        key: str,
        agent_run_id: str | None = None,
    ) -> SubmissionContext:
        return SubmissionContext(
            connection_id=str(caller.connection_id),
            client_id=caller.client_id,
            client_name=caller.client_name,
            source_category=source_category,
            source_identifier=source_identifier,
            supporting_reference=supporting_reference,
            received_at=datetime.now(UTC),
            idempotency_key_hash=digest(f"{caller.user_id}:{key}"),
            agent_run_id=agent_run_id,
        )

    @staticmethod
    def _check_key(key: str) -> None:
        if not IDEMPOTENCY_KEY.fullmatch(key):
            raise ToolFailure(
                "invalid_argument",
                "idempotency_key must be 8-128 characters of letters, digits, '.', '_', ':' or '-'",
            )

    async def _claim(
        self, caller: Caller, goal: GoalContract, key: str, payload: dict[str, Any]
    ) -> tuple[SubmissionRecord, bool]:
        record, created = await self._store.claim_submission(
            SubmissionRecord(
                user_id=caller.user_id,
                idempotency_key=key,
                goal_id=goal.goal_id,
                connection_id=caller.connection_id,
                payload_hash=_payload_hash(payload),
            )
        )
        if not created and record.payload_hash != _payload_hash(payload):
            raise ToolFailure(
                "idempotency_conflict",
                "This idempotency_key was already used for a different submission.",
            )
        return record, created

    async def _replay(self, caller: Caller, record: SubmissionRecord, key: str) -> SubmissionResult:
        if record.status == "pending":
            return SubmissionResult(
                status="in_progress",
                goal_id=str(record.goal_id),
                idempotency_key=key,
                message="A submission with this key is still being processed. Retry shortly.",
            )
        stored = SubmissionResult.model_validate(record.result)
        publication = stored.publication
        if publication is not None and publication.status == "error":
            # The evidence was committed but repricing failed; retrying completes it.
            publication = await self._reprice(caller, record.goal_id)
            await self._store.finish_submission(
                caller.user_id,
                key,
                "committed",
                stored.model_copy(update={"publication": publication}).model_dump(mode="json"),
            )
        return stored.model_copy(
            update={"status": "replayed", "publication": publication, "llm_calls": 0}
        )

    async def _reprice(self, caller: Caller, goal_id: UUID) -> PublicationView:
        deps = self._deps()
        service = BaselineRepriceService(
            deps.goals, deps.evidence, deps.baseline_forecasts, owner_id=caller.user_id
        )
        try:
            outcome: RepriceResult = await service.publish_if_priceable(goal_id)
        except Exception as error:
            log.warning("mcp_reprice_failed", error_type=type(error).__name__)
            return PublicationView(
                status="error",
                priced=False,
                reason="Evidence was saved but the forecast could not be republished. Retry the "
                "same submission to try again.",
            )
        priced = outcome.status in _PUBLISHED_STATUSES and outcome.probability is not None
        return PublicationView(
            status=outcome.status,
            priced=priced,
            probability=outcome.probability if priced else None,
            reason=_clip(outcome.reason),
        )

    async def _commit(
        self,
        caller: Caller,
        goal: GoalContract,
        key: str,
        events: list[EvidenceEventProposal],
        submission: SubmissionContext,
        agent_run_id: UUID | None,
        llm_calls: int,
    ) -> SubmissionResult:
        deps = self._deps()
        async with self._locks.get(str(goal.goal_id)):
            before = {item.evidence_id for item in await deps.evidence.list_for_goal(goal.goal_id)}
            try:
                commit = await deps.evidence.commit(
                    user_id=caller.user_id,
                    goal_id=goal.goal_id,
                    events=events,
                    agent_run_id=agent_run_id,
                    conflicts=[],
                    submission=submission,
                )
            except Exception:
                await self._store.finish_submission(caller.user_id, key, "failed", {})
                raise
            publication = await self._reprice(caller, goal.goal_id)
        result = SubmissionResult(
            status="committed",
            goal_id=str(goal.goal_id),
            idempotency_key=key,
            evidence=[self._evidence_item(item) for item in commit.events],
            dedup=[
                "corroborated_existing" if item.evidence_id in before else "new"
                for item in commit.events
            ],
            publication=publication,
            llm_calls=llm_calls,
        )
        await self._store.finish_submission(
            caller.user_id, key, "committed", result.model_dump(mode="json")
        )
        return result

    async def submit_structured_evidence(
        self,
        caller: Caller,
        *,
        goal_id: str,
        metric: str,
        value: float,
        unit: str,
        observation_kind: str,
        idempotency_key: str,
        source_category: str,
        observed_at: str | None = None,
        period: str | None = None,
        source_identifier: str | None = None,
        supporting_reference: str | None = None,
        note: str | None = None,
    ) -> SubmissionResult:
        self.require_scope(caller, EVIDENCE_WRITE)
        self._check_key(idempotency_key)
        goal = await self._goal(caller, goal_id)
        policy = observation_policy(goal)
        metric_policy = self._validate(policy, metric, unit, observation_kind)
        try:
            when = resolve_observed_at(metric_policy, observed_at, period, datetime.now(UTC))
        except ValueError as error:
            raise ToolFailure("invalid_argument", str(error)) from None
        payload = {
            "tool": "submit_structured_evidence",
            "goal_id": str(goal.goal_id),
            "metric": metric_policy.metric,
            "value": value,
            "unit": metric_policy.unit,
            "kind": observation_kind,
            "observed_at": when.isoformat(),
            "source": [source_category, source_identifier, supporting_reference],
        }
        record, created = await self._claim(caller, goal, idempotency_key, payload)
        if not created:
            return await self._replay(caller, record, idempotency_key)
        label = f"{metric_policy.label}: {value:g} {metric_policy.unit}"
        summary = _clip(
            f"{label} ({observation_kind}) reported by "
            f"{caller.client_name or 'a connected agent'} via {source_category}"
            + (f". Note: {note}" if note else ""),
            300,
        )
        event = EvidenceEventProposal(
            event_type="agent_observation",
            observation_kind=observation_kind,  # type: ignore[arg-type]
            domain="personal_agent",
            metric=metric_policy.metric,
            numeric_value=value,
            unit=metric_policy.unit,
            observed_at=when.isoformat(),
            source_type="personal_agent",
            summary=summary,
            event_identity=self._identity(caller, idempotency_key, 0, observation_kind),
        )
        submission = self._submission(
            caller, source_category, source_identifier, supporting_reference, idempotency_key
        )
        return await self._commit(caller, goal, idempotency_key, [event], submission, None, 0)

    @staticmethod
    def _identity(caller: Caller, key: str, index: int, kind: str) -> str | None:
        # Increments are occurrences: two equal reports on one day are two events unless
        # they are the same submission. Snapshots and periods dedupe by value instead.
        if kind != "increment":
            return None
        return "agent:" + digest(f"{caller.user_id}:{key}:{index}")[:24]

    @staticmethod
    def _validate(
        policy: ObservationPolicy, metric: str, unit: str, observation_kind: str
    ) -> MetricPolicy:
        if not policy.priceable_family:
            raise ToolFailure(
                "not_accepted",
                "This goal has no numerical model yet, so it does not accept structured evidence.",
            )
        metric_policy = match_metric(policy, metric)
        if metric_policy is None:
            raise ToolFailure(
                "invalid_argument",
                f"Metric {metric!r} is not used by this goal's model.",
                details={"accepted_metrics": [item.metric for item in policy.metrics]},
            )
        if not unit_matches(metric_policy.unit, unit, metric_policy):
            raise ToolFailure(
                "invalid_argument",
                f"Unit {unit!r} does not match {metric_policy.metric}, which uses "
                f"{metric_policy.unit!r}.",
            )
        if observation_kind not in metric_policy.accepted_kinds:
            raise ToolFailure(
                "invalid_argument",
                f"observation_kind {observation_kind!r} is not accepted for "
                f"{metric_policy.metric}.",
                details={"accepted_kinds": list(metric_policy.accepted_kinds)},
            )
        return metric_policy

    async def submit_observation(
        self,
        caller: Caller,
        *,
        goal_id: str,
        text: str,
        idempotency_key: str,
        source_category: str,
        source_identifier: str | None = None,
        supporting_reference: str | None = None,
    ) -> SubmissionResult:
        self.require_scope(caller, EVIDENCE_WRITE, INFERENCE)
        self._check_key(idempotency_key)
        goal = await self._goal(caller, goal_id)
        policy = observation_policy(goal)
        payload = {
            "tool": "submit_observation",
            "goal_id": str(goal.goal_id),
            "text": text,
            "source": [source_category, source_identifier, supporting_reference],
        }
        record, created = await self._claim(caller, goal, idempotency_key, payload)
        if not created:
            return await self._replay(caller, record, idempotency_key)
        try:
            proposal, run_id = await self._extract(caller, goal, text)
        except ToolFailure:
            await self._store.finish_submission(caller.user_id, idempotency_key, "failed", {})
            raise
        candidates, problems = self._check_extraction(policy, proposal)
        if problems:
            result = SubmissionResult(
                status="needs_clarification",
                goal_id=goal_id,
                idempotency_key=idempotency_key,
                questions=problems[:_MAX_LIST],
                candidates=candidates[:_MAX_LIST],
                llm_calls=1,
                message=(
                    "Nothing was committed. Confirm the values and resubmit them with "
                    "submit_structured_evidence, which needs no model call."
                ),
            )
            await self._store.finish_submission(
                caller.user_id, idempotency_key, "committed", result.model_dump(mode="json")
            )
            return result
        received = datetime.now(UTC)
        events = []
        for index, (event, metric_policy) in enumerate(candidates_with_policy(policy, proposal)):
            event = anchor_reported_today_increment(
                event.model_copy(update={"source_type": "manual"}), received
            )
            events.append(
                event.model_copy(
                    update={
                        "metric": metric_policy.metric,
                        "unit": metric_policy.unit,
                        "source_type": "personal_agent",
                        "domain": "personal_agent",
                        "summary": _clip(event.summary, 300),
                        "event_identity": self._identity(
                            caller, idempotency_key, index, str(event.observation_kind)
                        ),
                    }
                )
            )
        submission = self._submission(
            caller,
            source_category,
            source_identifier,
            supporting_reference,
            idempotency_key,
            agent_run_id=run_id,
        )
        return await self._commit(
            caller,
            goal,
            idempotency_key,
            events,
            submission,
            UUID(run_id) if run_id else None,
            1,
        )

    async def _extract(
        self, caller: Caller, goal: GoalContract, text: str
    ) -> tuple[EvidenceAgentProposal, str | None]:
        deps = self._deps()
        state: AgentGraphState = {"thread_id": str(uuid4()), "user_id": str(caller.user_id)}
        payload = {
            "evidence_text": text,
            "github_records": [],
            "mcp_records": [],
            "goal_id": str(goal.goal_id),
            "goal": goal.model_dump(mode="json"),
            "user_answers": {},
            "previous_validation_errors": [],
            "current_time": datetime.now(UTC).isoformat(),
        }
        try:
            raw, run_id = await complete_agent(
                deps,
                state,
                "evidence",
                EvidenceAgentProposal,
                payload,
                0,
            )
        except ProviderBudgetExceededError:
            raise ToolFailure(
                "budget_exhausted",
                "Your model credit limit has been reached. Use submit_structured_evidence, "
                "which needs no model call, or add your own provider key in Settings.",
            ) from None
        except ProviderNotConfiguredError:
            raise ToolFailure(
                "inference_unavailable",
                "Natural-language interpretation is not available for this account. Check the "
                "inference mode in PlayItOut Settings, or use submit_structured_evidence.",
            ) from None
        except TransientProviderError:
            raise ToolFailure(
                "inference_unavailable",
                "The model provider is temporarily unavailable.",
                retryable=True,
            ) from None
        except (ForbiddenError, SemanticProviderError, DomainError) as error:
            raise ToolFailure("inference_failed", _clip(str(error), 200)) from None
        return EvidenceAgentProposal.model_validate(raw), run_id

    @staticmethod
    def _check_extraction(
        policy: ObservationPolicy, proposal: EvidenceAgentProposal
    ) -> tuple[list[dict[str, Any]], list[str]]:
        candidates: list[dict[str, Any]] = []
        problems: list[str] = [item.question for item in proposal.ambiguities]
        if not proposal.events:
            problems.append("No measurable observation was found in the text.")
        for event in proposal.events:
            metric_policy = match_metric(policy, event.metric) if policy.priceable_family else None
            candidates.append(
                {
                    "metric": metric_policy.metric if metric_policy else event.metric,
                    "value": event.numeric_value,
                    "unit": metric_policy.unit if metric_policy else event.unit,
                    "observation_kind": event.observation_kind,
                    "observed_at": event.observed_at,
                }
            )
            if metric_policy is None:
                problems.append(f"{event.metric!r} is not a metric this goal's model uses.")
                continue
            if event.numeric_value is None:
                problems.append(f"No numeric value was found for {metric_policy.metric}.")
            if event.observation_kind not in metric_policy.accepted_kinds:
                problems.append(
                    f"Is {metric_policy.metric} a current total (snapshot), an additional "
                    "amount (increment), or a measurement for a period?"
                )
        return candidates, list(dict.fromkeys(problems))

    # --- What If ----------------------------------------------------------------------

    async def simulate_intervention(
        self, caller: Caller, goal_id: str, changes: list[ChangeInput]
    ) -> SimulationView:
        self.require_scope(caller, SIMULATE)
        goal = await self._goal(caller, goal_id)
        published = await self._forecast(caller, goal)
        service = self._what_if(caller.principal)
        baseline = await service.baseline_state(str(goal.goal_id))
        if not baseline.priced:
            return SimulationView(
                goal_id=goal_id,
                status="NOT_PRICED",
                priced=False,
                causal_status="baseline_not_priced",
                published_baseline=published,
                message=baseline.message or "The goal cannot be priced yet.",
                limitations=_clip_list(baseline.limitations),
            )
        request = build_what_if_request(goal_id, baseline, changes)
        result: WhatIfResult = await service.fast_reprice(request)
        receipt = result.receipt or {}
        unmapped = receipt.get("unmapped")
        if not isinstance(unmapped, list):
            unmapped = unmapped_change_metrics(
                {item.name for item in baseline.assumptions}, [item.metric for item in changes]
            )
        mapped = [item.metric for item in changes if item.metric not in unmapped]
        limitations = _clip_list(receipt.get("limitations")) or _clip_list(baseline.limitations)
        return SimulationView(
            goal_id=goal_id,
            status=result.status,
            priced=result.priced,
            causal_status=str(receipt.get("causal_status") or "")
            or ("parameter_intervention" if result.priced else None),
            published_baseline=published,
            scenario_baseline_probability=result.baseline_probability,
            scenario_probability=result.scenario_probability,
            delta_pp=result.expected_uplift_pp,
            uplift_interval_pp=list(result.uplift_interval_pp)
            if result.uplift_interval_pp
            else None,
            mapped_changes=mapped,
            unmapped_changes=[str(item) for item in unmapped],
            assumptions=[
                {
                    "name": item.name,
                    "value": _compact(item.value),
                    "unit": item.unit,
                    "source": str(getattr(item.source, "value", item.source)),
                }
                for item in result.assumptions[:_MAX_LIST]
            ],
            limitations=limitations,
            diagnostics=_compact(result.diagnostics.model_dump()) if result.diagnostics else {},
            message=_clip(result.message),
        )


def candidates_with_policy(
    policy: ObservationPolicy, proposal: EvidenceAgentProposal
) -> list[tuple[EvidenceEventProposal, MetricPolicy]]:
    pairs = []
    for event in proposal.events:
        metric_policy = match_metric(policy, event.metric)
        if metric_policy is not None:
            pairs.append((event, metric_policy))
    return pairs


def build_what_if_request(goal_id: str, baseline: Any, changes: list[ChangeInput]) -> WhatIfRequest:
    """Same request the web client builds from a baseline, plus typed parameter changes."""
    return WhatIfRequest(
        goal_id=goal_id,
        current_value=baseline.current_value if baseline.current_value is not None else 0,
        target_value=baseline.target_value if baseline.target_value is not None else 1,
        periods=baseline.periods or 8,
        direction=baseline.direction,
        assumptions=baseline.assumptions,
        intervention=None,
        parsed_changes=[
            InterventionChangeInput(
                metric=item.metric,
                operation=item.operation,
                value=item.value,
                unit=item.unit,
                provenance="USER_ASSUMPTION",
            )
            for item in changes
        ],
        config=baseline.config,
    )
