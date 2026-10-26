from datetime import UTC, datetime, timedelta

from personal_markets.agents.model_planner import infer_primitive_kind, refine_architect_proposal
from personal_markets.evidence.metrics import clip_metric_name, observation_kind
from personal_markets.forecasting.hiring import aggregate_funnel_from_evidence
from personal_markets.ports import (
    EvidenceAgentProposal,
    EvidenceEventProposal,
    GoalArchitectProposal,
)
from personal_markets.remote_mcp.policy import ObservationPolicy, informational_policy
from personal_markets.remote_mcp.tools import RemoteMcpTools, candidates_with_policy


def _fde_proposal(**overrides: object) -> GoalArchitectProposal:
    payload: dict[str, object] = {
        "ready_to_commit": True,
        "title": "Land a forward-deployed engineer offer after applying and interviewing",
        "goal_type": "deadline_event",
        "success_metric": "signed_offer",
        "success_operator": "==",
        "success_target": "offer_received",
        "deadline": (datetime.now(UTC) + timedelta(days=180)).date().isoformat(),
        "state_dimensions": ["applications_submitted", "technical_interview", "signed_offer"],
        "model_family_compatibility": "composed_dependency_dag",
        "primitive_kind": "dependency_dag",
    }
    payload.update(overrides)
    return GoalArchitectProposal.model_validate(payload)


def _event(metric: str, value: float, unit: str = "count") -> EvidenceEventProposal:
    return EvidenceEventProposal.model_validate(
        {
            "event_type": "observation",
            "domain": "user_state",
            "metric": metric,
            "numeric_value": value,
            "unit": unit,
            "observed_at": datetime.now(UTC).isoformat(),
            "source_type": "manual",
            "summary": metric,
            "observation_kind": "increment",
        }
    )


def _evidence(metric: str, value: float, summary: str, unit: str = "count"):
    from uuid import uuid4

    from personal_markets.evidence.domain import NormalizedEvidence, Provenance

    return NormalizedEvidence(
        evidence_id=uuid4(),
        event_type="observation",
        domain="user_state",
        metric=metric,
        numeric_value=value,
        unit=unit,
        observed_at=datetime.now(UTC),
        source_quality="user_entered",
        provenance=Provenance(
            source_type="manual",
            source_authority="self_report",
            observed_vs_entered="user_entered",
            parsing_status="ok",
            completeness="complete",
            conflict_status="none",
        ),
        summary=summary,
        fingerprint=str(uuid4()),
    )


def test_natural_fde_goal_uses_hiring_funnel_not_empty_dag() -> None:
    assert infer_primitive_kind(_fde_proposal()) == "funnel"
    refined = refine_architect_proposal(_fde_proposal())
    assert refined.primitive_kind == "funnel"
    assert refined.model_family_compatibility == "composed_funnel"


def test_unmodeled_hiring_activity_is_not_mapped_onto_funnel_stages() -> None:
    state = aggregate_funnel_from_evidence(
        [
            _evidence("applications_submitted", 17, "17 job applications"),
            _evidence("recruiter_replies", 3, "3 recruiter replies"),
            _evidence("coffee_chats", 10, "10 coffee chats with FDEs"),
            _evidence("cold_emails", 20, "20 cold emails to startup founders"),
            _evidence("referrals", 2, "2 referrals"),
            _evidence("neetcode_submissions", 14, "NeetCode technical preparation"),
        ]
    )
    assert state.applications == 17
    assert state.responses == 3
    assert state.technicals == 0
    assert state.practice_hours == 0.0


def test_long_metric_names_are_clipped_to_mcp_limit() -> None:
    raw = "weekly_neetcode_distinct_problems_solved_from_github_bulk_sync_" + ("x" * 80)
    assert len(clip_metric_name(raw)) == 80


def test_period_unit_does_not_count_as_an_increment() -> None:
    assert (
        observation_kind("applications_submitted", "observation", unit="applications/week")
        == "period"
    )


def test_unmapped_observations_are_kept_as_informational() -> None:
    policy = ObservationPolicy(
        goal_id="00000000-0000-0000-0000-000000000001",
        model_family="hiring_funnel",
        priceable_family=True,
        metrics=[],
        kind_semantics={},
        validation_rules=[],
        limitations=[],
    )
    proposal = EvidenceAgentProposal(events=[_event("coffee_chats", 10)])
    candidates, problems = RemoteMcpTools._check_extraction(policy, proposal)
    assert problems == []
    assert candidates[0]["metric"] == "coffee_chats"
    pairs = candidates_with_policy(policy, proposal)
    assert len(pairs) == 1
    assert pairs[0][1].why.startswith("Recorded as informational")
    info = informational_policy("coffee_chats", "count", "increment")
    assert info.metric == "coffee_chats"
