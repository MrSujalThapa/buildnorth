from personal_markets.evidence.source_policy import withhold_commit_only_solution_claims
from personal_markets.ports import EvidenceAgentProposal, EvidenceEventProposal


def _event(metric: str) -> EvidenceEventProposal:
    return EvidenceEventProposal(
        event_type="activity", domain="coding", metric=metric, numeric_value=1,
        unit="count", observed_at="2026-10-20T23:40:08Z", source_type="mcp_sync",
        observation_kind="event", summary="GitHub commit 408fa7c",
    )


def test_repeat_submission_commit_cannot_verify_a_solved_problem() -> None:
    records = [{
        "cursor_context": {"source_type": "github"},
        "tool_identity": "GITHUB_LIST_COMMITS",
        "payload": {"commit": {"message": "Add: validate-parentheses - submission-11"}},
    }]
    proposal = EvidenceAgentProposal(
        events=[_event("leetcode_problems_solved"), _event("practice_commits")]
    )
    filtered = withhold_commit_only_solution_claims(proposal, records)
    assert [event.metric for event in filtered.events] == ["practice_commits"]
    assert "do not verify accepted solutions" in filtered.conflicts[0]


def test_non_commit_evidence_is_not_withheld_by_github_commit_rule() -> None:
    proposal = EvidenceAgentProposal(events=[_event("leetcode_problems_solved")])
    records = [{
        "cursor_context": {"source_type": "notion"},
        "tool_identity": "NOTION_FETCH_ALL_BLOCK_CONTENTS",
    }]
    assert withhold_commit_only_solution_claims(proposal, records) == proposal
