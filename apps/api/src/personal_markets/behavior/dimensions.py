from __future__ import annotations

from datetime import datetime

from personal_markets.behavior.domain import (
    ActionContext,
    BehaviorDimension,
    BehaviorProfile,
    CommitmentTrial,
    DimensionProvenance,
    ExecutionEstimate,
)
from personal_markets.behavior.model import ESTIMATOR_VERSION, hierarchical_posteriors

LABELS = {
    "follow_through": "Follow-through",
    "consistency": "Consistency",
    "commitment_realism": "Commitment realism",
    "momentum": "Momentum",
    "reliability": "Reliability",
    "recovery": "Recovery after misses",
    "evidence_quality": "Evidence quality",
    "goal_relevance": "Goal relevance",
}


def _confidence(n_eff: float, minimum: float) -> tuple[bool, str]:
    if n_eff < minimum:
        return True, "insufficient"
    if n_eff < minimum * 2:
        return False, "low"
    if n_eff < minimum * 4:
        return False, "medium"
    return False, "high"


def _percent(value: float | None, limited: bool) -> int | None:
    if value is None or limited:
        return None
    return int(round(value * 100))


def build_profile(
    trials: list[CommitmentTrial],
    context: ActionContext,
    execution: ExecutionEstimate,
    *,
    as_of: datetime,
) -> BehaviorProfile:
    posts = hierarchical_posteriors(trials, context, as_of=as_of, half_life_days=execution.half_life_days)
    features = execution.features
    sources = sorted({item.source for item in trials})
    completed = sum(item.outcome for item in trials)
    window = None
    if trials:
        window = max(1.0, (as_of - min(item.observed_at for item in trials)).total_seconds() / 86400)

    follow_limited, follow_conf = _confidence(posts["action"].n_eff, 4)
    follow = BehaviorDimension(
        key="follow_through",
        label=LABELS["follow_through"],
        value=None if follow_limited else execution.action_mean,
        display_percent=_percent(execution.action_mean, follow_limited),
        limited_evidence=follow_limited,
        confidence=follow_conf,  # type: ignore[arg-type]
        provenance=DimensionProvenance(
            comparable_commitments=len(trials),
            completed=completed,
            recency_weighted_completion=execution.action_mean,
            evidence_window_days=window,
            sources=sources,
            n_eff=posts["action"].n_eff,
            formula="recency-weighted Beta-Bernoulli with hierarchical shrinkage",
            details=[
                f"{len(trials)} comparable commitments",
                f"{completed:.0f} completed",
                f"recency-weighted completion = {execution.action_mean:.3f}",
                f"half-life = {execution.half_life_days:.0f} days",
                f"sources: {', '.join(sources) or 'none'}",
                f"confidence = {follow_conf}",
            ],
        ),
    )

    consist_limited, consist_conf = _confidence(features.get("n_raw", 0.0), 6)
    burst = features.get("burstiness", 0.0)
    consistency_value = max(0.0, min(1.0, 0.5 - 0.5 * burst))
    consistency = BehaviorDimension(
        key="consistency",
        label=LABELS["consistency"],
        value=None if consist_limited else consistency_value,
        display_percent=_percent(consistency_value, consist_limited),
        limited_evidence=consist_limited,
        confidence=consist_conf,  # type: ignore[arg-type]
        provenance=DimensionProvenance(
            comparable_commitments=len(trials),
            completed=completed,
            sources=sources,
            n_eff=features.get("n_raw", 0.0),
            formula="1 - burstiness of inter-session gaps, burstiness=(σ-μ)/(σ+μ)",
            details=[f"burstiness = {burst:.3f}"],
        ),
    )

    realism_n = sum(1 for item in trials if item.planned_amount and item.realized_amount is not None)
    realism_limited, realism_conf = _confidence(float(realism_n), 4)
    realism_value = features.get("realism", 1.0)
    realism = BehaviorDimension(
        key="commitment_realism",
        label=LABELS["commitment_realism"],
        value=None if realism_limited else realism_value,
        display_percent=_percent(realism_value, realism_limited),
        limited_evidence=realism_limited,
        confidence=realism_conf,  # type: ignore[arg-type]
        provenance=DimensionProvenance(
            comparable_commitments=realism_n,
            completed=completed,
            sources=sources,
            n_eff=float(realism_n),
            formula="median(realized / planned) over comparable windows",
            details=[f"planned-vs-realized pairs = {realism_n}"],
        ),
    )

    mom_limited, mom_conf = _confidence(features.get("n_raw", 0.0), 8)
    momentum_value = 1.0 / (1.0 + pow(2.718281828, -4 * features.get("momentum", 0.0)))
    momentum = BehaviorDimension(
        key="momentum",
        label=LABELS["momentum"],
        value=None if mom_limited else momentum_value,
        display_percent=_percent(momentum_value, mom_limited),
        limited_evidence=mom_limited,
        confidence=mom_conf,  # type: ignore[arg-type]
        provenance=DimensionProvenance(
            comparable_commitments=len(trials),
            completed=completed,
            sources=sources,
            n_eff=features.get("n_raw", 0.0),
            formula="logistic map of recent-window rate minus long-run rate",
            details=[
                f"recent rate = {features.get('recent_rate', 0):.3f}",
                f"long-run rate = {features.get('longrun_rate', 0):.3f}",
            ],
        ),
    )

    rel_limited, rel_conf = _confidence(features.get("n_raw", 0.0), 8)
    reliability_value = 1.0 / (1.0 + 4.0 * features.get("variance", 0.25))
    reliability = BehaviorDimension(
        key="reliability",
        label=LABELS["reliability"],
        value=None if rel_limited else reliability_value,
        display_percent=_percent(reliability_value, rel_limited),
        limited_evidence=rel_limited,
        confidence=rel_conf,  # type: ignore[arg-type]
        provenance=DimensionProvenance(
            comparable_commitments=len(trials),
            completed=completed,
            sources=sources,
            n_eff=features.get("n_raw", 0.0),
            formula="1 / (1 + 4 Var[outcome])",
            details=[f"outcome variance = {features.get('variance', 0):.3f}"],
        ),
    )

    recoveries = sum(1 for item in trials if item.outcome < 0.5)
    rec_limited, rec_conf = _confidence(float(recoveries), 3)
    recovery_value = features.get("recovery", 0.5)
    recovery = BehaviorDimension(
        key="recovery",
        label=LABELS["recovery"],
        value=None if rec_limited else recovery_value,
        display_percent=_percent(recovery_value, rec_limited),
        limited_evidence=rec_limited,
        confidence=rec_conf,  # type: ignore[arg-type]
        provenance=DimensionProvenance(
            comparable_commitments=recoveries,
            completed=completed,
            sources=sources,
            n_eff=float(recoveries),
            formula="P(complete within 7 days | just missed)",
            details=[f"miss episodes = {recoveries}"],
        ),
    )

    quality_value = execution.n_eff / (execution.n_eff + 8.0)
    quality_limited = execution.confidence == "insufficient"
    quality = BehaviorDimension(
        key="evidence_quality",
        label=LABELS["evidence_quality"],
        value=None if quality_limited else quality_value,
        display_percent=_percent(quality_value, quality_limited),
        limited_evidence=quality_limited,
        confidence=execution.confidence,
        provenance=DimensionProvenance(
            comparable_commitments=len(trials),
            completed=completed,
            evidence_window_days=window,
            sources=sources,
            n_eff=execution.n_eff,
            formula="n_eff / (n_eff + 8), gated by source mix",
            details=[f"n_eff = {execution.n_eff:.2f}", f"sources = {', '.join(sources) or 'none'}"],
        ),
    )

    relv_limited, relv_conf = _confidence(features.get("n_raw", 0.0), 4)
    relevance_value = features.get("relevance", 0.0)
    relevance = BehaviorDimension(
        key="goal_relevance",
        label=LABELS["goal_relevance"],
        value=None if relv_limited else relevance_value,
        display_percent=_percent(relevance_value, relv_limited),
        limited_evidence=relv_limited,
        confidence=relv_conf,  # type: ignore[arg-type]
        provenance=DimensionProvenance(
            comparable_commitments=len(trials),
            completed=completed,
            sources=sources,
            n_eff=features.get("n_raw", 0.0),
            formula="mean token/n-gram overlap between past actions and the current intervention",
            details=[f"mean overlap = {relevance_value:.3f}"],
        ),
    )

    return BehaviorProfile(
        estimator_version=ESTIMATOR_VERSION,
        as_of=as_of,
        execution=execution,
        dimensions=[follow, consistency, realism, momentum, reliability, recovery, quality, relevance],
        evidence_sufficiency=execution.confidence,
        n_raw=execution.n_raw,
        n_eff=execution.n_eff,
    )
