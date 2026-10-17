import type { WhatIfBaselineState } from "../api/client";

export function buildWhatIfRequestFromBaseline(
  goalId: string,
  baseline: WhatIfBaselineState,
  intervention: WhatIfBaselineState["default_intervention"] = baseline.default_intervention,
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
    config: baseline.config,
  };
}

export function buildCompareRequest(goalId: string, baseline: WhatIfBaselineState) {
  return {
    base: buildWhatIfRequestFromBaseline(goalId, baseline, null),
    paths: baseline.compare_candidates.map((candidate) => ({
      id: candidate.id,
      label: candidate.title,
      intervention: candidate.intervention,
    })),
  };
}

export function buildTargetSearchRequest(
  goalId: string,
  baseline: WhatIfBaselineState,
  targetProbability: number,
) {
  return {
    base: buildWhatIfRequestFromBaseline(goalId, baseline, null),
    target_probability: targetProbability,
    limits: {
      hours_per_week: baseline.resource_constraints.hours_per_week ?? 20,
      money: baseline.resource_budget.money_per_month ?? 0,
      energy: 1,
    },
    candidates: [],
  };
}

export function buildFuturesRequest(
  goalId: string,
  baseline: WhatIfBaselineState,
  decision: string,
  scenarioLabels: string[],
) {
  const labels =
    scenarioLabels.length > 0
      ? scenarioLabels
      : [
          "Strong upside path",
          "Steady progress path",
          "Downside / delay path",
        ];

  return {
    goal_id: goalId,
    name: decision,
    outcomes: labels.map((label) => ({
      label,
      downside: /downside|fail|delay|no offer|return to job/i.test(label),
    })),
    assumptions: baseline.assumptions,
    evidence_basis: [`decision:${decision.slice(0, 120)}`],
    seed: baseline.config.seed,
  };
}
