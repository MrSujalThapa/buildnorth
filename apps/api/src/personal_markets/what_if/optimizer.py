from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from personal_markets.what_if.domain import ResourceCost, StructuredIntervention


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    hours_per_week: float
    money: float
    energy: float


@dataclass(frozen=True, slots=True)
class ActionBundle:
    actions: tuple[StructuredIntervention, ...]
    expected_effect: float
    cost: ResourceCost
    dominated: bool = False


class ActionOptimizer:
    def enumerate(
        self, actions: list[StructuredIntervention], limits: ResourceLimits
    ) -> list[ActionBundle]:
        feasible: list[ActionBundle] = []
        for size in range(1, len(actions) + 1):
            for bundle in combinations(actions, size):
                groups = [action.exclusivity_group for action in bundle if action.exclusivity_group]
                if len(groups) != len(set(groups)):
                    continue
                cost = ResourceCost(
                    hours_per_week=sum(action.cost.hours_per_week for action in bundle),
                    money=sum(action.cost.money for action in bundle),
                    energy=sum(action.cost.energy for action in bundle),
                )
                if (
                    cost.hours_per_week > limits.hours_per_week
                    or cost.money > limits.money
                    or cost.energy > limits.energy
                ):
                    continue
                effect = sum(self._effect(action) for action in bundle)
                feasible.append(ActionBundle(bundle, effect, cost))
        return sorted(
            feasible,
            key=lambda item: (-item.expected_effect, item.cost.hours_per_week, item.cost.money),
        )

    def minimum_for_target(
        self, bundles: list[ActionBundle], required_effect: float
    ) -> list[ActionBundle]:
        candidates = [item for item in bundles if item.expected_effect >= required_effect]
        return sorted(
            candidates,
            key=lambda item: (item.cost.hours_per_week, item.cost.money, item.cost.energy),
        )[:3]

    @staticmethod
    def pareto(points: list[tuple[str, float, float]]) -> dict[str, bool]:
        return {
            point_id: any(
                other_id != point_id
                and other_cost <= cost
                and other_uplift >= uplift
                and (other_cost < cost or other_uplift > uplift)
                for other_id, other_cost, other_uplift in points
            )
            for point_id, cost, uplift in points
        }

    @staticmethod
    def _effect(action: StructuredIntervention) -> float:
        if action.effect_per_unit is None:
            return 0
        full = (
            action.amount
            * action.effect_per_unit
            / (1 + action.diminishing_return * abs(action.amount))
        )
        if action.execution_probability is None:
            return full
        return full * action.execution_probability
