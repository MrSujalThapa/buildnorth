from __future__ import annotations

import time
from collections.abc import Callable

import httpx


class VerifiedEmailCache:
    """Bounded, short-lived cache for Clerk's verified primary email lookup."""

    def __init__(
        self,
        lookup: Callable[[str, str], tuple[str | None, bool]] | None = None,
        ttl_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lookup = lookup or lookup_verified_email
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[str, tuple[float, str]] = {}

    def resolve(
        self, clerk_user_id: str, secret: str, *, fresh: bool = False
    ) -> tuple[str | None, bool]:
        now = self._clock()
        cached = self._entries.get(clerk_user_id)
        if not fresh and cached and cached[0] > now:
            return cached[1], True
        email, verified = self._lookup(clerk_user_id, secret)
        if email and verified:
            if len(self._entries) >= 256:
                self._entries = {
                    key: value for key, value in self._entries.items() if value[0] > now
                }
                if len(self._entries) >= 256:
                    self._entries.pop(next(iter(self._entries)))
            self._entries[clerk_user_id] = (now + self._ttl, email)
        else:
            self._entries.pop(clerk_user_id, None)
        return email, verified


def lookup_verified_email(clerk_user_id: str, secret: str) -> tuple[str | None, bool]:
    """Return the Clerk user's primary email and whether Clerk marked it verified."""
    if not clerk_user_id or not secret:
        return None, False
    try:
        response = httpx.get(
            f"https://api.clerk.com/v1/users/{clerk_user_id}",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=5.0,
        )
    except httpx.HTTPError:
        return None, False
    if response.status_code != 200:
        return None, False
    body = response.json()
    emails = body.get("email_addresses") or []
    primary_id = body.get("primary_email_address_id")
    primary = next((item for item in emails if item.get("id") == primary_id), None)
    if primary is None and emails:
        primary = emails[0]
    if not isinstance(primary, dict):
        return None, False
    address = str(primary.get("email_address") or "").strip().lower() or None
    verification = primary.get("verification") or {}
    verified = str(verification.get("status") or "").lower() == "verified"
    return address, verified
