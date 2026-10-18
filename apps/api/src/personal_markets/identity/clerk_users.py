from __future__ import annotations

import httpx


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
