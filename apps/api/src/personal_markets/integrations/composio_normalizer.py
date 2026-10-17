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
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        external_id = str(row.get("id") or row.get("sha") or row.get("node_id") or f"{tool_name}:{index}")
        events = _infer_events(plugin_id, tool_name, row, recipe_step)
        body = {
            **row,
            "summary": _summary_for_row(plugin_id, tool_name, row),
            "events": events,
            "tool_name": tool_name,
            "provider": plugin_id,
            "observed_at": _observed_at(row),
        }
        from personal_markets.integrations.mcp_repository import payload_hash

        records.append(
            RawSourceRecord(
                id=uuid4(),
                plugin_connection_id=plugin_connection_id,
                external_id=external_id,
                tool_identity=tool_name,
                retrieved_at=datetime.now(UTC),
                payload=body,
                payload_hash=payload_hash(body),
                sync_run_id=sync_run_id,
                cursor_context={"user_id": user_id, "source_type": plugin_id},
            )
        )
    if not records and payload:
        body = {
            "summary": f"{plugin_id} sync via {tool_name}",
            "events": [],
            "provider": plugin_id,
            "observed_at": datetime.now(UTC).isoformat(),
            "raw": payload,
        }
        from personal_markets.integrations.mcp_repository import payload_hash

        records.append(
            RawSourceRecord(
                id=uuid4(),
                plugin_connection_id=plugin_connection_id,
                external_id=f"{tool_name}:aggregate",
                tool_identity=tool_name,
                retrieved_at=datetime.now(UTC),
                payload=body,
                payload_hash=payload_hash(body),
                sync_run_id=sync_run_id,
                cursor_context={"user_id": user_id, "source_type": plugin_id},
            )
        )
    return records


def _extract_rows(payload: dict[str, Any]) -> list[Any]:
    for key in ("records", "items", "data", "commits", "repositories", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = value.get("items") or value.get("repositories") or value.get("results")
            if isinstance(nested, list):
                return nested
    return [payload] if payload else []


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
    return datetime.now(UTC).isoformat()


def _summary_for_row(plugin_id: str, tool_name: str, row: dict[str, Any]) -> str:
    if "commit" in row or tool_name.lower().find("commit") >= 0:
        message = row.get("commit", {}).get("message") if isinstance(row.get("commit"), dict) else row.get("message")
        repo = row.get("repository") or row.get("repo") or ""
        return f"GitHub commit: {str(message or row.get('sha') or 'activity')[:120]} ({repo})"
    if row.get("full_name") or row.get("name"):
        return f"{plugin_id} resource: {row.get('full_name') or row.get('name')}"
    return f"{plugin_id} observation via {tool_name}"


def _infer_events(
    plugin_id: str,
    tool_name: str,
    row: dict[str, Any],
    recipe_step: SyncRecipeStep | None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    observed = _observed_at(row)
    status = str(row.get("status") or row.get("state") or row.get("outcome") or "").lower()
    planned = row.get("planned_duration") or row.get("duration_planned") or row.get("planned_hours")
    actual = row.get("actual_duration") or row.get("duration_actual") or row.get("hours")
    if status in {"completed", "done", "attended", "kept"}:
        events.append(
            {
                "event_type": "commitment_completed",
                "domain": str(row.get("domain") or plugin_id),
                "metric": str(row.get("metric") or "commitment_outcome"),
                "numeric_value": actual,
                "categorical_value": "completed",
                "unit": str(row.get("unit") or "hours") if actual is not None else None,
                "observed_at": observed,
                "summary": str(row.get("title") or row.get("name") or "Completed commitment"),
            }
        )
    elif status in {"missed", "skipped", "no-show", "cancelled"}:
        events.append(
            {
                "event_type": "commitment_missed",
                "domain": str(row.get("domain") or plugin_id),
                "metric": str(row.get("metric") or "commitment_outcome"),
                "categorical_value": "missed",
                "observed_at": observed,
                "summary": str(row.get("title") or row.get("name") or "Missed commitment"),
            }
        )
    elif planned is not None:
        events.append(
            {
                "event_type": "commitment_created",
                "domain": str(row.get("domain") or plugin_id),
                "metric": str(row.get("metric") or "duration_planned"),
                "numeric_value": planned,
                "categorical_value": "planned",
                "unit": str(row.get("unit") or "hours"),
                "observed_at": observed,
                "summary": str(row.get("title") or row.get("name") or "Planned commitment"),
            }
        )
    if plugin_id == "github" and ("commit" in tool_name.lower() or "commit" in row):
        message = row.get("commit", {}).get("message") if isinstance(row.get("commit"), dict) else row.get("message")
        events.append(
            {
                "event_type": "repository_activity",
                "domain": "software",
                "metric": "commits_pushed",
                "numeric_value": 1,
                "unit": "count",
                "observed_at": observed,
                "summary": f"Commit: {str(message or row.get('sha') or 'activity')[:160]}",
            }
        )
    elif plugin_id == "github" and row.get("state") and row.get("title"):
        events.append(
            {
                "event_type": "issue_activity",
                "domain": "software",
                "metric": "issue_update",
                "categorical_value": str(row.get("state")),
                "observed_at": observed,
                "summary": f"Issue: {row.get('title')}",
            }
        )
    repo = (recipe_step.arguments.get("owner"), recipe_step.arguments.get("repo")) if recipe_step else (None, None)
    if repo[0] and repo[1] and not events:
        events.append(
            {
                "event_type": "repository_activity",
                "domain": "software",
                "metric": "external_event",
                "categorical_value": "synced",
                "observed_at": observed,
                "summary": _summary_for_row(plugin_id, tool_name, row),
            }
        )
    return events
