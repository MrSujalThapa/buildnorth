from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    """Optional live research adapter.

    Codex MCP OAuth tokens are not application credentials. Runtime Monid stays
    `not_configured` until product-level Monid application credentials exist.
    """

    def __init__(self, enabled: bool, api_base: str | None, client_id: str | None) -> None:
        self._enabled = enabled
        self._api_base = api_base
        self._client_id = client_id

    @property
    def configured(self) -> bool:
        return bool(self._enabled and self._api_base and self._client_id)

    async def search(self, query: ResearchQuery) -> ResearchResult:
        del query
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
        monid = await self._monid.search(query)
        limitations: list[dict[str, str]] = []
        if not monid.configured:
            limitations.append(
                {
                    "source": "monid",
                    "status": "not_configured",
                    "detail": "Application Monid OAuth credentials are not provisioned.",
                }
            )
        return ResearchResult(
            claims=[*frozen.claims, *monid.claims],
            retrieved_at=query.as_of,
            provenance=[*frozen.provenance, *monid.provenance, *limitations],
            configured=True,
        )
