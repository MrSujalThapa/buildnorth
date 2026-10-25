"""Turn normalized source records into a provider-neutral preview.

Presentation follows the shape of each record. Names of connected apps are
display data, not a reason to choose a template.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

RecordKind = Literal["measurement", "activity", "message", "document", "record"]
_ACTOR_KEYS = ("from", "sender", "author_name", "author")
_TEXT_KEYS = ("snippet", "preview", "text", "body", "plain_text", "markdown", "content")
_TITLE_KEYS = ("subject", "title", "name", "summary")


class PreviewField(BaseModel):
    key: str
    label: str
    role: str


class PreviewMetric(BaseModel):
    label: str
    value: float
    unit: str | None = None


class PreviewMeasurement(BaseModel):
    id: str
    label: str
    detail: str
    unit: str | None = None
    ambiguous: bool = False


class PreviewRecord(BaseModel):
    kind: RecordKind
    title: str
    subtitle: str | None = None
    timestamp: str | None = None
    metric: str | None = None
    numeric_value: float | None = None
    unit: str | None = None
    text: str | None = None
    actor: str | None = None
    metrics: list[PreviewMetric] = Field(default_factory=list)


class SourcePreview(BaseModel):
    resource_title: str
    resource_type: str
    tool_name: str = ""
    arguments: dict[str, str] = Field(default_factory=dict)
    fields: list[PreviewField] = Field(default_factory=list)
    measurements: list[PreviewMeasurement] = Field(default_factory=list)
    records: list[PreviewRecord] = Field(default_factory=list)
    validation_status: Literal["unverified"] = "unverified"
    promotes_to_verified_outcome: bool = False
    error: str | None = None


def present_source(
    *,
    resource_title: str,
    resource_type: str,
    tool_name: str,
    arguments: dict[str, Any],
    payloads: list[dict[str, Any]],
) -> SourcePreview:
    records = [item for item in (_present_record(payload) for payload in payloads) if item]
    records = records[:8]
    return SourcePreview(
        resource_title=resource_title,
        resource_type=resource_type or "resource",
        tool_name=tool_name,
        arguments={key: str(value) for key, value in arguments.items() if value not in (None, "")},
        fields=_fields(records),
        measurements=_measurements(records),
        records=records,
    )


def _present_record(payload: dict[str, Any]) -> PreviewRecord | None:
    event = _event(payload)
    if not _has_content(payload, event):
        return None
    kind = _kind(payload, event)
    numeric = _number(event.get("numeric_value"))
    metric = _text(event.get("metric"))
    unit = _text(event.get("unit"))
    timestamp = _text(event.get("observed_at")) or _text(payload.get("date"))
    actor = _actor(payload)
    body = _body(payload)
    title = _title(payload, event) or resource_fallback(kind, timestamp)
    metrics: list[PreviewMetric] = []
    if numeric is not None:
        metrics.append(PreviewMetric(label=metric or "Value", value=numeric, unit=unit))
    return PreviewRecord(
        kind=kind,
        title=title,
        subtitle=metric if kind == "measurement" and metric and metric != title else None,
        timestamp=timestamp or None,
        metric=metric,
        numeric_value=numeric,
        unit=unit,
        text=_clip(body or _text(event.get("summary"))),
        actor=actor,
        metrics=metrics,
    )


def resource_fallback(kind: RecordKind, timestamp: str | None) -> str:
    if timestamp:
        return timestamp
    fallback = {"message": "Message", "document": "Document", "activity": "Activity"}
    return fallback.get(kind, "Record")


def _event(payload: dict[str, Any]) -> dict[str, Any]:
    events = payload.get("events")
    if isinstance(events, list) and events and isinstance(events[0], dict):
        return events[0]
    return payload


def _kind(payload: dict[str, Any], event: dict[str, Any]) -> RecordKind:
    actor = _actor(payload)
    subject = _text(payload.get("subject"))
    body = _body(payload)
    numeric = _number(event.get("numeric_value"))
    if actor and (subject or body):
        return "message"
    if body and len(body) > 40 and numeric is None:
        return "document"
    if isinstance(payload.get("values"), list) or (
        numeric is not None and _text(event.get("metric")) and "values" in payload
    ):
        return "measurement"
    named_activity = (
        _text(payload.get("name")) or _text(payload.get("title")) or _text(payload.get("status"))
    )
    if numeric is not None and named_activity:
        return "activity"
    if numeric is not None and _text(event.get("metric")):
        return "measurement"
    if event.get("event_type") in {"source_activity", "scheduled_event"} or numeric is not None:
        return "activity"
    return "record"


def _measurements(records: list[PreviewRecord]) -> list[PreviewMeasurement]:
    grouped: dict[tuple[str, str | None], list[PreviewRecord]] = {}
    for record in records:
        if record.numeric_value is None:
            continue
        label = record.metric or (record.metrics[0].label if record.metrics else "Measurement")
        grouped.setdefault((label, record.unit), []).append(record)
    proposals: list[PreviewMeasurement] = []
    ambiguous_group = len(grouped) != 1
    for (label, unit), rows in grouped.items():
        missing_name = label in {"Measurement", "Value"}
        detail = f"{len(rows)} recorded value" if len(rows) == 1 else f"{len(rows)} recorded values"
        if unit:
            detail = f"{detail} · {unit}"
        proposals.append(
            PreviewMeasurement(
                id=_slug(f"{label}-{unit or 'value'}"),
                label=label,
                detail=detail,
                unit=unit,
                ambiguous=ambiguous_group or missing_name or unit is None,
            )
        )
    if proposals or not records:
        return proposals
    kind = records[0].kind
    label = {
        "message": "Messages",
        "document": "Documents",
        "activity": "Activity",
        "record": "Records",
    }.get(kind, "Records")
    count = len(records)
    return [
        PreviewMeasurement(
            id=kind,
            label=label,
            detail=f"{count} record" if count == 1 else f"{count} records",
            ambiguous=len({record.kind for record in records}) > 1,
        )
    ]


def _fields(records: list[PreviewRecord]) -> list[PreviewField]:
    fields: list[PreviewField] = []
    if any(record.timestamp for record in records):
        fields.append(PreviewField(key="timestamp", label="When", role="timestamp"))
    if any(record.metric for record in records):
        fields.append(PreviewField(key="metric", label="Measurement", role="metric"))
    if any(record.numeric_value is not None for record in records):
        fields.append(PreviewField(key="numeric_value", label="Value", role="number"))
    if any(record.unit for record in records):
        fields.append(PreviewField(key="unit", label="Unit", role="unit"))
    if any(record.actor for record in records):
        fields.append(PreviewField(key="actor", label="From", role="actor"))
    if any(record.text for record in records):
        fields.append(PreviewField(key="text", label="Preview", role="text"))
    return fields


def _has_content(payload: dict[str, Any], event: dict[str, Any]) -> bool:
    if _number(event.get("numeric_value")) is not None:
        return True
    fact_keys = ("metric", "observed_at", "summary")
    if any(_text(event.get(key) or payload.get(key)) for key in fact_keys):
        return True
    if _actor(payload) or _body(payload) or _title(payload, event):
        return True
    values = payload.get("values")
    return isinstance(values, list) and any(cell not in (None, "") for cell in values)


def _actor(payload: dict[str, Any]) -> str | None:
    for key in _ACTOR_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
        if isinstance(value, dict):
            nested = value.get("name") or value.get("email") or value.get("display_name")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()[:120]
    return None


def _body(payload: dict[str, Any]) -> str | None:
    for key in _TEXT_KEYS:
        value = _text(payload.get(key))
        if value:
            return value
    return None


def _title(payload: dict[str, Any], event: dict[str, Any]) -> str | None:
    for source in (payload, event):
        for key in _TITLE_KEYS:
            value = _text(source.get(key))
            if value:
                return value[:160]
    return None


def _clip(value: str | None) -> str | None:
    if not value:
        return None
    return value[:280]


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "measurement"
