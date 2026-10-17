from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from personal_markets.behavior.domain import ActionContext, CommitmentTrial
from personal_markets.behavior.tokenize import overlap_score, tokenize
from personal_markets.evidence.domain import NormalizedEvidence

COMPLETION_MARKERS = frozenset(
    {"completed", "complete", "done", "attended", "hit", "success", "kept", "yes", "true"}
)
MISS_MARKERS = frozenset({"missed", "miss", "skipped", "absent", "failed", "no", "false"})
PLAN_MARKERS = frozenset({"created", "planned", "scheduled", "commitment", "intent"})
BEHAVIOR_EVENT_TYPES = frozenset(
    {
        "commitment_created",
        "commitment_completed",
        "commitment_missed",
        "practice",
        "workout",
        "habit",
        "session",
        "study",
        "planned_block",
    }
)
ACTIVITY_ONLY_TYPES = frozenset(
    {"repository_activity", "issue_activity", "observation", "note", "external_event"}
)


def session_key(observed_at: datetime, action_type: str, source: str) -> str:
    day = observed_at.astimezone(UTC).date().isoformat()
    return f"{day}|{action_type}|{source}"


def collapse_correlated_events(trials: list[CommitmentTrial]) -> list[CommitmentTrial]:
    """Count one coding session as one trial, not one trial per commit."""

    grouped: dict[str, list[CommitmentTrial]] = defaultdict(list)
    for trial in trials:
        grouped[trial.session_key].append(trial)
    collapsed: list[CommitmentTrial] = []
    for key, rows in grouped.items():
        rows = sorted(rows, key=lambda item: item.observed_at)
        first = rows[0]
        planned = [item.planned_amount for item in rows if item.planned_amount is not None]
        realized = [item.realized_amount for item in rows if item.realized_amount is not None]
        collapsed.append(
            first.model_copy(
                update={
                    "trial_id": f"session:{key}",
                    "session_key": key,
                    "outcome": max(item.outcome for item in rows),
                    "planned_amount": max(planned) if planned else first.planned_amount,
                    "realized_amount": sum(realized) if realized else first.realized_amount,
                    "event_count": sum(item.event_count for item in rows),
                    "tokens": sorted({token for item in rows for token in item.tokens}),
                }
            )
        )
    return sorted(collapsed, key=lambda item: item.observed_at)


def _parse_observed_at(value: object) -> datetime | None:
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str) and value not in {"", "unknown"}:
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp


def trials_from_evidence(events: Iterable[NormalizedEvidence]) -> list[CommitmentTrial]:
    planned: list[NormalizedEvidence] = []
    observed: list[NormalizedEvidence] = []
    for event in events:
        event_type = event.event_type.lower()
        category = (event.categorical_value or "").lower()
        if event_type in ACTIVITY_ONLY_TYPES and event_type not in BEHAVIOR_EVENT_TYPES:
            continue
        if event_type == "commitment_created" or category in PLAN_MARKERS or event.metric.endswith(
            "_planned"
        ):
            planned.append(event)
        elif (
            event_type in {"commitment_completed", "commitment_missed"}
            or category in COMPLETION_MARKERS
            or category in MISS_MARKERS
            or event_type in BEHAVIOR_EVENT_TYPES
        ):
            observed.append(event)

    used: set[int] = set()
    trials: list[CommitmentTrial] = []
    for index, plan in enumerate(planned):
        stamp = _parse_observed_at(plan.observed_at)
        if stamp is None:
            continue
        match = _best_match(plan, observed, stamp, used)
        outcome = 0.0
        realized = None
        delay = None
        source = plan.provenance.source_type
        quality = plan.source_quality
        if match is not None:
            match_index, completion = match
            used.add(match_index)
            realized = completion.numeric_value
            completed_at = _parse_observed_at(completion.observed_at)
            category = (completion.categorical_value or "").lower()
            if completion.event_type.lower() == "commitment_missed" or category in MISS_MARKERS:
                outcome = 0.0
            elif category in COMPLETION_MARKERS or completion.event_type.lower() == "commitment_completed":
                outcome = 1.0
            elif plan.numeric_value and realized is not None and plan.numeric_value > 0:
                outcome = min(1.0, max(0.0, realized / plan.numeric_value))
            else:
                outcome = 1.0
            if completed_at is not None:
                delay = max(0.0, (completed_at - stamp).total_seconds() / 86400)
            source = completion.provenance.source_type
            quality = completion.source_quality
        action = _action_type(plan)
        trials.append(
            CommitmentTrial(
                trial_id=f"plan:{index}:{plan.fingerprint[:12]}",
                domain=plan.domain or "general",
                action_type=action,
                plan_class=action,
                planned_amount=plan.numeric_value,
                realized_amount=realized,
                unit=plan.unit,
                outcome=outcome,
                observed_at=stamp,
                delay_days=delay,
                session_key=session_key(stamp, action, source),
                source=source,
                source_quality=quality,
                tokens=tokenize(plan.domain, plan.metric, plan.summary, plan.event_type),
            )
        )

    for index, event in enumerate(observed):
        if index in used:
            continue
        # Completions without a plan are activity, not follow-through trials.
        if event.event_type.lower() not in {"commitment_completed", "commitment_missed"}:
            continue
        stamp = _parse_observed_at(event.observed_at)
        if stamp is None:
            continue
        category = (event.categorical_value or "").lower()
        outcome = 0.0 if event.event_type.lower() == "commitment_missed" or category in MISS_MARKERS else 1.0
        action = _action_type(event)
        trials.append(
            CommitmentTrial(
                trial_id=f"obs:{index}:{event.fingerprint[:12]}",
                domain=event.domain or "general",
                action_type=action,
                plan_class=action,
                planned_amount=event.numeric_value,
                realized_amount=event.numeric_value if outcome else 0.0,
                unit=event.unit,
                outcome=outcome,
                observed_at=stamp,
                session_key=session_key(stamp, action, event.provenance.source_type),
                source=event.provenance.source_type,
                source_quality=event.source_quality,
                tokens=tokenize(event.domain, event.metric, event.summary, event.event_type),
            )
        )
    return collapse_correlated_events(trials)


def _action_type(event: NormalizedEvidence) -> str:
    metric = event.metric.lower()
    if metric:
        return metric
    return event.event_type.lower() or "unspecified"


def _best_match(
    plan: NormalizedEvidence,
    observed: list[NormalizedEvidence],
    plan_at: datetime,
    used: set[int],
) -> tuple[int, NormalizedEvidence] | None:
    window = timedelta(days=7)
    best: tuple[float, int, NormalizedEvidence] | None = None
    plan_tokens = tokenize(plan.domain, plan.metric, plan.summary)
    for index, event in enumerate(observed):
        if index in used:
            continue
        stamp = _parse_observed_at(event.observed_at)
        if stamp is None or stamp < plan_at - timedelta(hours=6) or stamp > plan_at + window:
            continue
        if plan.domain and event.domain and plan.domain != event.domain:
            continue
        score = overlap_score(
            plan_tokens,
            tokenize(event.domain, event.metric, event.summary),
            plan.summary,
            event.summary,
        )
        if plan.metric and event.metric and plan.metric.split("_")[0] == event.metric.split("_")[0]:
            score += 0.4
        if best is None or score > best[0]:
            best = (score, index, event)
    if best is None or best[0] < 0.05:
        return None
    return best[1], best[2]


def context_from_text(text: str, *, domain: str = "general", planned_amount: float | None = None) -> ActionContext:
    tokens = tokenize(text, domain)
    action = tokens[0] if tokens else "unspecified"
    return ActionContext(
        action_type=action,
        domain=domain,
        planned_amount=planned_amount,
        tokens=tokens,
        description=text,
    )
