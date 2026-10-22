import type { ParsedInterventionChange, WhatIfBaselineState } from "../api/client";

type InterventionPayload = Record<string, unknown>;
type AnalysisDepth = "simple" | "deep";

export function simulationConfigForView(
  view: AnalysisDepth,
  seed: number,
): Record<string, number> {
  if (view === "deep") {
    return {
      seed,
      minimum_draws: 8000,
      batch_draws: 4000,
      maximum_draws: 20000,
    };
  }
  return {
    seed,
    minimum_draws: 2000,
    batch_draws: 2000,
    maximum_draws: 4000,
  };
}

function fallbackIntervention(
  baseline: WhatIfBaselineState,
  title: string,
): InterventionPayload {
  const current = (baseline.default_intervention ?? {}) as InterventionPayload;
  return {
    id: typeof current.id === "string" && current.id ? current.id : "custom-path",
    title,
    action_type: typeof current.action_type === "string" ? current.action_type : "flow_change",
    target_dimension:
      typeof current.target_dimension === "string" ? current.target_dimension : "target",
    amount: 1,
    unit: "units/period",
    duration_periods: baseline.periods ?? 8,
    effect_per_unit: null,
    effect_source: null,
    diminishing_return: Number(current.diminishing_return ?? 0),
    cost: current.cost ?? { hours_per_week: 0, money: 0, energy: 0 },
  };
}

export function buildWhatIfRequestFromBaseline(
  goalId: string,
  baseline: WhatIfBaselineState,
  intervention: WhatIfBaselineState["default_intervention"] = baseline.default_intervention,
  view: AnalysisDepth = "simple",
): Record<string, unknown> {
  return {
    goal_id: goalId,
    current_value: baseline.current_value ?? 0,
    target_value: baseline.target_value ?? 1,
    periods: baseline.periods ?? 8,
    direction: baseline.direction,
    assumptions: baseline.assumptions,
    intervention,
    parsed_changes: [],
    config: simulationConfigForView(view, baseline.config.seed),
  };
}

export function buildCompareRequest(
  goalId: string,
  baseline: WhatIfBaselineState,
  extraPaths: { id: string; label: string; parsed_changes: ParsedInterventionChange[] }[] = [],
  view: AnalysisDepth = "simple",
) {
  const catalog = extraPaths.length
    ? []
    : baseline.compare_candidates.map((candidate) => ({
        id: candidate.id,
        label: candidate.title,
        intervention: candidate.intervention,
        parsed_changes: [],
      }));
  const custom = extraPaths.map((path) => ({
    id: path.id,
    label: path.label,
    intervention: fallbackIntervention(baseline, path.label),
    parsed_changes: path.parsed_changes,
  }));
  const paths = [...custom, ...catalog];
  return {
    base: buildWhatIfRequestFromBaseline(goalId, baseline, null, view),
    paths,
  };
}

export function buildTargetSearchRequest(
  goalId: string,
  baseline: WhatIfBaselineState,
  targetProbability: number,
  view: AnalysisDepth = "simple",
) {
  const names = new Set(baseline.assumptions.map((item) => item.name));
  const continuous =
    names.has("flow")
      ? { assumption: "flow", increasing: true }
      : names.has("weekly_application_rate")
        ? { assumption: "weekly_application_rate", increasing: true }
        : null;
  return {
    base: buildWhatIfRequestFromBaseline(goalId, baseline, null, view),
    target_probability: targetProbability,
    limits: {
      hours_per_week: baseline.resource_constraints.hours_per_week ?? 20,
      money: baseline.resource_budget.money_per_month ?? 0,
      energy: 1,
    },
    candidates: baseline.compare_candidates
      .map((candidate) => candidate.intervention)
      .filter((item) => item != null),
    continuous_variable: continuous,
  };
}

export function buildFuturesRequest(
  goalId: string,
  baseline: WhatIfBaselineState,
  decision: string,
  scenarioLabels: string[],
  parsedChanges: ParsedInterventionChange[] = [],
  view: AnalysisDepth = "simple",
) {
  const labels =
    scenarioLabels.length > 0
      ? scenarioLabels
      : [
          "Strong upside path",
          "Steady progress path",
          "Downside / delay path",
        ];
  const config = simulationConfigForView(view, baseline.config.seed);

  return {
    goal_id: goalId,
    name: decision,
    outcomes: labels.map((label) => ({
      label,
      downside: /downside|fail|delay|no offer|return to job/i.test(label),
    })),
    assumptions: baseline.assumptions,
    evidence_basis: [`decision:${decision.slice(0, 120)}`],
    seed: config.seed,
    parsed_changes: parsedChanges,
    config,
  };
}
