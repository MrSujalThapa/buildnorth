"""Provider-backed model listing. Never invents model IDs."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from personal_markets.integrations.inference_catalog import classify_discovered


def parse_provider_models(provider: str, payload: object) -> list[dict[str, Any]]:
    rows = _rows(payload)
    discovered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        model_id, display_name = _identity(row)
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        cap = classify_discovered(provider, model_id, display_name=display_name)
        discovered.append(asdict(cap))
    discovered.sort(
        key=lambda item: (
            0 if item["compatibility"] == "structured" else 1,
            0 if item["source"] == "catalog" else 1,
            str(item.get("display_name") or item["model"]),
        )
    )
    return discovered


def recommended_model(provider: str, discovered: list[dict[str, Any]], fallback: str) -> str:
    cataloged = [
        item["model"]
        for item in discovered
        if item.get("source") == "catalog" and item.get("structured")
    ]
    if fallback in cataloged:
        return fallback
    if cataloged:
        return cataloged[0]
    structured = [item["model"] for item in discovered if item.get("structured")]
    return structured[0] if structured else fallback


def _rows(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        models = payload.get("models")
        if isinstance(models, list):
            return [item for item in models if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _identity(row: dict[str, Any]) -> tuple[str, str | None]:
    model_id = str(row.get("id") or row.get("model") or "").strip()
    display = row.get("display_name") or row.get("name")
    display_name = str(display).strip() if isinstance(display, str) and display.strip() else None
    return model_id, display_name
