"""Bounded live checks. Uses existing server credentials; never prints or stores them.

This deliberately uses an isolated in-memory identity/ledger and tiny budgets. It
does not grant entitlements or write into real user databases.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from personal_markets.core.config import Settings
from personal_markets.identity.budget import InferenceBudgetService, InMemoryBudgetStore
from personal_markets.identity.credentials import InMemoryCredentialStore
from personal_markets.identity.domain import Principal
from personal_markets.identity.inference_audit import InferenceAudit
from personal_markets.identity.inference_router import InferenceRouter
from personal_markets.identity.testing import make_principal
from personal_markets.integrations.inference_catalog import default_model
from personal_markets.integrations.monid import MonidHTTPResearch
from personal_markets.ports import InferenceRequest, ResearchQuery


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Authorize small live API calls")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to run the bounded checks")
    settings = Settings().model_copy(
        update={"openai_max_retries": 0, "openai_max_output_tokens": 2048, "inference_model": None}
    )
    results: list[dict[str, object]] = []
    for provider in ("spur", "openai", "anthropic"):
        key = {
            "spur": settings.spur_api_key,
            "openai": settings.openai_api_key,
            "anthropic": settings.anthropic_api_key,
        }[provider]
        if not key:
            results.append(
                {
                    "provider": provider,
                    "status": "NOT VERIFIED",
                    "reason": "No configured credential",
                }
            )
            continue
        owner = make_principal(
            f"phase2-live-{provider}",
            invited=True,
            hosted=True,
            quota_usd=0.15,
            quota_tokens=12_000,
        )

        async def lookup(user: UUID, scoped_owner: Principal = owner) -> Principal | None:
            return scoped_owner if user == scoped_owner.user_id else None

        store = InMemoryBudgetStore()
        scoped = settings.model_copy(update={"inference_provider": provider})
        router = InferenceRouter(
            scoped,
            InMemoryCredentialStore(),
            InferenceBudgetService(store, scoped),
            InferenceAudit(store),
            lookup,
        )
        result: dict[str, object] = {
            "provider": provider,
            "model": default_model(provider),
            "live": True,
        }
        try:
            response = await router.complete_structured(
                InferenceRequest(
                    instructions="Return JSON with ok true. Do not explain.",
                    input={"ping": "pong"},
                    output_schema={
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                    agent_name="smoke",
                    user_id=owner.user_id,
                )
            )
            result.update(
                {
                    "status": "PASS",
                    "output": response.structured_output,
                    "usage": response.usage,
                    "latency_ms": response.latency_ms,
                    "estimated_cost_usd": response.estimated_cost_usd,
                }
            )
        except Exception as error:
            result.update(
                {"status": "FAIL", "error_type": type(error).__name__, "message": str(error)}
            )
        results.append(result)
    if settings.monid_api_key:
        owner = make_principal(
            "phase2-live-research", invited=True, hosted=True, quota_usd=0.05, quota_tokens=0
        )

        class Identity:
            async def get_user(self, user: UUID) -> Principal | None:
                return owner if user == owner.user_id else None

        store = InMemoryBudgetStore()
        research = await MonidHTTPResearch(
            settings, budget=InferenceBudgetService(store, settings), identity=Identity()
        ).search(
            ResearchQuery(
                query="web search scientific research papers",
                as_of=datetime.now(UTC),
                external_required=True,
                user_id=owner.user_id,
            )
        )
        results.append(
            {
                "provider": "monid",
                "live": True,
                "status": "PASS" if research.claims else "INSUFFICIENT_EVIDENCE",
                "source_count": len(research.claims),
                "provenance": research.provenance,
                "tool_trace": research.tool_trace,
                "note": "Retrieval proves tool execution, not source/parameter verification.",
            }
        )
    else:
        results.append(
            {"provider": "monid", "status": "NOT VERIFIED", "reason": "No configured credential"}
        )
    artifact = {"checked_at": datetime.now(UTC).isoformat(), "results": results}
    path = Path("artifacts/phase2/live-smoke.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, json.dumps(artifact, indent=2), encoding="utf-8")
    print(json.dumps(artifact, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
