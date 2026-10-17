from __future__ import annotations

from datetime import UTC, datetime

from personal_markets.integrations.mcp_domain import RawSourceRecord
from personal_markets.ports import EvidenceEventProposal


def raw_records_to_proposals(records: list[RawSourceRecord]) -> list[EvidenceEventProposal]:
    proposals: list[EvidenceEventProposal] = []
    for record in records:
        proposals.extend(_record_to_proposals(record))
    return proposals


def _record_to_proposals(record: RawSourceRecord) -> list[EvidenceEventProposal]:
    payload = record.payload
    observed = payload.get("observed_at") or record.retrieved_at.isoformat()
    summary = str(payload.get("summary") or payload.get("title") or record.external_id)
    metric = str(payload.get("metric") or "external_event")
    domain = str(payload.get("domain") or "external")
    numeric = payload.get("numeric_value")
    categorical = payload.get("categorical_value")
    unit = payload.get("unit")
    event_type = str(payload.get("event_type") or "observation")

    if isinstance(payload.get("events"), list):
        nested: list[EvidenceEventProposal] = []
        for item in payload["events"]:
            if not isinstance(item, dict):
                continue
            nested.append(
                EvidenceEventProposal.model_validate(
                    {
                        "event_type": item.get("event_type") or event_type,
                        "domain": item.get("domain") or domain,
                        "metric": item.get("metric") or metric,
                        "numeric_value": item.get("numeric_value"),
                        "categorical_value": item.get("categorical_value"),
                        "unit": item.get("unit"),
                        "observed_at": item.get("observed_at") or observed,
                        "source_type": "mcp_sync",
                        "summary": str(item.get("summary") or summary),
                    }
                )
            )
        if nested:
            return nested

    return [
        EvidenceEventProposal(
            event_type=event_type,
            domain=domain,
            metric=metric,
            numeric_value=float(numeric) if numeric is not None else None,
            categorical_value=str(categorical) if categorical is not None else None,
            unit=str(unit) if unit is not None else None,
            observed_at=str(observed),
            source_type="mcp_sync",
            summary=summary,
        )
    ]
