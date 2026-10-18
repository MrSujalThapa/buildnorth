from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from personal_markets.core.config import get_settings
from personal_markets.core.errors import ResourceNotFoundError
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import Principal
from personal_markets.integrations.csv_import import (
    CsvColumnMapping,
    CsvImportRequest,
    parse_csv,
    preview_csv,
)
from personal_markets.integrations.github import GitHubEvidenceSource
from personal_markets.ports import (
    AgentWorkflow,
    EvidenceEventProposal,
    ResumePayload,
    WorkflowRequest,
    WorkflowSnapshot,
)
from personal_markets.wiring import (
    get_agent_workflow,
    get_baseline_reprice_service,
    get_evidence_service,
    get_github_cursor_store,
    get_goal_service,
)

router = APIRouter(prefix="/api/v1", tags=["agents"])


class CreateThreadBody(BaseModel):
    kind: str = "create_goal"
    intent: str | None = None
    goal_id: UUID | None = None
    evidence_text: str | None = None
    github_login: str | None = None
    mcp_records: list[dict[str, Any]] | None = None
    evidence_events: list[EvidenceEventProposal] | None = None


class ResumeBody(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)
    confirmed: bool | None = None
    cancelled: bool = False


@router.post("/agent/threads", response_model=WorkflowSnapshot)
async def start_thread(
    body: CreateThreadBody,
    workflow: Annotated[AgentWorkflow, Depends(get_agent_workflow)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> WorkflowSnapshot:
    request = WorkflowRequest(
        kind=body.kind,  # type: ignore[arg-type]
        intent=body.intent,
        goal_id=body.goal_id,
        evidence_text=body.evidence_text,
        github_login=body.github_login,
        mcp_records=body.mcp_records,
        evidence_events=body.evidence_events,
        user_id=principal.user_id,
    )
    return await workflow.start(request)


@router.get("/agent/threads/{thread_id}", response_model=WorkflowSnapshot)
async def get_thread(
    thread_id: UUID,
    workflow: Annotated[AgentWorkflow, Depends(get_agent_workflow)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> WorkflowSnapshot:
    snapshot = await workflow.snapshot(thread_id)
    _assert_thread_owner(snapshot, principal)
    return snapshot


@router.post("/agent/threads/{thread_id}/resume", response_model=WorkflowSnapshot)
async def resume_thread(
    thread_id: UUID,
    body: ResumeBody,
    workflow: Annotated[AgentWorkflow, Depends(get_agent_workflow)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> WorkflowSnapshot:
    snapshot = await workflow.snapshot(thread_id)
    _assert_thread_owner(snapshot, principal)
    return await workflow.resume(
        thread_id,
        ResumePayload(answers=body.answers, confirmed=body.confirmed, cancelled=body.cancelled),
    )


@router.get("/goals/{goal_id}/evidence")
async def list_evidence(
    goal_id: UUID,
    evidence: Annotated[Any, Depends(get_evidence_service)],
    goals: Annotated[Any, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> list[dict[str, Any]]:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    rows = await evidence.list_for_goal(goal_id)
    return [row.model_dump(mode="json") for row in rows]


@router.post("/goals/{goal_id}/evidence", response_model=WorkflowSnapshot)
async def add_manual_evidence(
    goal_id: UUID,
    body: CreateThreadBody,
    workflow: Annotated[AgentWorkflow, Depends(get_agent_workflow)],
    goals: Annotated[Any, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> WorkflowSnapshot:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    return await workflow.start(
        WorkflowRequest(
            kind="add_evidence",
            goal_id=goal_id,
            evidence_text=body.evidence_text or body.intent,
            evidence_events=body.evidence_events,
            user_id=principal.user_id,
        )
    )


class ManualStateEntry(BaseModel):
    """One state variable the user typed in because no connected source supplies it."""

    key: str
    label: str
    value: float
    unit: str | None = None


class ManualStateBody(BaseModel):
    entries: list[ManualStateEntry] = Field(min_length=1)


class ManualStateResponse(BaseModel):
    events: list[dict[str, Any]]
    reprice_status: str
    priced: bool
    reason: str | None = None
    probability: float | None = None


@router.post("/goals/{goal_id}/evidence/manual", response_model=ManualStateResponse)
async def add_manual_state(
    goal_id: UUID,
    body: ManualStateBody,
    evidence: Annotated[Any, Depends(get_evidence_service)],
    reprice: Annotated[Any, Depends(get_baseline_reprice_service)],
    goals: Annotated[Any, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> ManualStateResponse:
    """Commit numbers the user entered directly against a declared state requirement.

    A typed number is user data, not an agent proposal, so it does not go through the
    Evidence Agent: the requirement already names the metric, and round-tripping through
    an LLM would only add cost and a chance of renaming it. It commits through the same
    repository as every other event, so fingerprint de-duplication and provenance apply.
    """
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    observed_at = datetime.now(UTC).isoformat()
    proposals = [
        EvidenceEventProposal(
            event_type="manual_state_entry",
            domain="user_state",
            metric=entry.key,
            numeric_value=entry.value,
            unit=entry.unit,
            observed_at=observed_at,
            source_type="manual",
            summary=f"{entry.label} entered by the user",
        )
        for entry in body.entries
    ]
    commit = await evidence.commit(
        user_id=principal.user_id,
        goal_id=goal_id,
        events=proposals,
        agent_run_id=None,
        conflicts=[],
    )
    outcome = await reprice.publish_if_priceable(goal_id)
    priced = (
        outcome.status in {"completed", "limited", "unchanged"} and outcome.probability is not None
    )
    return ManualStateResponse(
        events=[row.model_dump(mode="json") for row in commit.events],
        reprice_status=outcome.status,
        priced=priced,
        reason=outcome.reason,
        probability=outcome.probability,
    )


@router.post("/goals/{goal_id}/github-sync", response_model=WorkflowSnapshot)
async def sync_github(
    goal_id: UUID,
    body: CreateThreadBody,
    workflow: Annotated[AgentWorkflow, Depends(get_agent_workflow)],
    cursors: Annotated[Any, Depends(get_github_cursor_store)],
    goals: Annotated[Any, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> WorkflowSnapshot:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    login = body.github_login
    if not login:
        raise ResourceNotFoundError("github_login is required")
    settings = get_settings()
    source = GitHubEvidenceSource(login, settings.github_token)
    cursor = await cursors.get(principal.user_id, login) if cursors else None
    batch = await source.sync(cursor)
    if cursors:
        await cursors.put(principal.user_id, login, batch.next_cursor)
    lines = [
        f"GitHub {item.get('event_type')} on {item.get('repo')} "
        f"({item.get('commit_count')} commits)"
        for item in batch.records[:12]
    ]
    return await workflow.start(
        WorkflowRequest(
            kind="add_evidence",
            goal_id=goal_id,
            evidence_text="\n".join(lines) or f"GitHub profile {login} had no new public events.",
            github_login=login,
            user_id=principal.user_id,
        )
    )


@router.post("/evidence/csv/preview")
async def csv_preview(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    raw = (await file.read()).decode("utf-8-sig")
    preview = preview_csv(raw)
    return preview.model_dump()


@router.post("/goals/{goal_id}/csv-import", response_model=WorkflowSnapshot)
async def csv_import(
    goal_id: UUID,
    file: Annotated[UploadFile, File()],
    metric: Annotated[str, Form()],
    workflow: Annotated[AgentWorkflow, Depends(get_agent_workflow)],
    goals: Annotated[Any, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
    numeric_value: Annotated[str | None, Form()] = None,
    observed_at: Annotated[str | None, Form()] = None,
    domain: Annotated[str | None, Form()] = None,
    event_type: Annotated[str | None, Form()] = None,
) -> WorkflowSnapshot:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    raw = (await file.read()).decode("utf-8-sig")
    records = parse_csv(
        raw,
        CsvImportRequest(
            mapping=CsvColumnMapping(
                metric=metric,
                numeric_value=numeric_value,
                observed_at=observed_at,
                domain=domain,
                event_type=event_type,
            )
        ),
    )
    events = [EvidenceEventProposal.model_validate(item) for item in records]
    return await workflow.start(
        WorkflowRequest(
            kind="add_evidence",
            goal_id=goal_id,
            evidence_events=events,
            user_id=principal.user_id,
        )
    )


def _assert_thread_owner(snapshot: WorkflowSnapshot, principal: Principal) -> None:
    owner = str((snapshot.debug or {}).get("user_id") or "")
    if owner != str(principal.user_id):
        raise ResourceNotFoundError(f"Workflow thread {snapshot.thread_id} was not found")
