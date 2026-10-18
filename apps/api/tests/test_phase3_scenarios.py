from datetime import UTC, datetime, timedelta

from personal_markets.agents.goal_mapping import proposal_to_contract
from personal_markets.agents.model_planner import refine_architect_proposal
from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.forecasting.compiler import spec_from_mapping
from personal_markets.forecasting.composition import composition_numeric_inputs, price_composition
from personal_markets.forecasting.hiring import is_hiring_goal
from personal_markets.ports import GoalArchitectProposal, ResearchArtifact, ResearchClaim
from personal_markets.what_if.domain import InterventionChangeInput, WhatIfRequest
from personal_markets.what_if.service import WhatIfService


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


def test_scenario_b_what_if_unmapped_publication_frequency() -> None:
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
    result = service._simulate_composition(goal, request, evidence)
    assert result is not None
    assert result.status == "NOT_PRICED"
    assert result.receipt.get("causal_status") == "unmapped_intervention"


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

