"""Bounded Monid discover/inspect/run adapter, using documented HTTP contracts.

Only an operator-allowlisted research tool may execute. Discovery cannot authorize
arbitrary tools. Unsupported schemas/pricing fail closed before a paid request.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from jsonschema import Draft202012Validator

from personal_markets.core.config import Settings
from personal_markets.ports import ResearchQuery, ResearchResult


class MonidHTTPResearch:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        budget: Any = None,
        identity: Any = None,
    ) -> None:
        self._settings = settings
        self._transport, self._budget, self._identity = transport, budget, identity

    async def search(self, query: ResearchQuery) -> ResearchResult:
        trace: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        provenance: list[dict[str, str]] = []
        sources: list[dict[str, Any]] = []
        settings = self._settings
        if not settings.monid_enabled or not settings.monid_api_key:
            return ResearchResult(
                claims=[],
                retrieved_at=now,
                provenance=[{"source": "monid", "status": "not_configured"}],
                configured=False,
            )
        base = (settings.monid_api_base or "https://api.monid.ai").rstrip("/")
        if base not in {"https://api.monid.ai", "https://api.monid.ai/v1"}:
            return ResearchResult(
                claims=[],
                retrieved_at=now,
                provenance=[{"source": "monid", "status": "unsupported_api_origin"}],
                configured=False,
            )
        base = base.removesuffix("/v1") + "/v1/"
        provider, endpoint = settings.monid_tool_provider, settings.monid_tool_endpoint
        try:
            async with asyncio.timeout(settings.monid_timeout_seconds):
                async with httpx.AsyncClient(
                    base_url=base,
                    transport=self._transport,
                    headers={"Authorization": f"Bearer {settings.monid_api_key}"},
                    timeout=min(10, settings.monid_timeout_seconds),
                    follow_redirects=False,
                ) as client:

                    async def call(
                        path: str, payload: dict[str, Any] | None = None
                    ) -> dict[str, Any]:
                        if len(trace) >= settings.monid_max_calls:
                            raise ValueError("tool_call_budget_exhausted")
                        response = (
                            await client.post(path, json=payload)
                            if payload is not None
                            else await client.get(path)
                        )
                        trace.append(
                            {"tool": path.split("/")[0], "http_status": response.status_code}
                        )
                        if (
                            response.status_code not in {200, 202}
                            or len(response.content) > 256_000
                        ):
                            raise ValueError("tool_request_failed")
                        result = response.json()
                        if not isinstance(result, dict):
                            raise ValueError("invalid_tool_response")
                        return result

                    discovered = await call("discover", {"query": query.query[:500], "limit": 3})
                    if not provider or not endpoint:
                        raise ValueError("research_tool_requires_operator_configuration")
                    if not any(
                        row.get("provider") == provider and row.get("endpoint") == endpoint
                        for row in discovered.get("results", [])
                    ):
                        raise ValueError("approved_tool_not_discovered")
                    inspected = await call("inspect", {"provider": provider, "endpoint": endpoint})
                    price = inspected.get("price") or {}
                    price_amount = price.get("amount")
                    currency = (
                        price_amount.get("currency")
                        if isinstance(price_amount, dict)
                        else price.get("currency")
                    )
                    if price.get("type") != "PER_CALL" or currency != "USD":
                        raise ValueError("unsupported_tool_pricing")
                    raw_amount = (
                        price_amount["value"] if isinstance(price_amount, dict) else price_amount
                    )
                    if not isinstance(raw_amount, (str, float, int)):
                        raise ValueError("unsupported_tool_pricing")
                    amount = float(raw_amount)
                    if not 0 <= amount <= settings.monid_max_cost_usd:
                        raise ValueError("research_cost_budget_exceeded")
                    schema = inspected.get("inputSchema")
                    input_contract = inspected.get("input") or {}
                    if schema is None and isinstance(input_contract, dict):
                        properties = {
                            key: value
                            for key, value in input_contract.items()
                            if key in {"queryParams", "body", "pathParams", "headers"}
                            and isinstance(value, dict)
                        }
                        if properties:
                            schema = {
                                "type": "object",
                                "properties": properties,
                                "required": list(properties),
                                "additionalProperties": False,
                            }
                    if not isinstance(schema, dict):
                        raise ValueError("missing_tool_input_schema")
                    tool_input = _render_template(settings.monid_tool_input_template, query.query)
                    Draft202012Validator(schema).validate(tool_input)
                    # No identity/budget = discovery/inspection only. A platform-paid run
                    # needs explicit per-owner dollar authorization, even when LLM uses BYOK.
                    if self._budget is None or self._identity is None or query.user_id is None:
                        raise ValueError("research_spend_authorization_required")
                    principal = await self._identity.get_user(query.user_id)
                    reservation = await self._budget.reserve_research(principal, amount)
                    try:
                        result = await call(
                            "run", {"provider": provider, "endpoint": endpoint, "input": tool_input}
                        )
                        while result.get("status") not in {"COMPLETED", "FAILED"}:
                            run_id = str(result.get("runId") or "")
                            if not run_id.isalnum() or len(run_id) > 64:
                                raise ValueError("invalid_research_run_id")
                            await asyncio.sleep(0.2)
                            result = await call(f"runs/{run_id}")
                    finally:
                        # Charge the quoted maximum if billing is uncertain; token usage is zero.
                        await self._budget.settle_research(reservation, principal, amount)
                    if (
                        result.get("status") != "COMPLETED"
                        or int((result.get("providerResponse") or {}).get("httpStatus", 500)) >= 400
                    ):
                        raise ValueError("research_provider_failed")
                    trace.append(
                        {
                            "tool": "approved_research",
                            "run_id": result.get("runId"),
                            "quoted_cost_usd": amount,
                        }
                    )
                    # Retain source material as candidates, never verified numeric priors.
                    sources = _source_material(result.get("output"), now)
                    if not sources:
                        raise ValueError("insufficient_source_material")
                    provenance = [{"source": s["source"], "source_type": "web"} for s in sources]
        except Exception as error:
            # Neither upstream exception bodies nor keys belong in persisted tool traces.
            known = str(error) if isinstance(error, ValueError) else type(error).__name__
            allowed = {
                "tool_call_budget_exhausted",
                "tool_request_failed",
                "invalid_tool_response",
                "research_tool_requires_operator_configuration",
                "approved_tool_not_discovered",
                "unsupported_tool_pricing",
                "research_cost_budget_exceeded",
                "missing_tool_input_schema",
                "research_spend_authorization_required",
                "invalid_research_run_id",
                "research_provider_failed",
                "insufficient_source_material",
            }
            provenance = [
                {
                    "source": "monid",
                    "status": known if known in allowed else "research_failed",
                    "detail": "External research did not establish a defensible parameter.",
                }
            ]
        return ResearchResult(
            claims=sources,
            retrieved_at=now,
            provenance=provenance,
            configured=True,
            tool_trace=trace,
        )


def _render_template(template: Any, query: str) -> Any:
    if isinstance(template, dict):
        return {k: _render_template(v, query) for k, v in template.items()}
    if isinstance(template, list):
        return [_render_template(v, query) for v in template]
    return template.replace("{query}", query[:500]) if isinstance(template, str) else template


def _source_material(output: Any, now: datetime) -> list[dict[str, Any]]:
    if isinstance(output, dict):
        rows = output.get("results") or output.get("sources") or output.get("data") or [output]
    else:
        rows = output
    if not isinstance(rows, list):
        return []
    sources = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or row.get("source") or "")
        parsed = urlparse(url)
        material = (
            row.get("content") or row.get("text") or row.get("markdown") or row.get("snippet")
        )
        if parsed.scheme != "https" or not parsed.hostname or not isinstance(material, str):
            continue
        sources.append(
            {
                "source": url,
                "source_type": "web",
                "claim": material[:12_000],
                "retrieved_at": now.isoformat(),
                "evidence_class": "assumption",
                "material_kind": "snippet" if row.get("snippet") == material else "document_text",
                "title": str(row.get("title") or "")[:200],
            }
        )
    return sources
