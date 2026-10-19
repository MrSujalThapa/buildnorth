from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from scipy.stats import norm, poisson

from personal_markets.agents.goal_mapping import proposal_to_contract
from personal_markets.agents.model_planner import infer_primitive_kind, refine_architect_proposal
from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.evidence.metrics import (
    canonicalize_metric,
    observation_kind,
    reduce_stock_value,
)
from personal_markets.forecasting.compiler import ForecastSpecV2, compile_spec, spec_from_mapping
from personal_markets.forecasting.composition import composition_numeric_inputs, price_composition
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.primitives import (
    funnel_path_probability,
    price_continuous_threshold,
    price_cumulative_count,
    price_deadline_hazard,
    price_dependency_dag,
    price_funnel,
    price_growth,
)
from personal_markets.forecasting.repository import InMemoryBaselineForecastRepository
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.ports import GoalArchitectProposal


def test_poisson_count_matches_analytical_survival() -> None:
    result = price_cumulative_count(
        current=5, target=15, rate=2.0, periods=5, n_rate_observations=1
    )
    assert result.priced
    assert result.probability == pytest.approx(float(poisson.sf(9, 10.0)))


def test_count_already_at_target_is_nearly_certain() -> None:
    result = price_cumulative_count(current=15, target=15, rate=0.0, periods=4)
    assert result.priced
    assert result.probability == pytest.approx(1.0 - 1e-6)


def test_threshold_projection_uses_normal_tail_on_both_sides_of_target() -> None:
    below = price_continuous_threshold(
        current=3100, target=3000, periods=10, trend=-10.1, noise=40, direction="at_most"
    )
    above = price_continuous_threshold(
        current=3100, target=3000, periods=10, trend=-9.9, noise=40, direction="at_most"
    )
    assert below.probability == pytest.approx(norm.cdf(3000, loc=2999, scale=40), abs=1e-9)
    assert abs(below.probability - above.probability) < 0.05
    achieved = price_continuous_threshold(
        current=2990, target=3000, periods=10, trend=5.0, noise=40, direction="at_most"
    )
    assert achieved.probability == pytest.approx(0.995)


def test_count_without_rate_is_unpriced() -> None:
    result = price_cumulative_count(current=2, target=15, rate=-1, periods=10)
    assert not result.priced
    assert result.probability is None


def test_loglinear_growth_reproducible_and_in_unit_interval() -> None:
    first = price_growth(current=1000, target=2000, periods=10, mu=0.08, sigma=0.05)
    second = price_growth(current=1000, target=2000, periods=10, mu=0.08, sigma=0.05)
    assert first.priced and second.priced
    assert first.probability == second.probability
    assert 0 < first.probability < 1


def test_funnel_independent_product() -> None:
    path = funnel_path_probability([0.5, 0.4])
    assert path == pytest.approx(0.2)
    priced = price_funnel(
        stage_counts=[10, 0, 0],
        conversions=[0.5, 0.4],
        independence="assumed_independent",
    )
    assert priced.priced
    assert priced.probability == pytest.approx(1.0 - (0.8**10))


def test_hazard_two_fair_periods_is_three_quarters() -> None:
    result = price_deadline_hazard([0.0, 0.0])
    assert result.probability == pytest.approx(0.75)


def test_dag_refuses_bare_probability_product() -> None:
    result = price_dependency_dag(
        durations_mean=[0.0, 0.0],
        durations_std=[0.0, 0.0],
        horizon=10,
        success_probabilities=[0.5, 0.5],
        correlation="unspecified",
    )
    assert not result.priced


def test_dag_mc_is_seed_reproducible() -> None:
    first = price_dependency_dag(
        durations_mean=[3.0, 3.0],
        durations_std=[0.4, 0.4],
        horizon=6,
        prerequisites=[[], [0]],
        correlation="independent",
        n_draws=2000,
        seed=7,
    )
    second = price_dependency_dag(
        durations_mean=[3.0, 3.0],
        durations_std=[0.4, 0.4],
        horizon=6,
        prerequisites=[[], [0]],
        correlation="independent",
        n_draws=2000,
        seed=7,
    )
    assert first.priced and first.probability == second.probability
    assert 0 <= first.probability <= 1
    assert first.diagnostics["hits"] == second.diagnostics["hits"]


def test_compiler_rejects_arbitrary_code_config() -> None:
    spec = ForecastSpecV2.model_validate(
        {
            "goal_id": uuid4(),
            "outcome": {
                "predicate": "metric_at_least",
                "metric": "subscribers",
                "threshold": 10000,
            },
            "deadline": datetime.now(UTC) + timedelta(days=180),
            "family": "composed_growth",
            "model_version": "1.0.0",
            "primitives": [
                {
                    "id": "primary",
                    "kind": "growth",
                    "metric": "subscribers",
                    "config": {"python": "print(1)"},
                }
            ],
            "composition": {"join": "single", "nodes": ["primary"]},
        }
    )
    result = compile_spec(spec)
    assert not result.accepted


def _evidence(
    metric: str, values: list[tuple[str, float]], kind: str = "snapshot"
) -> list[NormalizedEvidence]:
    rows = []
    for stamp, value in values:
        rows.append(
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
                    observation_kind=kind,  # type: ignore[arg-type]
                ),
                summary=metric,
                fingerprint=f"{metric}-{stamp}-{value}",
            )
        )
    return rows


def _proposal(**overrides: object) -> GoalArchitectProposal:
    payload: dict[str, object] = {
        "ready_to_commit": True,
        "title": "Reach 10000 YouTube subscribers by June",
        "goal_type": "threshold",
        "success_metric": "subscribers",
        "success_operator": ">=",
        "success_target": "10000",
        "deadline": (datetime.now(UTC) + timedelta(days=180)).date().isoformat(),
        "state_dimensions": ["subscribers"],
        "model_family_compatibility": "composed_growth",
        "success_unit": "count",
        "primitive_kind": "growth",
        "current_state_known": {"subscribers": "1200"},
    }
    payload.update(overrides)
    return GoalArchitectProposal.model_validate(payload)


def test_growth_goal_is_not_a_renamed_hiring_model() -> None:
    proposal = refine_architect_proposal(_proposal())
    assert infer_primitive_kind(proposal) == "growth"
    goal = proposal_to_contract(proposal)
    spec = spec_from_mapping(goal.model_requirements["forecast_spec"])
    assert spec is not None
    assert spec.primitives[0].kind == "growth"
    evidence = _evidence(
        "subscribers",
        [
            ("2026-01-01", 800),
            ("2026-02-01", 950),
            ("2026-03-01", 1200),
        ],
    )
    numeric = composition_numeric_inputs(goal, evidence)
    assert numeric is not None
    priced = price_composition(goal, numeric)
    assert priced is not None and priced.priced
    assert priced.transforms["method"] in {"loglinear_growth", "logistic_growth"}
    assert "deadline_event_hazard" not in priced.transforms.get("method", "")


def test_travel_without_rate_is_not_priced() -> None:
    proposal = refine_architect_proposal(
        _proposal(
            title="Visit 15 countries before 30",
            success_metric="countries_visited",
            success_target="15",
            primitive_kind="cumulative_count",
            current_state_known={"countries_visited": "7"},
        )
    )
    goal = proposal_to_contract(proposal)
    evidence = _evidence("countries_visited", [("2026-04-01", 7)])
    numeric = composition_numeric_inputs(goal, evidence)
    assert numeric is not None
    priced = price_composition(goal, numeric)
    assert priced is not None
    assert priced.priced is False
    assert priced.raw_probability is None
    assert any("rate" in item.lower() or "history" in item.lower() for item in priced.limitations)


def test_travel_with_rate_history_prices_poisson() -> None:
    proposal = refine_architect_proposal(
        _proposal(
            title="Visit 15 countries before 30",
            success_metric="countries_visited",
            success_target="15",
            primitive_kind="cumulative_count",
            current_state_known={"countries_visited": "6"},
        )
    )
    goal = proposal_to_contract(proposal)
    evidence = _evidence(
        "countries_visited",
        [("2024-01-01", 2), ("2025-01-01", 4), ("2026-01-01", 6)],
    )
    numeric = composition_numeric_inputs(goal, evidence)
    priced = price_composition(goal, numeric)
    assert priced is not None and priced.priced
    assert priced.raw_probability is not None
    assert 0 < priced.raw_probability < 1


def test_vague_success_asks_for_a_measurable_criterion() -> None:
    proposal = refine_architect_proposal(
        GoalArchitectProposal.model_validate(
            {
                "ready_to_commit": False,
                "title": "I want to become extremely successful someday",
                "goal_type": "deadline_event",
                "success_metric": "unspecified",
                "success_operator": ">=",
                "success_target": "unspecified",
                "deadline": (datetime.now(UTC) + timedelta(days=365)).date().isoformat(),
                "state_dimensions": ["unspecified"],
                "model_family_compatibility": "none",
            }
        )
    )
    assert proposal.ready_to_commit is False
    assert any(item.id == "measurable_outcome" for item in proposal.clarifications_required)


def test_generic_snapshot_then_increment_aggregation() -> None:
    assert canonicalize_metric("youtube_subscribers") == "subscribers"
    observations = [
        (datetime(2026, 1, 1, tzinfo=UTC), 1000.0, "snapshot"),
        (datetime(2026, 2, 1, tzinfo=UTC), 80.0, "increment"),
    ]
    assert reduce_stock_value(observations) == pytest.approx(1080.0)  # type: ignore[arg-type]
    assert observation_kind("subscribers", "manual_state_entry") == "snapshot"


def test_publish_growth_receipt_has_lineage() -> None:
    proposal = refine_architect_proposal(_proposal())
    goal = proposal_to_contract(proposal)
    evidence = _evidence(
        "subscribers",
        [("2026-01-01", 800), ("2026-02-01", 950), ("2026-03-01", 1200)],
    )
    numeric = composition_numeric_inputs(goal, evidence)
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(goal, proposal, ["ev-1"], {"goal_architect": "run"}, [], numeric)
    assert pricing.priced
    assert pricing.receipt["llm_used_for_probability"] is False
    assert pricing.receipt["publication"] == "priced"
    assert pricing.receipt["forecast_spec"]["spec_version"] == 2
    assert pricing.receipt["compiler_version"] == "composed_v1"


def test_unsupported_formula_does_not_execute() -> None:
    goal = GoalContract.model_validate(
        {
            "goal_id": uuid4(),
            "title": "Hack the probability",
            "goal_type": GoalType.THRESHOLD,
            "success_definition": {"metric": "x", "operator": ">=", "target": "10"},
            "deadline": datetime.now(UTC) + timedelta(days=30),
            "state_dimensions": ["x"],
            "model_requirements": {
                "forecast_spec": {
                    "spec_version": 2,
                    "goal_id": str(uuid4()),
                    "outcome": {"predicate": "metric_at_least", "metric": "x", "threshold": 10},
                    "deadline": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                    "family": "composed_growth",
                    "model_version": "1.0.0",
                    "primitives": [
                        {
                            "id": "primary",
                            "kind": "growth",
                            "metric": "x",
                            "config": {"eval": "1/0"},
                        }
                    ],
                    "composition": {"join": "single", "nodes": ["primary"]},
                }
            },
        }
    )
    assert spec_from_mapping(goal.model_requirements["forecast_spec"]) is None
    assert price_composition(goal, NumericInputs()) is None
