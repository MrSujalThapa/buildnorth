import type { ParsedInterventionChange, WhatIfAssumption, WhatIfBaselineState } from "../api/client";

type InterventionPayload = Record<string, unknown>;
type AnalysisDepth = "simple" | "deep";

export function simulationConfigForView(
  view: AnalysisDepth,
  seed: number,
): {
  seed: number;
  minimum_draws: number;
  batch_draws: number;
  maximum_draws: number;
  include_sensitivity: boolean;
} {
  if (view === "deep") {
    return {
      seed,
      minimum_draws: 8000,
      batch_draws: 4000,
      maximum_draws: 20000,
      include_sensitivity: true,
    };
  }
  return {
    seed,
    minimum_draws: 2000,
    batch_draws: 2000,
    maximum_draws: 4000,
    include_sensitivity: false,
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

/** Assumptions the backend reprices when set directly: flow and weekly application rate. */
const LEVER_NAMES = ["weekly_application_rate", "flow"] as const;

export function primaryLever(baseline: WhatIfBaselineState | undefined): WhatIfAssumption | null {
  if (!baseline?.priced) return null;
  for (const name of LEVER_NAMES) {
    const found = baseline.assumptions.find((item) => item.name === name && item.editable !== false);
    if (found && found.maximum > found.minimum) return found;
  }
  return baseline.assumptions.find((item) => item.editable !== false && item.name.endsWith(".rate") && item.maximum > item.minimum) ?? null;
}

export function leverUnitLabel(lever: WhatIfAssumption): string {
  if (lever.name === "weekly_application_rate") return "applications/week";
  return lever.unit.replace("currency/month", "/month").replace("units/period", "/period");
}

export function leverAxisTitle(lever: WhatIfAssumption): string {
  if (lever.unit.startsWith("currency")) return "Monthly contribution ($)";
  return leverUnitLabel(lever).replace(/^./, (first) => first.toUpperCase());
}

export function formatLeverValue(lever: WhatIfAssumption, value: number): string {
  const rounded = Math.abs(value) >= 100 ? Math.round(value).toLocaleString() : String(Math.round(value * 10) / 10);
  if (lever.unit.startsWith("currency")) return `$${rounded}/month`;
  return `${rounded} ${leverUnitLabel(lever)}`;
}

function snap(lever: WhatIfAssumption, value: number): number {
  const step = lever.step > 0 ? lever.step : 1;
  const clamped = Math.min(lever.maximum, Math.max(lever.minimum, value));
  return Math.round(clamped / step) * step;
}

/** Distinct lever settings between the current value and the assumption's maximum. */
export function leverLadder(lever: WhatIfAssumption, count: number): number[] {
  const start = Math.max(lever.minimum, lever.value * 0.5);
  const span = lever.maximum - start;
  const values = Array.from({ length: count }, (_, index) => snap(lever, start + (span * index) / Math.max(1, count - 1)));
  values.push(snap(lever, lever.value));
  return [...new Set(values)].sort((a, b) => a - b);
}

export function leverChange(lever: WhatIfAssumption, value: number): ParsedInterventionChange {
  return {
    metric: lever.name,
    operation: "set",
    value,
    unit: lever.unit,
    frequency: null,
    scope: "goal",
    provenance: "EXPLORATION_ASSUMPTION",
  };
}

export function leverPaths(lever: WhatIfAssumption, values: number[]) {
  return values.map((value) => ({
    id: `lever-${lever.name}-${value}`,
    label: Math.abs(value - lever.value) < 1e-9 ? `${formatLeverValue(lever, value)} (current)` : formatLeverValue(lever, value),
    parsed_changes: [leverChange(lever, value)],
  }));
}

export function defaultCompareValues(lever: WhatIfAssumption): number[] {
  const current = snap(lever, lever.value);
  const values = [current, snap(lever, lever.value * 1.5 || lever.step * 4), snap(lever, lever.value * 2 || lever.step * 8)];
  return [...new Set(values)];
}

export function buildCompareRequest(
  goalId: string,
  baseline: WhatIfBaselineState,
  extraPaths: { id: string; label: string; parsed_changes: ParsedInterventionChange[] }[] = [],
  view: AnalysisDepth = "simple",
) {
  const lever = primaryLever(baseline);
  const catalog = extraPaths.length || !lever ? [] : leverPaths(lever, defaultCompareValues(lever)).map((path) => ({
    ...path,
    intervention: fallbackIntervention(baseline, path.label),
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

export function buildLeverSweepRequest(
  goalId: string,
  baseline: WhatIfBaselineState,
  lever: WhatIfAssumption,
  values: number[],
  view: AnalysisDepth = "simple",
) {
  return {
    base: buildWhatIfRequestFromBaseline(goalId, baseline, null, view),
    paths: leverPaths(lever, values).map((path) => ({
      ...path,
      intervention: fallbackIntervention(baseline, path.label),
    })),
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
