"""Composed count goals expose their fitted rate as a What If lever."""

from datetime import UTC, datetime, timedelta

from personal_markets.agents.goal_mapping import proposal_to_contract
from personal_markets.agents.model_planner import refine_architect_proposal
from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.goals.domain import GoalContract
from personal_markets.ports import GoalArchitectProposal
from personal_markets.what_if.baseline_state import build_baseline_state
from personal_markets.what_if.operationalize import operationalize_strategy


def _reading_goal() -> GoalContract:
    return proposal_to_contract(
        refine_architect_proposal(
            GoalArchitectProposal.model_validate(
                {
                    "ready_to_commit": True,
                    "title": "Read 20 books",
                    "goal_type": "threshold",
                    "success_metric": "books_read_count",
                    "success_operator": ">=",
                    "success_target": "20",
                    "deadline": (datetime.now(UTC) + timedelta(days=200)).date().isoformat(),
                    "primitive_kind": "cumulative_count",
                    "state_dimensions": ["books_read_count"],
                    "current_state_known": {"books_read_count": "5"},
                    "model_family_compatibility": "exploratory_general",
                }
            )
        )
    )


def _evidence(values: list[tuple[int, float]]) -> list[NormalizedEvidence]:
    now = datetime.now(UTC)
    return [
        NormalizedEvidence(
            event_type="uploaded_measurement",
            domain="user_state",
            metric="books_read_count",
            numeric_value=value,
            unit="books",
            observed_at=now - timedelta(days=days),
            source_quality="user_imported",
            provenance=Provenance(
                source_type="upload",
                source_authority="user_file",
                observed_vs_entered="imported",
                parsing_status="ok",
                completeness="complete",
                conflict_status="none",
                observation_kind="snapshot",
            ),
            summary="books",
            fingerprint=f"books-{days}",
        )
        for days, value in values
    ]


def test_reading_goal_exposes_primary_rate_not_an_application_lever() -> None:
    baseline = build_baseline_state(_reading_goal(), _evidence([(90, 2), (60, 3), (30, 4), (0, 5)]))
    names = [item.name for item in baseline.assumptions if item.editable]
    assert "primary.rate" in names
    assert baseline.priceability is not None
    assert baseline.priceability.status == "PRICED"
    assert baseline.priceability.missing == []
    assert "weekly_application_rate" not in names
    assert "flow" not in names
    plan, changes = operationalize_strategy(baseline, "what if I read 1 more book a week")  # type: ignore[misc]
    assert plan.family == "cadence"
    assert plan.levers[0].assumption == "primary.rate"
    assert changes[0].metric == "primary.rate"
    assert changes[0].value == 1


def test_unrelated_outreach_on_a_reading_goal_is_described_not_priced() -> None:
    baseline = build_baseline_state(_reading_goal(), _evidence([(90, 2), (60, 3), (30, 4), (0, 5)]))
    plan, changes = operationalize_strategy(baseline, "what if I cold email founders")  # type: ignore[misc]
    assert changes == [] and plan.unpriced
    assert plan.levers == []
