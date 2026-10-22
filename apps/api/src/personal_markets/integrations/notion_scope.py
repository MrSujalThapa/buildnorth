"""Bounded traversal of child pages under one authorized Notion page."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

FetchChildren = Callable[[str, str | None], Awaitable[dict[str, Any]]]


async def discover_child_page_ids(
    parent_id: str,
    fetch_children: FetchChildren,
    *,
    max_pages: int = 100,
    max_depth: int = 5,
) -> list[str]:
    """Return accessible descendants; fail if the safety bound prevents completion."""
    UUID(parent_id)
    seen = {str(UUID(parent_id))}
    queue = [(str(UUID(parent_id)), 0)]
    discovered: list[str] = []
    calls = 0
    while queue:
        current, depth = queue.pop(0)
        cursor: str | None = None
        while True:
            calls += 1
            if calls > max_pages:
                raise RuntimeError("Notion watched area is too large to reconcile safely")
            result = await fetch_children(current, cursor)
            rows = result.get("results") or result.get("records") or []
            if not isinstance(rows, list):
                raise RuntimeError("Notion child-page response has an unsupported shape")
            for row in rows:
                if not isinstance(row, dict) or row.get("type") != "child_page":
                    continue
                if row.get("archived") or row.get("in_trash"):
                    continue
                try:
                    child_id = str(UUID(str(row.get("id") or "")))
                except ValueError:
                    continue
                if child_id in seen:
                    continue
                if depth >= max_depth:
                    raise RuntimeError("Notion watched area exceeds the supported depth")
                seen.add(child_id)
                discovered.append(child_id)
                queue.append((child_id, depth + 1))
            if not result.get("has_more"):
                break
            next_cursor = result.get("next_cursor")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                raise RuntimeError("Notion child-page pagination cursor is invalid")
            cursor = next_cursor
    return discovered
