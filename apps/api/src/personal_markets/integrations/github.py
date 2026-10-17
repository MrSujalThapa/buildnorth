import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from personal_markets.ports import EvidenceBatch


class GitHubEvidenceSource:
    """Public GitHub activity as raw evidence. Commits are not a skill score."""

    def __init__(
        self, login: str, token: str | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self._login = login
        self._token = token
        self._client = client

    async def sync(self, cursor: str | None) -> EvidenceBatch:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "personal-markets"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        url = urljoin("https://api.github.com/", f"users/{self._login}/events/public")
        if self._client is not None:
            response = await self._client.get(url, headers=headers, params={"per_page": 30})
            response.raise_for_status()
            payload = response.json()
        else:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(url, headers=headers, params={"per_page": 30})
                response.raise_for_status()
                payload = response.json()
        records: list[dict[str, Any]] = []
        latest = cursor
        for event in payload:
            event_id = str(event.get("id"))
            if cursor and event_id == cursor:
                break
            records.append(_normalize_event(event))
            if latest is None:
                latest = event_id
        return EvidenceBatch(records=records, next_cursor=latest)


def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    created = event.get("created_at") or datetime.now(UTC).isoformat()
    payload = event.get("payload") or {}
    commits = payload.get("commits") or []
    return {
        "source_type": "github",
        "external_event_id": str(event.get("id")),
        "event_type": str(event.get("type") or "github_event"),
        "observed_at": created,
        "repo": (event.get("repo") or {}).get("name"),
        "login": (event.get("actor") or {}).get("login"),
        "commit_count": len(commits) if isinstance(commits, list) else 0,
        "raw_ref": json.dumps(
            {
                "id": event.get("id"),
                "type": event.get("type"),
                "repo": (event.get("repo") or {}).get("name"),
                "created_at": created,
            },
            sort_keys=True,
        ),
    }
