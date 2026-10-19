from datetime import datetime
from typing import Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field

SourceType = Literal["manual", "github", "csv", "mcp_sync", "upload", "personal_agent"]
SourceAuthority = Literal["self_report", "platform_public", "user_file", "agent_report"]
ObservedVsEntered = Literal["directly_observed", "user_entered", "imported", "agent_reported"]
# Assigned by the server from where evidence came from, never by the submitter.
# `verified_outcome` is reserved for a future outcome-verification step; nothing in
# the current ingestion paths can assign it.
VerificationStatus = Literal[
    "self_reported",
    "agent_reported",
    "user_file",
    "provider_backed",
    "corroborated",
    "verified_outcome",
]


class CorroboratingSource(BaseModel):
    source_type: str
    event_type: str = ""
    summary: str = ""
    observed_at: str | None = None
    connection_id: str | None = None


class SubmissionContext(BaseModel):
    """Who delivered evidence through an external channel, recorded at receipt."""

    channel: Literal["remote_mcp"] = "remote_mcp"
    connection_id: str
    client_id: str
    client_name: str | None = None
    source_category: str
    source_identifier: str | None = None
    supporting_reference: str | None = None
    received_at: datetime
    idempotency_key_hash: str | None = None
    agent_run_id: str | None = None


class Provenance(BaseModel):
    source_type: SourceType
    source_authority: SourceAuthority
    observed_vs_entered: ObservedVsEntered
    parsing_status: Literal["ok", "partial", "ambiguous"]
    completeness: Literal["complete", "partial"]
    conflict_status: Literal["none", "flagged"]
    raw_event_id: str | None = None
    external_event_id: str | None = None
    observation_kind: Literal["snapshot", "increment", "period", "event", "uncertain"] | None = None
    event_identity: str | None = None
    corroborating_sources: list[CorroboratingSource] = Field(default_factory=list)
    verification_status: VerificationStatus | None = None
    submission: SubmissionContext | None = None


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
    source_authority: SourceAuthority
    observed_vs_entered: ObservedVsEntered
    verification_status: VerificationStatus


SOURCE_METADATA: dict[str, SourceMetadata] = {
    "manual": {
        "source_quality": "user_entered",
        "source_authority": "self_report",
        "observed_vs_entered": "user_entered",
        "verification_status": "self_reported",
    },
    "github": {
        "source_quality": "platform_public",
        "source_authority": "platform_public",
        "observed_vs_entered": "directly_observed",
        "verification_status": "provider_backed",
    },
    "csv": {
        "source_quality": "user_imported",
        "source_authority": "user_file",
        "observed_vs_entered": "imported",
        "verification_status": "user_file",
    },
    "mcp_sync": {
        "source_quality": "platform_public",
        "source_authority": "platform_public",
        "observed_vs_entered": "directly_observed",
        "verification_status": "provider_backed",
    },
    "upload": {
        "source_quality": "user_imported",
        "source_authority": "user_file",
        "observed_vs_entered": "imported",
        "verification_status": "user_file",
    },
    "personal_agent": {
        "source_quality": "agent_reported",
        "source_authority": "agent_report",
        "observed_vs_entered": "agent_reported",
        "verification_status": "agent_reported",
    },
}


def metadata_for(source_type: str) -> SourceMetadata:
    return SOURCE_METADATA.get(source_type, SOURCE_METADATA["manual"])


def verification_status_for(
    source_type: str, corroborating: list[CorroboratingSource]
) -> VerificationStatus:
    """Trust follows the sources on record, not anything a submitter claims.

    Evidence counts as corroborated only when a provider-backed source and a source of a
    different type agree on the same fingerprint. Two reports from the same kind of
    channel (for example two agent connections) are not independent.
    """
    own = metadata_for(source_type)["verification_status"]
    types = {source_type, *(item.source_type for item in corroborating)}
    provider_backed = any(
        metadata_for(item)["verification_status"] == "provider_backed" for item in types
    )
    if provider_backed and len(types) > 1:
        return "corroborated"
    return own
