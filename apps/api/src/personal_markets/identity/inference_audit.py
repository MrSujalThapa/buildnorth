"""Privacy-safe execution metadata in the existing inference ledger."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from personal_markets.identity.budget import InMemoryBudgetStore, PostgresBudgetStore
from personal_markets.persistence.database import autocommit_connection, transaction


class InferenceAudit:
    def __init__(self, store: InMemoryBudgetStore | PostgresBudgetStore) -> None:
        self._store = store

    async def record(self, row: dict[str, Any], reservation_id: UUID | None = None) -> None:
        row.setdefault("usage_reported", True)
        if isinstance(self._store, InMemoryBudgetStore):
            if reservation_id:
                for item in self._store.ledger:
                    if item.get("reservation_id") == reservation_id:
                        item.update(row)
                        return
            self._store.ledger.append(dict(row))
            return
        async with transaction(self._store._engine) as conn:
            if reservation_id:
                await conn.execute(
                    text("""
                    update inference_ledger set billing_mode=:billing_mode,
                      credential_version=:credential_version, outcome=:outcome,
                      latency_ms=:latency_ms, execution_id=:execution_id,
                      usage_reported=:usage_reported
                    where reservation_id=:reservation_id
                """),
                    {**row, "reservation_id": reservation_id},
                )
            else:
                await conn.execute(
                    text("""
                    insert into inference_ledger
                      (user_id, clerk_user_id, agent_name, provider, model, billing_mode,
                       input_tokens, output_tokens, estimated_cost_usd, credential_version,
                       outcome, latency_ms, execution_id, usage_reported)
                    values (:user_id, :clerk_user_id, :agent_name, :provider, :model, :billing_mode,
                            :input_tokens, :output_tokens, :estimated_cost_usd, :credential_version,
                            :outcome, :latency_ms, :execution_id, :usage_reported)
                    on conflict (execution_id) where execution_id is not null do nothing
                """),
                    row,
                )

    async def byok_summary(self, owner: UUID) -> dict[str, Any]:
        if isinstance(self._store, InMemoryBudgetStore):
            rows = [
                r
                for r in self._store.ledger
                if r.get("user_id") == owner and r.get("billing_mode") == "byok"
            ]
            return {
                "calls": len(rows),
                "input_tokens": sum(int(str(r["input_tokens"])) for r in rows),
                "output_tokens": sum(int(str(r["output_tokens"])) for r in rows),
                "estimated_cost_usd": sum(float(str(r["estimated_cost_usd"])) for r in rows),
            }
        async with autocommit_connection(self._store._engine) as conn:
            row = (
                (
                    await conn.execute(
                        text("""
                select count(*) as calls, coalesce(sum(input_tokens), 0) as input_tokens,
                  coalesce(sum(output_tokens), 0) as output_tokens,
                  coalesce(sum(estimated_cost_usd), 0) as estimated_cost_usd
                from inference_ledger where user_id=:owner and billing_mode='byok'
            """),
                        {"owner": owner},
                    )
                )
                .mappings()
                .one()
            )
        return dict(row)
