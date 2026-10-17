from personal_markets.forecasting.families import AssumptionSource
from personal_markets.what_if.domain import Assumption
from personal_markets.what_if.intervention_models import InterventionChangeResponse
from personal_markets.what_if.intervention_overrides import (
    apply_parsed_changes_to_assumptions,
    changes_to_state_overrides,
)


def _flow_assumption(value: float = 6000) -> Assumption:
    return Assumption(
        name="flow",
        value=value,
        minimum=0,
        maximum=20_000,
        step=100,
        source=AssumptionSource.USER,
        unit="currency/month",
    )


def test_monthly_contribution_updates_flow_assumption() -> None:
    assumptions = [_flow_assumption()]
    changes = [
        InterventionChangeResponse(
            metric="monthly_contribution",
            operation="set",
            value=1500,
            unit="currency/month",
            provenance="USER_ASSUMPTION",
        )
    ]
    updated = apply_parsed_changes_to_assumptions(assumptions, changes)
    assert updated[0].value == 1500
    assert updated[0].source == AssumptionSource.USER


def test_changes_to_state_overrides_maps_domain_keys() -> None:
    changes = [
        InterventionChangeResponse(
            metric="monthly_contribution",
            operation="set",
            value=500,
            unit="currency/month",
            provenance="USER_ASSUMPTION",
        ),
        InterventionChangeResponse(
            metric="weekly_running_km",
            operation="set",
            value=40,
            unit="km/week",
            provenance="USER_ASSUMPTION",
        ),
    ]
    assert changes_to_state_overrides(changes) == {
        "monthly_contribution": 500,
        "weekly_distance_km": 40.0,
    }
