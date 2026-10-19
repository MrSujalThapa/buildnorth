from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.core.config import Settings
from personal_markets.core.errors import UnauthorizedError
from personal_markets.identity import tokens as token_mod

ISSUER = "https://example.clerk.accounts.dev"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
ALLOWED_AZP = "http://localhost:5173"
UNAUTHORIZED_AZP = "https://evil.example"
KID = "playitout-test-key"


def _b64url_uint(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode("ascii")


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def trusted_jwks(rsa_key) -> dict[str, Any]:
    numbers = rsa_key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        ]
    }


@pytest.fixture
def clerk_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        test_auth_secret=None,
        clerk_jwks_url=JWKS_URL,
        clerk_issuer=ISSUER,
        clerk_authorized_parties=[ALLOWED_AZP],
        admin_emails=["admin@example.test"],
    )


@pytest.fixture
def install_trusted_jwks(monkeypatch, trusted_jwks) -> list[dict[str, Any]]:
    decode_kwargs: list[dict[str, Any]] = []
    real_decode = token_mod.jwt.decode

    def fetch_data(self) -> dict[str, Any]:
        del self
        return trusted_jwks

    def spy_decode(*args, **kwargs):
        decode_kwargs.append(kwargs)
        return real_decode(*args, **kwargs)

    monkeypatch.setattr(token_mod.jwt.PyJWKClient, "fetch_data", fetch_data)
    monkeypatch.setattr(token_mod.jwt, "decode", spy_decode)
    return decode_kwargs


def _sign(
    rsa_key,
    *,
    azp: str,
    aud: str | None = None,
    ttl_seconds: int = 3600,
    iss: str = ISSUER,
    sub: str = "user_clerk_admin",
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": sub,
        "iss": iss,
        "azp": azp,
        "iat": int(now.timestamp()),
        "nbf": int((now - timedelta(seconds=5)).timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    if aud is not None:
        payload["aud"] = aud
    return jwt.encode(payload, rsa_key, algorithm="RS256", headers={"kid": KID})


def _assert_crypto_checks(kwargs: dict[str, Any]) -> None:
    assert kwargs.get("algorithms") == ["RS256"]
    assert "audience" not in kwargs
    assert kwargs.get("issuer") == ISSUER
    options = kwargs.get("options") or {}
    assert options.get("verify_aud") is False
    assert "exp" in options.get("require", [])
    assert "sub" in options.get("require", [])


def test_allowed_azp_without_aud_is_accepted(
    rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=ALLOWED_AZP)
    claims = token_mod._verify_clerk_token(token, clerk_settings)
    assert claims.clerk_user_id == "user_clerk_admin"
    assert install_trusted_jwks
    _assert_crypto_checks(install_trusted_jwks[-1])


def test_unauthorized_azp_without_aud_is_rejected_after_signature(
    rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=UNAUTHORIZED_AZP)
    with pytest.raises(UnauthorizedError, match="azp") as raised:
        token_mod._verify_clerk_token(token, clerk_settings)
    assert "invalid token" not in str(raised.value)
    assert install_trusted_jwks
    _assert_crypto_checks(install_trusted_jwks[-1])


def test_unauthorized_azp_with_valid_aud_is_still_rejected(
    rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=UNAUTHORIZED_AZP, aud=ALLOWED_AZP)
    with pytest.raises(UnauthorizedError, match="azp") as raised:
        token_mod._verify_clerk_token(token, clerk_settings)
    assert "invalid token" not in str(raised.value)
    assert install_trusted_jwks
    _assert_crypto_checks(install_trusted_jwks[-1])


def test_tampered_signature_with_allowed_azp_is_rejected(
    rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=ALLOWED_AZP)
    header, payload, signature = token.split(".")
    flipped = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{flipped}{signature[1:]}"
    with pytest.raises(UnauthorizedError, match="invalid token"):
        token_mod._verify_clerk_token(tampered, clerk_settings)
    assert all("azp" not in str(kwargs) for kwargs in install_trusted_jwks)


def test_expired_token_with_allowed_azp_is_rejected(
    rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=ALLOWED_AZP, ttl_seconds=-60)
    with pytest.raises(UnauthorizedError, match="token expired"):
        token_mod._verify_clerk_token(token, clerk_settings)


def _http_client(monkeypatch, clerk_settings) -> TestClient:
    monkeypatch.setattr("personal_markets.identity.deps.get_settings", lambda: clerk_settings)
    app = isolated_app()
    app.state.auth_bypass_principal = None
    return TestClient(app)


def test_http_allowed_azp_without_aud_reaches_me(
    monkeypatch, rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=ALLOWED_AZP)
    with _http_client(monkeypatch, clerk_settings) as client:
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert response.json()["clerk_user_id"] == "user_clerk_admin"
    _assert_crypto_checks(install_trusted_jwks[-1])


def test_http_unauthorized_azp_without_aud_is_401(
    monkeypatch, rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=UNAUTHORIZED_AZP)
    with _http_client(monkeypatch, clerk_settings) as client:
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "token azp is not allowed"
    _assert_crypto_checks(install_trusted_jwks[-1])


def test_http_unauthorized_azp_with_valid_aud_is_401(
    monkeypatch, rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=UNAUTHORIZED_AZP, aud=ALLOWED_AZP)
    with _http_client(monkeypatch, clerk_settings) as client:
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "token azp is not allowed"
    _assert_crypto_checks(install_trusted_jwks[-1])


def test_http_tampered_signature_is_401(
    monkeypatch, rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=ALLOWED_AZP)
    header, payload, signature = token.split(".")
    flipped = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{flipped}{signature[1:]}"
    with _http_client(monkeypatch, clerk_settings) as client:
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        denied = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 200
    assert denied.status_code == 401
    assert denied.json()["error"]["message"] == "invalid token"


def test_http_expired_token_is_401(
    monkeypatch, rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=ALLOWED_AZP, ttl_seconds=-60)
    with _http_client(monkeypatch, clerk_settings) as client:
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "token expired"


def test_wrong_clerk_issuer_is_rejected(
    rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=ALLOWED_AZP, iss="https://evil.clerk.accounts.dev")
    with pytest.raises(UnauthorizedError, match="invalid token"):
        token_mod._verify_clerk_token(token, clerk_settings)


def test_http_wrong_issuer_is_401(
    monkeypatch, rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=ALLOWED_AZP, iss="https://evil.clerk.accounts.dev")
    with _http_client(monkeypatch, clerk_settings) as client:
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "invalid token"


def test_http_uninvited_clerk_identity_cannot_list_goals(
    monkeypatch, rsa_key, clerk_settings, install_trusted_jwks
) -> None:
    token = _sign(rsa_key, azp=ALLOWED_AZP, sub="user_uninvited_clerk")
    with _http_client(monkeypatch, clerk_settings) as client:
        me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        goals = client.get("/api/v1/goals", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["invited"] is False
    assert goals.status_code == 403


@pytest.mark.parametrize("header", [
    {"alg": "none", "typ": "JWT"},
    {"alg": "HS256", "kid": "untrusted"},
    {"alg": "RS256"},
    {"alg": "RS256", "kid": ""},
])
def test_http_invalid_signing_header_is_401_without_jwks_lookup(
    monkeypatch, clerk_settings, header,
) -> None:
    import json

    def encode(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    def unexpected_lookup(*args, **kwargs):
        raise AssertionError("Malformed signing headers must not fetch JWKS")

    monkeypatch.setattr(token_mod.jwt.PyJWKClient, "get_signing_key_from_jwt", unexpected_lookup)
    token = encode(header) + "." + encode({"sub": "forged", "role": "admin", "exp": 1}) + "."
    with _http_client(monkeypatch, clerk_settings) as client:
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "invalid token"


def test_http_unknown_signing_key_is_401(
    monkeypatch, rsa_key, clerk_settings, install_trusted_jwks,
) -> None:
    token = jwt.encode(
        {"sub": "forged", "role": "admin", "exp": 1}, rsa_key,
        algorithm="RS256", headers={"kid": "unknown-key"},
    )
    with _http_client(monkeypatch, clerk_settings) as client:
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "invalid token"
