from datetime import UTC, datetime, timedelta
from uuid import uuid4

from personal_markets.behavior.domain import CommitmentTrial
from personal_markets.behavior.traits import (
    DEFAULT_TRAIT_IDS,
    TraitEstimate,
    TraitProfile,
    context_for_domain,
    custom_trait_from_name,
    estimate_traits,
)
from personal_markets.evidence.domain import NormalizedEvidence, Provenance

NOW = datetime(2026, 10, 20, tzinfo=UTC)


def _trial(
    days_ago: float,
    outcome: float,
    *,
    domain: str = "career",
    planned: float = 5.0,
    realized: float | None = None,
    delay: float | None = 0.0,
) -> CommitmentTrial:
    observed = NOW - timedelta(days=days_ago)
    return CommitmentTrial(
        trial_id=str(uuid4()),
        domain=domain,
        action_type="practice",
        planned_amount=planned,
        realized_amount=planned * outcome if realized is None else realized,
        outcome=outcome,
        observed_at=observed,
        delay_days=delay,
        session_key=str(uuid4()),
        source="commitment",
    )


def _evidence(
    metric: str, value: float, days_ago: float, domain: str = "career"
) -> NormalizedEvidence:
    return NormalizedEvidence(
        evidence_id=uuid4(),
        event_type="observation",
        domain=domain,
        metric=metric,
        numeric_value=value,
        observed_at=NOW - timedelta(days=days_ago),
        source_quality="user_entered",
        provenance=Provenance(
            source_type="manual",
            source_authority="self_report",
            observed_vs_entered="user_entered",
            parsing_status="ok",
            completeness="complete",
            conflict_status="none",
        ),
        summary=metric,
        fingerprint=str(uuid4()),
    )


def _trait(profile: TraitProfile, trait_id: str) -> TraitEstimate:
    return next(item for item in profile.traits if item.id == trait_id)


def test_empty_profile_has_axes_but_no_fabricated_values() -> None:
    profile = estimate_traits([], [], as_of=NOW)
    assert [item.id for item in profile.traits] == list(DEFAULT_TRAIT_IDS)
    assert all(item.value is None for item in profile.traits)
    assert all(item.confidence == "insufficient" for item in profile.traits)
    assert [series.id for series in profile.series] == ["overall"]


def test_discipline_needs_enough_trials_and_tracks_follow_through() -> None:
    sparse = estimate_traits([_trial(3, 1.0), _trial(2, 1.0)], [], as_of=NOW)
    assert _trait(sparse, "discipline").value is None
    reliable = estimate_traits([_trial(day, 1.0) for day in range(1, 13)], [], as_of=NOW)
    flaky = estimate_traits(
        [_trial(day, 1.0 if day % 3 == 0 else 0.0, realized=0) for day in range(1, 13)],
        [],
        as_of=NOW,
    )
    high = _trait(reliable, "discipline")
    low = _trait(flaky, "discipline")
    assert high.value is not None and low.value is not None
    assert high.value > 0.75 > 0.5 > low.value
    assert high.interval is not None and high.interval[0] <= high.value <= high.interval[1]
    assert high.forecast_use == "execution_probability"


def test_realism_penalizes_overdelivery_as_well_as_shortfall() -> None:
    matched = estimate_traits(
        [_trial(day, 1.0, planned=5, realized=5) for day in range(1, 9)], [], as_of=NOW
    )
    overshoot = estimate_traits(
        [_trial(day, 1.0, planned=5, realized=12) for day in range(1, 9)], [], as_of=NOW
    )
    shortfall = estimate_traits(
        [_trial(day, 0.4, planned=5, realized=2) for day in range(1, 9)], [], as_of=NOW
    )
    exact = _trait(matched, "realism").value
    assert exact is not None and exact > 0.8
    assert (_trait(overshoot, "realism").value or 1) < exact
    assert (_trait(shortfall, "realism").value or 1) < exact
    # Realism is calibration, not follow-through: overshooting keeps discipline high.
    assert (_trait(overshoot, "discipline").value or 0) > 0.75


def test_focus_comes_from_on_task_share_not_hours_logged() -> None:
    hours_only = estimate_traits(
        [], [_evidence("hours_per_week", 40, day) for day in range(1, 10)], as_of=NOW
    )
    assert _trait(hours_only, "focus").value is None
    sessions = estimate_traits(
        [], [_evidence("focus_ratio", 0.82, day) for day in range(1, 10)], as_of=NOW
    )
    distracted = estimate_traits(
        [], [_evidence("focus_ratio", 0.35, day) for day in range(1, 10)], as_of=NOW
    )
    assert (_trait(sessions, "focus").value or 0) > (_trait(distracted, "focus").value or 1)


def test_time_management_is_discounted_when_commitments_exceed_capacity() -> None:
    trials = [_trial(day, 1.0, delay=0.0) for day in range(1, 11)]
    roomy = estimate_traits(
        trials,
        [
            _evidence("available_hours_per_week", 20, 2),
            _evidence("committed_hours_per_week", 15, 2),
        ],
        as_of=NOW,
    )
    overbooked = estimate_traits(
        trials,
        [
            _evidence("available_hours_per_week", 10, 2),
            _evidence("committed_hours_per_week", 25, 2),
        ],
        as_of=NOW,
    )
    roomy_value = _trait(roomy, "time_management").value
    overbooked_value = _trait(overbooked, "time_management").value
    assert roomy_value is not None and overbooked_value is not None
    assert overbooked_value < roomy_value * 0.5


def test_consistency_separates_steady_from_bursty_weeks() -> None:
    steady = [
        _trial(week * 7 + offset, 1.0 if offset else 0.0)
        for week in range(6)
        for offset in range(3)
    ]
    bursty = [
        _trial(week * 7 + offset, 1.0 if week % 2 else 0.0)
        for week in range(6)
        for offset in range(3)
    ]
    steady_value = _trait(estimate_traits(steady, [], as_of=NOW), "consistency").value
    bursty_value = _trait(estimate_traits(bursty, [], as_of=NOW), "consistency").value
    assert steady_value is not None and bursty_value is not None
    assert steady_value > bursty_value


def test_recovery_scores_what_happens_after_misses() -> None:
    quick = [_trial(30 - 2 * i, 0.0 if i % 2 == 0 else 1.0) for i in range(12)]
    profile = estimate_traits(quick, [], selected=["discipline", "recovery", "focus"], as_of=NOW)
    assert (_trait(profile, "recovery").value or 0) > 0.6


def test_context_series_only_appear_when_contexts_have_real_trials() -> None:
    career_only = estimate_traits([_trial(day, 1.0) for day in range(1, 15)], [], as_of=NOW)
    assert [series.id for series in career_only.series] == ["overall"]
    mixed = [
        *(_trial(day, 1.0, domain="hiring") for day in range(1, 15)),
        *(_trial(day, 0.0 if day % 2 else 1.0, domain="running") for day in range(1, 15)),
    ]
    profile = estimate_traits(mixed, [], as_of=NOW)
    assert [series.id for series in profile.series] == ["career", "personal"]
    career, personal = profile.series
    assert (career.values["discipline"] or 0) > (personal.values["discipline"] or 1)
    assert context_for_domain("family_dinner") == "relationships"


def test_custom_trait_scores_only_its_own_metric() -> None:
    creative = custom_trait_from_name("Creative focus", "Time in a creative flow state.")
    unsupported = estimate_traits(
        [], [], selected=["discipline", "focus", creative.id], custom=[creative], as_of=NOW
    )
    assert _trait(unsupported, creative.id).value is None
    supported = estimate_traits(
        [],
        [_evidence(creative.metric, 0.7, day, domain="creative") for day in range(1, 8)],
        selected=["discipline", "focus", creative.id],
        custom=[creative],
        as_of=NOW,
    )
    value = _trait(supported, creative.id).value
    assert value is not None and 0.55 < value < 0.8


def test_change_readout_reflects_recent_evidence() -> None:
    improving = [
        *(_trial(60 - day, 0.0, realized=0) for day in range(10)),
        *(_trial(day, 1.0) for day in range(1, 12)),
    ]
    trait = _trait(estimate_traits(improving, [], as_of=NOW), "discipline")
    assert trait.value is not None and trait.previous_value is not None
    assert trait.value > trait.previous_value
