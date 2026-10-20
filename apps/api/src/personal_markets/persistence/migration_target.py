from __future__ import annotations

from sqlalchemy.engine import make_url

from personal_markets.core.config import safe_database_identity

_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_LOCAL_ENVIRONMENTS = frozenset({"development", "test", "pytest"})


class MigrationTargetError(ValueError):
    pass


def is_loopback_url(database_url: str) -> bool:
    host = (make_url(database_url).host or "").lower()
    return host in _LOOPBACK


def is_hosted_supabase_url(database_url: str) -> bool:
    host = (make_url(database_url).host or "").lower()
    return "supabase.com" in host or "supabase.co" in host


def require_migration_url(
    database_url: str | None,
    environment: str,
    *,
    allow_local: bool = False,
) -> str:
    """Refuse silent local defaults and accidental loopback migrates in staging."""
    if not database_url or not database_url.strip():
        raise MigrationTargetError(
            "PM_DATABASE_URL is required. Render already holds the hosted Supabase URL; "
            "do not fall back to local Postgres."
        )
    identity = safe_database_identity(database_url)
    loopback = is_loopback_url(database_url)
    if loopback and not allow_local and environment not in _LOCAL_ENVIRONMENTS:
        raise MigrationTargetError(
            f"refusing to migrate loopback database {identity} while PM_ENVIRONMENT={environment}. "
            "Use the hosted Supabase URL from Render, or pass --allow-local for a local CLI database."
        )
    return database_url
