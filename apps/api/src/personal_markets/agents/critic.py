from datetime import UTC, datetime
from uuid import UUID

from personal_markets.ports import CriticArtifact, EvidenceEventProposal, PricingResult


def deterministic_critic(
    evidence: list[EvidenceEventProposal],
    evidence_ids: list[str],
    pricing: PricingResult,
    now: datetime | None = None,
) -> list[str]:
    issues: list[str] = []
    clock = now or datetime.now(UTC)
    if len(evidence_ids) != len(set(evidence_ids)):
        issues.append("Duplicated evidence IDs in the draft receipt.")
    fingerprints = [
        f"{item.event_type}|{item.metric}|{item.numeric_value}|{item.categorical_value}|{item.observed_at}"
        for item in evidence
    ]
    if len(fingerprints) != len(set(fingerprints)):
        issues.append("Duplicated evidence fingerprints.")
    for item in evidence:
        observed = _parse(item.observed_at)
        if observed and observed > clock:
            issues.append("Future leakage: evidence observed_at is after now.")
        if not item.summary:
            issues.append("Incomplete provenance: evidence summary is empty.")
    if pricing.priced and pricing.raw_probability is None:
        issues.append("Priced forecast is missing a numerical probability.")
    if (
        pricing.priced
        and pricing.raw_probability is not None
        and not 0 <= pricing.raw_probability <= 1
    ):
        issues.append("Numerical probability is outside [0, 1].")
    if pricing.forecast_status == "CALIBRATED" and not pricing.priced:
        issues.append("Calibration mismatch: status is CALIBRATED but no model priced the goal.")
    if (
        "course_completion" in str(pricing.receipt.get("model", {}))
        and pricing.forecast_status == "CALIBRATED"
    ):
        metric = str(pricing.receipt.get("goal_metric") or "")
        if metric and metric != "course_completion":
            issues.append("Model/domain mismatch versus OULAD completion calibration.")
    provenance_markers = [
        pricing.receipt.get("coefficient_provenance"),
        pricing.receipt.get("effect_provenance"),
        pricing.receipt.get("provenance"),
    ]
    if any(marker == "LLM_GENERATED_COEFFICIENT" for marker in provenance_markers):
        issues.append("Unsupported coefficient provenance: LLM_GENERATED_COEFFICIENT.")
    return issues


def merge_critic_decision(
    deterministic_issues: list[str], llm: CriticArtifact, priced: bool
) -> CriticArtifact:
    issues = list(dict.fromkeys([*deterministic_issues, *llm.issues]))
    limitations = list(dict.fromkeys(llm.limitations))
    required_actions = list(dict.fromkeys(llm.required_actions))
    severe = any(
        marker in issue.lower()
        for issue in issues
        for marker in (
            "future leakage",
            "duplicate",
            "missing a numerical",
            "outside [0, 1]",
            "mismatch",
            "unsupported coefficient",
        )
    )
    decision = llm.decision
    if severe:
        decision = "withhold"
    elif not priced and decision == "publish":
        decision = "publish_with_limitations"
        limitations.append("No calibrated model applies; probability withheld.")
    rank = {"withhold": 2, "publish_with_limitations": 1, "publish": 0}
    if rank[decision] < rank[llm.decision]:
        decision = llm.decision
    return CriticArtifact(
        decision=decision, issues=issues, limitations=limitations, required_actions=required_actions
    )


def deterministic_critic_decision(
    issues: list[str], pricing: PricingResult
) -> CriticArtifact | None:
    severe = any(
        marker in issue.lower()
        for issue in issues
        for marker in (
            "future leakage",
            "duplicate",
            "missing a numerical",
            "outside [0, 1]",
            "mismatch",
            "unsupported coefficient",
        )
    )
    if severe:
        return CriticArtifact(
            decision="withhold",
            issues=issues,
            limitations=pricing.limitations,
            required_actions=["Resolve deterministic validation failures before publication."],
        )
    if not pricing.priced and pricing.raw_probability is None:
        return CriticArtifact(
            decision="withhold",
            issues=issues,
            limitations=list(
                dict.fromkeys(
                    [*pricing.limitations, "No applicable numerical model produced a probability."]
                )
            ),
            required_actions=["Add a valid model, reference basis, or explicit assumption set."],
        )
    return None


def _parse(value: str) -> datetime | None:
    if not value or value.lower() in {"unknown", "unspecified"}:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def goal_id_from_state(value: str | None) -> UUID | None:
    if not value:
        return None
    return UUID(value)
