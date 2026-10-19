import base64
import os
from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.core.config import get_settings
from personal_markets.identity.factory import get_credential_store
from personal_markets.identity.testing import make_principal
from personal_markets.integrations.inference_http import NativeInferenceAdapter


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    import json

    monkeypatch.setenv(
        "PM_BYOK_ENCRYPTION_KEYS",
        json.dumps({"v1": base64.urlsafe_b64encode(os.urandom(32)).decode()}),
    )
    get_settings.cache_clear()

    async def validate(_self: NativeInferenceAdapter) -> None:
        return None

    monkeypatch.setattr(NativeInferenceAdapter, "validate_key", validate)
    app = isolated_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_key_lifecycle_and_automatic_byok_activation(client: TestClient) -> None:
    url = "/api/v1/settings/inference"
    secret = "sk-phase2-private-key-1234"
    saved = client.put(url + "/credentials/openai", json={"api_key": secret})
    assert saved.status_code == 200, saved.text
    assert saved.json()["masked_suffix"] == "••••1234"
    assert secret not in saved.text
    first_version = saved.json()["version"]
    assert client.get(url).json()["preference"] == {
        "mode": "byok",
        "provider": "openai",
        "model": None,
    }
    chosen = client.put(url, json={"mode": "byok", "provider": "openai", "model": "gpt-5.4-mini"})
    assert chosen.status_code == 200, chosen.text
    validated = client.post(url + "/credentials/openai/validate")
    assert validated.status_code == 200
    replaced = client.put(url + "/credentials/openai", json={"api_key": secret + "5678"})
    assert replaced.status_code == 200
    assert replaced.json()["version"] != first_version
    assert client.get(url).json()["preference"]["mode"] == "byok"
    assert client.delete(url + "/credentials/openai").status_code == 204
    settings = client.get(url)
    assert settings.headers["cache-control"] == "no-store"
    assert settings.json()["credentials"] == []
    assert settings.json()["preference"]["mode"] == "byok"
    assert client.post(url + "/credentials/openai/validate").status_code == 503


def test_connecting_anthropic_switches_from_hosted_without_spending_credits(
    client: TestClient,
) -> None:
    url = "/api/v1/settings/inference"
    before = client.get("/api/v1/me").json()["hosted"]
    saved = client.put(url + "/credentials/anthropic", json={"api_key": "sk-ant-private-1234"})
    assert saved.status_code == 200, saved.text
    current = client.get(url).json()
    assert current["preference"] == {"mode": "byok", "provider": "anthropic", "model": None}
    assert current["credentials"][0]["masked_suffix"] == "••••1234"
    assert client.get("/api/v1/me").json()["hosted"] == before
    switched = client.put(url, json={"mode": "hosted", "provider": "anthropic", "model": None})
    assert switched.status_code == 200, switched.text
    assert switched.json()["preference"]["mode"] == "hosted"


def test_validation_errors_never_echo_secrets(client: TestClient) -> None:
    secret = "sk-x"
    response = client.put("/api/v1/settings/inference/credentials/openai", json={"api_key": secret})
    assert response.status_code == 422
    assert secret not in response.text
    response = client.put(
        "/api/v1/settings/inference/credentials/other", json={"api_key": "sk-secret-value"}
    )
    assert response.status_code == 422
    assert "sk-secret-value" not in response.text


def test_two_accounts_cannot_read_replace_or_delete_other_credential(client: TestClient) -> None:
    url = "/api/v1/settings/inference"
    first = cast(FastAPI, client.app).state.auth_bypass_principal
    assert (
        client.put(
            url + "/credentials/anthropic", json={"api_key": "sk-ant-owner-one-key"}
        ).status_code
        == 200
    )
    cast(FastAPI, client.app).state.auth_bypass_principal = make_principal(
        "other-key-owner", invited=True
    )
    assert client.get(url).json()["credentials"] == []
    assert client.post(url + "/credentials/anthropic/validate").status_code == 503
    assert client.delete(url + "/credentials/anthropic").status_code == 204
    cast(FastAPI, client.app).state.auth_bypass_principal = first
    assert len(client.get(url).json()["credentials"]) == 1


def test_unsupported_model_does_not_change_saved_preference(client: TestClient) -> None:
    url = "/api/v1/settings/inference"
    response = client.put(url, json={"mode": "hosted", "provider": "openai", "model": "unknown"})
    assert response.status_code == 422
    assert client.get(url).json()["preference"]["model"] is None


def test_settings_distinguishes_budget_from_missing_hosted_credential(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PM_INFERENCE_PROVIDER", "openai")
    monkeypatch.setenv("PM_OPENAI_API_KEY", "")
    get_settings.cache_clear()
    response = client.get("/api/v1/settings/inference")
    assert response.status_code == 200, response.text
    assert response.json()["hosted_provider"] == "openai"
    assert response.json()["hosted_configured"] is False


def test_authentication_and_invite_are_required(client: TestClient) -> None:
    cast(FastAPI, client.app).state.auth_bypass_principal = None
    assert client.get("/api/v1/settings/inference").status_code == 401
    cast(FastAPI, client.app).state.auth_bypass_principal = make_principal(
        "uninvited-key-owner", invited=False
    )
    assert client.get("/api/v1/settings/inference").status_code == 403


def test_public_clients_cannot_claim_trusted_connector_ingestion(client: TestClient) -> None:
    response = client.post(
        "/api/v1/agent/threads",
        json={
            "kind": "add_evidence",
            "mcp_records": [{"provider": "github", "payload": {"trusted": True}}],
        },
    )
    assert response.status_code == 403


def test_production_transport_rejects_plain_http(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PM_ENVIRONMENT", "production")
    get_settings.cache_clear()
    response = client.put(
        "/api/v1/settings/inference/credentials/openai",
        json={"api_key": "sk-transport-test-secret"},
    )
    assert response.status_code == 403
    assert "sk-transport-test-secret" not in response.text
    monkeypatch.setenv("PM_ENVIRONMENT", "test")
    get_settings.cache_clear()


async def test_persistence_only_contains_ciphertext(client: TestClient) -> None:
    secret = "sk-plaintext-must-never-persist"
    assert (
        client.put(
            "/api/v1/settings/inference/credentials/openai", json={"api_key": secret}
        ).status_code
        == 200
    )
    row = await get_credential_store().get(
        cast(FastAPI, client.app).state.auth_bypass_principal.user_id, "openai"
    )
    assert row is not None
    assert secret not in repr(row)
    assert secret not in row.ciphertext
