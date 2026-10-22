from datetime import UTC, datetime

from personal_markets.profile.parameters import (
    build_parameter_profile,
    demo_parameter_evidence,
    demo_parameter_profile,
)


def test_demo_parameter_profile_uses_estimator_not_hardcoded_polygon() -> None:
    as_of = datetime(2026, 10, 21, tzinfo=UTC)
    profile = demo_parameter_profile(as_of=as_of)
    assert "Demonstration" in profile.disclaimer
    measured = [item for item in profile.dimensions if item.value is not None]
    assert len(measured) >= 4
    keys = {item.key for item in profile.dimensions}
    assert "follow_through" not in keys
    assert "weekly_applications" in keys
    recomputed = build_parameter_profile(
        demo_parameter_evidence(as_of=as_of), as_of=as_of, demo=True
    )
    by_key = {item.key: item.value for item in recomputed.dimensions}
    for item in profile.dimensions:
        assert item.value == by_key[item.key]


def test_real_profile_omits_parameters_without_observations() -> None:
    profile = build_parameter_profile([], demo=False)
    assert profile.dimensions == []
    assert profile.execution.usable is False


def test_selected_parameter_ids_limit_axes() -> None:
    as_of = datetime(2026, 10, 21, tzinfo=UTC)
    profile = build_parameter_profile(
        demo_parameter_evidence(as_of=as_of),
        selected_ids=["weekly_applications", "monthly_savings"],
        as_of=as_of,
        demo=True,
    )
    assert {item.key for item in profile.dimensions} == {
        "weekly_applications",
        "monthly_savings",
    }
