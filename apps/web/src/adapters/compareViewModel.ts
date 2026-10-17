import type {
  PathComparisonResult,
  ScenarioDistribution,
  TargetSearchResult,
  WhatIfBaselineState,
} from "../api/client";
import type { CompareOption, FutureOutcome, GoalPath } from "./templateTypes";
import type { PathStrategy, SimulationCluster, SimulationPoint } from "./simulations";

function levelFromNumber(value: number, thresholds: [number, number]): CompareOption["downside"] {
  if (value <= thresholds[0]) return "Low";
  if (value <= thresholds[1]) return "Medium";
  return "High";
}

export function toCompareOptions(
  baseline: WhatIfBaselineState | undefined,
  comparison: PathComparisonResult | undefined,
): CompareOption[] {
  if (comparison?.paths.length) {
    return comparison.paths.map((path) => ({
      id: path.id,
      label: path.label,
      odds: path.primary_goal_probability * 100,
      downside: levelFromNumber(path.downside_probability, [0.25, 0.5]),
      time: levelFromNumber(path.resource_cost.hours_per_week, [5, 12]),
      followThrough: Math.round(path.execution_probability * 100),
      sensitivity: levelFromNumber(path.fragility_pp ?? 0, [3, 8]),
      note: `${path.model_status.replaceAll("_", " ")} · median ${Math.round(path.median * 100)}%`,
    }));
  }

  return (baseline?.compare_candidates ?? []).map((candidate) => ({
    id: candidate.id,
    label: candidate.title,
    odds: null,
    downside: "Medium" as const,
    time: "Medium" as const,
    followThrough: 70,
    sensitivity: "Medium" as const,
    note: candidate.provenance.join(" · ") || "Awaiting backend comparison.",
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

export function toGoalPaths(
  targetSearch: TargetSearchResult | undefined,
  comparison: PathComparisonResult | undefined,
): GoalPath[] {
  if (targetSearch?.paths.length) {
    return targetSearch.paths.map((path, index) => ({
      id: `path-${index}`,
      label: path.label,
      odds: path.resulting_probability * 100,
      requirement: path.valid_because,
      subpaths: path.action_ids.map((id) => id.replaceAll("_", " ")),
    }));
  }

  if (comparison?.paths.length) {
    return comparison.paths.map((path) => ({
      id: path.id,
      label: path.label,
      odds: path.primary_goal_probability * 100,
      requirement: `p10 ${Math.round(path.p10 * 100)}% · p90 ${Math.round(path.p90 * 100)}%`,
      subpaths: [`Execution ${Math.round(path.execution_probability * 100)}%`, path.model_status],
    }));
  }

  return [];
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

export function futuresFromDistribution(
  distribution: ScenarioDistribution | undefined,
  marketCategory: string,
): { clusters: SimulationCluster[]; points: SimulationPoint[] } | undefined {
  if (!distribution?.outcomes.length) return undefined;
  const axes =
    marketCategory === "Startup"
      ? { xMin: 0, xMax: 100, yMin: 2, yMax: 42 }
      : marketCategory === "Career"
        ? { xMin: 1, xMax: 28, yMin: 8, yMax: 100 }
        : { xMin: 0, xMax: 100, yMin: 0, yMax: 100 };

  const clusters: SimulationCluster[] = distribution.outcomes.map((outcome, index) => ({
    id: `outcome-${index}`,
    label: outcome.label,
    short: outcome.label.split(" ").slice(0, 2).join(" "),
    probability:
      outcome.probability != null ? Math.round(outcome.probability * 100) : 0,
    tone: outcome.downside ? "negative" : outcome.probability != null && outcome.probability >= 0.25 ? "positive" : "neutral",
    goalRate: outcome.median ?? (outcome.probability ?? 0.5),
  }));

  const points: SimulationPoint[] = [];
  let pointId = 1;
  distribution.outcomes.forEach((outcome, index) => {
    const clusterId = `outcome-${index}`;
    const copies = Math.max(1, Math.round((outcome.probability ?? 0.1) * 500));
    const xCenter =
      outcome.median != null
        ? outcome.median * (marketCategory === "Career" ? axes.xMax : 100)
        : axes.xMin + (index + 1) * ((axes.xMax - axes.xMin) / Math.max(distribution.outcomes.length, 1));
    const yCenter =
      outcome.median != null
        ? outcome.median * 100
        : axes.yMin + (axes.yMax - axes.yMin) * 0.5;
    for (let i = 0; i < copies; i += 1) {
      points.push({
        id: pointId++,
        x: xCenter + ((i % 5) - 2) * 0.8,
        y: yCenter + ((i % 7) - 3) * 0.6,
        clusterId,
        goalHit: (outcome.median ?? outcome.probability ?? 0) >= 0.5,
        seed: pointId + index,
      });
    }
  });

  return { clusters, points };
}

/** Build comparison cloud points from backend path quantiles — no local fixture draws. */
export function comparePointsFromResult(
  comparison: PathComparisonResult | undefined,
): SimulationPoint[] | undefined {
  if (!comparison?.paths.length) return undefined;
  const points: SimulationPoint[] = [];
  let pointId = 1;
  for (const path of comparison.paths) {
    const samples = [
      path.p10 * 100,
      path.median * 100,
      path.primary_goal_probability * 100,
      path.p90 * 100,
    ];
    samples.forEach((center, index) => {
      const copies = index === 2 ? 6 : 4;
      for (let i = 0; i < copies; i += 1) {
        points.push({
          id: pointId++,
          x: path.resource_cost.hours_per_week + ((i % 3) - 1) * 0.5,
          y: center + ((i % 5) - 2) * 0.35,
          optionId: path.id,
          clusterId: path.id,
          goalHit: center >= 50,
          seed: pointId + index,
        });
      }
    });
  }
  return points;
}
