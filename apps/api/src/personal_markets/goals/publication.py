from __future__ import annotations

from datetime import UTC, datetime

from personal_markets.ports import CriticArtifact, WorkflowSnapshot

WithholdCategory = str


def blocks_current_forecast(snapshot: WorkflowSnapshot) -> bool:
    """A previous receipt is history while this creation is unresolved or withheld."""
    return snapshot.status in {
        "withheld", "evidence_pending", "evidence_running", "evidence_failed",
    } or (snapshot.critic is not None and snapshot.critic.decision == "withhold")

_CATEGORY_ACTIONS: dict[str, str] = {
    "missing_user_information": (
        "Add starting progress, a target, a deadline, or your current pace as evidence."
    ),
    "missing_evidence": "Connect a source or submit a recent measurement for this goal.",
    "insufficient_model": (
        "This goal does not yet match a calibrated numerical family. "
        "Add measurable current/target values so a model can apply."
    ),
    "unsupported_assumptions": (
        "Replace uncalibrated assumptions with observed evidence before odds can be published."
    ),
    "provider_failure": "Retry the workflow, or switch inference provider in Settings.",
    "critic_validation_failure": (
        "Resolve the critic issues below. "
        "PlayItOut will not invent a probability to fill the chart."
    ),
}


def classify_withhold(critic: CriticArtifact) -> WithholdCategory:
    blob = " ".join([*critic.issues, *critic.limitations, *critic.required_actions]).lower()
    if any(
        token in blob for token in ("provider", "inference", "timeout", "rate limit", "api key")
    ):
        return "provider_failure"
    if any(token in blob for token in ("assumption", "uncalibrated", "unsupported")):
        return "unsupported_assumptions"
    if any(
        token in blob
        for token in ("inapplicable", "no model", "family", "cannot price", "unpriced")
    ):
        return "insufficient_model"
    if any(token in blob for token in ("no evidence", "missing evidence", "evidence required")):
        return "missing_evidence"
    if any(
        token in blob
        for token in ("missing", "unknown", "need", "starting", "current state", "deadline")
    ):
        return "missing_user_information"
    return "critic_validation_failure"


def publication_snapshot(critic: CriticArtifact, status: str) -> dict[str, object]:
    recorded_at = datetime.now(UTC).isoformat()
    if status != "withheld":
        return {
            "status": status,
            "category": None,
            "reason": None,
            "issues": list(critic.issues),
            "limitations": list(critic.limitations),
            "required_actions": list(critic.required_actions),
            "recorded_at": recorded_at,
        }
    category = classify_withhold(critic)
    reason = critic.issues[0] if critic.issues else "The critic withheld a published probability."
    actions = list(critic.required_actions) or [_CATEGORY_ACTIONS[category]]
    return {
        "status": "withheld",
        "category": category,
        "reason": reason,
        "issues": list(critic.issues),
        "limitations": list(critic.limitations),
        "required_actions": actions,
        "recorded_at": recorded_at,
    }
