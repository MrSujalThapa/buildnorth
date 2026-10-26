from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from personal_markets.agents.intervention_service import InterventionAgentService
from personal_markets.forecasting.course_grade import (
    CourseGradeRequest,
    CourseGradeResult,
    evaluate_course_grade,
)
from personal_markets.goals.service import GoalService
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import Principal
from personal_markets.what_if.domain import (
    ActionFrontierResult,
    InterventionChangeInput,
    MarketHistoryPointResponse,
    PathComparisonRequest,
    PathComparisonResult,
    PossibleFuturesRequest,
    ScenarioDistribution,
    TargetSearchRequest,
    TargetSearchResult,
    WhatIfBaselineState,
    WhatIfExplorationResponse,
    WhatIfRequest,
    WhatIfResult,
)
from personal_markets.what_if.futures_decision import parse_futures_decision
from personal_markets.what_if.intervention_models import (
    ParseDecisionRequest,
    ParseDecisionResponse,
    ParseInterventionRequest,
    ParseInterventionResponse,
    TypedDecisionResponse,
)
from personal_markets.what_if.operationalize import resolve_option
from personal_markets.what_if.service import WhatIfService
from personal_markets.what_if.strategy_plan import StrategyChangesRequest, StrategyChangesResponse
from personal_markets.wiring import get_goal_service, get_intervention_service, get_what_if_service

router = APIRouter(prefix="/api/v1/what-if", tags=["what-if"])


@router.get("/baseline-state/{goal_id}", response_model=WhatIfBaselineState)
async def baseline_state(
    goal_id: str,
    service: Annotated[WhatIfService, Depends(get_what_if_service)],
) -> WhatIfBaselineState:
    return await service.baseline_state(goal_id)


@router.post("/simulate", response_model=WhatIfResult)
async def simulate(
    payload: WhatIfRequest,
    service: Annotated[WhatIfService, Depends(get_what_if_service)],
) -> WhatIfResult:
    started = perf_counter()
    result = await service.simulate(payload)
    return result.model_copy(
        update={"llm_calls": 0, "total_latency_ms": (perf_counter() - started) * 1000}
    )


@router.post("/fast-reprice", response_model=WhatIfResult)
async def fast_reprice(
    payload: WhatIfRequest,
    service: Annotated[WhatIfService, Depends(get_what_if_service)],
) -> WhatIfResult:
    started = perf_counter()
    result = await service.fast_reprice(payload)
    return result.model_copy(
        update={"llm_calls": 0, "total_latency_ms": (perf_counter() - started) * 1000}
    )


@router.get("/history/{goal_id}", response_model=list[MarketHistoryPointResponse])
async def history(
    goal_id: str,
    service: Annotated[WhatIfService, Depends(get_what_if_service)],
) -> list[MarketHistoryPointResponse]:
    return await service.history(goal_id)


@router.get("/explorations/{goal_id}", response_model=list[WhatIfExplorationResponse])
async def explorations(
    goal_id: str,
    service: Annotated[WhatIfService, Depends(get_what_if_service)],
) -> list[WhatIfExplorationResponse]:
    return await service.explorations(goal_id)


@router.post("/target-search", response_model=TargetSearchResult)
async def target_search(
    payload: TargetSearchRequest,
    service: Annotated[WhatIfService, Depends(get_what_if_service)],
) -> TargetSearchResult:
    return await service.target_search(payload)


@router.post("/action-frontier", response_model=ActionFrontierResult)
async def action_frontier(
    payload: TargetSearchRequest,
    service: Annotated[WhatIfService, Depends(get_what_if_service)],
) -> ActionFrontierResult:
    return await service.action_frontier(payload)


@router.post("/possible-futures", response_model=ScenarioDistribution)
async def possible_futures(
    payload: PossibleFuturesRequest,
    service: Annotated[WhatIfService, Depends(get_what_if_service)],
) -> ScenarioDistribution:
    return await service.possible_futures(payload)


@router.post("/compare-paths", response_model=PathComparisonResult)
async def compare_paths(
    payload: PathComparisonRequest,
    service: Annotated[WhatIfService, Depends(get_what_if_service)],
) -> PathComparisonResult:
    return await service.compare_paths(payload)


@router.post("/parse-decision", response_model=ParseDecisionResponse)
async def parse_decision(
    payload: ParseDecisionRequest,
    principal: Annotated[Principal, Depends(get_invited_principal)],
    goals: Annotated[GoalService, Depends(get_goal_service)],
) -> ParseDecisionResponse:
    goal = await goals.get_goal_by_string(payload.goal_id, owner_id=principal.user_id)
    parsed = parse_futures_decision(payload.text, goal=goal)
    decision = None
    if parsed.decision is not None:
        decision = TypedDecisionResponse(
            action=parsed.decision.action,
            alternative=parsed.decision.alternative,
            timing=parsed.decision.timing,
            constraints=list(parsed.decision.constraints),
        )
    return ParseDecisionResponse(
        raw_text=parsed.raw_text,
        decision=decision,
        scenario_labels=list(parsed.scenario_labels),
        unsupported=list(parsed.unsupported),
        changes=InterventionAgentService.explicit_changes(goal, payload.text) or [],
    )


@router.post("/parse-intervention", response_model=ParseInterventionResponse)
async def parse_intervention(
    payload: ParseInterventionRequest,
    service: Annotated[InterventionAgentService, Depends(get_intervention_service)],
) -> ParseInterventionResponse:
    return await service.parse(payload.goal_id, payload.text)


@router.post("/strategy-changes", response_model=StrategyChangesResponse)
async def strategy_changes(
    payload: StrategyChangesRequest,
    service: Annotated[WhatIfService, Depends(get_what_if_service)],
) -> StrategyChangesResponse:
    """Deterministic: turns the user's chosen option and inputs into model changes."""
    baseline = await service.baseline_state(payload.goal_id)
    return resolve_option(
        baseline, payload.family, payload.option_id, payload.inputs, payload.text
    )


class PlanEvaluationRequest(BaseModel):
    goal_id: str
    changes: list[InterventionChangeInput] = Field(min_length=1, max_length=5)


@router.post("/plan-evaluation", response_model=WhatIfResult)
async def plan_evaluation(
    payload: PlanEvaluationRequest,
    service: Annotated[WhatIfService, Depends(get_what_if_service)],
) -> WhatIfResult:
    """Conditional odds for an adopted plan under today's evidence. Not a forecast."""
    return await service.evaluate_plan(payload.goal_id, payload.changes)


@router.post("/course-grade", response_model=CourseGradeResult)
async def course_grade(
    payload: CourseGradeRequest,
    _: Annotated[Principal, Depends(get_invited_principal)],
) -> CourseGradeResult:
    """Syllabus arithmetic only. Hypothetical remaining scores are not stored."""
    return evaluate_course_grade(payload)
