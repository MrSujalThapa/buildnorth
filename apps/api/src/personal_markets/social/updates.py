"""Public "what moves the odds" rows derived from published forecast receipts.

Inputs are `market_forecast_history` rows whose `receipt_json` is either the full
receipt (in-memory) or the public projection selected by the Postgres adapter. Only
counts, owner-published metric names, model identifiers and change flags leave this
module; evidence values, identifiers and assumption values never do.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from personal_markets.social.domain import (
    PublicMarketUpdate,
    PublicModelChange,
    PublicModeledSensitivity,
    PublicStatusChange,
)

MAX_PUBLIC_DRIVERS = 5
MAX_DRIVER_NAME_LENGTH = 60
# Assumption names that could describe the owner's behaviour or observed state.
PRIVATE_DRIVER_PARTS = (
    "trait",
    "behavior",
    "behaviour",
    "execution",
    "follow_through",
    "consistency",
    "commitment",
    "momentum",
    "reliability",
    "recovery",
    "adherence",
    "personal",
    "observed",
    "current",
    "journal",
    "email",
    "token",
    "secret",
    "account",
)


@dataclass(frozen=True, slots=True)
class PublishedReceiptFacts:
    published_at: datetime
    probability: float
    forecast_status: str | None
    model: str | None
    evidence_ids: tuple[str, ...] | None
    goal_contract_version: int | None
    spec_deadline: str | None
    assumption_names: tuple[str, ...]


def metric_key(value: str) -> str:
    return re.sub(r"[\s\-]+", "_", value.strip().lower())


def metric_label(value: str) -> str:
    return metric_key(value).replace("_", " ")


def _receipt(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("receipt_json")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _assumption_names(receipt: dict[str, Any]) -> tuple[str, ...]:
    projected = receipt.get("assumption_names")
    if isinstance(projected, list):
        names = [item for item in projected if isinstance(item, str)]
    else:
        raw = receipt.get("assumptions")
        items = raw if isinstance(raw, list) else []
        names = [
            str(item.get("name") or item.get("id"))
            for item in items
            if isinstance(item, dict) and (item.get("name") or item.get("id"))
        ]
    return tuple(names)


def _model_name(row: dict[str, Any]) -> str | None:
    family = row.get("model_family")
    version = row.get("model_version")
    if not family:
        return None
    return f"{family}@{version}" if version else str(family)


def receipt_facts(rows: list[dict[str, Any]]) -> list[PublishedReceiptFacts]:
    facts: list[PublishedReceiptFacts] = []
    for row in rows:
        if str(row.get("source_kind") or "published_forecast") != "published_forecast":
            continue
        probability = row.get("probability")
        created = row.get("created_at")
        if probability is None or not isinstance(created, datetime):
            continue
        receipt = _receipt(row)
        ids = receipt.get("normalized_evidence_ids")
        version = receipt.get("goal_contract_version")
        spec = receipt.get("forecast_spec")
        deadline = spec.get("deadline") if isinstance(spec, dict) else None
        facts.append(
            PublishedReceiptFacts(
                published_at=created,
                probability=float(probability),
                forecast_status=str(row["forecast_status"]) if row.get("forecast_status") else None,
                model=_model_name(row),
                evidence_ids=tuple(str(item) for item in ids) if isinstance(ids, list) else None,
                goal_contract_version=version if isinstance(version, int) else None,
                spec_deadline=str(deadline) if deadline else None,
                assumption_names=_assumption_names(receipt),
            )
        )
    return facts


def new_evidence_ids(facts: list[PublishedReceiptFacts]) -> set[str]:
    """Evidence ids first seen at each publication; used to look up metric names."""
    seen: set[str] = set()
    found: set[str] = set()
    for fact in facts:
        if fact.evidence_ids is None:
            continue
        current = set(fact.evidence_ids)
        found |= current - seen
        seen = current
    return found


def _status_label(status: str | None) -> str | None:
    return status.replace("_", " ").lower() if status else None


def derive_updates(
    facts: list[PublishedReceiptFacts],
    *,
    tracked_metrics: list[str],
    evidence_metrics: dict[str, str],
) -> list[PublicMarketUpdate]:
    public_metrics = {metric_key(item) for item in tracked_metrics if item}
    updates: list[PublicMarketUpdate] = []
    previous: PublishedReceiptFacts | None = None
    for fact in facts:
        recorded = fact.evidence_ids is not None
        comparable = recorded and previous is not None and previous.evidence_ids is not None
        current_ids = set(fact.evidence_ids or ())
        prior_ids = set(previous.evidence_ids or ()) if previous else set()
        added = current_ids - prior_ids if previous is None or comparable else set()
        named: list[str] = []
        other = 0
        for evidence_id in sorted(added):
            metric = evidence_metrics.get(evidence_id)
            if metric and metric_key(metric) in public_metrics:
                label = metric_label(metric)
                if label not in named:
                    named.append(label)
            else:
                other += 1
        model_change = None
        status_change = None
        definition_revised = False
        deadline_changed = False
        if previous is not None:
            if previous.model and fact.model and previous.model != fact.model:
                model_change = PublicModelChange(previous=previous.model, current=fact.model)
            if (
                previous.forecast_status
                and fact.forecast_status
                and previous.forecast_status != fact.forecast_status
            ):
                status_change = PublicStatusChange(
                    previous=_status_label(previous.forecast_status) or "",
                    current=_status_label(fact.forecast_status) or "",
                )
            definition_revised = (
                previous.goal_contract_version is not None
                and fact.goal_contract_version is not None
                and fact.goal_contract_version > previous.goal_contract_version
            )
            deadline_changed = bool(
                previous.spec_deadline
                and fact.spec_deadline
                and previous.spec_deadline[:10] != fact.spec_deadline[:10]
            )
        updates.append(
            PublicMarketUpdate(
                published_at=fact.published_at,
                probability=fact.probability,
                previous_probability=previous.probability if previous else None,
                change_points=(
                    round((fact.probability - previous.probability) * 100, 1) if previous else None
                ),
                kind="first_publication" if previous is None else "update",
                receipt_recorded=recorded,
                evidence_total=len(current_ids) if recorded else None,
                new_evidence_count=(
                    len(added) if (previous is None and recorded) or comparable else None
                ),
                retired_evidence_count=len(prior_ids - current_ids) if comparable else None,
                new_evidence_metrics=sorted(named),
                other_new_evidence_count=other,
                model=fact.model,
                model_change=model_change,
                status_change=status_change,
                definition_revised=definition_revised,
                deadline_changed=deadline_changed,
            )
        )
        previous = fact
    return updates


def _public_driver(name: str) -> str | None:
    key = metric_key(name)
    if not key or len(key) > MAX_DRIVER_NAME_LENGTH:
        return None
    if any(part in key for part in PRIVATE_DRIVER_PARTS):
        return None
    return key.replace(".", " ").replace("_", " ")


def modeled_sensitivity(facts: list[PublishedReceiptFacts]) -> PublicModeledSensitivity | None:
    if not facts:
        return None
    latest = facts[-1]
    drivers: list[str] = []
    for name in latest.assumption_names:
        label = _public_driver(name)
        if label and label not in drivers:
            drivers.append(label)
    if not drivers:
        return None
    return PublicModeledSensitivity(
        published_at=latest.published_at,
        model=latest.model,
        drivers=drivers[:MAX_PUBLIC_DRIVERS],
    )
