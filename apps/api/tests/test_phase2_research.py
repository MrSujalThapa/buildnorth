from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from personal_markets.agents.research_service import validate_research
from personal_markets.core.config import Settings
from personal_markets.identity.budget import InferenceBudgetService, InMemoryBudgetStore
from personal_markets.identity.domain import Principal
from personal_markets.identity.testing import make_principal
from personal_markets.integrations.monid import MonidHTTPResearch
from personal_markets.ports import ResearchArtifact, ResearchClaim, ResearchQuery, ResearchResult


@pytest.mark.parametrize(
    "price,schema,expected_runs", [(0.01, True, 1), (0.10, True, 0), (0.01, False, 0)]
)
async def test_discover_inspect_validate_budget_then_run(
    price: float, schema: bool, expected_runs: int
) -> None:
    user = make_principal(
        "research-test", invited=True, hosted=True, quota_usd=0.05, quota_tokens=0
    )
    settings = Settings(
        monid_enabled=True,
        monid_api_key="test-key",
        monid_api_base="https://api.monid.ai",
        monid_tool_provider="approved",
        monid_tool_endpoint="/search",
        monid_max_cost_usd=0.02,
        monid_tool_input_template={"queryParams": {"query": "{query}"}},
    )
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path.endswith("discover"):
            return httpx.Response(
                200, json={"results": [{"provider": "approved", "endpoint": "/search"}]}
            )
        if req.url.path.endswith("inspect"):
            return httpx.Response(
                200,
                json={
                    "price": {"type": "PER_CALL", "amount": {"value": price, "currency": "USD"}},
                    "input": {
                        "queryParams": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        }
                    }
                    if schema
                    else {},
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "COMPLETED",
                "runId": "run123",
                "providerResponse": {"httpStatus": 200},
                "output": {
                    "results": [
                        {
                            "url": "https://example.org/study",
                            "content": "Study found an applicable rate of 0.12.",
                        }
                    ]
                },
            },
        )

    class Identity:
        async def get_user(self, owner: UUID) -> Principal | None:
            return user if owner == user.user_id else None

    store = InMemoryBudgetStore()
    result = await MonidHTTPResearch(
        settings, httpx.MockTransport(handler), InferenceBudgetService(store, settings), Identity()
    ).search(
        ResearchQuery(
            query="applicable rate",
            as_of=datetime.now(UTC),
            external_required=True,
            user_id=user.user_id,
        )
    )
    assert sum(path.endswith("run") for path in paths) == expected_runs
    assert paths[:2] == ["/v1/discover", "/v1/inspect"]
    assert len(store.ledger) == expected_runs
    if expected_runs:
        assert result.claims[0]["source"] == "https://example.org/study"
        assert result.tool_trace[-1]["run_id"] == "run123"
        assert store.ledger[0]["input_tokens"] == store.ledger[0]["output_tokens"] == 0
    else:
        assert result.claims == []


def test_research_rejects_invented_sources_quotes_and_population_transfer() -> None:
    now = datetime.now(UTC)
    original = "The rate was 0.12 in a different population."
    retrieved = ResearchResult(
        claims=[
            {
                "source": "https://example.org/study",
                "claim": original,
                "source_type": "web",
                "material_kind": "snippet",
            }
        ],
        retrieved_at=now,
        provenance=[],
    )
    claims = [
        ResearchClaim(
            claim="A prior",
            source="https://example.org/study",
            retrieved_at=now.isoformat(),
            source_type="web",
            evidence_class="associative",
            supporting_quote=original,
            population="other cohort",
            applicability="mismatch",
            parameter="stage_rate",
            value=0.12,
            unit="fraction",
            contradiction="Another study disagrees",
        ),
        ResearchClaim(
            claim="Fake",
            source="https://invented.invalid",
            retrieved_at=now.isoformat(),
            source_type="web",
            evidence_class="assumption",
        ),
    ]
    result = validate_research(ResearchArtifact(claims=claims), retrieved, external_required=True)
    assert result.status == "insufficient_evidence"
    assert len(result.claims) == 1
    assert result.claims[0].verification == "candidate"
    assert result.parameter_provenance[0]["used_by_engine"] is False
    assert any("Contradictory" in item for item in result.limitations)
    assert any("snippets" in item for item in result.limitations)
    claims[0].supporting_quote = "A quote that never appeared"
    assert not validate_research(ResearchArtifact(claims=claims), retrieved, True).claims
