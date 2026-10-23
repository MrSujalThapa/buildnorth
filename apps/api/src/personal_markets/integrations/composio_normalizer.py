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
        external_id = str(
            (row.get("sha") if plugin_id == "github" else None)
            or row.get("id") or row.get("node_id") or f"{tool_name}:{index}"
        )
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

        if plugin_id == "notion" and isinstance(row.get("markdown"), str):
            fingerprint = payload_hash({
                "id": row.get("id") or (recipe_step.arguments.get("page_id") if recipe_step else None),
                "markdown": row["markdown"],
            })
        elif plugin_id == "github" and row.get("sha"):
            # A commit SHA identifies immutable content; provider request IDs do not.
            fingerprint = payload_hash({"sha": row["sha"]})
        else:
            fingerprint = payload_hash({
                key: value for key, value in body.items()
                if key not in {"request_id", "response_id", "trace_id", "retrieved_at"}
            })
        if plugin_id == "notion":
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
    if any(isinstance(payload.get(key), str) and payload[key].strip()
           for key in ("markdown", "content", "text", "plain_text")):
        return [payload]
    for key in ("records", "items", "data", "commits", "repositories", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested_key in ("items", "repositories", "results", "commits", "data"):
                if isinstance(value.get(nested_key), list):
                    return value[nested_key]
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
    if status in {
        "completed", "done", "attended", "kept", "missed", "skipped", "no-show", "cancelled"
    }:
        events.append(
            {
                # Provider task status is activity evidence, not proof that the
                # user previously committed to a matching action window.
                "event_type": "source_activity",
                "domain": str(row.get("domain") or plugin_id),
                "metric": str(row.get("metric") or "activity_status"),
                "numeric_value": actual,
                "categorical_value": status,
                "unit": str(row.get("unit") or "hours") if actual is not None else None,
                "observed_at": observed,
                "summary": str(row.get("title") or row.get("name") or "Source activity"),
            }
        )
    elif planned is not None:
        events.append(
            {
                "event_type": "source_plan",
                "domain": str(row.get("domain") or plugin_id),
                "metric": str(row.get("metric") or "duration_planned"),
                "numeric_value": planned,
                "categorical_value": "planned",
                "unit": str(row.get("unit") or "hours"),
                "observed_at": observed,
                "summary": str(row.get("title") or row.get("name") or "Source plan"),
            }
        )
    if plugin_id == "github" and ("commit" in tool_name.lower() or "commit" in row):
        message = (
            row.get("commit", {}).get("message")
            if isinstance(row.get("commit"), dict)
            else row.get("message")
        )
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
    elif (
        plugin_id == "github"
        and row.get("state")
        and row.get("title")
        and ("issue" in tool_name.lower() or "pull_request" in tool_name.lower())
    ):
        is_pull_request = "pull_request" in tool_name.lower()
        events.append(
            {
                "event_type": "pull_request_activity" if is_pull_request else "issue_activity",
                "domain": "software",
                "metric": "pull_request_update" if is_pull_request else "issue_update",
                "categorical_value": str(row.get("state")),
                "observed_at": observed,
                "summary": f"{'Pull request' if is_pull_request else 'Issue'}: {row.get('title')}",
            }
        )
    return events
