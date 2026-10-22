from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.persistence.agent_store import InMemoryEvidenceRepository
from personal_markets.ports import EvidenceEventProposal
from personal_markets.what_if.domain import (
    InterventionChangeInput,
    PossibleFuturesRequest,
    ScenarioDefinition,
    ScenarioDistribution,
)
from personal_markets.what_if.service import WhatIfService


@pytest.mark.asyncio
async def test_possible_futures_prices_startup_from_evidence() -> None:
    goal_id = uuid4()
    goal = GoalContract.model_validate(
        {
            "goal_id": goal_id,
            "title": "Quit and work on my startup",
            "goal_type": GoalType.MULTI_OUTCOME,
            "success_definition": {"metric": "startup_outcome", "target": "raise_external_funding"},
            "deadline": datetime.now(UTC) + timedelta(days=400),
            "state_dimensions": ["mrr", "runway"],
        }
    )
    goal_repo = InMemoryGoalRepository()
    await goal_repo.create(goal, uuid4())
    goals = GoalService(goal_repo)
    evidence_repo = InMemoryEvidenceRepository({goal_id: True})
    evidence_service = EvidenceService(evidence_repo)
    user_id = uuid4()
    await evidence_repo.insert(
        user_id,
        goal_id,
        EvidenceEventProposal.model_validate(
            {
                "source_type": "manual",
                "event_type": "observation",
                "domain": "startup",
                "metric": "mrr",
                "numeric_value": 9000.0,
                "unit": "USD",
                "observed_at": datetime.now(UTC).isoformat(),
                "summary": "mrr snapshot",
            }
        ),
        fingerprint="f1",
        agent_run_id=None,
        conflict="none",
    )
    service = WhatIfService(goals, evidence=evidence_service)
    result = await service.possible_futures(
        PossibleFuturesRequest(
            goal_id=str(goal_id),
            name="Startup futures",
            outcomes=[
                ScenarioDefinition(label="Raise seed"),
                ScenarioDefinition(label="Bootstrap sustainably"),
                ScenarioDefinition(label="Other", downside=True),
            ],
            include_other=True,
        )
    )
    assert result.priced is True
    total = sum(item.probability or 0 for item in result.outcomes) + result.other_probability
    assert total == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_possible_futures_prices_finance_from_mc_clusters() -> None:
    goal_id = uuid4()
    goal = GoalContract.model_validate(
        {
            "goal_id": goal_id,
            "title": "Reach one million dollars in net worth",
            "goal_type": GoalType.CONTINUOUS_TARGET,
            "success_definition": {"metric": "net_worth", "operator": ">=", "amount": 1_000_000},
            "deadline": datetime.now(UTC) + timedelta(days=365 * 8),
            "state_dimensions": ["liquid_assets", "income", "expenses"],
        }
    )
    goal_repo = InMemoryGoalRepository()
    await goal_repo.create(goal, uuid4())
    goals = GoalService(goal_repo)
    evidence_repo = InMemoryEvidenceRepository({goal_id: True})
    evidence_service = EvidenceService(evidence_repo)
    user_id = uuid4()
    for metric, value, unit in (
        ("net_worth", 180_000.0, "CAD"),
        ("monthly_contribution", 2500.0, "CAD/month"),
    ):
        await evidence_repo.insert(
            user_id,
            goal_id,
            EvidenceEventProposal.model_validate(
                {
                    "source_type": "manual",
                    "event_type": "observation",
                    "domain": "finance",
                    "metric": metric,
                    "numeric_value": value,
                    "unit": unit,
                    "observed_at": datetime.now(UTC).isoformat(),
                    "summary": f"{metric}={value}",
                }
            ),
            fingerprint=f"{metric}-{value}",
            agent_run_id=None,
            conflict="none",
        )
    service = WhatIfService(goals, evidence=evidence_service)
    result = await service.possible_futures(
        PossibleFuturesRequest(
            goal_id=str(goal_id),
            name="Finance futures",
            outcomes=[
                ScenarioDefinition(label="Target reached"),
                ScenarioDefinition(label="Meaningful progress"),
                ScenarioDefinition(label="Current trajectory"),
                ScenarioDefinition(label="Downside outcome", downside=True),
            ],
            include_other=True,
        )
    )
    assert result.priced is True
    assert all(item.probability is not None for item in result.outcomes)
    total = sum(item.probability or 0 for item in result.outcomes) + result.other_probability
    assert total == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_possible_futures_prices_running_from_mc_clusters() -> None:
    goal_id = uuid4()
    goal = GoalContract.model_validate(
        {
            "goal_id": goal_id,
            "title": "Run a 10K in under 50 minutes",
            "goal_type": GoalType.THRESHOLD,
            "success_definition": {"metric": "10k_time_seconds", "operator": "<=", "value": 3000},
            "deadline": datetime.now(UTC) + timedelta(days=365),
            "state_dimensions": ["recent_race_time", "weekly_distance"],
        }
    )
    goal_repo = InMemoryGoalRepository()
    await goal_repo.create(goal, uuid4())
    goals = GoalService(goal_repo)
    evidence_repo = InMemoryEvidenceRepository({goal_id: True})
    evidence_service = EvidenceService(evidence_repo)
    user_id = uuid4()
    for metric, value, unit in (
        ("10k_time_seconds", 3300.0, "seconds"),
        ("weekly_distance_km", 35.0, "km/week"),
    ):
        await evidence_repo.insert(
            user_id,
            goal_id,
            EvidenceEventProposal.model_validate(
                {
                    "source_type": "manual",
                    "event_type": "observation",
                    "domain": "running",
                    "metric": metric,
                    "numeric_value": value,
                    "unit": unit,
                    "observed_at": datetime.now(UTC).isoformat(),
                    "summary": f"{metric}={value}",
                }
            ),
            fingerprint=f"{metric}-{value}",
            agent_run_id=None,
            conflict="none",
        )
    service = WhatIfService(goals, evidence=evidence_service)
    result = await service.possible_futures(
        PossibleFuturesRequest(
            goal_id=str(goal_id),
            name="Running futures",
            outcomes=[
                ScenarioDefinition(label="Target reached"),
                ScenarioDefinition(label="Meaningful progress"),
                ScenarioDefinition(label="Downside outcome", downside=True),
            ],
            include_other=False,
        )
    )
    assert result.priced is True
    total = sum(item.probability or 0 for item in result.outcomes)
    assert total == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_possible_futures_prices_career_from_funnel_model() -> None:
    goal_id = uuid4()
    goal = GoalContract.model_validate(
        {
            "goal_id": goal_id,
            "title": "Receive a Big Tech SWE offer",
            "goal_type": GoalType.DEADLINE_EVENT,
            "success_definition": {"metric": "offer_received", "target": "swe_offer"},
            "deadline": datetime.now(UTC) + timedelta(days=180),
            "state_dimensions": ["application_pipeline", "interview_outcomes"],
        }
    )
    goal_repo = InMemoryGoalRepository()
    await goal_repo.create(goal, uuid4())
    goals = GoalService(goal_repo)
    evidence_repo = InMemoryEvidenceRepository({goal_id: True})
    evidence_service = EvidenceService(evidence_repo)
    user_id = uuid4()
    for metric, value in (("applications_submitted", 12.0), ("responses_received", 3.0)):
        await evidence_repo.insert(
            user_id,
            goal_id,
            EvidenceEventProposal.model_validate(
                {
                    "source_type": "manual",
                    "event_type": "observation",
                    "domain": "career",
                    "metric": metric,
                    "numeric_value": value,
                    "unit": "count",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "summary": f"{metric}={value}",
                }
            ),
            fingerprint=f"{metric}-{value}",
            agent_run_id=None,
            conflict="none",
        )
    service = WhatIfService(goals, evidence=evidence_service)
    result = await service.possible_futures(
        PossibleFuturesRequest(
            goal_id=str(goal_id),
            name="Career futures",
            outcomes=[
                ScenarioDefinition(label="Target reached"),
                ScenarioDefinition(label="Meaningful progress"),
                ScenarioDefinition(label="Downside outcome", downside=True),
            ],
            include_other=True,
        )
    )
    assert result.priced is True
    total = sum(item.probability or 0 for item in result.outcomes) + result.other_probability
    assert total == pytest.approx(1.0)


def _prob(result: ScenarioDistribution, needle: str) -> float:
    for item in result.outcomes:
        if needle.lower() in item.label.lower():
            return float(item.probability or 0)
    raise AssertionError(f"missing outcome containing {needle!r}")


@pytest.mark.asyncio
async def test_startup_parsed_changes_shift_raise_seed_mass() -> None:
    goal_id = uuid4()
    goal = GoalContract.model_validate(
        {
            "goal_id": goal_id,
            "title": "Quit and work on my startup",
            "goal_type": GoalType.MULTI_OUTCOME,
            "success_definition": {"metric": "startup_outcome", "target": "raise_external_funding"},
            "deadline": datetime.now(UTC) + timedelta(days=400),
            "state_dimensions": ["mrr", "runway"],
        }
    )
    goal_repo = InMemoryGoalRepository()
    await goal_repo.create(goal, uuid4())
    evidence_repo = InMemoryEvidenceRepository({goal_id: True})
    await evidence_repo.insert(
        uuid4(),
        goal_id,
        EvidenceEventProposal.model_validate(
            {
                "source_type": "manual",
                "event_type": "observation",
                "domain": "startup",
                "metric": "mrr",
                "numeric_value": 9000.0,
                "unit": "USD",
                "observed_at": datetime.now(UTC).isoformat(),
                "summary": "mrr snapshot",
            }
        ),
        fingerprint="mrr",
        agent_run_id=None,
        conflict="none",
    )
    service = WhatIfService(GoalService(goal_repo), evidence=EvidenceService(evidence_repo))
    labels = [
        ScenarioDefinition(label="Raise seed"),
        ScenarioDefinition(label="Bootstrap sustainably"),
        ScenarioDefinition(label="Downside / return to job", downside=True),
    ]
    baseline = await service.possible_futures(
        PossibleFuturesRequest(goal_id=str(goal_id), name="Baseline", outcomes=labels)
    )
    boosted = await service.possible_futures(
        PossibleFuturesRequest(
            goal_id=str(goal_id),
            name="More conversations",
            outcomes=labels,
            parsed_changes=[
                InterventionChangeInput(
                    metric="user_conversations_per_week",
                    operation="set",
                    value=8,
                    unit="per week",
                    provenance="USER_ASSUMPTION",
                )
            ],
        )
    )
    assert baseline.priced and boosted.priced
    assert _prob(boosted, "Raise") > _prob(baseline, "Raise")


@pytest.mark.asyncio
async def test_hiring_parsed_changes_shift_offer_mass() -> None:
    goal_id = uuid4()
    goal = GoalContract.model_validate(
        {
            "goal_id": goal_id,
            "title": "Receive a Big Tech SWE offer",
            "goal_type": GoalType.DEADLINE_EVENT,
            "success_definition": {"metric": "offer_received", "target": "swe_offer"},
            "deadline": datetime.now(UTC) + timedelta(days=180),
            "state_dimensions": ["application_pipeline", "interview_outcomes"],
        }
    )
    goal_repo = InMemoryGoalRepository()
    await goal_repo.create(goal, uuid4())
    evidence_repo = InMemoryEvidenceRepository({goal_id: True})
    user_id = uuid4()
    for metric, value in (("applications_submitted", 4.0), ("responses_received", 1.0)):
        await evidence_repo.insert(
            user_id,
            goal_id,
            EvidenceEventProposal.model_validate(
                {
                    "source_type": "manual",
                    "event_type": "observation",
                    "domain": "career",
                    "metric": metric,
                    "numeric_value": value,
                    "unit": "count",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "summary": f"{metric}={value}",
                }
            ),
            fingerprint=f"{metric}-{value}",
            agent_run_id=None,
            conflict="none",
        )
    service = WhatIfService(GoalService(goal_repo), evidence=EvidenceService(evidence_repo))
    labels = [
        ScenarioDefinition(label="Offer received"),
        ScenarioDefinition(label="Final-stage pipeline"),
        ScenarioDefinition(label="No meaningful progress", downside=True),
    ]
    baseline = await service.possible_futures(
        PossibleFuturesRequest(goal_id=str(goal_id), name="Baseline", outcomes=labels)
    )
    boosted = await service.possible_futures(
        PossibleFuturesRequest(
            goal_id=str(goal_id),
            name="More applications",
            outcomes=labels,
            parsed_changes=[
                InterventionChangeInput(
                    metric="applications_per_week",
                    operation="set",
                    value=12,
                    unit="per week",
                    provenance="USER_ASSUMPTION",
                )
            ],
        )
    )
    assert baseline.priced and boosted.priced
    assert _prob(boosted, "Offer") > _prob(baseline, "Offer")
