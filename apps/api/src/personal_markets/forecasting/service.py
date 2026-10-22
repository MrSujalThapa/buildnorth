from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from personal_markets.agents.critic import deterministic_critic
from personal_markets.forecasting.engine import NumericInputs, family_receipt_metadata, price_family
from personal_markets.forecasting.registry import (
    ForecastModelRegistry,
    OuladCompletionApplicabilityPolicy,
)
from personal_markets.forecasting.repository import (
    BaselineForecastRepository,
    InMemoryBaselineForecastRepository,
    PublishedBaseline,
    history_point,
)
from personal_markets.goals.domain import GoalContract
from personal_markets.ports import (
    CriticArtifact,
    EvidenceEventProposal,
    GoalArchitectProposal,
    PricingResult,
)


class BaselineForecastService:
    """Single application boundary for baseline pricing and publication.

    Agents supply semantic contracts/evidence and the Critic may veto. Neither can
    provide or replace a numerical probability. What If does not depend on this service.
    """

    def __init__(
        self, repository: BaselineForecastRepository, registry: ForecastModelRegistry | None = None
    ) -> None:
        self._repository = repository
        self._registry = registry or ForecastModelRegistry()

    def compute(
        self,
        goal: GoalContract,
        proposal: GoalArchitectProposal,
        evidence_ids: list[str],
        agent_run_ids: dict[str, str],
        research_source_ids: list[str],
        inputs: NumericInputs | None = None,
    ) -> PricingResult:
        _ = proposal  # semantic only; never a probability source
        numeric = inputs or NumericInputs()
        from personal_markets.forecasting.composition import price_composition

        composed = price_composition(goal, numeric)
        if composed is not None:
            family_price = composed
            model = None
        else:
            model = self._registry.select_for(goal, numeric)
            family_price = price_family(model, goal, numeric)
        oulad = _oulad_limitations(goal)
        limitations = list(dict.fromkeys([*family_price.limitations, *oulad]))
        priced = family_price.priced and family_price.raw_probability is not None
        from personal_markets.forecasting.spec import compile_existing_spec

        spec = compile_existing_spec(goal, inputs)
        if spec.research_required:
            priced = False
            spec.status = "INSUFFICIENT_EVIDENCE"
            limitations.append(
                "Required external parameters remain unapproved; research candidates "
                "cannot be used as numerical assumptions."
            )
        else:
            spec.status = "READY" if priced else "NEEDS_INPUT"
        if model is None:
            spec_payload = goal.model_requirements.get("forecast_spec") or {}
            metadata = {
                "family": spec_payload.get("family") or "composed",
                "version": spec_payload.get("model_version")
                or spec_payload.get("compiler_version")
                or "composed_v1",
                "simulation_method": (family_price.transforms or {}).get("method")
                or "composed_primitives",
                "maximum_status": "EXPLORATORY",
            }
        else:
            metadata = family_receipt_metadata(model)
        receipt: dict[str, Any] = {
            "receipt_version": 1,
            "forecast_kind": "baseline",
            "priced": priced,
            "goal_id": str(goal.goal_id),
            "goal_contract_version": goal.version,
            "forecast_spec": spec.model_dump(mode="json"),
            "goal_metric": goal.success_definition.get("metric"),
            "goal_type": goal.goal_type.value,
            "forecast_status": family_price.forecast_status,
            "model": {
                "family": metadata["family"],
                "version": metadata["version"],
                "simulation_method": metadata["simulation_method"],
                "maximum_status": metadata["maximum_status"],
            },
            "model_registry_family": metadata["family"],
            "model_registry_version": metadata["version"],
            "normalized_evidence_ids": evidence_ids,
            "evidence_watermark": evidence_ids[-1] if evidence_ids else "none",
            "state_snapshot_id": "unavailable",
            "state_snapshot_version": 0,
            "research_source_ids": research_source_ids,
            "reference_versions": _reference_lineage(research_source_ids, metadata["family"]),
            "numeric_inputs": {
                "state": numeric.state,
                "assumptions": numeric.assumptions,
                "assumption_sources": numeric.assumption_sources,
            },
            "state_hash": hashlib.sha256(
                json.dumps(numeric.state, sort_keys=True, default=str).encode()
            ).hexdigest(),
            "agent_run_ids": agent_run_ids,
            "assumptions": family_price.used_assumptions,
            "feature_transforms": family_price.transforms,
            "calibration": {"method": None, "applied": False, "reason": "no valid calibrator"},
            "raw_probability": family_price.raw_probability if priced else None,
            "calibrated_probability": None,
            "final_probability": None,
            "critic_decision": None,
            "publication": "priced" if priced else "NOT_PRICED",
            "limitations": limitations,
            "created_at": datetime.now(UTC).isoformat(),
            "run_id": str(uuid4()),
            "llm_used_for_probability": False,
            "parameter_lineage": spec.parameter_provenance or family_price.used_assumptions,
            "compiler_version": spec.compiler_version,
        }
        return PricingResult(
            priced=priced,
            forecast_status=family_price.forecast_status,
            raw_probability=family_price.raw_probability if priced else None,
            calibrated_probability=None,
            model_version=f"{metadata['family']}@{metadata['version']}",
            limitations=limitations,
            receipt=receipt,
        )

    def deterministic_issues(
        self, evidence: list[EvidenceEventProposal], evidence_ids: list[str], pricing: PricingResult
    ) -> list[str]:
        return deterministic_critic(evidence, evidence_ids, pricing)

    async def publish(
        self,
        goal: GoalContract,
        pricing: PricingResult,
        critic: CriticArtifact,
        *,
        published_at: datetime | None = None,
    ) -> str:
        if critic.decision == "withhold":
            return "withheld"
        if not pricing.priced or pricing.raw_probability is None:
            return "limited"
        final_probability = (
            pricing.calibrated_probability
            if pricing.calibrated_probability is not None
            else pricing.raw_probability
        )
        receipt = dict(pricing.receipt)
        receipt.update(
            {
                "raw_probability": pricing.raw_probability,
                "calibrated_probability": pricing.calibrated_probability,
                "final_probability": final_probability,
                "critic_decision": critic.decision,
            }
        )
        published = pricing.model_copy(update={"receipt": receipt})
        point = history_point(goal, published)
        if point is not None:
            history = await self.published_history(goal.goal_id)
            if any(
                item.material_hash == point.material_hash
                or item.evidence_watermark == point.evidence_watermark
                for item in history
            ):
                return "unchanged"
        if published_at is None:
            await self._repository.publish(goal, published, critic)
        else:
            await self._repository.publish(goal, published, critic, published_at=published_at)
        return "limited" if critic.decision == "publish_with_limitations" else "completed"

    def history(self, goal_id: UUID) -> list[PublishedBaseline]:
        return self._repository.history(goal_id)

    async def published_history(self, goal_id: UUID) -> list[PublishedBaseline]:
        loader = getattr(self._repository, "load_history", None)
        if loader is not None:
            loaded = loader(goal_id)
            if hasattr(loaded, "__await__"):
                return await loaded
            return list(loaded)
        return self._repository.history(goal_id)


def _oulad_limitations(goal: GoalContract) -> list[str]:
    """Only report OULAD applicability for goals that actually target its metric.

    Evaluating the policy unconditionally leaked education-reference reasons such as
    "unsupported checkpoint day" onto unrelated finance and running receipts.
    """
    policy = OuladCompletionApplicabilityPolicy()
    metric = str(goal.success_definition.get("metric") or "")
    if metric != policy.supported_metric:
        return []
    target = goal.success_definition.get("target")
    try:
        checkpoint = int(target) if target is not None else -1
    except (TypeError, ValueError):
        checkpoint = -1
    decision = policy.evaluate(goal.goal_type.value, metric, checkpoint)
    limitations = list(decision.reasons)
    if decision.applicable:
        limitations.append(
            "OULAD path is applicable only with frozen checkpoint features, which this goal lacks."
        )
    return limitations


def _reference_lineage(source_ids: list[str], family: str) -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[5] / "data" / "reference"
    primary = {
        "deadline_event_hazard": "hiring_funnel_rates.json",
        "continuous_target_transition": "net_worth_assumptions.json",
        "threshold_trend": "running_performance_assumptions.json",
        "multi_outcome_transition": "startup_outcome_priors.json",
    }.get(family)
    result = []
    for source in dict.fromkeys(source_ids):
        if not source:
            continue
        filename = source.removeprefix("frozen://")
        local = Path(filename).name == filename and (root / filename).is_file()
        result.append(
            {
                "id": source,
                "source": "REFERENCE_DATA" if local else "RESEARCH_CANDIDATE",
                "checksum_sha256": hashlib.sha256((root / filename).read_bytes()).hexdigest()
                if local
                else None,
                "used_by_engine": local and filename == primary,
            }
        )
    return result


# Re-export for callers that imported the in-memory repository from this module.
__all__ = [
    "BaselineForecastService",
    "InMemoryBaselineForecastRepository",
    "NumericInputs",
]
