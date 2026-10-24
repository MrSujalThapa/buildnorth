import type {
  PathComparisonResult,
  ScenarioDistribution,
  TargetSearchResult,
  WhatIfBaselineState,
} from "../api/client";
import { formatOutcome } from "./outcomeFormat";
import type { CompareOption, FutureOutcome } from "./templateTypes";
import type { PathStrategy } from "./simulations";

function levelFromNumber(value: number, thresholds: [number, number]): CompareOption["downside"] {
  if (value <= thresholds[0]) return "Low";
  if (value <= thresholds[1]) return "Medium";
  return "High";
}

function asPercent(value: number | null | undefined): number | null {
  return value == null ? null : value * 100;
}

export function toCompareOptions(
  baseline: WhatIfBaselineState | undefined,
  comparison: PathComparisonResult | undefined,
): CompareOption[] {
  if (comparison?.paths.length) {
    const unit = baseline?.target_unit ?? null;
    return comparison.paths.map((path) => {
      const priced = path.primary_goal_probability != null;
      return {
        id: path.id,
        label: path.label,
        odds: asPercent(path.primary_goal_probability),
        downside:
          path.downside_probability == null
            ? "Medium"
            : levelFromNumber(path.downside_probability, [0.25, 0.5]),
        time: levelFromNumber(path.resource_cost.hours_per_week, [5, 12]),
        followThrough:
          path.execution_probability == null ? 0 : Math.round(path.execution_probability * 100),
        sensitivity: levelFromNumber(path.fragility_pp ?? 0, [3, 8]),
        note: priced
          ? `${path.model_status.replaceAll("_", " ")} · median result ${
              path.median == null ? "—" : formatOutcome(path.median, unit)
            }`
          : `${path.model_status.replaceAll("_", " ")} · not priced`,
        outcome: priced ? { p10: path.p10, p50: path.median, p90: path.p90 } : null,
      };
    });
  }

  return (baseline?.compare_candidates ?? []).filter(
    (candidate) => candidate.intervention?.effect_per_unit != null,
  ).map((candidate) => ({
    id: candidate.id,
    label: candidate.title,
    odds: null,
    downside: "Medium" as const,
    time: "Medium" as const,
    followThrough: 70,
    sensitivity: "Medium" as const,
    note: candidate.provenance.join(" · ") || "Awaiting backend comparison.",
    outcome: null,
  }));
}

export function toFutureOutcomes(distribution: ScenarioDistribution | undefined): FutureOutcome[] {
  if (!distribution?.outcomes.length) return [];
  return distribution.outcomes.map((outcome, index) => ({
    id: `future-${index}`,
    label: outcome.label,
    probability:
      outcome.probability != null ? Math.round(outcome.probability * 100) : null,
    tone: outcome.downside ? "negative" : outcome.probability != null && outcome.probability >= 0.25 ? "positive" : "neutral",
  }));
}

function fragilityLabel(value: number | null | undefined): "Low" | "Medium" | "High" {
  if (value == null || value <= 3) return "Low";
  if (value <= 8) return "Medium";
  return "High";
}

export function toPathStrategies(targetSearch: TargetSearchResult | undefined): PathStrategy[] | undefined {
  if (!targetSearch?.paths.length) return undefined;
  const sorted = [...targetSearch.paths].sort(
    (a, b) => b.resulting_probability - a.resulting_probability,
  );
  return sorted.map((path, index) => ({
    id: `path-${index}`,
    label: path.label,
    odds: path.resulting_probability * 100,
    requirement: path.valid_because,
    subpaths: path.action_ids.map((id) => id.replaceAll("_", " ")),
    cost: Math.max(8, path.resource_cost.hours_per_week * 4),
    fragility: fragilityLabel(path.fragility_pp),
    onFrontier: index < Math.min(3, sorted.length),
    variants: [],
  }));
}

export type FutureScenario = {
  id: string;
  label: string;
  /** Share of simulated futures in this scenario, 0–100; null when unweighted. */
  probability: number | null;
  tone: "positive" | "neutral" | "negative";
  /** Terminal-value quantiles in the goal's unit, not odds. */
  outcome: { p10: number | null; p50: number | null; p90: number | null } | null;
};

export function futuresFromDistribution(distribution: ScenarioDistribution | undefined): FutureScenario[] | undefined {
  if (!distribution?.outcomes.length) return undefined;
  return distribution.outcomes.map((outcome, index) => ({
    id: `outcome-${index}`,
    label: outcome.label,
    probability: outcome.probability != null ? Math.round(outcome.probability * 100) : null,
    tone: outcome.downside
      ? "negative"
      : outcome.probability != null && outcome.probability >= 0.25
        ? "positive"
        : "neutral",
    outcome:
      outcome.p10 == null && outcome.median == null && outcome.p90 == null
        ? null
        : { p10: outcome.p10, p50: outcome.median, p90: outcome.p90 },
  }));
}
