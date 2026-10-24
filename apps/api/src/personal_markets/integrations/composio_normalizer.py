from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from personal_markets.integrations.mcp_domain import RawSourceRecord, SyncRecipeStep


def normalize_tool_result(
    *,
    plugin_id: str,
    plugin_connection_id: Any,
    sync_run_id: Any,
    tool_name: str,
    payload: dict[str, Any],
    user_id: str,
    recipe_step: SyncRecipeStep | None = None,
) -> list[RawSourceRecord]:
    """Map generic Composio tool payloads into RawSourceRecords with optional nested events."""
    rows = _extract_rows(payload)
    records: list[RawSourceRecord] = []
    from personal_markets.integrations.mcp_repository import payload_hash
    from personal_markets.integrations.provider_contract import get_adapter

    adapter = get_adapter(plugin_id)
    for index, row in enumerate(rows):
        if isinstance(row, list):
            row = {"row_index": index, "values": row[:20]}
        if not isinstance(row, dict):
            continue
        source_uri = recipe_step.resource_uri if recipe_step else None
        external_id = str(
            (row.get("sha") if plugin_id == "github" else None)
            or row.get("id")
            or row.get("node_id")
            or row.get("uuid")
            or f"{source_uri or tool_name}:{index}"
        )
        events = adapter.observations(tool_name, row, recipe_step)
        if not events:
            if plugin_id == "notion":
                events = _legacy_status_events(plugin_id, row)
            elif plugin_id not in {"github", "calendar"}:
                events = _generic_observations(
                    plugin_id, tool_name, row, source_uri, str(plugin_connection_id), external_id
                )
        body = {
            **row,
            "summary": _summary_for_row(plugin_id, tool_name, row),
            "events": events,
            "tool_name": tool_name,
            "provider": plugin_id,
            "connected_account_id": str(plugin_connection_id),
            "resource_uri": source_uri,
            "observed_at": _observed_at(row),
            "ingested_at": datetime.now(UTC).isoformat(),
            "evidence_classification": (
                events[0].get("classification") if events else "raw_content"
            ),
            "validation_status": "unverified",
            "promotes_to_verified_outcome": False,
        }
        adapter_fingerprint = adapter.fingerprint(tool_name, row, recipe_step)
        if adapter_fingerprint is not None:
            fingerprint = payload_hash(adapter_fingerprint)
        elif plugin_id == "github" and row.get("sha"):
            # A commit SHA identifies immutable content; provider request IDs do not.
            fingerprint = payload_hash({"sha": row["sha"]})
        else:
            hash_body = {
                key: value
                for key, value in body.items()
                if key
                not in {
                    "request_id",
                    "response_id",
                    "trace_id",
                    "retrieved_at",
                    "ingested_at",
                }
            }
            raw_events = hash_body.get("events")
            if isinstance(raw_events, list):
                hash_body["events"] = [
                    {key: value for key, value in event.items() if key != "ingested_at"}
                    if isinstance(event, dict)
                    else event
                    for event in raw_events
                ]
            fingerprint = payload_hash(hash_body)
        if plugin_id == "notion" or plugin_id not in {"github", "calendar"}:
            external_id = f"{external_id}:{fingerprint[:16]}"
        records.append(
            RawSourceRecord(
                id=uuid4(),
                plugin_connection_id=plugin_connection_id,
                external_id=external_id,
                tool_identity=tool_name,
                retrieved_at=datetime.now(UTC),
                payload=body,
                payload_hash=fingerprint,
                sync_run_id=sync_run_id,
                cursor_context={"user_id": user_id, "source_type": plugin_id},
            )
        )
    return records


def _extract_rows(payload: dict[str, Any]) -> list[Any]:
    # Some read tools return one document alongside an empty ``data`` list.
    # A page body is still a source record even when it has no child rows.
    if any(
        isinstance(payload.get(key), str) and payload[key].strip()
        for key in ("markdown", "content", "text", "plain_text")
    ):
        return [payload]
    for key in (
        "records",
        "items",
        "data",
        "commits",
        "repositories",
        "results",
        "messages",
        "activities",
        "events",
        "files",
        "values",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return value[:100]
        if isinstance(value, dict):
            for nested_key in (
                "items",
                "repositories",
                "results",
                "commits",
                "data",
                "messages",
                "activities",
                "events",
                "files",
                "values",
            ):
                if isinstance(value.get(nested_key), list):
                    nested: list[Any] = value[nested_key]
                    return nested[:100]
    return [payload] if payload and not payload.get("has_more") else []


def _observed_at(row: dict[str, Any]) -> str:
    for key in ("observed_at", "updated_at", "created_at", "date", "timestamp", "committed_date"):
        value = row.get(key)
        if value:
            return str(value)
    commit = row.get("commit")
    if isinstance(commit, dict):
        author = commit.get("author") or {}
        if isinstance(author, dict) and author.get("date"):
            return str(author["date"])
    return ""


def _summary_for_row(plugin_id: str, tool_name: str, row: dict[str, Any]) -> str:
    if isinstance(row.get("values"), list):
        return f"{plugin_id} row: {' | '.join(str(value)[:40] for value in row['values'][:5])}"[
            :160
        ]
    if "commit" in row or tool_name.lower().find("commit") >= 0:
        message = (
            row.get("commit", {}).get("message")
            if isinstance(row.get("commit"), dict)
            else row.get("message")
        )
        repo = row.get("repository") or row.get("repo") or ""
        return f"GitHub commit: {str(message or row.get('sha') or 'activity')[:120]} ({repo})"
    if row.get("full_name") or row.get("name"):
        return f"{plugin_id} resource: {row.get('full_name') or row.get('name')}"
    return f"{plugin_id} observation via {tool_name}"


def _generic_observations(
    plugin_id: str,
    tool_name: str,
    row: dict[str, Any],
    source_uri: str | None,
    connected_account_id: str,
    external_id: str,
) -> list[dict[str, Any]]:
    """Preserve source facts without promoting activity into a verified outcome."""
    status = str(row.get("status") or row.get("state") or "").lower()
    tokens = tool_name.lower()
    scheduled = ("calendar" in tokens or "event" in tokens) and bool(row.get("start"))
    activity = bool(
        status in {"completed", "done", "sent", "merged", "closed"}
        or any(word in tokens for word in ("activit", "commit", "message", "event"))
    )
    classification = "raw_content" if scheduled or not activity else "observed_activity"
    metric: str | None = None
    numeric_value: float | None = None
    unit: str | None = None
    if classification == "observed_activity":
        for key, inferred_unit in (
            ("distance_meters", "m"),
            ("distance_km", "km"),
            ("distance_miles", "mi"),
            ("distance", None),
        ):
            value = row.get(key)
            candidate_unit = inferred_unit or row.get("distance_unit") or row.get("unit")
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value >= 0
                and candidate_unit in {"m", "km", "mi", "meters", "kilometers", "miles"}
            ):
                metric, numeric_value, unit = "distance", float(value), str(candidate_unit)
                break
    summary = str(
        row.get("title")
        or row.get("summary")
        or row.get("name")
        or row.get("subject")
        or row.get("text")
        or (
            _summary_for_row(plugin_id, tool_name, row)
            if isinstance(row.get("values"), list)
            else None
        )
        or f"{plugin_id} record"
    )[:160]
    return [
        {
            "event_type": "scheduled_event"
            if scheduled
            else "source_activity"
            if activity
            else "source_content",
            "domain": plugin_id,
            "metric": metric,
            "numeric_value": numeric_value,
            "unit": unit,
            "categorical_value": status or None,
            "observed_at": _observed_at(row),
            "summary": summary,
            "provider": plugin_id,
            "connected_account_id": connected_account_id,
            "resource_id": source_uri,
            "source_event_id": external_id,
            "activity_type": "scheduled_event"
            if scheduled
            else "activity"
            if activity
            else "content",
            "classification": classification,
            "validation_status": "unverified",
            "ingested_at": datetime.now(UTC).isoformat(),
            "provenance": {
                "tool": tool_name,
                "raw_id": external_id,
                "promotes_to_verified_outcome": False,
            },
        }
    ]


def _legacy_status_events(plugin_id: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    """Retain the existing Notion task fixture semantics without inferring outcomes."""
    status = str(row.get("status") or row.get("state") or "").lower()
    planned = row.get("planned_duration") or row.get("duration_planned") or row.get("planned_hours")
    actual = row.get("actual_duration") or row.get("duration_actual") or row.get("hours")
    if status in {
        "completed",
        "done",
        "attended",
        "kept",
        "missed",
        "skipped",
        "no-show",
        "cancelled",
    }:
        event_type, value, category = "source_activity", actual, status
    elif planned is not None:
        event_type, value, category = "source_plan", planned, "planned"
    else:
        return []
    return [
        {
            "event_type": event_type,
            "domain": str(row.get("domain") or plugin_id),
            "metric": str(
                row.get("metric") or ("activity_status" if status else "duration_planned")
            ),
            "numeric_value": value,
            "categorical_value": category,
            "unit": str(row.get("unit") or "hours") if value is not None else None,
            "observed_at": _observed_at(row),
            "summary": str(row.get("title") or row.get("name") or "Source activity"),
            "classification": "observed_activity",
            "validation_status": "unverified",
            "provenance": {"promotes_to_verified_outcome": False},
        }
    ]
