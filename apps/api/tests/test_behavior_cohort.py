from datetime import UTC, datetime, timedelta
from uuid import uuid4

from personal_markets.behavior.cohort import authentic_evidence, behavior_cohort_goals
from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.goals.domain import GoalContract, GoalType


def _goal(*, synthetic: bool) -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title="Read twenty books",
        goal_type=GoalType.THRESHOLD,
        success_definition={"target": 20},
        deadline=datetime.now(UTC) + timedelta(days=30),
        state_dimensions=["books"],
        model_requirements={"workspace_seed": "fixture-v1"} if synthetic else {},
    )


def test_synthetic_commitments_are_separate_from_authentic_behavior() -> None:
    authentic, fixture = _goal(synthetic=False), _goal(synthetic=True)
    demo = _goal(synthetic=False).model_copy(
        update={"model_requirements": {"demo_seed": "seeds/demo.json"}}
    )
    assert behavior_cohort_goals([authentic, fixture, demo]) == [authentic]
    assert behavior_cohort_goals([authentic, fixture, demo], synthetic=True) == [fixture, demo]
    assert behavior_cohort_goals([fixture]) == []


def test_seed_identity_and_demo_quality_cannot_enter_authentic_evidence() -> None:
    def row(*, identity: str | None, quality: str) -> NormalizedEvidence:
        return NormalizedEvidence(
            event_type="observation",
            domain="reading",
            metric="reading_minutes",
            numeric_value=45,
            observed_at=datetime.now(UTC),
            source_quality=quality,
            provenance=Provenance(
                source_type="manual",
                source_authority="self_report",
                observed_vs_entered="user_entered",
                parsing_status="ok",
                completeness="complete",
                conflict_status="none",
                event_identity=identity,
            ),
            summary="Read",
            fingerprint=str(uuid4()),
        )

    real = row(identity="report:abc", quality="user_entered")
    assert authentic_evidence(
        [
            row(identity="seed:v1:goal:event", quality="user_entered"),
            row(identity=None, quality="demo_fixture"),
            row(identity=None, quality="synthetic_demo"),
            real,
        ]
    ) == [real]
