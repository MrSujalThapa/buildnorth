import type { WhatIfBaselineState, WhatIfResult } from "../api/client";
import type { WhatIfPreview } from "./templateTypes";
import type { RepresentativePoint, SimulationPoint } from "./simulationTypes";

export type ImpactViewModel = {
  distributionPoints: SimulationPoint[];
  stats: { p10: number; p50: number; p90: number };
  likelyRangeLabel: string;
  causalCaption: string | null;
  fullExecutionOdds: number | null;
  followThroughPercent: number | null;
  downsideTail: number | null;
  sensitivity: { label: string; swingPp: number }[];
  opportunityCosts: string[];
  fragilityPp: number | null;
  drawCount: number | null;
  seed: number | null;
  modelLabel: string | null;
  llmCalls: number | null;
  simulationCloudAvailable: boolean;
  metaLabel: string;
  representatives: RepresentativePoint[];
};

function binsToPoints(bins: WhatIfResult["distribution_bins"], seed: number): SimulationPoint[] {
  const points: SimulationPoint[] = [];
  let id = 0;
  bins.forEach((bin, binIndex) => {
    const center = ((bin.lower + bin.upper) / 2) * 100;
    const copies = Math.max(1, Math.round(bin.mass * 120));
    for (let i = 0; i < copies; i += 1) {
      points.push({
        id: id++,
        x: center,
        y: 50 + (i % 5) * 3,
        clusterId: `bin-${binIndex}`,
        goalHit: center >= 50,
        seed: seed + id,
      });
    }
  });
  return points;
}

function statsFromResult(result: WhatIfResult | undefined, points: SimulationPoint[]) {
  const q = result?.outcome_quantiles ?? {};
  const p10 = q.p10 != null ? q.p10 * 100 : points.length ? Math.min(...points.map((p) => p.x)) : 0;
  const p50 = q.p50 != null ? q.p50 * 100 : points.length ? percentile(points.map((p) => p.x), 0.5) : 0;
  const p90 = q.p90 != null ? q.p90 * 100 : points.length ? Math.max(...points.map((p) => p.x)) : 0;
  return { p10, p50, p90 };
}

export function formatLikelyRange(stats: { p10: number; p90: number }, pointCount: number): string {
  if (!pointCount) return "—";
  if (!Number.isFinite(stats.p10) || !Number.isFinite(stats.p90)) return "—";
  if (Math.abs(stats.p90 - stats.p10) < 1e-9) return "—";
  return `${stats.p10.toFixed(0)}–${stats.p90.toFixed(0)}%`;
}

export function causalCaption(result: WhatIfResult | undefined): string | null {
  if (!result) return null;
  if (result.message) return result.message;
  const status = result.receipt?.causal_status;
  if (status === "parameter_intervention") {
    return "This is a hypothetical model-parameter change, not a causally identified intervention.";
  }
  if (status === "unmapped_intervention") {
    return "This action is not mapped to a supported mechanism. No causal effect was invented.";
  }
  return null;
}

function percentile(values: number[], ratio: number): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor((sorted.length - 1) * ratio)] ?? 0;
}

export function toImpactViewModel(
  _preview: WhatIfPreview,
  result: WhatIfResult | undefined,
  baseline: WhatIfBaselineState | undefined,
): ImpactViewModel {
  const seed = result?.diagnostics?.seed ?? baseline?.config.seed ?? null;
  const distributionPoints =
    result?.distribution_bins?.length && seed != null ? binsToPoints(result.distribution_bins, seed) : [];
  const stats = statsFromResult(result, distributionPoints);
  const sensitivity = (result?.sensitivity ?? []).slice(0, 5).map((item) => ({
    label: item.label,
    swingPp: item.swing ?? item.probability_swing_pp ?? 0,
  }));

  return {
    distributionPoints,
    stats,
    likelyRangeLabel: formatLikelyRange(stats, distributionPoints.length),
    causalCaption: causalCaption(result),
    fullExecutionOdds:
      result?.conditional_on_execution_probability != null
        ? result.conditional_on_execution_probability * 100
        : null,
    followThroughPercent:
      result?.execution_probability != null ? result.execution_probability * 100 : null,
    downsideTail: stats.p10,
    sensitivity,
    opportunityCosts: result?.opportunity_costs ?? [],
    fragilityPp: result?.fragility_pp ?? null,
    drawCount: result?.diagnostics?.n_draws ?? null,
    seed,
    modelLabel: baseline ? `${baseline.model_family}@${baseline.model_version}` : null,
    llmCalls: result?.llm_calls ?? null,
    simulationCloudAvailable: false,
    metaLabel: result?.priced ? "Backend Monte Carlo" : "Not priced",
    representatives: [],
  };
}
