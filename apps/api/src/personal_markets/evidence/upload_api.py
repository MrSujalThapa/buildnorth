from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from personal_markets.evidence.service import EvidenceService
from personal_markets.evidence.uploads import UploadService
from personal_markets.forecasting.reprice import BaselineRepriceService
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import Principal
from personal_markets.wiring import (
    get_baseline_reprice_service,
    get_evidence_service,
    get_goal_service,
    get_upload_service,
)

router = APIRouter(prefix="/api/v1", tags=["uploads"])


class MappingBody(BaseModel):
    metric: str
    value_column: str
    observed_at_column: str | None = None
    unit_column: str | None = None
    metric_column: str | None = None
    unit: str | None = None
    observation_kind: str = "snapshot"
    event_type: str = "uploaded_measurement"


def _dump(record: Any) -> dict[str, Any]:
    return {
        "upload_id": str(record.upload_id),
        "goal_id": str(record.goal_id),
        "filename": record.filename,
        "content_type": record.content_type,
        "byte_size": record.byte_size,
        "sha256": record.sha256,
        "status": record.status,
        "preview": record.preview,
        "mapping": record.mapping,
        "created_at": record.created_at,
        "lineage": {key: value for key, value in record.lineage.items() if key != "storage_path"},
    }


@router.post("/goals/{goal_id}/uploads")
async def create_upload(
    goal_id: UUID,
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(get_invited_principal)],
    goals: Annotated[Any, Depends(get_goal_service)],
    uploads: Annotated[UploadService, Depends(get_upload_service)],
) -> dict[str, Any]:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    content = await file.read()
    record = await uploads.ingest(
        principal.user_id,
        goal_id,
        file.filename or "upload.bin",
        content,
        file.content_type or "application/octet-stream",
    )
    return _dump(record)


@router.get("/goals/{goal_id}/uploads")
async def list_uploads(
    goal_id: UUID,
    principal: Annotated[Principal, Depends(get_invited_principal)],
    goals: Annotated[Any, Depends(get_goal_service)],
    uploads: Annotated[UploadService, Depends(get_upload_service)],
) -> list[dict[str, Any]]:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    return [_dump(item) for item in await uploads.list_for_goal(principal.user_id, goal_id)]


@router.post("/goals/{goal_id}/uploads/{upload_id}/map")
async def map_upload(
    goal_id: UUID,
    upload_id: UUID,
    body: MappingBody,
    principal: Annotated[Principal, Depends(get_invited_principal)],
    goals: Annotated[Any, Depends(get_goal_service)],
    uploads: Annotated[UploadService, Depends(get_upload_service)],
    evidence: Annotated[EvidenceService, Depends(get_evidence_service)],
    reprice: Annotated[BaselineRepriceService, Depends(get_baseline_reprice_service)],
) -> dict[str, Any]:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    record, events = await uploads.approve_mapping(principal.user_id, upload_id, body.model_dump())
    commit = await evidence.commit(principal.user_id, goal_id, events, None, [])
    priced = await reprice.publish_if_priceable(goal_id)
    return {
        "upload": _dump(record),
        "imported": len(commit.events),
        "reprice_status": priced.status,
        "priced": priced.status not in {"not_priced", "limited"},
        "probability": priced.probability,
        "reason": priced.reason,
    }


@router.delete("/goals/{goal_id}/uploads/{upload_id}")
async def delete_upload(
    goal_id: UUID,
    upload_id: UUID,
    principal: Annotated[Principal, Depends(get_invited_principal)],
    goals: Annotated[Any, Depends(get_goal_service)],
    uploads: Annotated[UploadService, Depends(get_upload_service)],
) -> dict[str, str]:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    await uploads.delete(principal.user_id, upload_id)
    return {"status": "deleted"}
