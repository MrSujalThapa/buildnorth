"""Deterministic Goal Architect refinement and primitive selection.

The LLM proposes a typed goal. This module chooses a registered primitive
composition or keeps an existing domain adapter. It never assigns a probability.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from personal_markets.evidence.metrics import canonicalize_metric, is_rate_label, stock_concept
from personal_markets.forecasting.compiler import (
    CompositionGraph,
    ForecastSpecV2,
    ObservableInput,
    OutcomeSpec,
    PrimitiveNode,
    compile_spec,
)
from personal_markets.forecasting.primitives import COMPILER_VERSION, PRIMITIVE_VERSIONS
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.targets import parse_number
from personal_markets.ports import ClarificationQuestion, GoalArchitectProposal

_UNMEASURABLE = (
    "successful",
    "success someday",
    "happy",
    "fulfilled",
    "better person",
    "extremely successful",
)
_COUNT_UNITS = {"count", "countries", "books", "videos", "customers", "subscribers", "users"}
_GROWTH_TOKENS = (
    "subscriber",
    "followers",
    "audience",
    "mrr",
    "traffic",
    "visitors",
    "views",
)
_COUNT_TOKENS = (
    "countries",
    "books",
    "videos",
    "customers",
    "posts",
    "articles",
    "certifications",
    "visits",
)
_THRESHOLD_TOKENS = (
    "marathon",
    "half marathon",
    "pace",
    "lift",
    "exam",
    "score",
    "kg",
    "lb",
    "minutes",
    "hours",
)
_FUNNEL_TOKENS = ("interview", "application", "offer", "pipeline", "conversion")
_DAG_TOKENS = ("then", "after", "launch", "milestone", "and then")


def refine_architect_proposal(proposal: GoalArchitectProposal) -> GoalArchitectProposal:
    """Fill primitive selection and targeted clarifications. Does not invent parameters."""
    if not isinstance(proposal, GoalArchitectProposal):
        proposal = GoalArchitectProposal.model_validate(proposal)
    blob = _blob(proposal)
    if _unmeasurable(proposal, blob) and not proposal.clarifications_required:
        return proposal.model_copy(
            update={
                "ready_to_commit": False,
                "model_family_compatibility": "none",
                "clarifications_required": [
                    ClarificationQuestion(
                        id="measurable_outcome",
                        question="What measurable result counts as success, and by what date?",
                        why_needed="A probability needs a numeric success criterion and a horizon.",
                    )
                ],
                "notes": (proposal.notes + " Unmeasurable outcome refused.").strip(),
            }
        )
    inferred = infer_primitive_kind(proposal)
    kind = proposal.primitive_kind or inferred
    # Sequential launch → then → milestone is a DAG even if the architect labelled it a
    # funnel or growth process. Hiring pipelines stay a funnel: "after applying" is not
    # a product-launch DAG, and empty DAG nodes only accept the final offer event.
    if inferred == "funnel":
        kind = "funnel"
    elif inferred == "dependency_dag":
        kind = "dependency_dag"
    clarifications = list(proposal.clarifications_required)
    if proposal.success_target in {"", "unspecified"} and not any(
        item.id == "success_target" for item in clarifications
    ):
        clarifications.append(
            ClarificationQuestion(
                id="success_target",
                question="What numeric target defines success?",
                why_needed="The model needs an explicit threshold or event definition.",
            )
        )
    if _needs_current_state(kind, proposal) and not any(
        item.id == "current_state" for item in clarifications
    ):
        clarifications.append(
            ClarificationQuestion(
                id="current_state",
                question=f"What is the current {proposal.success_metric or 'value'}?",
                why_needed="The starting state defines remaining distance to the target.",
            )
        )
    if kind in {"growth", "cumulative_count"} and not any(
        item.id == "history_available" for item in clarifications
    ):
        clarifications.append(
            ClarificationQuestion(
                id="history_available",
                question="Do you have dated measurements (CSV, spreadsheet, or a few past values)?",
                why_needed=(
                    "Rate or growth is estimated from your history; "
                    "no generic prior is invented."
                ),
            )
        )
    ready = proposal.ready_to_commit and not clarifications
    if proposal.ready_to_commit and proposal.success_metric not in {"", "unspecified"}:
        # Outcome-definition questions block commit; precision-only history questions do not
        # if the user already stated a measurable target and deadline.
        blocking = [
            item for item in clarifications if item.id in {"measurable_outcome", "success_target"}
        ]
        ready = proposal.ready_to_commit and not blocking
        if not blocking:
            clarifications = [item for item in clarifications if item.id != "history_available"]
            current_known = bool(proposal.current_state_known)
            if current_known:
                clarifications = [item for item in clarifications if item.id != "current_state"]
            ready = True
    family = {
        "cumulative_count": "composed_cumulative_count",
        "growth": "composed_growth",
        "funnel": "composed_funnel",
        "dependency_dag": "composed_dependency_dag",
        "continuous_threshold": "composed_continuous_threshold",
        "habit": "habit_beta_recency",
        "deadline_hazard": "deadline_event_hazard",
        "financial": "continuous_target_transition",
    }.get(kind, proposal.model_family_compatibility)
    primitives = proposal.primitives or (
        [{"id": "primary", "kind": kind, "config": {}}] if kind else []
    )
    return proposal.model_copy(
        update={
            "primitive_kind": kind,
            "primitives": primitives,
            "clarifications_required": clarifications,
            "ready_to_commit": ready,
            "model_family_compatibility": family,
        }
    )


def infer_primitive_kind(proposal: GoalArchitectProposal) -> str | None:
    blob = _blob(proposal)
    if proposal.goal_type == "habit":
        return "habit"
    outcome = " ".join(
        [proposal.title, proposal.success_metric, proposal.success_target]
    ).lower()
    hiring_funnel = any(token in outcome for token in _FUNNEL_TOKENS)
    sequential_launch = (
        proposal.goal_type == "multi_outcome" or any(token in blob for token in _DAG_TOKENS)
    ) and ("launch" in blob or "then" in blob or "milestone" in blob)
    if sequential_launch and not hiring_funnel:
        return "dependency_dag"
    if hiring_funnel and proposal.goal_type in {"deadline_event", "multi_outcome"}:
        return "funnel"
    if any(token in blob for token in _GROWTH_TOKENS):
        return "growth"
    if (
        any(token in blob for token in _COUNT_TOKENS)
        or (proposal.success_unit or "").lower() in _COUNT_UNITS
    ):
        return "cumulative_count"
    if any(token in blob for token in _THRESHOLD_TOKENS) or proposal.goal_type == "threshold":
        if any(token in blob for token in ("$", "usd", "cad", "eur", "dollar", "saving")):
            return "financial"
        return "continuous_threshold"
    if proposal.goal_type == "continuous_target":
        return "financial" if any(token in blob for token in ("$", "usd", "dollar")) else "growth"
    if proposal.goal_type == "deadline_event":
        return "deadline_hazard"
    return None


def preferred_domain_adapter(goal: GoalContract, proposal: GoalArchitectProposal) -> bool:
    from personal_markets.forecasting.finance import is_finance_goal
    from personal_markets.forecasting.hiring import is_hiring_goal
    from personal_markets.forecasting.running import is_running_goal
    from personal_markets.forecasting.startup import is_startup_goal

    kind = proposal.primitive_kind or infer_primitive_kind(proposal)
    hiring = is_hiring_goal(goal, proposal)
    running = is_running_goal(goal, proposal)
    startup = is_startup_goal(goal, proposal)
    finance = is_finance_goal(goal, proposal)
    if kind == "dependency_dag":
        return False
    if kind == "cumulative_count":
        return False
    if kind == "growth":
        # Keep the startup adapter for plain MRR goals; audience growth is composed.
        return bool(startup and not hiring)
    if kind in {"funnel", "deadline_hazard"}:
        return hiring
    if kind == "continuous_threshold":
        return running
    if kind == "habit":
        return True
    if kind == "financial":
        return bool(finance or startup)
    return bool(hiring or running or startup or finance)


def compose_spec(goal: GoalContract, proposal: GoalArchitectProposal) -> ForecastSpecV2 | None:
    kind = proposal.primitive_kind or infer_primitive_kind(proposal)
    if kind is None:
        return None
    metric = proposal.success_metric
    threshold = parse_number(proposal.success_target)
    predicate = "event_by_deadline"
    if proposal.success_operator in {">=", ">"}:
        predicate = "metric_at_least"
    elif proposal.success_operator in {"<=", "<"}:
        predicate = "metric_at_most"
    elif kind == "habit":
        predicate = "habit_rate"
    node = PrimitiveNode(
        id="primary",
        kind=kind,  # type: ignore[arg-type]
        metric=metric,
        unit=proposal.success_unit,
        state_bindings={"current": metric},
        config=_default_config(kind, proposal),
    )
    extra: list[PrimitiveNode] = []
    join: str = "single"
    if kind == "dependency_dag":
        extra = _milestone_nodes(proposal)
        if extra:
            node = extra[0]
            join = "sequential_and"
    primitives = extra or [node]
    spec = ForecastSpecV2(
        goal_id=goal.goal_id,
        goal_contract_version=goal.version,
        outcome=OutcomeSpec(
            predicate=predicate,  # type: ignore[arg-type]
            metric=metric,
            threshold=threshold,
            units=proposal.success_unit,
        ),
        deadline=goal.deadline,
        units=proposal.success_unit,
        family=f"composed_{kind}",
        model_version=PRIMITIVE_VERSIONS.get(kind, "1.0.0"),
        primitives=primitives,
        composition=CompositionGraph(join=join, nodes=[item.id for item in primitives]),  # type: ignore[arg-type]
        required_state=[metric]
        if kind in {"cumulative_count", "growth", "continuous_threshold"}
        else [],
        required_parameters=_required_parameters(kind),
        observable_inputs=[
            ObservableInput(
                metric=metric,
                unit=proposal.success_unit,
                kind="snapshot" if kind != "habit" else "categorical",
                aliases=_stock_aliases(metric, proposal.state_dimensions),
            )
        ],
        research_required=proposal.research_required,
        research_questions=list(proposal.research_questions),
        compiler_version=COMPILER_VERSION,
        assumptions=[
            "Parameters are estimated from this user's evidence or explicit assumptions.",
            "No LLM-generated probability is used.",
        ],
        limitations=["Composition compatibility does not imply empirical calibration."],
        status="NEEDS_INPUT",
    )
    result = compile_spec(spec)
    return result.spec if result.accepted else None


def _stock_aliases(metric: str, dimensions: list[str]) -> list[str]:
    """Labels that name the same stock as `metric`; rate/frequency dimensions are excluded."""
    concept = stock_concept(metric)
    aliases = [concept] if concept and canonicalize_metric(metric) != concept else []
    for dimension in dimensions:
        if is_rate_label(dimension):
            continue
        if canonicalize_metric(dimension) == canonicalize_metric(metric) or (
            concept is not None and stock_concept(dimension) == concept
        ):
            aliases.append(dimension)
    return list(dict.fromkeys(aliases))


def _default_config(kind: str, proposal: GoalArchitectProposal) -> dict[str, Any]:
    if kind == "funnel":
        stages = [item for item in proposal.state_dimensions[:4] if item]
        if len(stages) < 2:
            stages = ["start", "success"]
        return {"stages": stages, "time_unit": "week"}
    if kind == "growth":
        return {"process": "loglinear", "time_unit": "week"}
    if kind == "cumulative_count":
        return {"process": "poisson", "time_unit": "week"}
    if kind == "continuous_threshold":
        direction = "at_most" if proposal.success_operator in {"<=", "<"} else "at_least"
        return {"direction": direction, "time_unit": "week"}
    if kind == "dependency_dag":
        return {"nodes": [], "correlation": "unspecified", "n_draws": 4000, "seed": 42}
    return {"time_unit": "week"}


def _milestone_nodes(proposal: GoalArchitectProposal) -> list[PrimitiveNode]:
    """Each milestone target must be stated by the user; no default targets are assumed."""
    sources = [proposal.success_target, proposal.success_metric, proposal.title]
    customer_target = _first_match(sources, _customer_target)
    revenue_target = _first_match(sources, _currency_amount)
    if (
        revenue_target is None
        and "mrr" in proposal.success_metric.lower()
        and "customer" not in proposal.success_target.lower()
    ):
        revenue_target = parse_number(proposal.success_target)
    if customer_target is None and revenue_target is None:
        return []
    nodes = [
        PrimitiveNode(
            id="launch",
            kind="deadline_hazard",
            metric="launched",
            state_bindings={"current": "launched"},
            config={"time_unit": "week", "target": 1.0},
        )
    ]
    if customer_target is not None:
        nodes.append(
            PrimitiveNode(
                id="customers",
                kind="cumulative_count",
                metric="customers",
                state_bindings={"current": "customers"},
                config={"process": "poisson", "time_unit": "week", "target": customer_target},
                prerequisites=["launch"],
            )
        )
    if revenue_target is not None:
        nodes.append(
            PrimitiveNode(
                id="revenue",
                kind="growth",
                metric="mrr",
                state_bindings={"current": "mrr"},
                config={"process": "loglinear", "time_unit": "week", "target": revenue_target},
                prerequisites=[nodes[-1].id],
            )
        )
    return nodes


def _first_match(sources: list[str], extract: Callable[[str], float | None]) -> float | None:
    for source in sources:
        value = extract(source.lower())
        if value is not None:
            return value
    return None


def _customer_target(text: str) -> float | None:
    match = re.search(r"(\d[\d,]*)\s+(?:[a-z]+\s+)?customers?\b", text)
    return float(match.group(1).replace(",", "")) if match else None


def _currency_amount(text: str) -> float | None:
    match = re.search(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k\b)?", text)
    if match is None:
        return None
    value = float(match.group(1).replace(",", ""))
    return value * 1000 if match.group(2) else value


def _required_parameters(kind: str) -> list[str]:
    return {
        "cumulative_count": ["rate"],
        "growth": ["mu", "sigma"],
        "continuous_threshold": ["trend", "noise"],
        "funnel": ["conversions"],
        "deadline_hazard": ["baseline_logit"],
        "habit": ["prior_alpha", "prior_beta"],
        "dependency_dag": ["durations"],
        "financial": ["return_distribution"],
    }.get(kind, [])


def _blob(proposal: GoalArchitectProposal) -> str:
    return " ".join(
        [
            proposal.title,
            proposal.success_metric,
            proposal.success_target,
            proposal.success_unit or "",
            proposal.notes,
            " ".join(proposal.state_dimensions),
        ]
    ).lower()


def _unmeasurable(proposal: GoalArchitectProposal, blob: str) -> bool:
    if parse_number(proposal.success_target) is not None:
        return False
    if (
        proposal.success_metric not in {"", "unspecified"}
        and proposal.goal_type == "deadline_event"
    ):
        return False
    return any(token in blob for token in _UNMEASURABLE) or proposal.success_metric in {
        "",
        "unspecified",
        "success",
    }


def _needs_current_state(kind: str | None, proposal: GoalArchitectProposal) -> bool:
    if kind not in {"cumulative_count", "growth", "continuous_threshold"}:
        return False
    return not proposal.current_state_known
