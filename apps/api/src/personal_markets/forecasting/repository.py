from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.goals.domain import GoalContract
from personal_markets.persistence.database import transaction
from personal_markets.ports import CriticArtifact, PricingResult


@dataclass(frozen=True, slots=True)
class PublishedBaseline:
    goal_id: UUID
    probability: float
    forecast_status: str
    evidence_watermark: str
    model_family: str
    model_version: str
    assumption_hash: str
    material_hash: str
    source_kind: str
    receipt: dict[str, Any]


class BaselineForecastRepository(Protocol):
    async def publish(
        self, goal: GoalContract, pricing: PricingResult, critic: CriticArtifact
    ) -> PublishedBaseline | None: ...

    def history(self, goal_id: UUID) -> list[PublishedBaseline]: ...


class InMemoryBaselineForecastRepository:
    def __init__(self) -> None:
        self.published: list[tuple[GoalContract, PricingResult, CriticArtifact]] = []
        self._history: dict[UUID, dict[str, PublishedBaseline]] = {}

    async def publish(
        self, goal: GoalContract, pricing: PricingResult, critic: CriticArtifact
    ) -> PublishedBaseline | None:
        self.published.append((goal, pricing, critic))
        point = history_point(goal, pricing)
        if point is None:
            return None
        points = self._history.setdefault(goal.goal_id, {})
        if point.material_hash not in points:
            points[point.material_hash] = point
        return point

    def history(self, goal_id: UUID) -> list[PublishedBaseline]:
        return list(self._history.get(goal_id, {}).values())


class PostgresBaselineForecastRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._memory = InMemoryBaselineForecastRepository()

    async def publish(
        self, goal: GoalContract, pricing: PricingResult, critic: CriticArtifact
    ) -> PublishedBaseline | None:
        await self._memory.publish(goal, pricing, critic)
        point = history_point(goal, pricing)
        if point is None:
            return None
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into market_forecast_history (
                  goal_id, probability, forecast_status, evidence_watermark,
                  model_family, model_version, assumption_hash, material_hash,
                  simulation_artifact_id, source_kind
                ) values (
                  :goal_id, :probability, :forecast_status, :evidence_watermark,
                  :model_family, :model_version, :assumption_hash, :material_hash,
                  null, 'published_forecast'
                ) on conflict (goal_id, material_hash) do nothing
                """),
                {
                    "goal_id": goal.goal_id,
                    "probability": point.probability,
                    "forecast_status": point.forecast_status,
                    "evidence_watermark": point.evidence_watermark,
                    "model_family": point.model_family,
                    "model_version": point.model_version,
                    "assumption_hash": point.assumption_hash,
                    "material_hash": point.material_hash,
                },
            )
        return point

    def history(self, goal_id: UUID) -> list[PublishedBaseline]:
        return self._memory.history(goal_id)


def material_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def history_point(goal: GoalContract, pricing: PricingResult) -> PublishedBaseline | None:
    if not pricing.priced or pricing.raw_probability is None:
        return None
    probability = (
        pricing.calibrated_probability
        if pricing.calibrated_probability is not None
        else pricing.raw_probability
    )
    raw_model = pricing.receipt.get("model")
    model = raw_model if isinstance(raw_model, dict) else {}
    family = str(model.get("family") or pricing.receipt.get("model_registry_family") or "unknown")
    version = str(
        model.get("version") or pricing.receipt.get("model_registry_version") or "unspecified"
    )
    watermark = str(pricing.receipt.get("evidence_watermark") or "none")
    assumption_payload = {
        "assumptions": pricing.receipt.get("assumptions") or [],
        "goal_contract_version": goal.version,
        "model_family": family,
        "model_version": version,
    }
    hashed = material_hash(
        {
            "goal_id": str(goal.goal_id),
            "probability": probability,
            "forecast_status": pricing.forecast_status,
            "evidence_watermark": watermark,
            "assumption": assumption_payload,
        }
    )
    return PublishedBaseline(
        goal_id=goal.goal_id,
        probability=probability,
        forecast_status=pricing.forecast_status,
        evidence_watermark=watermark,
        model_family=family,
        model_version=version,
        assumption_hash=material_hash(assumption_payload),
        material_hash=hashed,
        source_kind="published_forecast",
        receipt=dict(pricing.receipt),
    )
