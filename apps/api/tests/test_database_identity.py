from personal_markets.core.config import safe_database_identity


def test_safe_database_identity_omits_credentials() -> None:
    identity = safe_database_identity(
        "postgresql://postgres:super-secret@127.0.0.1:54322/playitout_phase0_test"
    )
    assert identity == "127.0.0.1:54322/playitout_phase0_test"
    assert "super-secret" not in identity
    assert "postgres:" not in identity


def test_missing_database_url_is_memory() -> None:
    assert safe_database_identity(None) == "memory"
