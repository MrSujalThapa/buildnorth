from __future__ import annotations

from dataclasses import dataclass

READ = "goals:read"
GOALS_WRITE = "goals:write"
EVIDENCE_WRITE = "evidence:write"
SIMULATE = "whatif:simulate"
INFERENCE = "inference:use"

ALL_SCOPES: tuple[str, ...] = (READ, GOALS_WRITE, EVIDENCE_WRITE, SIMULATE, INFERENCE)
# Granted when a client asks for nothing specific. Spending model credits and
# creating goals are never implied; the client must request them and the user
# must approve them.
DEFAULT_SCOPES: tuple[str, ...] = (READ, EVIDENCE_WRITE, SIMULATE)


@dataclass(frozen=True, slots=True)
class ScopeInfo:
    scope: str
    label: str
    description: str
    writes: bool
    spends_credits: bool


SCOPE_INFO: dict[str, ScopeInfo] = {
    READ: ScopeInfo(
        READ,
        "Read goals and forecasts",
        "List your goals and read published forecasts, evidence summaries and history.",
        writes=False,
        spends_credits=False,
    ),
    GOALS_WRITE: ScopeInfo(
        GOALS_WRITE,
        "Create goals",
        "Start PlayItOut's Goal Architect to create a market. Nothing is saved until you confirm.",
        writes=True,
        spends_credits=True,
    ),
    EVIDENCE_WRITE: ScopeInfo(
        EVIDENCE_WRITE,
        "Submit evidence",
        "Add observations to your goals. Evidence is labeled as agent-reported and may "
        "republish a forecast.",
        writes=True,
        spends_credits=False,
    ),
    SIMULATE: ScopeInfo(
        SIMULATE,
        "Run What If scenarios",
        "Run hypothetical scenarios. They never change your published forecast.",
        writes=False,
        spends_credits=False,
    ),
    INFERENCE: ScopeInfo(
        INFERENCE,
        "Use model credits",
        "Let PlayItOut's agents interpret natural-language text, using your hosted credits "
        "or your own provider key.",
        writes=False,
        spends_credits=True,
    ),
}

# Scopes each tool needs. The gateway challenges with 403 insufficient_scope before
# the tool runs; tools also re-check so no handler relies on the gateway alone.
TOOL_SCOPES: dict[str, tuple[str, ...]] = {
    "list_goals": (READ,),
    "get_goal": (READ,),
    "get_forecast_readiness": (READ,),
    "list_milestones": (READ,),
    "get_forecast": (READ,),
    "get_forecast_history": (READ,),
    "get_evidence_summary": (READ,),
    "get_observation_policy": (READ,),
    "get_best_interventions": (READ,),
    "create_goal": (GOALS_WRITE, INFERENCE),
    "continue_goal_creation": (GOALS_WRITE, INFERENCE),
    "compare_forecasts": (READ,),
    "compare_scenarios": (SIMULATE,),
    "submit_structured_rows": (EVIDENCE_WRITE,),
    "submit_table_text": (EVIDENCE_WRITE,),
    "submit_file_bytes": (EVIDENCE_WRITE,),
    "show_odds_chart": (READ,),
    "get_odds_chart_image": (READ,),
    "submit_structured_evidence": (EVIDENCE_WRITE,),
    "submit_observation": (EVIDENCE_WRITE, INFERENCE),
    "simulate_intervention": (SIMULATE,),
}


def normalize_scopes(requested: list[str] | None) -> list[str]:
    if not requested:
        return list(DEFAULT_SCOPES)
    known = [scope for scope in ALL_SCOPES if scope in set(requested)]
    return known
