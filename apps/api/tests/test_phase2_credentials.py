from uuid import uuid4

import pytest

from personal_markets.core.errors import ProviderNotConfiguredError
from personal_markets.identity.credentials import CredentialCipher, InMemoryCredentialStore


def test_cipher_authenticates_owner_provider_and_ciphertext() -> None:
    import base64
    import os

    cipher = CredentialCipher({"v1": base64.urlsafe_b64encode(os.urandom(32)).decode()}, "v1")
    owner = uuid4()
    sealed = cipher.encrypt(owner, "openai", "sk-test-secret")
    assert "sk-test-secret" not in sealed
    assert cipher.decrypt(owner, "openai", sealed) == "sk-test-secret"
    for user, provider, value in [
        (uuid4(), "openai", sealed),
        (owner, "anthropic", sealed),
        (owner, "openai", sealed[:-3] + "bad"),
    ]:
        with pytest.raises(ProviderNotConfiguredError):
            cipher.decrypt(user, provider, value)


async def test_credentials_are_scoped_and_replacement_is_immediate() -> None:
    store = InMemoryCredentialStore()
    a, b = uuid4(), uuid4()
    await store.put(a, "openai", "encrypted-one", "1234")
    assert await store.get(b, "openai") is None
    first = await store.get(a, "openai")
    await store.put(a, "openai", "encrypted-two", "5678")
    second = await store.get(a, "openai")
    assert first and second and first.version != second.version
    await store.delete(b, "openai")
    assert await store.get(a, "openai") is not None
    await store.delete(a, "openai")
    assert await store.get(a, "openai") is None


def test_key_ring_rotation_preserves_old_backups() -> None:
    import base64
    import os

    old_key, new_key = [base64.urlsafe_b64encode(os.urandom(32)).decode() for _ in range(2)]
    owner = uuid4()
    old = CredentialCipher({"v1": old_key}, "v1").encrypt(owner, "openai", "sk-owner-secret")
    rotated = CredentialCipher({"v1": old_key, "v2": new_key}, "v2")
    assert rotated.decrypt(owner, "openai", old) == "sk-owner-secret"
    current = rotated.encrypt(owner, "openai", rotated.decrypt(owner, "openai", old))
    assert current.startswith("v2:")
    assert (
        CredentialCipher({"v2": new_key}, "v2").decrypt(owner, "openai", current)
        == "sk-owner-secret"
    )
