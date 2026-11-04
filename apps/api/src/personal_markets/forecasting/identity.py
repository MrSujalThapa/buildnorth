"""Stable identity for a numerical forecast evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any


def evaluation_input_hash(
    *,
    goal_version: int,
    model_family: str,
    model_version: str,
    evidence_ids: list[str],
    numeric_state: dict[str, Any],
    numeric_assumptions: dict[str, Any],
    assumption_sources: dict[str, Any],
) -> str:
    transforms = numeric_state.get("pricing_transforms")
    reference_version = (
        transforms.get("reference_version") if isinstance(transforms, dict) else None
    )
    payload = {
        "goal_version": goal_version,
        "model": [model_family, model_version],
        "evidence_ids": sorted(evidence_ids),
        "numeric_state": numeric_state,
        "numeric_assumptions": numeric_assumptions,
        "assumption_sources": assumption_sources,
        "reference_version": reference_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def published_replay_time(
    receipt: dict[str, Any], *, goal_version: int, evidence_ids: list[str]
) -> datetime | None:
    """Use a receipt's clock only for an unchanged, same-day evaluation."""
    if (
        receipt.get("goal_contract_version") != goal_version
        or receipt.get("receipt_version") != 2
        or receipt.get("normalized_evidence_ids") != evidence_ids
    ):
        return None
    recorded = receipt.get("evaluated_at")
    if not isinstance(recorded, str):
        return None
    try:
        parsed = datetime.fromisoformat(recorded)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.astimezone(UTC).date() != datetime.now(UTC).date():
        return None
    return parsed
