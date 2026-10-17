from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from personal_markets.behavior.tokenize import overlap_score, tokenize

RELEVANCE_LABELS = (
    (0.22, "high"),
    (0.10, "medium"),
    (0.04, "low"),
    (0.0, "irrelevant"),
)


def goal_text(goal: dict[str, Any] | None) -> str:
    payload = goal or {}
    parts = [
        payload.get("title"),
        payload.get("goal_title"),
        payload.get("goal_type"),
        payload.get("success_event"),
        payload.get("description"),
    ]
    dims = payload.get("state_dimensions") or []
    success = payload.get("success_definition") or {}
    return " ".join(str(item) for item in [*parts, *dims, *success.values()] if item)


def resource_text(resource: dict[str, Any]) -> str:
    return " ".join(
        str(resource.get(key) or "")
        for key in ("label", "name", "description", "rationale", "why", "resource_type", "type", "mime_type")
    )


def score_resource(resource: dict[str, Any], goal: dict[str, Any] | None) -> float:
    left = resource_text(resource)
    right = goal_text(goal)
    return overlap_score(tokenize(left), tokenize(right), left, right)


def relevance_label(score: float) -> str:
    for threshold, label in RELEVANCE_LABELS:
        if score >= threshold:
            return label
    return "irrelevant"


def rank_resources(
    resources: Iterable[dict[str, Any]],
    goal: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in resources:
        if not isinstance(item, dict):
            continue
        scored.append((score_resource(item, goal), item))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("label") or pair[1].get("id") or "")))
    ranked: list[dict[str, Any]] = []
    for score, item in scored:
        label = str(item.get("label") or item.get("name") or item.get("id") or "")
        resource_id = str(item.get("resource_id") or item.get("id") or label)
        why = str(item.get("description") or item.get("rationale") or item.get("why") or "").strip()
        if not why:
            why = f"Metadata overlap with the goal contract ({score:.2f})."
        relevance = relevance_label(score)
        ranked.append(
            {
                "resource_id": resource_id,
                "label": label,
                "rationale": why,
                "why": why,
                "resource_type": str(item.get("resource_type") or item.get("type") or "resource"),
                "goal_relevance": relevance,
                "state_variables": list(item.get("state_variables") or _guess_state_variables(item, goal)),
                "recommended": relevance in {"high", "medium"},
                "score": score,
                "plugin_id": item.get("plugin_id") or item.get("provider"),
            }
        )
    return ranked


def _guess_state_variables(resource: dict[str, Any], goal: dict[str, Any] | None) -> list[str]:
    dims = [str(item) for item in (goal or {}).get("state_dimensions") or []]
    if not dims:
        return []
    text = resource_text(resource)
    tokens = set(tokenize(text))
    return [dim for dim in dims if set(tokenize(dim)) & tokens]
