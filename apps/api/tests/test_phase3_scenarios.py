import json
from datetime import UTC, datetime, timedelta

import pytest

from personal_markets.agents.goal_mapping import proposal_to_contract
from personal_markets.agents.intervention_critic import critique_intervention
from personal_markets.agents.model_planner import refine_architect_proposal
from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.forecasting.compiler import spec_from_mapping
from personal_markets.forecasting.composition import composition_numeric_inputs, price_composition
from personal_markets.forecasting.hiring import is_hiring_goal
from personal_markets.ports import (
    GoalArchitectProposal,
    InterventionAgentProposal,
    ResearchArtifact,
    ResearchClaim,
)
from personal_markets.what_if.domain import InterventionChangeInput, WhatIfRequest
from personal_markets.what_if.intervention_registry import allowed_metrics, composed_metric_units
from personal_markets.what_if.repository import InMemorySimulationRepository
from personal_markets.what_if.service import WhatIfService
from personal_markets.what_if.simulation import SimulationEngine


def _proposal(**overrides: object) -> GoalArchitectProposal:
    payload: dict[str, object] = {
        "ready_to_commit": True,
        "title": "Get a software internship offer",
        "goal_type": "deadline_event",
        "success_metric": "offer_received",
        "success_operator": "==",
        "success_target": "written_offer",
        "deadline": (datetime.now(UTC) + timedelta(days=200)).date().isoformat(),
        "state_dimensions": ["applications_submitted"],
        "model_family_compatibility": "deadline_event_hazard",
        "success_unit": "event",
    }
    payload.update(overrides)
    return GoalArchitectProposal.model_validate(payload)


def _rows(metric: str, points: list[tuple[str, float]]) -> list[NormalizedEvidence]:
    return [
        NormalizedEvidence(
            event_type="uploaded_measurement",
            domain="user_state",
            metric=metric,
            numeric_value=value,
            unit="count",
            observed_at=datetime.fromisoformat(stamp).replace(tzinfo=UTC),
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
            summary=metric,
            fingerprint=f"{metric}-{stamp}",
        )
        for stamp, value in points
    ]


def test_scenario_a_hiring_still_uses_domain_adapter() -> None:
    proposal = _proposal()
    goal = proposal_to_contract(proposal)
    assert is_hiring_goal(goal, proposal)
    spec = goal.model_requirements["forecast_spec"]
    assert spec.get("spec_version") in {1, 2}
    assert spec.get("family") != "composed_growth"


def test_sequential_launch_then_mrr_is_dag_even_if_architect_says_funnel() -> None:
    proposal = refine_architect_proposal(
        _proposal(
            title="Launch my B2B SaaS product, then reach 100 paying customers, then $5,000 MRR",
            goal_type="deadline_event",
            success_metric="paying_customers and MRR",
            success_operator=">=",
            success_target="100 paying customers AND $5,000 MRR",
            primitive_kind="funnel",
            primitives=[{"id": "primary", "kind": "funnel", "config": {}}],
            model_family_compatibility="composed_funnel",
        )
    )
    assert proposal.primitive_kind == "dependency_dag"
    goal = proposal_to_contract(proposal)
    spec = spec_from_mapping(goal.model_requirements["forecast_spec"])
    assert spec is not None
    assert spec.family == "composed_dependency_dag"
    assert spec.composition.join == "sequential_and"
    assert [node.id for node in spec.primitives] == ["launch", "customers", "revenue"]


def test_scenario_d_sequential_composition_does_not_multiply_blindly() -> None:
    proposal = refine_architect_proposal(
        _proposal(
            title="Launch, reach 100 customers, then $5000 MRR",
            goal_type="threshold",
            success_metric="mrr",
            success_operator=">=",
            success_target="5000",
            primitive_kind="dependency_dag",
            state_dimensions=["launched", "customers", "mrr"],
            current_state_known={"mrr": "200"},
        )
    )
    goal = proposal_to_contract(proposal)
    spec = spec_from_mapping(goal.model_requirements["forecast_spec"])
    assert spec is not None
    assert spec.composition.join == "sequential_and"
    assert len(spec.primitives) >= 2
    evidence = [
        *_rows("customers", [("2025-10-01", 10), ("2026-01-01", 30), ("2026-04-01", 50)]),
        *_rows("mrr", [("2025-10-01", 80), ("2026-01-01", 140), ("2026-04-01", 200)]),
        *_rows("launched", [("2026-01-01", 1)]),
    ]
    numeric = composition_numeric_inputs(goal, evidence)
    priced = price_composition(goal, numeric)
    assert priced is not None and priced.priced
    assert priced.transforms.get("method") == "sequential_waiting_time_mc"
    assert any(
        "product" in item.lower() or "waiting-time" in item.lower()
        for item in priced.limitations
    )


def _dag_targets(**overrides: object) -> dict[str, float | None]:
    proposal = refine_architect_proposal(
        _proposal(goal_type="multi_outcome", primitive_kind="dependency_dag", **overrides)
    )
    goal = proposal_to_contract(proposal)
    spec = spec_from_mapping(goal.model_requirements["forecast_spec"])
    assert spec is not None
    return {node.id: node.config.get("target") for node in spec.primitives}


def test_dag_milestone_targets_come_from_each_stated_milestone() -> None:
    targets = _dag_targets(
        title="Launch B2B SaaS, then 100 paying customers, then $5,000 MRR",
        success_metric=(
            "Count of paying customers AND monthly recurring revenue at deadline: "
            "paying_customers >= 100 and MRR >= 5000 USD/month"
        ),
        success_operator=">=",
        success_target="100 paying customers AND $5,000 MRR",
        state_dimensions=["paying_customer_count", "monthly_recurring_revenue_usd"],
    )
    assert targets == {"launch": 1.0, "customers": 100.0, "revenue": 5000.0}


def test_dag_launch_milestone_accepts_categorical_launch_event() -> None:
    proposal = refine_architect_proposal(
        _proposal(
            title="Launch B2B SaaS, then 100 paying customers, then $5,000 MRR",
            goal_type="multi_outcome",
            primitive_kind="dependency_dag",
            success_metric="paying_customers and MRR",
            success_operator=">=",
            success_target="100 paying customers AND $5,000 MRR",
            deadline=(datetime.now(UTC) + timedelta(days=330)).date().isoformat(),
        )
    )
    goal = proposal_to_contract(proposal)
    launch = _rows("launch_status", [("2026-01-15", 0)])[0].model_copy(
        update={"numeric_value": None, "categorical_value": "launched", "event_type": "event"}
    )
    evidence = [
        launch,
        *_rows("number_of_paying_customers", [("2026-10-18", 50)]),
        *_rows("customers", [("2026-02-20", 10), ("2026-06-20", 31), ("2026-10-15", 50)]),
        *_rows("monthly_recurring_revenue_usd", [("2026-10-18", 1900)]),
        *_rows("mrr", [("2026-02-20", 300), ("2026-06-20", 1100), ("2026-10-15", 1900)]),
    ]
    numeric = composition_numeric_inputs(goal, evidence)
    assert numeric is not None
    launch_state = (numeric.state.get("composition_prepared") or {}).get("nodes", {}).get("launch")
    assert launch_state is not None
    assert launch_state["current"] == 1.0
    priced = price_composition(goal, numeric)
    assert priced is not None
    assert not any("launched" in item for item in priced.limitations), priced.limitations
    assert priced.priced
    json.dumps(priced.transforms, allow_nan=False)


def test_forecast_receipt_json_rejects_non_finite_floats() -> None:
    from personal_markets.forecasting.repository import jsonable_receipt

    cleaned = jsonable_receipt({"p": 0.2, "mean": float("inf"), "nested": [float("nan"), 1]})
    assert cleaned == {"p": 0.2, "mean": None, "nested": [None, 1]}
    json.dumps(cleaned, allow_nan=False)


def test_dag_without_a_stated_revenue_target_does_not_invent_one() -> None:
    targets = _dag_targets(
        title="Launch my app, then reach 40 paying customers",
        success_metric="paying_customers",
        success_operator=">=",
        success_target="40",
        state_dimensions=["paying_customers"],
    )
    assert "revenue" not in targets
    assert targets.get("customers") == 40.0


def test_scenario_f_frozen_applicable_research_can_fill_a_rate() -> None:
    proposal = refine_architect_proposal(
        _proposal(
            title="Visit 15 countries",
            goal_type="threshold",
            success_metric="countries_visited",
            success_operator=">=",
            success_target="15",
            primitive_kind="cumulative_count",
            current_state_known={"countries_visited": "5"},
        )
    )
    goal = proposal_to_contract(proposal)
    artifact = ResearchArtifact(
        claims=[
            ResearchClaim(
                claim="Travelers in this cohort visit 2 countries per year.",
                source="frozen://travel_rate.json",
                retrieved_at=datetime.now(UTC).isoformat(),
                source_type="frozen",
                evidence_class="reference_rule",
                supporting_quote="2 countries per year",
                population="self-identified long-term travelers",
                applicability="applicable",
                parameter="rate",
                value=2.0 / 52.0,
                unit="countries/week",
                verification="frozen_reference",
                material_kind="frozen_reference",
            )
        ],
        status="sufficient",
        parameter_provenance=[
            {
                "parameter": "rate",
                "value": 2.0 / 52.0,
                "unit": "countries/week",
                "source": "frozen://travel_rate.json",
                "applicability": "applicable",
                "verification": "frozen_reference",
                "status": "used",
                "used_by_engine": True,
            }
        ],
    )
    requirements = dict(goal.model_requirements)
    spec = dict(requirements["forecast_spec"])
    spec["parameter_provenance"] = artifact.parameter_provenance
    spec["research_required"] = False
    goal = goal.model_copy(update={"model_requirements": {**requirements, "forecast_spec": spec}})
    numeric = composition_numeric_inputs(goal, _rows("countries_visited", [("2026-01-01", 5)]))
    priced = price_composition(goal, numeric)
    assert priced is not None and priced.priced
    assert any(
        item.get("name") == "primary.rate" or "rate" in str(item)
        for item in priced.used_assumptions
    )


@pytest.mark.asyncio
async def test_scenario_b_what_if_unmapped_publication_frequency() -> None:
    proposal = refine_architect_proposal(
        _proposal(
            title="Reach 10000 subscribers",
            goal_type="threshold",
            success_metric="subscribers",
            success_operator=">=",
            success_target="10000",
            primitive_kind="growth",
            current_state_known={"subscribers": "1200"},
        )
    )
    goal = proposal_to_contract(proposal)
    evidence = _rows(
        "subscribers",
        [("2026-01-01", 800), ("2026-02-01", 950), ("2026-03-01", 1200)],
    )
    service = WhatIfService.__new__(WhatIfService)
    request = WhatIfRequest(
        goal_id=str(goal.goal_id),
        current_value=1200,
        target_value=10000,
        periods=24,
        assumptions=[],
        parsed_changes=[
            InterventionChangeInput(
                metric="videos_per_week",
                operation="set",
                value=2,
                unit="videos/week",
                provenance="EXPLORATION_ASSUMPTION",
            )
        ],
    )
    result = await service._simulate_composition(goal, request, evidence, persist=False)
    assert result is not None
    assert result.status == "NOT_PRICED"
    assert result.receipt.get("causal_status") == "unmapped_intervention"


def _country_goal_and_history() -> tuple[object, list[NormalizedEvidence]]:
    proposal = refine_architect_proposal(
        _proposal(
            title="Visit 15 countries",
            goal_type="threshold",
            success_metric="countries_visited",
            success_operator=">=",
            success_target="15",
            success_unit="countries",
            primitive_kind="cumulative_count",
            deadline=(datetime.now(UTC) + timedelta(days=800)).date().isoformat(),
        )
    )
    goal = proposal_to_contract(proposal)
    history = _rows(
        "countries_visited",
        [("2024-05-01", 2), ("2025-04-26", 4), ("2026-04-21", 5), ("2026-09-28", 6)],
    )
    return goal, history


def _rate_change(value: float, unit: str = "count/week") -> InterventionChangeInput:
    return InterventionChangeInput(
        metric="primary.rate",
        operation="add",
        value=value,
        unit=unit,
        provenance="EXPLORATION_ASSUMPTION",
    )


def test_composed_goal_offers_simulator_parameters_with_units() -> None:
    goal, _ = _country_goal_and_history()
    assert composed_metric_units(goal) == {"primary.rate": "count/week"}
    assert allowed_metrics(goal) == {"primary.rate"}


def test_critic_drops_composed_change_with_wrong_unit() -> None:
    goal, _ = _country_goal_and_history()
    proposal = InterventionAgentProposal.model_validate(
        {
            "understood_action": "Visit two more countries per year",
            "pricing_status": "PRICED",
            "changes": [
                {"metric": "primary.rate", "operation": "add", "value": 2, "unit": "count/year",
                 "provenance": "EXPLORATION_ASSUMPTION", "strength": "EXPLORATORY"},
            ],
        }
    )
    critic = critique_intervention(goal, proposal)
    assert critic.validated_changes == []
    assert critic.approved is False


@pytest.mark.asyncio
async def test_composed_what_if_without_mapped_changes_is_not_priced() -> None:
    goal, history = _country_goal_and_history()
    service = WhatIfService.__new__(WhatIfService)
    request = WhatIfRequest(
        goal_id=str(goal.goal_id), current_value=6, target_value=15, periods=100,
        assumptions=[], parsed_changes=[],
    )
    result = await service._simulate_composition(goal, request, history, persist=False)
    assert result is not None
    assert result.status == "NOT_PRICED"
    assert result.expected_uplift_pp is None


@pytest.mark.asyncio
async def test_composed_rate_add_raises_probability_from_estimated_rate() -> None:
    goal, history = _country_goal_and_history()
    service = WhatIfService.__new__(WhatIfService)
    request = WhatIfRequest(
        goal_id=str(goal.goal_id), current_value=6, target_value=15, periods=100,
        assumptions=[], parsed_changes=[_rate_change(2 / 52.1775)],
    )
    result = await service._simulate_composition(goal, request, history, persist=False)
    assert result is not None and result.priced
    assert result.expected_uplift_pp is not None and result.expected_uplift_pp > 0
    estimated = composition_numeric_inputs(goal, history)
    assert estimated is not None
    assert result.receipt["overrides"]["primary.rate"] == pytest.approx(
        estimated.assumptions["primary.rate"] + 2 / 52.1775
    )


@pytest.mark.asyncio
async def test_composed_scenario_persists_without_publishing_forecast() -> None:
    goal, history = _country_goal_and_history()
    service = WhatIfService.__new__(WhatIfService)
    service._repository = InMemorySimulationRepository()
    service._engine = SimulationEngine()
    request = WhatIfRequest(
        goal_id=str(goal.goal_id), current_value=6, target_value=15, periods=100,
        assumptions=[], parsed_changes=[_rate_change(2 / 52.1775)],
    )
    result = await service._simulate_composition(goal, request, history, persist=True)
    assert result is not None and result.priced and result.run_id
    assert result.persisted
    runs = await service._repository.list_runs(goal.goal_id)
    assert len(runs) == 1
    assert runs[0].receipt["scenario"]["causal_status"] == "parameter_intervention"
    assert await service._repository.history(goal.goal_id) == []


def test_scenario_e_running_keeps_domain_adapter() -> None:
    proposal = refine_architect_proposal(
        _proposal(
            title="Run a half marathon under two hours",
            goal_type="threshold",
            success_metric="race_time_seconds",
            success_operator="<=",
            success_target="7200",
            primitive_kind="continuous_threshold",
            state_dimensions=["race_time_seconds", "weekly_distance"],
            current_state_known={"race_time_seconds": "7800"},
        )
    )
    goal = proposal_to_contract(proposal)
    spec = goal.model_requirements["forecast_spec"]
    assert spec.get("family") != "composed_growth"
    assert spec.get("spec_version") in {1, 2}


def _live_growth_goal() -> object:
    # Shape returned by the live Goal Architect: a descriptive metric label and mixed
    # stock/rate state dimensions.
    proposal = refine_architect_proposal(
        _proposal(
            title="Reach 10,000 YouTube subscribers by 2027-06-30",
            goal_type="threshold",
            success_metric="Total YouTube channel subscriber count",
            success_operator=">=",
            success_target="10000",
            success_unit="subscribers",
            primitive_kind="growth",
            state_dimensions=[
                "current subscriber count",
                "subscriber gain per month",
                "video publish frequency",
                "average views per video",
            ],
            model_family_compatibility="composed_growth",
        )
    )
    return proposal_to_contract(proposal)


def test_descriptive_metric_label_binds_canonical_uploads() -> None:
    goal = _live_growth_goal()
    evidence = _rows(
        "subscribers",
        [("2026-05-01", 520), ("2026-07-01", 760), ("2026-09-01", 1040), ("2026-10-15", 1200)],
    )
    priced = price_composition(goal, composition_numeric_inputs(goal, evidence))
    assert priced is not None and priced.priced
    assert priced.raw_probability is not None and 0 < priced.raw_probability < 1


def test_rate_dimensions_are_not_read_as_the_target_stock() -> None:
    goal = _live_growth_goal()
    history = _rows(
        "subscribers",
        [("2026-05-01", 520), ("2026-07-01", 760), ("2026-09-01", 1040), ("2026-10-15", 1200)],
    )
    noise = _rows("subscriber gain per month", [("2026-10-16", 120)]) + _rows(
        "video publish frequency", [("2026-10-16", 2)]
    )
    now = datetime(2026, 10, 18, tzinfo=UTC)
    clean = composition_numeric_inputs(goal, history, now=now)
    mixed = composition_numeric_inputs(goal, history + noise, now=now)
    assert clean is not None and mixed is not None
    assert mixed.state == clean.state

