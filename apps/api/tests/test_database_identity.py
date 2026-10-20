import pytest

from personal_markets.core.config import safe_database_identity
from personal_markets.persistence.migration_target import (
    MigrationTargetError,
    is_hosted_supabase_url,
    require_migration_url,
)


def test_safe_database_identity_omits_credentials() -> None:
    identity = safe_database_identity(
        "postgresql://postgres:super-secret@127.0.0.1:54322/playitout_phase0_test"
    )
    assert identity == "127.0.0.1:54322/playitout_phase0_test"
    assert "super-secret" not in identity
    assert "postgres:" not in identity


def test_missing_database_url_is_memory() -> None:
    assert safe_database_identity(None) == "memory"


def test_hosted_supabase_url_is_detected() -> None:
    url = (
        "postgresql://postgres.abc:secret@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
        "?sslmode=require"
    )
    assert is_hosted_supabase_url(url)
    assert "secret" not in safe_database_identity(url)
    assert require_migration_url(url, "staging") == url


def test_staging_refuses_loopback_without_allow_local() -> None:
    local = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    with pytest.raises(MigrationTargetError):
        require_migration_url(local, "staging")
    assert require_migration_url(local, "development") == local
    assert require_migration_url(local, "staging", allow_local=True) == local


def test_missing_migration_url_is_refused() -> None:
    with pytest.raises(MigrationTargetError):
        require_migration_url(None, "development")
