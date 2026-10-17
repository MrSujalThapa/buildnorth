from datetime import datetime
from typing import Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    source_type: Literal["manual", "github", "csv", "mcp_sync"]
    source_authority: Literal["self_report", "platform_public", "user_file"]
    observed_vs_entered: Literal["directly_observed", "user_entered", "imported"]
    parsing_status: Literal["ok", "partial", "ambiguous"]
    completeness: Literal["complete", "partial"]
    conflict_status: Literal["none", "flagged"]
    raw_event_id: str | None = None
    external_event_id: str | None = None


class NormalizedEvidence(BaseModel):
    evidence_id: UUID | None = None
    event_type: str
    domain: str
    metric: str
    numeric_value: float | None = None
    categorical_value: str | None = None
    unit: str | None = None
    observed_at: datetime | None = None
    source_quality: str
    provenance: Provenance
    summary: str
    fingerprint: str


class EvidenceCommit(BaseModel):
    events: list[NormalizedEvidence]
    ambiguities: list[dict[str, str]] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class SourceMetadata(TypedDict):
    source_quality: str
    source_authority: Literal["self_report", "platform_public", "user_file"]
    observed_vs_entered: Literal["directly_observed", "user_entered", "imported"]


SOURCE_METADATA: dict[str, SourceMetadata] = {
    "manual": {
        "source_quality": "user_entered",
        "source_authority": "self_report",
        "observed_vs_entered": "user_entered",
    },
    "github": {
        "source_quality": "platform_public",
        "source_authority": "platform_public",
        "observed_vs_entered": "directly_observed",
    },
    "csv": {
        "source_quality": "user_imported",
        "source_authority": "user_file",
        "observed_vs_entered": "imported",
    },
    "mcp_sync": {
        "source_quality": "platform_public",
        "source_authority": "platform_public",
        "observed_vs_entered": "directly_observed",
    },
}


def metadata_for(source_type: str) -> SourceMetadata:
    return SOURCE_METADATA.get(source_type, SOURCE_METADATA["manual"])
