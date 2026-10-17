from datetime import UTC, datetime
from uuid import UUID, uuid4

from personal_markets.evidence.domain import NormalizedEvidence, Provenance, metadata_for
from personal_markets.ports import EvidenceEventProposal


def _parse_observed_at(value: str) -> datetime | None:
    if not value or value.lower() in {"unknown", "unspecified"}:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def proposal_to_normalized(
    event: EvidenceEventProposal,
    fingerprint: str,
    evidence_id: UUID | None = None,
    conflict: str = "none",
    raw_event_id: str | None = None,
) -> NormalizedEvidence:
    meta = metadata_for(event.source_type)
    observed = _parse_observed_at(event.observed_at)
    return NormalizedEvidence(
        evidence_id=evidence_id or uuid4(),
        event_type=event.event_type,
        domain=event.domain,
        metric=event.metric,
        numeric_value=event.numeric_value,
        categorical_value=event.categorical_value,
        unit=event.unit,
        observed_at=observed or datetime.now(UTC),
        source_quality=str(meta["source_quality"]),
        provenance=Provenance(
            source_type=event.source_type,
            source_authority=meta["source_authority"],
            observed_vs_entered=meta["observed_vs_entered"],
            parsing_status="ok",
            completeness="complete"
            if event.numeric_value is not None or event.categorical_value
            else "partial",
            conflict_status="flagged" if conflict != "none" else "none",
            raw_event_id=raw_event_id,
        ),
        summary=event.summary,
        fingerprint=fingerprint,
    )
