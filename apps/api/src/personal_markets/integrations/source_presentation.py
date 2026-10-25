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
    cells: list[str] = Field(default_factory=list)
    field_labels: list[str] = Field(default_factory=list, exclude=True)


class SourcePreview(BaseModel):
    resource_title: str
    resource_type: str
    tool_name: str = ""
    arguments: dict[str, str] = Field(default_factory=dict)
    fields: list[PreviewField] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    measurements: list[PreviewMeasurement] = Field(default_factory=list)
    records: list[PreviewRecord] = Field(default_factory=list)
    notice: str | None = None
    validation_status: Literal["unverified"] = "unverified"
    promotes_to_verified_outcome: bool = False
    error: str | None = None


_NO_MEASUREMENT = (
    "No measurable progress detected. You can monitor this source for changes "
    "or choose which fields matter."
)
_SYNTHETIC = re.compile(r"^[a-z0-9_]+ (?:row|record|observation|resource)\b", re.IGNORECASE)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_HIDDEN = {
    "events",
    "provider",
    "tool_name",
    "summary",
    "connected_account_id",
    "resource_uri",
    "observed_at",
    "ingested_at",
    "evidence_classification",
    "validation_status",
    "promotes_to_verified_outcome",
    "row_index",
    "values",
    "raw",
    "id",
    "uuid",
    "block_id",
    "page_id",
    "object",
    "request_id",
    "parent",
    "url",
    "href",
    "etag",
    "created_time",
    "last_edited_time",
    "created_at",
    "updated_at",
    "archived",
    "cover",
    "icon",
}


def present_source(
    *,
    resource_title: str,
    resource_type: str,
    tool_name: str,
    arguments: dict[str, Any],
    payloads: list[dict[str, Any]],
) -> SourcePreview:
    records = [item for item in (_present_record(payload) for payload in payloads) if item]
    columns, records = _arrange(records)
    records = records[:8]
    measurements = _measurements(records)
    kinds = {record.kind for record in records}
    if measurements or not records:
        notice = None
    elif kinds & {"document", "message", "activity"}:
        notice = "Readable content is below. No measurable progress was confirmed."
    else:
        notice = _NO_MEASUREMENT
    return SourcePreview(
        resource_title=resource_title,
        resource_type=resource_type or "resource",
        tool_name=tool_name,
        arguments={key: str(value) for key, value in arguments.items() if value not in (None, "")},
        fields=_fields(records),
        columns=columns,
        measurements=measurements,
        records=records,
        notice=notice,
    )


def _present_record(payload: dict[str, Any]) -> PreviewRecord | None:
    event = _event(payload)
    cells = _cells(payload)
    labels, object_cells = _object_fields(payload)
    if not _has_content(payload, event, cells, object_cells):
        return None
    kind = _kind(payload, event, cells)
    numeric = _number(event.get("numeric_value"))
    metric = _text(event.get("metric")) or _text(payload.get("metric"))
    unit = _text(event.get("unit")) or _text(payload.get("unit"))
    timestamp = (
        _text(event.get("observed_at"))
        or _text(payload.get("date"))
        or _text(payload.get("observed_at"))
        or _text(payload.get("messageTimestamp"))
    )
    actor = _actor(payload)
    body = _body(payload)
    title = _title(payload, event)
    if not title:
        nonempty = [cell for cell in cells or object_cells if cell]
        title = nonempty[0][:120] if nonempty else resource_fallback(kind, timestamp)
    text = _clip(body or _display(event.get("summary")) or _display(payload.get("summary")))
    if text and (text == title or title.startswith(text)):
        text = None
    metrics: list[PreviewMetric] = []
    if numeric is not None:
        metrics.append(PreviewMetric(label=metric or "Value", value=numeric, unit=unit))
    shown_cells = [] if kind == "measurement" else (cells or object_cells)
    return PreviewRecord(
        kind=kind,
        title=title,
        subtitle=metric if kind == "measurement" and metric and metric != title else None,
        timestamp=timestamp or None,
        metric=metric,
        numeric_value=numeric,
        unit=unit,
        text=text,
        actor=actor,
        metrics=metrics,
        cells=shown_cells,
        field_labels=[] if kind == "measurement" or cells else labels,
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


def _kind(payload: dict[str, Any], event: dict[str, Any], cells: list[str]) -> RecordKind:
    actor = _actor(payload)
    subject = _text(payload.get("subject"))
    body = _body(payload)
    numeric = _number(event.get("numeric_value"))
    metric = _text(event.get("metric")) or _text(payload.get("metric"))
    named = (
        _text(payload.get("name")) or _text(payload.get("title")) or _text(payload.get("status"))
    )
    if actor and (subject or body):
        return "message"
    if numeric is not None and metric and not named:
        return "measurement"
    if body and len(body) > 40 and numeric is None:
        return "document"
    if numeric is not None and named:
        return "activity"
    if event.get("event_type") == "source_activity" or (
        event.get("event_type") == "scheduled_event" and named and numeric is None and not cells
    ):
        return "activity"
    if numeric is not None:
        return "activity"
    if any(len(cell) > 80 for cell in cells):
        return "document"
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
    return proposals


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


def _has_content(
    payload: dict[str, Any],
    event: dict[str, Any],
    cells: list[str],
    object_cells: list[str],
) -> bool:
    if _number(event.get("numeric_value")) is not None:
        return True
    if any(cells) or any(object_cells):
        return True
    if _display(event.get("summary")) or _display(payload.get("summary")):
        return True
    if _text(event.get("metric")) or _text(event.get("observed_at")) or _text(payload.get("date")):
        return True
    return bool(_actor(payload) or _body(payload) or _title(payload, event))


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
            value = _display(source.get(key)) if key == "summary" else _text(source.get(key))
            if value and not _identifier(value):
                return value[:160]
    return None


def _display(value: Any) -> str | None:
    text = _text(value)
    if text and _SYNTHETIC.match(text):
        return None
    return text


def _cells(payload: dict[str, Any]) -> list[str]:
    values = payload.get("values")
    if not isinstance(values, list):
        return []
    cells = [_cell(value) for value in values[:12]]
    while cells and not cells[-1]:
        cells.pop()
    return cells


def _cell(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, bool)):
        return ""
    text = str(value).strip()
    if not text or set(text) <= set("|-\u00b7• "):
        return ""
    if _SYNTHETIC.match(text):
        return ""
    return text


def _object_fields(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    if isinstance(payload.get("values"), list):
        return [], []
    labels: list[str] = []
    cells: list[str] = []
    for key, value in payload.items():
        if key in _HIDDEN or key.startswith("_"):
            continue
        text = _cell(value)
        if not text or len(text) > 160 or _identifier(text):
            continue
        labels.append(key.replace("_", " ").strip().title())
        cells.append(text)
    return labels, cells


def _arrange(records: list[PreviewRecord]) -> tuple[list[str], list[PreviewRecord]]:
    if any(record.kind == "measurement" for record in records):
        return [], records
    if records and all(record.cells and not record.field_labels for record in records):
        return _arrange_grid(records)
    labels = records[0].field_labels if records else []
    if len(labels) >= 2 and all(
        record.kind == "record" and record.field_labels == labels for record in records
    ):
        arranged = [
            record.model_copy(update={"kind": "record", "text": None, "title": record.cells[0]})
            for record in records
            if any(record.cells)
        ]
        return labels, arranged
    return [], [_without_duplicate(record) for record in records if _visible(record)]


def _arrange_grid(records: list[PreviewRecord]) -> tuple[list[str], list[PreviewRecord]]:
    header = records[0].cells
    if len(records) > 1 and _header(header):
        width = len(header)
        columns = [cell for cell in header if cell]
        if len(columns) != width:
            columns = [cell or "Value" for cell in header]
        body = []
        for record in records[1:]:
            cells = (record.cells + [""] * width)[:width]
            if not any(cells):
                continue
            body.append(record.model_copy(update={"cells": cells, "text": None, "kind": "record"}))
        measured = _measured_grid(columns, body)
        if measured:
            return [], measured
        return columns, body
    prose: list[PreviewRecord] = []
    for record in records:
        nonempty = [cell for cell in record.cells if cell]
        if not nonempty:
            continue
        if len(nonempty) == 1:
            text = nonempty[0]
            title = text if len(text) <= 90 else f"{text[:90].rstrip()}…"
            prose.append(
                record.model_copy(
                    update={
                        "kind": "document" if len(text) > 80 else "record",
                        "title": title,
                        "text": None if text == title else text,
                        "cells": [],
                    }
                )
            )
            continue
        prose.append(
            record.model_copy(
                update={
                    "kind": "record",
                    "title": nonempty[0][:120],
                    "text": " · ".join(nonempty[1:]) or None,
                    "cells": nonempty,
                }
            )
        )
    return [], prose


def _header(cells: list[str]) -> bool:
    filled = [cell for cell in cells if cell]
    if len(filled) < 2:
        return False
    return not any(_data_like(cell) for cell in filled)


def _data_like(cell: str) -> bool:
    if len(cell) > 40 or _quantity(cell) is not None or _DATE.search(cell):
        return True
    return bool(re.search(r"\d{3,}", cell) or "—" in cell or " - " in cell)


def _measured_grid(columns: list[str], records: list[PreviewRecord]) -> list[PreviewRecord]:
    date_index = _date_column(columns, records)
    numeric_indexes = [
        index
        for index in range(len(columns))
        if index != date_index and _mostly_numeric(records, index)
    ]
    if len(numeric_indexes) != 1 or date_index is None:
        return []
    value_index = numeric_indexes[0]
    unit_index = next(
        (
            index
            for index, column in enumerate(columns)
            if column.strip().lower() in {"unit", "units"}
        ),
        None,
    )
    if unit_index is None and not _measure_name(columns[value_index]):
        return []
    measured: list[PreviewRecord] = []
    for record in records:
        raw = record.cells[value_index] if value_index < len(record.cells) else ""
        number = _quantity(raw)
        if number is None:
            continue
        timestamp = record.cells[date_index] if date_index is not None else None
        unit = None
        if unit_index is not None and record.cells[unit_index]:
            unit = record.cells[unit_index]
        label = columns[value_index]
        measured.append(
            PreviewRecord(
                kind="measurement",
                title=timestamp or record.title,
                timestamp=timestamp or None,
                metric=label,
                numeric_value=number,
                unit=unit,
                metrics=[PreviewMetric(label=label, value=number, unit=unit)],
            )
        )
    return measured


def _date_column(columns: list[str], records: list[PreviewRecord]) -> int | None:
    for index, column in enumerate(columns):
        key = re.sub(r"[^a-z0-9]+", "_", column.lower()).strip("_")
        values = [
            record.cells[index]
            for record in records
            if index < len(record.cells) and record.cells[index]
        ]
        named = key in {"date", "day", "when", "observed_at", "timestamp"}
        hits = sum(bool(_DATE.search(value)) for value in values)
        dated = bool(values) and hits >= max(1, len(values) // 2)
        if named or dated:
            return index
    return None


def _mostly_numeric(records: list[PreviewRecord], index: int) -> bool:
    values = [
        record.cells[index]
        for record in records
        if index < len(record.cells) and record.cells[index]
    ]
    if not values:
        return False
    return sum(_quantity(value) is not None for value in values) >= max(1, (len(values) * 3) // 5)


def _without_duplicate(record: PreviewRecord) -> PreviewRecord:
    nonempty = [cell for cell in record.cells if cell]
    if record.kind == "document" and nonempty and not record.text:
        text = nonempty[0]
        title = text if len(text) <= 90 else f"{text[:90].rstrip()}…"
        return record.model_copy(
            update={"title": title, "text": None if text == title else text, "cells": []}
        )
    if record.text and (record.text == record.title or record.title.startswith(record.text)):
        return record.model_copy(update={"text": None})
    return record


def _visible(record: PreviewRecord) -> bool:
    return bool(
        record.title or record.text or record.numeric_value is not None or any(record.cells)
    )


_MEASURE_WORDS = frozenset(
    {
        "hour",
        "hours",
        "minute",
        "minutes",
        "second",
        "seconds",
        "km",
        "mile",
        "miles",
        "meter",
        "meters",
        "kilometer",
        "kilometers",
        "rep",
        "reps",
        "calorie",
        "calories",
        "duration",
        "distance",
        "weight",
        "quantity",
        "amount",
    }
)


def _measure_name(label: str) -> bool:
    tokens = set(re.split(r"[^a-z0-9]+", label.lower()))
    return bool(tokens & _MEASURE_WORDS)


def _identifier(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            value.strip(),
            re.IGNORECASE,
        )
    )


def _quantity(value: str) -> float | None:
    cleaned = value.replace(",", "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned):
        return None
    return float(cleaned)


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
