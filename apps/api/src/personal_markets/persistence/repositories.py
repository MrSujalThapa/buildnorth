from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from personal_markets.evidence.domain import metadata_for
from personal_markets.evidence.mapping import proposal_to_normalized
from personal_markets.goals.domain import GoalContract
from personal_markets.persistence.database import autocommit_connection, transaction
from personal_markets.ports import EvidenceEventProposal


class PostgresGoalRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list(self) -> list[GoalContract]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text("select * from goals where status = 'active' order by title")
                )
            ).mappings()
            return [self._to_domain(dict(row)) for row in rows]

    async def list_for_user(self, user_id: UUID) -> list[GoalContract]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        "select * from goals where user_id = :user_id"
                        " and status = 'active' order by title"
                    ),
                    {"user_id": user_id},
                )
            ).mappings()
            return [self._to_domain(dict(row)) for row in rows]

    async def get(self, goal_id: UUID) -> GoalContract | None:
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("select * from goals where id = :id and status = 'active'"),
                        {"id": goal_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            return self._to_domain(dict(row)) if row else None

    async def get_for_user(self, goal_id: UUID, user_id: UUID) -> GoalContract | None:
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "select * from goals where id = :id and user_id = :user_id"
                            " and status = 'active'"
                        ),
                        {"id": goal_id, "user_id": user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            return self._to_domain(dict(row)) if row else None

    async def upsert_seed(self, goal: GoalContract) -> bool:
        raise RuntimeError("Use PostgresSeedRepository.seed for atomic fixture ingestion")

    async def create(self, goal: GoalContract, user_id: UUID) -> GoalContract:
        existing = await self.get(goal.goal_id)
        if existing is not None:
            return existing
        values = goal.model_dump(mode="python")
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into goals (
                  id, user_id, title, goal_type, success_definition_json, deadline,
                  target_probability, forecast_status, resource_constraints_json,
                  state_dimensions_json, model_requirements_json, version
                ) values (
                  :goal_id, :user_id, :title, :goal_type, cast(:success_definition as jsonb), :deadline,
                  :target_probability, :forecast_status, cast(:resource_constraints as jsonb),
                  cast(:state_dimensions as jsonb), cast(:model_requirements as jsonb), :version
                ) on conflict (id) do nothing
                """),
                {
                    **values,
                    "user_id": user_id,
                    "success_definition": json.dumps(values["success_definition"]),
                    "resource_constraints": json.dumps(values["resource_constraints"]),
                    "state_dimensions": json.dumps(values["state_dimensions"]),
                    "model_requirements": json.dumps(values["model_requirements"]),
                },
            )
        stored = await self.get(goal.goal_id)
        assert stored is not None
        return stored

    async def archive_for_user(self, goal_id: UUID, user_id: UUID) -> bool:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text(
                    "update goals set status = 'archived', updated_at = now()"
                    " where id = :id and user_id = :user_id and status = 'active'"
                ),
                {"id": goal_id, "user_id": user_id},
            )
        return bool(result.rowcount)

    async def restore_for_user(self, goal_id: UUID, user_id: UUID) -> bool:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text(
                    "update goals set status = 'active', updated_at = now()"
                    " where id = :id and user_id = :user_id and status = 'archived'"
                ),
                {"id": goal_id, "user_id": user_id},
            )
        return bool(result.rowcount)

    async def merge_requirements(
        self, goal_id: UUID, user_id: UUID, patch: dict[str, Any]
    ) -> GoalContract | None:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text(
                    """
                    update goals
                    set model_requirements_json = coalesce(model_requirements_json, '{}'::jsonb)
                      || cast(:patch as jsonb),
                        updated_at = now()
                    where id = :id and user_id = :user_id
                    """
                ),
                {"id": goal_id, "user_id": user_id, "patch": json.dumps(patch)},
            )
        if not result.rowcount:
            return None
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("select * from goals where id = :id and user_id = :user_id"),
                        {"id": goal_id, "user_id": user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._to_domain(dict(row)) if row else None

    @staticmethod
    def _to_domain(row: dict[str, Any]) -> GoalContract:
        return GoalContract(
            goal_id=row["id"],
            title=row["title"],
            goal_type=row["goal_type"],
            success_definition=row["success_definition_json"],
            deadline=row["deadline"],
            target_probability=row["target_probability"],
            resource_constraints=row["resource_constraints_json"],
            state_dimensions=row["state_dimensions_json"],
            model_requirements=row["model_requirements_json"],
            forecast_status=row["forecast_status"],
            version=row["version"],
        )


class PostgresSeedRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def seed(self, payload: dict[str, Any]) -> dict[str, int]:
        async with transaction(self._engine) as connection:
            goals = sum([await self._upsert_goal(connection, row) for row in payload["goals"]])
            events = sum(
                [await self._upsert_event(connection, row) for row in payload["raw_source_events"]]
            )
            history = sum(
                [
                    await self._insert_market_history(connection, row)
                    for row in payload.get("market_history", [])
                ]
            )
            evidence = sum(
                [
                    await self._upsert_evidence(connection, row)
                    for row in payload.get("evidence_events", [])
                ]
            )
        return {
            "goals_upserted": goals,
            "raw_events_upserted": events,
            "market_history_inserted": history,
            "evidence_events_upserted": evidence,
        }

    async def _upsert_goal(self, connection: AsyncConnection, row: dict[str, Any]) -> int:
        user_id = row["user_id"]
        values = GoalContract.model_validate(row).model_dump(mode="python")
        result = await connection.execute(
            text("""
            insert into goals (
              id, user_id, title, goal_type, success_definition_json, deadline,
              target_probability, forecast_status, resource_constraints_json,
              state_dimensions_json, model_requirements_json, version
            ) values (
              :goal_id, :user_id, :title, :goal_type, cast(:success_definition as jsonb), :deadline,
              :target_probability, :forecast_status, cast(:resource_constraints as jsonb),
              cast(:state_dimensions as jsonb), cast(:model_requirements as jsonb), :version
            ) on conflict (id) do update set
              title=excluded.title, success_definition_json=excluded.success_definition_json,
              deadline=excluded.deadline,
              resource_constraints_json=excluded.resource_constraints_json,
              state_dimensions_json=excluded.state_dimensions_json,
              model_requirements_json=excluded.model_requirements_json, version=excluded.version,
              updated_at=now()
        """),
            {
                **values,
                "user_id": user_id,
                "success_definition": json.dumps(values["success_definition"]),
                "resource_constraints": json.dumps(values["resource_constraints"]),
                "state_dimensions": json.dumps(values["state_dimensions"]),
                "model_requirements": json.dumps(values["model_requirements"]),
            },
        )
        return result.rowcount

    async def _upsert_event(self, connection: AsyncConnection, row: dict[str, Any]) -> int:
        canonical = json.dumps(row["payload"], sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        result = await connection.execute(
            text("""
            insert into raw_source_events (
              id, user_id, source_type, external_event_id, content_fingerprint,
              observed_at, raw_payload_ref, raw_payload_json
            ) values (
              :id, :user_id, :source_type, :external_event_id, :fingerprint,
              :observed_at, :payload_ref, cast(:payload as jsonb)
            ) on conflict do nothing
        """),
            {
                **row,
                "observed_at": datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00")),
                "fingerprint": fingerprint,
                "payload_ref": f"seed://{row['id']}",
                "payload": canonical,
            },
        )
        return result.rowcount

    async def _upsert_evidence(self, connection: AsyncConnection, row: dict[str, Any]) -> int:
        meta = metadata_for(row["source_type"])
        proposal = EvidenceEventProposal.model_validate(
            {
                "source_type": row["source_type"],
                "event_type": row["event_type"],
                "domain": row["domain"],
                "metric": row["metric"],
                "numeric_value": row.get("numeric_value"),
                "categorical_value": row.get("categorical_value"),
                "unit": row.get("unit"),
                "observed_at": row["observed_at"],
                "summary": row.get("summary") or row["metric"],
            }
        )
        normalized = proposal_to_normalized(
            proposal,
            row["fingerprint"],
            evidence_id=UUID(row["id"]),
            raw_event_id=row.get("raw_source_event_id"),
        )
        provenance = normalized.provenance.model_dump(mode="json")
        provenance["fingerprint"] = row["fingerprint"]
        provenance["summary"] = normalized.summary
        result = await connection.execute(
            text("""
            insert into evidence_events (
              id, user_id, raw_source_event_id, event_type, domain, metric, numeric_value,
              categorical_value, unit, observed_at, source_quality, provenance_json, status
            ) values (
              :id, :user_id, :raw_source_event_id, :event_type, :domain, :metric, :numeric_value,
              :categorical_value, :unit, :observed_at, :source_quality, cast(:provenance as jsonb), 'active'
            ) on conflict (id) do nothing
            """),
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "raw_source_event_id": row.get("raw_source_event_id"),
                "event_type": row["event_type"],
                "domain": row["domain"],
                "metric": row["metric"],
                "numeric_value": row.get("numeric_value"),
                "categorical_value": row.get("categorical_value"),
                "unit": row.get("unit"),
                "observed_at": datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00")),
                "source_quality": meta["source_quality"],
                "provenance": json.dumps(provenance),
            },
        )
        link = await connection.execute(
            text("""
            insert into goal_evidence (goal_id, evidence_id, relevance_metadata_json)
            values (:goal_id, :evidence_id, cast(:metadata as jsonb))
            on conflict do nothing
            """),
            {
                "goal_id": row["goal_id"],
                "evidence_id": row["id"],
                "metadata": json.dumps({"seed": True, "provenance": "DEMO_SEED"}),
            },
        )
        return result.rowcount + link.rowcount

    async def _insert_market_history(self, connection: AsyncConnection, row: dict[str, Any]) -> int:
        result = await connection.execute(
            text("""
            insert into market_forecast_history (
              id, goal_id, probability, forecast_status, evidence_watermark,
              model_family, model_version, assumption_hash, material_hash,
              simulation_artifact_id, source_kind, created_at
            ) values (
              :id, :goal_id, :probability, :forecast_status, :evidence_watermark,
              :model_family, :model_version, :assumption_hash, :material_hash,
              null, 'synthetic_demo', :created_at
            ) on conflict (goal_id, material_hash) do nothing
            """),
            {
                **row,
                "created_at": datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
            },
        )
        return result.rowcount


class ForecastArtifactRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append_bundle(
        self, snapshot: dict[str, Any], forecast: dict[str, Any], receipt: dict[str, Any]
    ) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into state_snapshots
                (id, goal_id, as_of, version, state_vector_json, uncertainty_json,
                 estimator_version, evidence_watermark)
                values (:id, :goal_id, :as_of, :version, cast(:state_vector_json as jsonb),
                 cast(:uncertainty_json as jsonb), :estimator_version, :evidence_watermark)
            """),
                snapshot,
            )
            await connection.execute(
                text("""
                insert into forecasts
                (id, goal_id, state_snapshot_id, model_version_id, raw_probability,
                 calibrated_probability, forecast_status, critic_decision, limitations_json)
                values (:id, :goal_id, :state_snapshot_id, :model_version_id, :raw_probability,
                 :calibrated_probability, :forecast_status, :critic_decision,
                 cast(:limitations_json as jsonb))
            """),
                forecast,
            )
            await connection.execute(
                text("""
                insert into forecast_receipts
                (id, forecast_id, receipt_version, inputs_json, feature_transforms_json,
                 model_details_json, assumptions_json, calibration_json, provenance_json)
                values (:id, :forecast_id, :receipt_version, cast(:inputs_json as jsonb),
                 cast(:feature_transforms_json as jsonb), cast(:model_details_json as jsonb),
                 cast(:assumptions_json as jsonb), cast(:calibration_json as jsonb),
                 cast(:provenance_json as jsonb))
            """),
                receipt,
            )
