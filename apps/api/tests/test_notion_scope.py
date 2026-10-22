from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from personal_markets.core.config import Settings
from personal_markets.integrations.composio_gateway import ComposioIntegrationGateway
from personal_markets.integrations.mcp_domain import MCPToolDescriptor
from personal_markets.integrations.notion_scope import discover_child_page_ids


@pytest.mark.asyncio
async def test_parent_scope_follows_only_accessible_child_pages_with_pagination() -> None:
    parent, child, grandchild, unrelated = [str(uuid4()) for _ in range(4)]
    calls: list[tuple[str, str | None]] = []

    async def fetch(block_id: str, cursor: str | None) -> dict:
        calls.append((block_id, cursor))
        if block_id == parent and cursor is None:
            return {"results": [{"type": "child_page", "id": child}],
                    "has_more": True, "next_cursor": "second"}
        if block_id == parent:
            return {"results": [{"type": "paragraph", "id": unrelated}], "has_more": False}
        if block_id == child:
            return {"results": [{"type": "child_page", "id": grandchild}], "has_more": False}
        return {"results": [], "has_more": False}

    assert await discover_child_page_ids(parent, fetch) == [child, grandchild]
    assert (unrelated, None) not in calls
    assert (parent, "second") in calls


@pytest.mark.asyncio
async def test_parent_scope_fails_closed_on_unfinished_pagination() -> None:
    parent = str(uuid4())

    async def fetch(_block_id: str, _cursor: str | None) -> dict:
        return {"results": [], "has_more": True, "next_cursor": None}

    with pytest.raises(RuntimeError, match="cursor"):
        await discover_child_page_ids(parent, fetch)


@pytest.mark.asyncio
async def test_composio_child_read_uses_documented_schema_and_selected_account() -> None:
    owner_id, parent_id, child_id = uuid4(), str(uuid4()), str(uuid4())
    gateway = ComposioIntegrationGateway(Settings(environment="test"))
    gateway.list_tools = AsyncMock(return_value=[MCPToolDescriptor(
        name="NOTION_FETCH_BLOCK_CONTENTS",
        input_schema={"properties": {"block_id": {}, "page_size": {}, "start_cursor": {}}},
    )])
    gateway.execute_tool = AsyncMock(side_effect=[
        {"results": [{"type": "child_page", "id": child_id}], "has_more": True,
         "next_cursor": "cursor-1"},
        {"results": [], "has_more": False},
        {"results": [], "has_more": False},
    ])
    assert await gateway.list_notion_child_pages(
        owner_id, parent_id, connected_account_id="selected-account"
    ) == [child_id]
    assert gateway.execute_tool.await_args_list[0].kwargs == {
        "connected_account_id": "selected-account"
    }
    assert gateway.execute_tool.await_args_list[1].args[2]["start_cursor"] == "cursor-1"
