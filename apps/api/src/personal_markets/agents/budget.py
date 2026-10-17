from datetime import date
from typing import Protocol

from personal_markets.agents.models import estimate_cost_usd, pool_for_model
from personal_markets.core.errors import ProviderBudgetExceededError


class UsageStore(Protocol):
    async def add(
        self,
        usage_date: date,
        pool: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> None: ...

    async def totals(self, usage_date: date) -> dict[str, dict[str, int | float]]: ...


class InMemoryUsageStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[date, str, str], dict[str, float]] = {}

    async def add(
        self,
        usage_date: date,
        pool: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> None:
        key = (usage_date, pool, model)
        current = self._rows.setdefault(
            key, {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
        )
        current["input_tokens"] += input_tokens
        current["output_tokens"] += output_tokens
        current["estimated_cost_usd"] += cost

    async def totals(self, usage_date: date) -> dict[str, dict[str, int | float]]:
        result: dict[str, dict[str, int | float]] = {}
        for (row_date, pool, _model), values in self._rows.items():
            if row_date != usage_date:
                continue
            bucket = result.setdefault(
                pool, {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
            )
            bucket["input_tokens"] += int(values["input_tokens"])
            bucket["output_tokens"] += int(values["output_tokens"])
            bucket["estimated_cost_usd"] += float(values["estimated_cost_usd"])
        return result


class TokenBudget:
    def __init__(
        self,
        store: UsageStore,
        high_volume_limit: int,
        premium_limit: int,
        max_cost_usd: float,
    ) -> None:
        self._store = store
        self._high_volume_limit = high_volume_limit
        self._premium_limit = premium_limit
        self._max_cost_usd = max_cost_usd

    async def ensure_allowed(self, model: str, projected_tokens: int = 0) -> None:
        today = date.today()
        totals = await self._store.totals(today)
        pool = pool_for_model(model)
        used = int(totals.get(pool, {}).get("input_tokens", 0)) + int(
            totals.get(pool, {}).get("output_tokens", 0)
        )
        limit = self._premium_limit if pool == "premium" else self._high_volume_limit
        if used + projected_tokens > limit:
            raise ProviderBudgetExceededError(
                f"Daily {pool} token budget would be exceeded ({used + projected_tokens} > {limit})"
            )
        cost = float(totals.get("premium", {}).get("estimated_cost_usd", 0)) + float(
            totals.get("high_volume", {}).get("estimated_cost_usd", 0)
        )
        if cost >= self._max_cost_usd:
            raise ProviderBudgetExceededError(
                f"Daily estimated OpenAI cost budget would be exceeded "
                f"({cost:.4f} >= {self._max_cost_usd})"
            )

    async def record(self, model: str, input_tokens: int, output_tokens: int) -> float:
        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        await self._store.add(
            date.today(), pool_for_model(model), model, input_tokens, output_tokens, cost
        )
        return cost
