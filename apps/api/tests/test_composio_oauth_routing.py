"""The requested toolkit must own the auth config and pending OAuth request."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from personal_markets.core.config import Settings
from personal_markets.integrations.composio_gateway import (
    ComposioIntegrationGateway,
    ConnectedAccountStatus,
    ConnectInitResult,
)
from personal_markets.integrations.mcp_domain import ConnectionType, PluginConnectionRecord
from personal_markets.integrations.mcp_repository import InMemoryIntegrationRepository
from personal_markets.integrations.mcp_service import IntegrationGatewayService


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["googledrive", "slack", "supabase", "outlook"])
async def test_auth_config_lookup_and_link_are_scoped_to_exact_toolkit(slug: str) -> None:
    calls: list[tuple[str, str]] = []

    def list_configs(**query: str) -> SimpleNamespace:
        assert query == {"toolkit_slug": slug}
        return SimpleNamespace(items=[SimpleNamespace(
            id=f"config-{slug}", toolkit=SimpleNamespace(slug=slug), status="ENABLED"
        )])

    def link(**args: str) -> SimpleNamespace:
        calls.append((args["user_id"], args["auth_config_id"]))
        return SimpleNamespace(id=f"request-{slug}", redirect_url=f"https://auth.test/{slug}")

    gateway = ComposioIntegrationGateway(Settings())
    gateway._client = SimpleNamespace(
        auth_configs=SimpleNamespace(list=list_configs),
        connected_accounts=SimpleNamespace(link=link),
    )
    owner = uuid4()
    result = await gateway.initiate_connection(owner, slug)
    assert result.auth_config_id == f"config-{slug}"
    assert result.connection_request_id == f"request-{slug}"
    assert calls == [(str(owner), f"config-{slug}")]


@pytest.mark.asyncio
async def test_mismatched_listed_or_created_auth_config_fails_before_link() -> None:
    linked = False

    def link(**_args: str) -> None:
        nonlocal linked
        linked = True

    auth_configs = SimpleNamespace(
        list=lambda **_query: SimpleNamespace(items=[SimpleNamespace(
            id="outlook-config", toolkit=SimpleNamespace(slug="outlook"), status="ENABLED"
        )]),
        create=lambda **_args: SimpleNamespace(id="created-id"),
        get=lambda _id: SimpleNamespace(toolkit=SimpleNamespace(slug="outlook")),
    )
    gateway = ComposioIntegrationGateway(Settings())
    gateway._client = SimpleNamespace(
        auth_configs=auth_configs, connected_accounts=SimpleNamespace(link=link)
    )
    with pytest.raises(ValueError, match="another toolkit"):
        await gateway.initiate_connection(uuid4(), "slack")
    assert not linked

    auth_configs.list = lambda **_query: SimpleNamespace(items=[])
    with pytest.raises(ValueError, match="another toolkit"):
        await gateway.initiate_connection(uuid4(), "slack")
    assert not linked


@pytest.mark.asyncio
async def test_pending_auth_is_reused_only_for_matching_complete_fresh_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryIntegrationRepository()
    service = IntegrationGatewayService(repository=repo)
    owner = service._default_user_id
    initiated: list[str] = []

    async def no_reconcile(_owner: UUID) -> None:
        return None

    async def initiate(_owner: UUID, slug: str) -> ConnectInitResult:
        initiated.append(slug)
        return ConnectInitResult(f"config-{slug}", f"request-{slug}", f"https://auth.test/{slug}")

    monkeypatch.setattr(service._composio, "_client", object())
    monkeypatch.setattr(service, "_reconcile_connections", no_reconcile)
    monkeypatch.setattr(service._composio, "initiate_connection", initiate)
    record = PluginConnectionRecord(
        id=uuid4(), user_id=owner, plugin_id="slack",
        connection_type=ConnectionType.MANAGED_GATEWAY, gateway_provider="composio",
        transport="http", auth_ref="old", status="pending_auth",
        account_metadata={
            "toolkit_slug": "outlook", "auth_config_id": "config-outlook",
            "connection_request_id": "request-outlook", "auth_url": "https://auth.test/outlook",
            "auth_url_created_at": datetime.now(UTC).isoformat(),
        },
        created_at=datetime.now(UTC),
    )
    await repo.upsert_connection(record)
    fresh = await service.connect_managed("slack")
    assert fresh["auth_url"] == "https://auth.test/slack"
    assert initiated == ["slack"]
    reused = await service.connect_managed("slack")
    assert reused["auth_url"] == fresh["auth_url"]
    assert initiated == ["slack"]
    stored = await repo.get_connection(owner, "slack")
    assert stored is not None
    await repo.upsert_connection(stored.model_copy(update={"account_metadata": {
        **stored.account_metadata,
        "auth_url_created_at": (datetime.now(UTC) - timedelta(minutes=6)).isoformat(),
    }}))
    await service.connect_managed("slack")
    assert initiated == ["slack", "slack"]


@pytest.mark.asyncio
async def test_concurrent_distinct_toolkits_keep_their_own_connection_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryIntegrationRepository()
    service = IntegrationGatewayService(repository=repo)
    owner = service._default_user_id

    async def no_reconcile(_owner: UUID) -> None:
        return None

    async def initiate(_owner: UUID, slug: str) -> ConnectInitResult:
        await asyncio.sleep(0)
        return ConnectInitResult(f"config-{slug}", f"request-{slug}", f"https://auth.test/{slug}")

    monkeypatch.setattr(service._composio, "_client", object())
    monkeypatch.setattr(service, "_reconcile_connections", no_reconcile)
    monkeypatch.setattr(service._composio, "initiate_connection", initiate)
    results = await asyncio.gather(
        service.connect_managed("googledrive"), service.connect_managed("slack")
    )
    assert [item["auth_url"] for item in results] == [
        "https://auth.test/googledrive", "https://auth.test/slack"
    ]
    for slug in ("googledrive", "slack"):
        stored = await repo.get_connection(owner, slug)
        assert stored is not None
        assert stored.account_metadata["toolkit_slug"] == slug


@pytest.mark.asyncio
async def test_callback_reconciliation_ignores_another_toolkits_active_account() -> None:
    wrong = SimpleNamespace(
        id="outlook-account", status="ACTIVE", toolkit=SimpleNamespace(slug="outlook")
    )
    right = SimpleNamespace(
        id="slack-account", status="ACTIVE", toolkit=SimpleNamespace(slug="slack")
    )
    returned = [wrong]
    client = SimpleNamespace(connected_accounts=SimpleNamespace(
        wait_for_connection=lambda _request, **_kwargs: wrong,
        list=lambda **_kwargs: SimpleNamespace(items=returned),
    ))
    gateway = ComposioIntegrationGateway(Settings())
    gateway._client = client
    pending = await gateway.connected_account_status(
        uuid4(), "slack", connection_request_id="slack-request"
    )
    assert pending.status == "pending_auth"
    assert pending.connected_account_id is None
    returned[:] = [wrong, right]
    connected = await gateway.connected_account_status(
        uuid4(), "slack", connection_request_id="slack-request"
    )
    assert connected.status == "connected"
    assert connected.connected_account_id == "slack-account"


@pytest.mark.asyncio
async def test_refresh_marks_only_the_requested_plugin_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryIntegrationRepository()
    service = IntegrationGatewayService(repository=repo)
    owner = service._default_user_id

    async def no_reconcile(_owner: UUID) -> None:
        return None

    async def no_discovery(_connection: object, **_kwargs: object) -> None:
        return None

    async def status(_owner: UUID, slug: str, **_kwargs: object) -> ConnectedAccountStatus:
        assert slug == "slack"
        return ConnectedAccountStatus("slack-account", "connected")

    monkeypatch.setattr(service._composio, "_client", object())
    monkeypatch.setattr(service, "_reconcile_connections", no_reconcile)
    monkeypatch.setattr(service, "_discover_and_persist", no_discovery)
    monkeypatch.setattr(service._composio, "connected_account_status", status)
    now = datetime.now(UTC)
    await repo.upsert_connection(PluginConnectionRecord(
        id=uuid4(), user_id=owner, plugin_id="slack",
        connection_type=ConnectionType.MANAGED_GATEWAY, gateway_provider="composio",
        transport="http", auth_ref="slack-request", status="pending_auth",
        account_metadata={"toolkit_slug": "slack", "connection_request_id": "slack-request"},
        created_at=now,
    ))
    result = await service.refresh_connection("slack")
    assert result["plugin_id"] == "slack" and result["status"] == "connected"
    stored = await repo.get_connection(owner, "slack")
    assert stored is not None and stored.status == "connected"
    assert stored.account_metadata["connected_account_id"] == "slack-account"
    assert await repo.get_connection(owner, "outlook") is None
