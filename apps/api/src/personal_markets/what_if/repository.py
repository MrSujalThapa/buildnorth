from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.persistence.database import transaction


@dataclass(frozen=True, slots=True)
class PersistedSimulation:
    id: UUID
    goal_id: UUID
    run_kind: str
    request_hash: str
    receipt: dict[str, Any]
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MarketHistoryPoint:
    id: UUID
    goal_id: UUID
    probability: float
    forecast_status: str
    evidence_watermark: str
    model_family: str
    model_version: str
    assumption_hash: str
    simulation_artifact_id: UUID | None
    source_kind: str = "published_forecast"
    created_at: datetime | None = None


def reject_simulation_history_write(
    probability: float | None, material_hash: str | None
) -> None:
    if probability is not None or material_hash is not None:
        raise ValueError(
            "Simulation artifacts cannot write market_forecast_history. "
            "Use BaselineForecastService.publish for baseline history."
        )


class SimulationRepository(Protocol):
    async def append(
        self,
        *,
        goal_id: UUID,
        run_kind: str,
        request_hash: str,
        state_hash: str,
        assumption_hash: str,
        model_family: str,
        model_version: str,
        status: str,
        receipt: dict[str, Any],
        probability: float | None,
        evidence_watermark: str,
        material_hash: str | None,
    ) -> tuple[PersistedSimulation, bool, bool]: ...

    async def history(self, goal_id: UUID) -> list[MarketHistoryPoint]: ...

    async def list_runs(
        self, goal_id: UUID, *, run_kind: str | None = "impact", limit: int = 50
    ) -> list[PersistedSimulation]: ...


class InMemorySimulationRepository:
    def __init__(self) -> None:
        self._runs: dict[str, PersistedSimulation] = {}
        self._history: dict[UUID, dict[str, MarketHistoryPoint]] = {}

    async def append(
        self,
        *,
        goal_id: UUID,
        run_kind: str,
        request_hash: str,
        state_hash: str,
        assumption_hash: str,
        model_family: str,
        model_version: str,
        status: str,
        receipt: dict[str, Any],
        probability: float | None,
        evidence_watermark: str,
        material_hash: str | None,
    ) -> tuple[PersistedSimulation, bool, bool]:
        del state_hash, assumption_hash, model_family, model_version, status
        del evidence_watermark
        reject_simulation_history_write(probability, material_hash)
        existing = self._runs.get(request_hash)
        if existing is not None:
            return existing, False, False
        run = PersistedSimulation(uuid4(), goal_id, run_kind, request_hash, receipt)
        self._runs[request_hash] = run
        return run, True, False

    async def history(self, goal_id: UUID) -> list[MarketHistoryPoint]:
        return list(self._history.get(goal_id, {}).values())

    async def list_runs(
        self, goal_id: UUID, *, run_kind: str | None = "impact", limit: int = 50
    ) -> list[PersistedSimulation]:
        runs = [
            run
            for run in self._runs.values()
            if run.goal_id == goal_id and (run_kind is None or run.run_kind == run_kind)
        ]
        runs.sort(key=lambda item: item.created_at or datetime.min, reverse=True)
        return runs[:limit]


class PostgresSimulationRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append(
        self,
        *,
        goal_id: UUID,
        run_kind: str,
        request_hash: str,
        state_hash: str,
        assumption_hash: str,
        model_family: str,
        model_version: str,
        status: str,
        receipt: dict[str, Any],
        probability: float | None,
        evidence_watermark: str,
        material_hash: str | None,
    ) -> tuple[PersistedSimulation, bool, bool]:
        del evidence_watermark
        reject_simulation_history_write(probability, material_hash)
        run_id = uuid4()
        async with transaction(self._engine) as connection:
            inserted = (
                await connection.execute(
                    text("""
                    insert into simulation_artifacts
                    (id, goal_id, run_kind, request_hash, state_hash, assumption_hash,
                     model_family, model_version, status, receipt_json)
                    values (:id, :goal_id, :run_kind, :request_hash, :state_hash,
                     :assumption_hash, :model_family, :model_version, :status,
                     cast(:receipt as jsonb))
                    on conflict (request_hash) do nothing returning id
                    """),
                    {
                        "id": run_id,
                        "goal_id": goal_id,
                        "run_kind": run_kind,
                        "request_hash": request_hash,
                        "state_hash": state_hash,
                        "assumption_hash": assumption_hash,
                        "model_family": model_family,
                        "model_version": model_version,
                        "status": status,
                        "receipt": json.dumps(receipt),
                    },
                )
            ).scalar_one_or_none()
            created = inserted is not None
            if not created:
                row = (
                    (
                        await connection.execute(
                            text("select * from simulation_artifacts where request_hash=:hash"),
                            {"hash": request_hash},
                        )
                    )
                    .mappings()
                    .one()
                )
                return self._run(dict(row)), False, False
        return (
            PersistedSimulation(run_id, goal_id, run_kind, request_hash, receipt),
            True,
            False,
        )

    async def history(self, goal_id: UUID) -> list[MarketHistoryPoint]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "select * from market_forecast_history "
                        "where goal_id=:id order by created_at"
                    ),
                    {"id": goal_id},
                )
            ).mappings()
            return [self._history_point(dict(row)) for row in rows]

    async def list_runs(
        self, goal_id: UUID, *, run_kind: str | None = "impact", limit: int = 50
    ) -> list[PersistedSimulation]:
        if run_kind is None:
            query = (
                "select * from simulation_artifacts where goal_id=:id "
                "order by created_at desc limit :limit"
            )
            params: dict[str, object] = {"id": goal_id, "limit": limit}
        else:
            query = (
                "select * from simulation_artifacts where goal_id=:id "
                "and run_kind=:run_kind "
                "order by created_at desc limit :limit"
            )
            params = {"id": goal_id, "run_kind": run_kind, "limit": limit}
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(text(query), params)
            ).mappings()
            return [self._run(dict(row)) for row in rows]

    @staticmethod
    def _run(row: dict[str, Any]) -> PersistedSimulation:
        return PersistedSimulation(
            row["id"],
            row["goal_id"],
            row["run_kind"],
            row["request_hash"],
            row["receipt_json"],
            row["created_at"],
        )

    @staticmethod
    def _history_point(row: dict[str, Any]) -> MarketHistoryPoint:
        return MarketHistoryPoint(
            id=row["id"],
            goal_id=row["goal_id"],
            probability=row["probability"],
            forecast_status=row["forecast_status"],
            evidence_watermark=row["evidence_watermark"],
            model_family=row["model_family"],
            model_version=row["model_version"],
            assumption_hash=row["assumption_hash"],
            simulation_artifact_id=row["simulation_artifact_id"],
            source_kind=row.get("source_kind", "published_forecast"),
            created_at=row["created_at"],
        )
