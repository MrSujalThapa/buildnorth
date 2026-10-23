from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.goals.domain import GoalContract
from personal_markets.persistence.database import autocommit_connection, transaction
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
    published_at: datetime | None = None


class BaselineForecastRepository(Protocol):
    async def publish(
        self,
        goal: GoalContract,
        pricing: PricingResult,
        critic: CriticArtifact,
        *,
        published_at: datetime | None = None,
    ) -> PublishedBaseline | None: ...

    def history(self, goal_id: UUID) -> list[PublishedBaseline]: ...


class InMemoryBaselineForecastRepository:
    def __init__(self) -> None:
        self.published: list[tuple[GoalContract, PricingResult, CriticArtifact]] = []
        self._history: dict[UUID, dict[str, PublishedBaseline]] = {}

    async def publish(
        self,
        goal: GoalContract,
        pricing: PricingResult,
        critic: CriticArtifact,
        *,
        published_at: datetime | None = None,
    ) -> PublishedBaseline | None:
        self.published.append((goal, pricing, critic))
        point = history_point(goal, pricing)
        if point is None:
            return None
        points = self._history.setdefault(goal.goal_id, {})
        if point.material_hash not in points:
            points[point.material_hash] = replace(
                point, published_at=published_at or datetime.now(UTC)
            )
        return points[point.material_hash]

    def history(self, goal_id: UUID) -> list[PublishedBaseline]:
        return list(self._history.get(goal_id, {}).values())


class PostgresBaselineForecastRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._memory = InMemoryBaselineForecastRepository()

    async def publish(
        self,
        goal: GoalContract,
        pricing: PricingResult,
        critic: CriticArtifact,
        *,
        published_at: datetime | None = None,
    ) -> PublishedBaseline | None:
        point = history_point(goal, pricing)
        if point is None:
            return None
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into market_forecast_history (
                  goal_id, probability, forecast_status, evidence_watermark,
                  model_family, model_version, assumption_hash, material_hash,
                  simulation_artifact_id, source_kind, receipt_json, created_at
                ) values (
                  :goal_id, :probability, :forecast_status, :evidence_watermark,
                  :model_family, :model_version, :assumption_hash, :material_hash,
                  null, 'published_forecast', cast(:receipt as jsonb),
                  coalesce(cast(:published_at as timestamptz), now())
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
                    "receipt": json.dumps(jsonable_receipt(point.receipt), allow_nan=False),
                    "published_at": published_at,
                },
            )
        await self._memory.publish(goal, pricing, critic, published_at=published_at)
        return point

    def history(self, goal_id: UUID) -> list[PublishedBaseline]:
        return self._memory.history(goal_id)

    async def load_history(self, goal_id: UUID) -> list[PublishedBaseline]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        "select * from market_forecast_history "
                        "where goal_id=:id and source_kind='published_forecast' "
                        "order by created_at"
                    ),
                    {"id": goal_id},
                )
            ).mappings()
            points = [_published_from_row(dict(row)) for row in rows]
        memory = self._memory._history.setdefault(goal_id, {})
        for point in points:
            memory[point.material_hash] = point
        return points


def jsonable_receipt(value: Any) -> Any:
    """Postgres jsonb rejects NaN/Infinity; drop those scalars rather than crash publish."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: jsonable_receipt(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable_receipt(item) for item in value]
    return value


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


def _published_from_row(row: dict[str, Any]) -> PublishedBaseline:
    receipt = row.get("receipt_json") or {}
    if not isinstance(receipt, dict):
        receipt = {}
    return PublishedBaseline(
        goal_id=row["goal_id"],
        probability=float(row["probability"]),
        forecast_status=str(row["forecast_status"]),
        evidence_watermark=str(row["evidence_watermark"]),
        model_family=str(row["model_family"]),
        model_version=str(row["model_version"]),
        assumption_hash=str(row["assumption_hash"]),
        material_hash=str(row["material_hash"]),
        source_kind=str(row.get("source_kind") or "published_forecast"),
        receipt=receipt,
        published_at=row.get("created_at"),
    )
