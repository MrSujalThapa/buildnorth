from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.agents.models import estimate_cost_usd
from personal_markets.core.config import Settings
from personal_markets.core.errors import (
    ForbiddenError,
    ProviderBudgetExceededError,
    ProviderNotConfiguredError,
)
from personal_markets.identity.domain import HostedUsage, Principal
from personal_markets.persistence.database import transaction


@dataclass(frozen=True, slots=True)
class Reservation:
    reservation_id: UUID
    user_id: UUID
    amount_usd: float
    tokens: int


class InferenceBudgetService:
    def __init__(self, store: BudgetStore, settings: Settings) -> None:
        self._store = store
        self._settings = settings

    async def usage_for(self, principal: Principal) -> HostedUsage:
        kill = not await self._store.hosted_enabled(self._settings.hosted_inference_enabled)
        counters = await self._store.counters(str(principal.user_id))
        global_counters = await self._store.counters("global")
        remaining_usd = max(
            0.0, principal.hosted_quota_usd - counters.reserved_usd - counters.spent_usd
        )
        remaining_tokens = max(
            0, principal.hosted_quota_tokens - counters.reserved_tokens - counters.spent_tokens
        )
        global_remaining = max(
            0.0,
            self._settings.hosted_global_quota_usd
            - global_counters.reserved_usd
            - global_counters.spent_usd,
        )
        return HostedUsage(
            enabled=principal.hosted_enabled and not kill,
            quota_usd=principal.hosted_quota_usd,
            quota_tokens=principal.hosted_quota_tokens,
            reserved_usd=counters.reserved_usd,
            spent_usd=counters.spent_usd,
            reserved_tokens=counters.reserved_tokens,
            spent_tokens=counters.spent_tokens,
            remaining_usd=remaining_usd,
            remaining_tokens=remaining_tokens,
            global_remaining_usd=global_remaining,
            kill_switch=kill,
        )

    async def set_kill_switch(self, enabled: bool) -> None:
        await self._store.set_hosted_enabled(enabled)

    async def reserve(
        self,
        principal: Principal,
        *,
        agent_name: str,
        provider: str,
        model: str,
        max_output_tokens: int,
        client_ip: str | None,
    ) -> Reservation:
        try:
            enabled = await self._store.hosted_enabled(self._settings.hosted_inference_enabled)
        except Exception as error:
            raise ProviderNotConfiguredError(
                "hosted inference status could not be verified"
            ) from error
        if not enabled:
            raise ProviderNotConfiguredError("hosted inference is disabled")
        if not principal.hosted_enabled:
            raise ForbiddenError("this account has no hosted inference entitlement")
        await self._enforce_rate_limits(principal.user_id, client_ip)
        max_tokens = min(int(max_output_tokens), self._settings.openai_max_output_tokens)
        projected_tokens = max(256, max_tokens + 512)
        projected_usd = estimate_cost_usd(model, 512, max_tokens)
        try:
            reserved = await self._store.reserve(
                user_id=principal.user_id,
                clerk_user_id=principal.clerk_user_id,
                agent_name=agent_name,
                provider=provider,
                model=model,
                amount_usd=projected_usd,
                tokens=projected_tokens,
                user_cap_usd=principal.hosted_quota_usd,
                user_cap_tokens=principal.hosted_quota_tokens,
                global_cap_usd=self._settings.hosted_global_quota_usd,
                global_cap_tokens=self._settings.hosted_global_quota_tokens,
            )
        except Exception as error:
            raise ProviderBudgetExceededError(
                "hosted inference budget could not be verified (fail-closed)"
            ) from error
        if reserved is None:
            raise ProviderBudgetExceededError(
                "hosted inference budget would be exceeded (application-enforced estimate)"
            )
        return reserved

    async def settle(
        self,
        reservation: Reservation,
        *,
        principal: Principal,
        agent_name: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        await self._store.settle(
            reservation,
            clerk_user_id=principal.clerk_user_id,
            agent_name=agent_name,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        )
        return cost

    async def release(self, reservation: Reservation) -> None:
        await self._store.release(reservation)

    async def _enforce_rate_limits(self, user_id: UUID, client_ip: str | None) -> None:
        window = datetime.now(UTC) - timedelta(minutes=1)
        user_count = await self._store.rate_count(user_id=user_id, ip_hash=None, since=window)
        if user_count >= self._settings.hosted_user_rpm:
            raise ProviderBudgetExceededError("per-user hosted inference rate limit exceeded")
        ip_hash = _ip_hash(client_ip)
        if ip_hash:
            ip_count = await self._store.rate_count(user_id=None, ip_hash=ip_hash, since=window)
            if ip_count >= self._settings.hosted_ip_rpm:
                raise ProviderBudgetExceededError("per-ip hosted inference rate limit exceeded")
        await self._store.record_rate(user_id, ip_hash)


@dataclass
class _Counters:
    reserved_usd: float = 0.0
    spent_usd: float = 0.0
    reserved_tokens: int = 0
    spent_tokens: int = 0


class BudgetStore:
    async def hosted_enabled(self, default: bool) -> bool: ...
    async def set_hosted_enabled(self, enabled: bool) -> None: ...
    async def counters(self, scope: str) -> _Counters: ...
    async def reserve(self, **kwargs: object) -> Reservation | None: ...
    async def settle(self, reservation: Reservation, **kwargs: object) -> None: ...
    async def release(self, reservation: Reservation) -> None: ...
    async def rate_count(self, user_id: UUID | None, ip_hash: str | None, since: datetime) -> int: ...
    async def record_rate(self, user_id: UUID, ip_hash: str | None) -> None: ...


class InMemoryBudgetStore(BudgetStore):
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._enabled: bool | None = None
        self._counters: dict[str, _Counters] = {"global": _Counters()}
        self._reservations: dict[UUID, Reservation] = {}
        self._rates: list[tuple[datetime, UUID | None, str | None]] = []
        self.ledger: list[dict[str, object]] = []

    async def hosted_enabled(self, default: bool) -> bool:
        return default if self._enabled is None else self._enabled

    async def set_hosted_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    async def counters(self, scope: str) -> _Counters:
        return self._counters.setdefault(scope, _Counters())

    async def reserve(
        self,
        *,
        user_id: UUID,
        clerk_user_id: str,
        agent_name: str,
        provider: str,
        model: str,
        amount_usd: float,
        tokens: int,
        user_cap_usd: float,
        user_cap_tokens: int,
        global_cap_usd: float,
        global_cap_tokens: int,
    ) -> Reservation | None:
        del clerk_user_id, agent_name, provider, model
        async with self._lock:
            user = self._counters.setdefault(str(user_id), _Counters())
            globe = self._counters.setdefault("global", _Counters())
            if (
                user.reserved_usd + user.spent_usd + amount_usd > user_cap_usd
                or user.reserved_tokens + user.spent_tokens + tokens > user_cap_tokens
                or globe.reserved_usd + globe.spent_usd + amount_usd > global_cap_usd
                or globe.reserved_tokens + globe.spent_tokens + tokens > global_cap_tokens
            ):
                return None
            user.reserved_usd += amount_usd
            user.reserved_tokens += tokens
            globe.reserved_usd += amount_usd
            globe.reserved_tokens += tokens
            reservation = Reservation(uuid4(), user_id, amount_usd, tokens)
            self._reservations[reservation.reservation_id] = reservation
            return reservation

    async def settle(
        self,
        reservation: Reservation,
        *,
        clerk_user_id: str,
        agent_name: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> None:
        async with self._lock:
            current = self._reservations.pop(reservation.reservation_id, None)
            if current is None:
                return
            user = self._counters.setdefault(str(reservation.user_id), _Counters())
            globe = self._counters.setdefault("global", _Counters())
            user.reserved_usd = max(0.0, user.reserved_usd - reservation.amount_usd)
            user.reserved_tokens = max(0, user.reserved_tokens - reservation.tokens)
            globe.reserved_usd = max(0.0, globe.reserved_usd - reservation.amount_usd)
            globe.reserved_tokens = max(0, globe.reserved_tokens - reservation.tokens)
            user.spent_usd += cost
            user.spent_tokens += input_tokens + output_tokens
            globe.spent_usd += cost
            globe.spent_tokens += input_tokens + output_tokens
            self.ledger.append(
                {
                    "user_id": reservation.user_id,
                    "clerk_user_id": clerk_user_id,
                    "agent_name": agent_name,
                    "provider": provider,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "estimated_cost_usd": cost,
                }
            )

    async def release(self, reservation: Reservation) -> None:
        async with self._lock:
            current = self._reservations.pop(reservation.reservation_id, None)
            if current is None:
                return
            user = self._counters.setdefault(str(reservation.user_id), _Counters())
            globe = self._counters.setdefault("global", _Counters())
            user.reserved_usd = max(0.0, user.reserved_usd - reservation.amount_usd)
            user.reserved_tokens = max(0, user.reserved_tokens - reservation.tokens)
            globe.reserved_usd = max(0.0, globe.reserved_usd - reservation.amount_usd)
            globe.reserved_tokens = max(0, globe.reserved_tokens - reservation.tokens)

    async def rate_count(self, user_id: UUID | None, ip_hash: str | None, since: datetime) -> int:
        return sum(
            1
            for created, stored_user, stored_ip in self._rates
            if created >= since
            and (user_id is None or stored_user == user_id)
            and (ip_hash is None or stored_ip == ip_hash)
        )

    async def record_rate(self, user_id: UUID, ip_hash: str | None) -> None:
        self._rates.append((datetime.now(UTC), user_id, ip_hash))


class PostgresBudgetStore(BudgetStore):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def hosted_enabled(self, default: bool) -> bool:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("select value_json from platform_controls where key = 'hosted_inference_enabled'")
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return default
        value = row["value_json"]
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"true", "1", "yes"}

    async def set_hosted_enabled(self, enabled: bool) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into platform_controls (key, value_json)
                values ('hosted_inference_enabled', cast(:value as jsonb))
                on conflict (key) do update set value_json = excluded.value_json
                """),
                {"value": "true" if enabled else "false"},
            )

    async def counters(self, scope: str) -> _Counters:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into hosted_budget_counters (scope)
                values (:scope)
                on conflict (scope) do nothing
                """),
                {"scope": scope},
            )
            row = (
                (
                    await connection.execute(
                        text("select * from hosted_budget_counters where scope = :scope"),
                        {"scope": scope},
                    )
                )
                .mappings()
                .one()
            )
        return _Counters(
            reserved_usd=float(row["reserved_usd"]),
            spent_usd=float(row["spent_usd"]),
            reserved_tokens=int(row["reserved_tokens"]),
            spent_tokens=int(row["spent_tokens"]),
        )

    async def reserve(
        self,
        *,
        user_id: UUID,
        clerk_user_id: str,
        agent_name: str,
        provider: str,
        model: str,
        amount_usd: float,
        tokens: int,
        user_cap_usd: float,
        user_cap_tokens: int,
        global_cap_usd: float,
        global_cap_tokens: int,
    ) -> Reservation | None:
        reservation_id = uuid4()
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into hosted_budget_counters (scope)
                values ('global')
                on conflict (scope) do nothing
                """),
            )
            await connection.execute(
                text("""
                insert into hosted_budget_counters (scope)
                values (:scope)
                on conflict (scope) do nothing
                """),
                {"scope": str(user_id)},
            )
            user_row = (
                await connection.execute(
                    text("""
                    update hosted_budget_counters
                    set reserved_usd = reserved_usd + :amount,
                        reserved_tokens = reserved_tokens + :tokens
                    where scope = :scope
                      and reserved_usd + spent_usd + :amount <= :cap_usd
                      and reserved_tokens + spent_tokens + :tokens <= :cap_tokens
                    returning scope
                    """),
                    {
                        "scope": str(user_id),
                        "amount": amount_usd,
                        "tokens": tokens,
                        "cap_usd": user_cap_usd,
                        "cap_tokens": user_cap_tokens,
                    },
                )
            ).first()
            if user_row is None:
                return None
            global_row = (
                await connection.execute(
                    text("""
                    update hosted_budget_counters
                    set reserved_usd = reserved_usd + :amount,
                        reserved_tokens = reserved_tokens + :tokens
                    where scope = 'global'
                      and reserved_usd + spent_usd + :amount <= :cap_usd
                      and reserved_tokens + spent_tokens + :tokens <= :cap_tokens
                    returning scope
                    """),
                    {
                        "amount": amount_usd,
                        "tokens": tokens,
                        "cap_usd": global_cap_usd,
                        "cap_tokens": global_cap_tokens,
                    },
                )
            ).first()
            if global_row is None:
                await connection.execute(
                    text("""
                    update hosted_budget_counters
                    set reserved_usd = reserved_usd - :amount,
                        reserved_tokens = reserved_tokens - :tokens
                    where scope = :scope
                    """),
                    {"scope": str(user_id), "amount": amount_usd, "tokens": tokens},
                )
                return None
            await connection.execute(
                text("""
                insert into inference_reservations (
                  id, user_id, clerk_user_id, agent_name, provider, model,
                  reserved_usd, reserved_tokens, status
                ) values (
                  :id, :user_id, :clerk_user_id, :agent_name, :provider, :model,
                  :reserved_usd, :reserved_tokens, 'reserved'
                )
                """),
                {
                    "id": reservation_id,
                    "user_id": user_id,
                    "clerk_user_id": clerk_user_id,
                    "agent_name": agent_name,
                    "provider": provider,
                    "model": model,
                    "reserved_usd": amount_usd,
                    "reserved_tokens": tokens,
                },
            )
        return Reservation(reservation_id, user_id, amount_usd, tokens)

    async def settle(
        self,
        reservation: Reservation,
        *,
        clerk_user_id: str,
        agent_name: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> None:
        async with transaction(self._engine) as connection:
            row = (
                await connection.execute(
                    text("""
                    update inference_reservations
                    set status = 'settled', settled_at = now()
                    where id = :id and status = 'reserved'
                    returning id
                    """),
                    {"id": reservation.reservation_id},
                )
            ).first()
            if row is None:
                return
            await connection.execute(
                text("""
                update hosted_budget_counters
                set reserved_usd = greatest(reserved_usd - :amount, 0),
                    reserved_tokens = greatest(reserved_tokens - :tokens, 0),
                    spent_usd = spent_usd + :cost,
                    spent_tokens = spent_tokens + :used
                where scope = :scope
                """),
                {
                    "amount": reservation.amount_usd,
                    "tokens": reservation.tokens,
                    "cost": cost,
                    "used": input_tokens + output_tokens,
                    "scope": str(reservation.user_id),
                },
            )
            await connection.execute(
                text("""
                update hosted_budget_counters
                set reserved_usd = greatest(reserved_usd - :amount, 0),
                    reserved_tokens = greatest(reserved_tokens - :tokens, 0),
                    spent_usd = spent_usd + :cost,
                    spent_tokens = spent_tokens + :used
                where scope = 'global'
                """),
                {
                    "amount": reservation.amount_usd,
                    "tokens": reservation.tokens,
                    "cost": cost,
                    "used": input_tokens + output_tokens,
                },
            )
            await connection.execute(
                text("""
                insert into inference_ledger (
                  user_id, clerk_user_id, reservation_id, agent_name, provider, model,
                  input_tokens, output_tokens, estimated_cost_usd
                ) values (
                  :user_id, :clerk_user_id, :reservation_id, :agent_name, :provider, :model,
                  :input_tokens, :output_tokens, :cost
                )
                """),
                {
                    "user_id": reservation.user_id,
                    "clerk_user_id": clerk_user_id,
                    "reservation_id": reservation.reservation_id,
                    "agent_name": agent_name,
                    "provider": provider,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost": cost,
                },
            )

    async def release(self, reservation: Reservation) -> None:
        async with transaction(self._engine) as connection:
            row = (
                await connection.execute(
                    text("""
                    update inference_reservations
                    set status = 'released', settled_at = now()
                    where id = :id and status = 'reserved'
                    returning id
                    """),
                    {"id": reservation.reservation_id},
                )
            ).first()
            if row is None:
                return
            await connection.execute(
                text("""
                update hosted_budget_counters
                set reserved_usd = greatest(reserved_usd - :amount, 0),
                    reserved_tokens = greatest(reserved_tokens - :tokens, 0)
                where scope = :scope
                """),
                {
                    "amount": reservation.amount_usd,
                    "tokens": reservation.tokens,
                    "scope": str(reservation.user_id),
                },
            )
            await connection.execute(
                text("""
                update hosted_budget_counters
                set reserved_usd = greatest(reserved_usd - :amount, 0),
                    reserved_tokens = greatest(reserved_tokens - :tokens, 0)
                where scope = 'global'
                """),
                {"amount": reservation.amount_usd, "tokens": reservation.tokens},
            )

    async def rate_count(self, user_id: UUID | None, ip_hash: str | None, since: datetime) -> int:
        async with self._engine.connect() as connection:
            if user_id is not None:
                value = await connection.scalar(
                    text(
                        "select count(*) from inference_rate_events where user_id = :user_id and created_at >= :since"
                    ),
                    {"user_id": user_id, "since": since},
                )
            else:
                value = await connection.scalar(
                    text(
                        "select count(*) from inference_rate_events where ip_hash = :ip_hash and created_at >= :since"
                    ),
                    {"ip_hash": ip_hash, "since": since},
                )
        return int(value or 0)

    async def record_rate(self, user_id: UUID, ip_hash: str | None) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text(
                    "insert into inference_rate_events (user_id, ip_hash) values (:user_id, :ip_hash)"
                ),
                {"user_id": user_id, "ip_hash": ip_hash},
            )


def _ip_hash(client_ip: str | None) -> str | None:
    if not client_ip:
        return None
    return hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
