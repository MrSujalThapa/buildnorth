from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.agents.budget import InMemoryUsageStore
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.evidence.mapping import proposal_to_normalized
from personal_markets.persistence.database import transaction
from personal_markets.ports import EvidenceEventProposal, WorkflowSnapshot


class InMemoryEvidenceRepository:
    def __init__(self, goals: dict[UUID, object] | None = None) -> None:
        self._events: dict[UUID, NormalizedEvidence] = {}
        self._by_fingerprint: dict[tuple[UUID, str], UUID] = {}
        self._goal_links: dict[UUID, list[UUID]] = {}
        self._goal_ids = goals if goals is not None else {}

    def track_goal(self, goal_id: UUID) -> None:
        self._goal_ids[goal_id] = True

    async def goal_exists(self, goal_id: UUID) -> bool:
        return goal_id in self._goal_ids or goal_id in self._goal_links

    async def list_for_goal(self, goal_id: UUID) -> list[NormalizedEvidence]:
        return [
            self._events[item] for item in self._goal_links.get(goal_id, []) if item in self._events
        ]

    async def find_fingerprint(self, user_id: UUID, fingerprint: str) -> NormalizedEvidence | None:
        evidence_id = self._by_fingerprint.get((user_id, fingerprint))
        return self._events.get(evidence_id) if evidence_id else None

    async def insert(
        self,
        user_id: UUID,
        goal_id: UUID,
        event: EvidenceEventProposal,
        fingerprint: str,
        agent_run_id: UUID | None,
        conflict: str,
    ) -> NormalizedEvidence:
        del agent_run_id
        existing = await self.find_fingerprint(user_id, fingerprint)
        if existing:
            return existing
        stored = proposal_to_normalized(event, fingerprint, conflict=conflict)
        assert stored.evidence_id is not None
        self._events[stored.evidence_id] = stored
        self._by_fingerprint[(user_id, fingerprint)] = stored.evidence_id
        self._goal_links.setdefault(goal_id, []).append(stored.evidence_id)
        return stored


class InMemoryThreadStore:
    def __init__(self) -> None:
        self._rows: dict[UUID, WorkflowSnapshot] = {}

    async def upsert(self, snapshot: WorkflowSnapshot) -> None:
        self._rows[snapshot.thread_id] = snapshot

    async def get(self, thread_id: UUID) -> WorkflowSnapshot | None:
        return self._rows.get(thread_id)


class InMemoryAgentRunStore:
    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []

    async def record(self, row: dict[str, Any]) -> None:
        self.runs.append(row)

    async def list_for_thread(self, thread_id: UUID) -> list[dict[str, Any]]:
        return [row for row in self.runs if str(row.get("thread_id")) == str(thread_id)]


class PostgresUsageStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add(
        self,
        usage_date: date,
        pool: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into openai_usage_daily
                  (usage_date, pool, model, input_tokens, output_tokens, estimated_cost_usd)
                values (:usage_date, :pool, :model, :input_tokens, :output_tokens, :cost)
                on conflict (usage_date, pool, model) do update set
                  input_tokens = openai_usage_daily.input_tokens + excluded.input_tokens,
                  output_tokens = openai_usage_daily.output_tokens + excluded.output_tokens,
                  estimated_cost_usd = openai_usage_daily.estimated_cost_usd + excluded.estimated_cost_usd
                """),
                {
                    "usage_date": usage_date,
                    "pool": pool,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost": cost,
                },
            )

    async def totals(self, usage_date: date) -> dict[str, dict[str, int | float]]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text("""
                    select pool, sum(input_tokens) as input_tokens, sum(output_tokens) as output_tokens,
                           sum(estimated_cost_usd) as estimated_cost_usd
                    from openai_usage_daily where usage_date = :usage_date group by pool
                    """),
                    {"usage_date": usage_date},
                )
            ).mappings()
        result: dict[str, dict[str, int | float]] = {}
        for row in rows:
            result[str(row["pool"])] = {
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "estimated_cost_usd": float(row["estimated_cost_usd"] or 0),
            }
        return result


class PostgresEvidenceRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def goal_exists(self, goal_id: UUID) -> bool:
        async with self._engine.connect() as connection:
            value = await connection.scalar(
                text("select 1 from goals where id = :id"), {"id": goal_id}
            )
        return value is not None

    async def list_for_goal(self, goal_id: UUID) -> list[NormalizedEvidence]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text("""
                    select e.* from evidence_events e
                    join goal_evidence g on g.evidence_id = e.id
                    where g.goal_id = :goal_id
                    order by e.created_at
                    """),
                    {"goal_id": goal_id},
                )
            ).mappings()
        return [self._to_domain(dict(row)) for row in rows]

    async def find_fingerprint(self, user_id: UUID, fingerprint: str) -> NormalizedEvidence | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                        select e.* from evidence_events e
                        where e.user_id = :user_id
                          and e.provenance_json ->> 'fingerprint' = :fingerprint
                        limit 1
                        """),
                        {"user_id": user_id, "fingerprint": fingerprint},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._to_domain(dict(row)) if row else None

    async def insert(
        self,
        user_id: UUID,
        goal_id: UUID,
        event: EvidenceEventProposal,
        fingerprint: str,
        agent_run_id: UUID | None,
        conflict: str,
    ) -> NormalizedEvidence:
        existing = await self.find_fingerprint(user_id, fingerprint)
        if existing:
            return existing
        stored = proposal_to_normalized(event, fingerprint, conflict=conflict)
        assert stored.evidence_id is not None
        payload = stored.model_dump(mode="json")
        payload["provenance"]["fingerprint"] = fingerprint
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into evidence_events (
                  id, user_id, event_type, domain, metric, numeric_value, categorical_value, unit,
                  observed_at, source_quality, provenance_json, status, agent_run_id
                ) values (
                  :id, :user_id, :event_type, :domain, :metric, :numeric_value, :categorical_value, :unit,
                  :observed_at, :source_quality, cast(:provenance as jsonb), 'active', :agent_run_id
                ) on conflict (id) do nothing
                """),
                {
                    "id": stored.evidence_id,
                    "user_id": user_id,
                    "event_type": stored.event_type,
                    "domain": stored.domain,
                    "metric": stored.metric,
                    "numeric_value": stored.numeric_value,
                    "categorical_value": stored.categorical_value,
                    "unit": stored.unit,
                    "observed_at": stored.observed_at,
                    "source_quality": stored.source_quality,
                    "provenance": json_dumps(payload["provenance"]),
                    "agent_run_id": agent_run_id,
                },
            )
            await connection.execute(
                text("""
                insert into goal_evidence (goal_id, evidence_id, relevance_metadata_json)
                values (:goal_id, :evidence_id, '{}'::jsonb)
                on conflict do nothing
                """),
                {"goal_id": goal_id, "evidence_id": stored.evidence_id},
            )
        return stored

    @staticmethod
    def _to_domain(row: dict[str, Any]) -> NormalizedEvidence:
        from personal_markets.evidence.domain import Provenance

        provenance = row["provenance_json"]
        return NormalizedEvidence(
            evidence_id=row["id"],
            event_type=row["event_type"],
            domain=row["domain"],
            metric=row["metric"],
            numeric_value=row["numeric_value"],
            categorical_value=row["categorical_value"],
            unit=row["unit"],
            observed_at=row["observed_at"],
            source_quality=row["source_quality"],
            provenance=Provenance.model_validate(
                {k: v for k, v in provenance.items() if k != "fingerprint"}
            ),
            summary=str(provenance.get("summary") or row["metric"]),
            fingerprint=str(provenance.get("fingerprint") or ""),
        )


class PostgresThreadStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def upsert(self, snapshot: WorkflowSnapshot) -> None:
        payload = snapshot.model_dump(mode="json")
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into workflow_threads (
                  id, user_id, kind, status, current_step, interrupt_payload, goal_id, result_json, updated_at
                ) values (
                  :id, :user_id, :kind, :status, :current_step, cast(:interrupt as jsonb), :goal_id,
                  cast(:result as jsonb), now()
                )
                on conflict (id) do update set
                  status=excluded.status,
                  current_step=excluded.current_step,
                  interrupt_payload=excluded.interrupt_payload,
                  goal_id=excluded.goal_id,
                  result_json=excluded.result_json,
                  updated_at=now()
                """),
                {
                    "id": snapshot.thread_id,
                    "user_id": payload.get("debug", {}).get("user_id")
                    or "10000000-0000-0000-0000-000000000001",
                    "kind": snapshot.kind,
                    "status": snapshot.status,
                    "current_step": snapshot.current_step,
                    "interrupt": json_dumps(payload.get("interrupt")),
                    "goal_id": snapshot.goal.goal_id if snapshot.goal else None,
                    "result": json_dumps(payload),
                },
            )

    async def get(self, thread_id: UUID) -> WorkflowSnapshot | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("select result_json from workflow_threads where id = :id"),
                        {"id": thread_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return WorkflowSnapshot.model_validate(row["result_json"])


class PostgresAgentRunStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, row: dict[str, Any]) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into agent_runs (
                  id, agent_type, agent_version, model_provider, model_name, input_refs_json,
                  output_json, validation_status, retry_count, duration_ms, token_usage_json,
                  estimated_cost, thread_id, prompt_version, prompt_checksum, tool_trace_json,
                  validation_errors_json, input_artifact_ids_json, interrupt_json, status
                ) values (
                  :id, :agent_type, :agent_version, :model_provider, :model_name, cast(:input_refs as jsonb),
                  cast(:output as jsonb), :validation_status, :retry_count, :duration_ms,
                  cast(:token_usage as jsonb), :estimated_cost, :thread_id, :prompt_version,
                  :prompt_checksum, cast(:tool_trace as jsonb), cast(:validation_errors as jsonb),
                  cast(:input_artifact_ids as jsonb), cast(:interrupt as jsonb), :status
                )
                on conflict (id) do nothing
                """),
                {
                    "id": row["id"],
                    "agent_type": row["agent_type"],
                    "agent_version": row.get("agent_version") or "v1",
                    "model_provider": row.get("model_provider"),
                    "model_name": row.get("model_name"),
                    "input_refs": json_dumps(row.get("input_refs") or []),
                    "output": json_dumps(row.get("output")),
                    "validation_status": row.get("validation_status") or "ok",
                    "retry_count": row.get("retry_count") or 0,
                    "duration_ms": row.get("duration_ms"),
                    "token_usage": json_dumps(row.get("token_usage") or {}),
                    "estimated_cost": row.get("estimated_cost"),
                    "thread_id": row.get("thread_id"),
                    "prompt_version": row.get("prompt_version"),
                    "prompt_checksum": row.get("prompt_checksum"),
                    "tool_trace": json_dumps(row.get("tool_trace") or []),
                    "validation_errors": json_dumps(row.get("validation_errors") or []),
                    "input_artifact_ids": json_dumps(row.get("input_artifact_ids") or []),
                    "interrupt": json_dumps(row.get("interrupt")),
                    "status": row.get("status") or "completed",
                },
            )

    async def list_for_thread(self, thread_id: UUID) -> list[dict[str, Any]]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "select * from agent_runs where thread_id = :thread_id order by created_at"
                    ),
                    {"thread_id": thread_id},
                )
            ).mappings()
        return [dict(row) for row in rows]


class PostgresReviewStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append(self, row: dict[str, Any]) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into forecast_reviews (
                  id, goal_id, thread_id, priced, forecast_status, critic_decision,
                  limitations_json, receipt_json, agent_run_ids_json
                ) values (
                  :id, :goal_id, :thread_id, :priced, :forecast_status, :critic_decision,
                  cast(:limitations as jsonb), cast(:receipt as jsonb), cast(:agent_run_ids as jsonb)
                ) on conflict (id) do nothing
                """),
                {
                    **row,
                    "limitations": json_dumps(row.get("limitations") or []),
                    "receipt": json_dumps(row.get("receipt") or {}),
                    "agent_run_ids": json_dumps(row.get("agent_run_ids") or {}),
                },
            )


class PostgresGithubCursorStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, user_id: UUID, login: str) -> str | None:
        async with self._engine.connect() as connection:
            value = await connection.scalar(
                text(
                    "select cursor from github_sync_cursors where user_id = :user_id and login = :login"
                ),
                {"user_id": user_id, "login": login},
            )
        return str(value) if value is not None else None

    async def put(self, user_id: UUID, login: str, cursor: str | None) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into github_sync_cursors (user_id, login, cursor, last_synced_at)
                values (:user_id, :login, :cursor, now())
                on conflict (user_id, login) do update set cursor=excluded.cursor, last_synced_at=now()
                """),
                {"user_id": user_id, "login": login, "cursor": cursor},
            )


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


__all__ = [
    "InMemoryAgentRunStore",
    "InMemoryEvidenceRepository",
    "InMemoryThreadStore",
    "InMemoryUsageStore",
    "PostgresAgentRunStore",
    "PostgresEvidenceRepository",
    "PostgresGithubCursorStore",
    "PostgresReviewStore",
    "PostgresThreadStore",
    "PostgresUsageStore",
]
