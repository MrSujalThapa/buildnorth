from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from personal_markets.core.config import Settings
from personal_markets.ports import ResearchQuery, ResearchResult


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[5]


REFERENCE_DIR = _repo_root() / "data" / "reference"


class FrozenReferenceProvider:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or REFERENCE_DIR

    async def search(self, query: ResearchQuery) -> ResearchResult:
        claims: list[dict[str, Any]] = []
        provenance: list[dict[str, str]] = []
        if not self._root.exists():
            return ResearchResult(
                claims=[],
                retrieved_at=query.as_of,
                provenance=[],
                configured=True,
            )
        needle = query.query.lower()
        for path in sorted(self._root.glob("*.json")):
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
            haystack = " ".join(
                [
                    str(payload.get("title") or ""),
                    str(payload.get("domain") or ""),
                    " ".join(payload.get("keywords") or []),
                    " ".join(claim.get("claim", "") for claim in payload.get("claims", [])),
                ]
            ).lower()
            if (
                needle
                and not any(token in haystack for token in needle.split() if len(token) > 3)
                and payload.get("domain") not in (query.allowed_domains or [])
            ):
                continue
            for claim in payload.get("claims", []):
                claims.append(
                    {
                        **claim,
                        "retrieved_at": query.as_of.isoformat(),
                        "source": claim.get("source") or path.name,
                    }
                )
            provenance.append({"source": path.name, "source_type": "frozen"})
        return ResearchResult(
            claims=claims, retrieved_at=query.as_of, provenance=provenance, configured=True
        )


class MonidResearchProvider:
    """Conditional application API adapter. Codex MCP credentials are never reused."""

    def __init__(
        self,
        enabled: bool,
        api_base: str | None,
        client_id: str | None,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._enabled = enabled
        self._api_base = api_base
        self._client_id = client_id
        self._settings = settings
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._enabled and self._settings and self._settings.monid_api_key)

    async def search(self, query: ResearchQuery) -> ResearchResult:
        if self.configured and self._settings is not None:
            from personal_markets.identity.factory import (
                get_identity_repository,
                get_inference_budget_service,
            )
            from personal_markets.integrations.monid import MonidHTTPResearch

            return await MonidHTTPResearch(
                self._settings,
                self._transport,
                get_inference_budget_service(),
                get_identity_repository(),
            ).search(query)
        return ResearchResult(
            claims=[],
            retrieved_at=datetime.now(UTC),
            provenance=[
                {
                    "source": "monid",
                    "source_type": "web",
                    "status": "not_configured" if not self.configured else "configured",
                }
            ],
            configured=self.configured,
        )


class CompositeResearchProvider:
    def __init__(self, frozen: FrozenReferenceProvider, monid: MonidResearchProvider) -> None:
        self._frozen = frozen
        self._monid = monid

    async def search(self, query: ResearchQuery) -> ResearchResult:
        frozen = await self._frozen.search(query)
        if not query.external_required:
            return frozen
        monid = await self._monid.search(query)
        limitations: list[dict[str, str]] = []
        if not monid.configured:
            limitations.append(
                {
                    "source": "monid",
                    "status": "not_configured",
                    "detail": "Application Monid API credentials are not configured.",
                }
            )
        return ResearchResult(
            claims=[*frozen.claims, *monid.claims],
            retrieved_at=query.as_of,
            provenance=[*frozen.provenance, *monid.provenance, *limitations],
            configured=True,
            tool_trace=monid.tool_trace,
        )
