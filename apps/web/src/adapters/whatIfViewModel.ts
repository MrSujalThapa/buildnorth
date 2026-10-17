import type { WhatIfBaselineState, WhatIfResult } from "../api/client";
import type { Market, OutcomePoint, WhatIfPlan, WhatIfPreview } from "./templateTypes";

export function defaultPlanForMarket(market: Market): WhatIfPlan {
  if (market.category === "Career") {
    return { effortHours: 2, cadence: 10, followThrough: 72, durationWeeks: 8 };
  }
  if (market.category === "Startup") {
    return { effortHours: 3, cadence: 5, followThrough: 76, durationWeeks: 10 };
  }
  if (market.category === "Competitions") {
    return { effortHours: 2.5, cadence: 4, followThrough: 80, durationWeeks: 4 };
  }
  return { effortHours: 1, cadence: 5, followThrough: 78, durationWeeks: 8 };
}

export function defaultQuestionForMarket(market: Market): string {
  if (market.category === "Career") return "What if I study LeetCode 2 hours a day?";
  if (market.category === "Startup") return "What if I spend 3 focused hours a day building and talking to users?";
  if (market.category === "Competitions") return "What if I practice every day before the event?";
  return `What if I put more consistent time into ${market.title.toLowerCase()}?`;
}

function fanToOutcome(fan: WhatIfResult["fan"]): OutcomePoint[] {
  if (!fan.length) return [];
  return fan.map((point, index) => ({
    step: index,
    low: point.p10 * 100,
    likely: point.p50 * 100,
    high: point.p90 * 100,
  }));
}

export function planWeeklyHours(plan: WhatIfPlan): number {
  return plan.effortHours * 7 + plan.cadence * 0.25;
}

export function previewFromResult(
  _market: Market,
  plan: WhatIfPlan,
  baseline: WhatIfBaselineState | undefined,
  result: WhatIfResult | undefined,
): WhatIfPreview {
  const baselineProb = result?.baseline_probability ?? baseline?.current_probability ?? null;
  const current = baselineProb != null ? baselineProb * 100 : null;
  const scenario =
    result?.scenario_probability != null ? result.scenario_probability * 100 : null;
  const improvement =
    result?.expected_uplift_pp ??
    (current != null && scenario != null ? scenario - current : null);
  const outcome = fanToOutcome(result?.fan ?? []);
  const possibleLow = outcome.length ? Math.min(...outcome.map((p) => p.low)) : null;
  const possibleHigh = outcome.length ? Math.max(...outcome.map((p) => p.high)) : null;
  const chanceHelps =
    result?.p_uplift_positive != null ? result.p_uplift_positive * 100 : null;
  const tradeoff =
    result?.opportunity_costs?.join(" · ") ||
    "Time spent here cannot be spent on other goals at the same intensity.";

  return {
    currentOdds: current,
    scenarioOdds: scenario,
    improvementPoints: improvement,
    possibleLow,
    possibleHigh,
    chanceHelps,
    weeklyHours: planWeeklyHours(plan),
    outcome,
    tradeoff,
  };
}
