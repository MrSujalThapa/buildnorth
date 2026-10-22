"""Conservative provider-evidence limits applied after structured interpretation."""

from __future__ import annotations

from typing import Any

from personal_markets.ports import EvidenceAgentProposal


def withhold_commit_only_solution_claims(
    proposal: EvidenceAgentProposal, records: list[dict[str, Any]]
) -> EvidenceAgentProposal:
    """A commit or submission file proves activity, not an accepted solution."""
    if not records or any(
        (row.get("cursor_context") or {}).get("source_type") != "github"
        or "COMMITS" not in str(row.get("tool_identity") or "").upper()
        for row in records
    ):
        return proposal
    withheld = []
    retained = []
    for event in proposal.events:
        metric = event.metric.lower().replace("-", "_")
        claims_solution = (
            "solved" in metric
            and any(term in metric for term in ("problem", "leetcode", "challenge"))
        ) or metric in {"leetcode_completed", "problems_completed", "accepted_submissions"}
        if event.source_type == "mcp_sync" and claims_solution:
            withheld.append(event)
        else:
            retained.append(event)
    if not withheld:
        return proposal
    return proposal.model_copy(update={
        "events": retained,
        "conflicts": [
            *proposal.conflicts,
            "GitHub commits show practice activity but do not verify accepted solutions."
        ],
    })
