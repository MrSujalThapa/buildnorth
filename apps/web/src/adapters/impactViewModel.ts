import type { WhatIfBaselineState, WhatIfResult } from "../api/client";
import { formatOutcomeRange, type OutcomeScale } from "./outcomeFormat";
import type { WhatIfPreview } from "./templateTypes";
import type { RepresentativePoint } from "./simulationTypes";

export type OutcomeBin = { lower: number; upper: number; mass: number };

export type ImpactViewModel = {
  /** Simulated end values in the goal's unit; masses sum to 1. */
  outcomeBins: OutcomeBin[];
  outcomeScale: OutcomeScale;
  stats: { p10: number | null; p50: number | null; p90: number | null };
  likelyRangeLabel: string;
  causalCaption: string | null;
  fullExecutionOdds: number | null;
  followThroughPercent: number | null;
  sensitivity: { label: string; swingPp: number }[];
  opportunityCosts: string[];
  fragilityPp: number | null;
  drawCount: number | null;
  seed: number | null;
  modelLabel: string | null;
  llmCalls: number | null;
  metaLabel: string;
  representatives: RepresentativePoint[];
};

function statsFromResult(result: WhatIfResult | undefined) {
  const q = result?.outcome_quantiles ?? {};
  return { p10: q.p10 ?? null, p50: q.p50 ?? null, p90: q.p90 ?? null };
}

export function outcomeScaleFor(baseline: WhatIfBaselineState | undefined): OutcomeScale {
  return {
    unit: baseline?.target_unit ?? null,
    target: baseline?.target_value ?? null,
    direction: baseline?.direction ?? "at_least",
  };
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

export function toImpactViewModel(
  _preview: WhatIfPreview,
  result: WhatIfResult | undefined,
  baseline: WhatIfBaselineState | undefined,
): ImpactViewModel {
  const seed = result?.diagnostics?.seed ?? baseline?.config.seed ?? null;
  const outcomeBins = (result?.distribution_bins ?? []).filter((bin) => bin.mass > 0);
  const outcomeScale = outcomeScaleFor(baseline);
  const stats = statsFromResult(result);
  const sensitivity = (result?.sensitivity ?? []).slice(0, 5).map((item) => ({
    label: item.label,
    swingPp: item.swing ?? item.probability_swing_pp ?? 0,
  }));

  return {
    outcomeBins,
    outcomeScale,
    stats,
    likelyRangeLabel: formatOutcomeRange(stats.p10, stats.p90, outcomeScale.unit),
    causalCaption: causalCaption(result),
    fullExecutionOdds:
      result?.conditional_on_execution_probability != null
        ? result.conditional_on_execution_probability * 100
        : null,
    followThroughPercent:
      result?.execution_probability != null ? result.execution_probability * 100 : null,
    sensitivity,
    opportunityCosts: result?.opportunity_costs ?? [],
    fragilityPp: result?.fragility_pp ?? null,
    drawCount: result?.diagnostics?.n_draws ?? null,
    seed,
    modelLabel: baseline ? `${baseline.model_family}@${baseline.model_version}` : null,
    llmCalls: result?.llm_calls ?? null,
    metaLabel: result?.priced ? "Backend Monte Carlo" : "Not priced",
    representatives: [],
  };
}
