import { describe, expect, it } from "vitest";

import type { WhatIfBaselineState } from "../api/client";
import {
  buildCompareRequest,
  buildFuturesRequest,
  buildTargetSearchRequest,
  simulationConfigForView,
} from "./whatIfRequests";

const baseline = {
  goal_id: "g1",
  priced: true,
  status: "PRICED",
  direction: "at_least",
  current_value: 10,
  target_value: 100,
  periods: 12,
  assumptions: [{ name: "flow", value: 3, minimum: 0, maximum: 20, step: 1, source: "USER", unit: "u", editable: true }],
  model_family: "continuous_target_transition",
  model_version: "1.0.0",
  evidence_count: 1,
  evidence_watermark: "none",
  reference_versions: [],
  domain_state: {},
  resource_constraints: { hours_per_week: 10, money: 0, energy: 1 },
  resource_budget: { hours_per_week: 10, money_per_month: 0 },
  limitations: [],
  config: { seed: 7, minimum_draws: 2000, batch_draws: 2000, maximum_draws: 4000 },
  compare_candidates: [
    {
      id: "more-apps",
      title: "Apply more",
      intervention: { id: "more-apps", title: "Apply more" },
      provenance: ["reference"],
    },
  ],
} as unknown as WhatIfBaselineState;

describe("whatIfRequests", () => {
  it("sends reverse candidates instead of an empty search set", () => {
    const request = buildTargetSearchRequest("g1", baseline, 0.75);
    expect(request.candidates).toHaveLength(1);
    expect(request.continuous_variable).toEqual({ assumption: "flow", increasing: true });
  });

  it("compares two user-specified paths via parsed_changes", () => {
    const request = buildCompareRequest("g1", baseline, [
      { id: "path-a", label: "Save 400 a month", parsed_changes: [{ metric: "flow", operation: "set", value: 400, unit: "CAD", frequency: null, scope: "goal_state", provenance: "USER_ASSUMPTION" }] },
      { id: "path-b", label: "Save 800 a month", parsed_changes: [{ metric: "flow", operation: "set", value: 800, unit: "CAD", frequency: null, scope: "goal_state", provenance: "USER_ASSUMPTION" }] },
    ]);
    expect(request.paths).toHaveLength(2);
    expect(request.paths[0].parsed_changes[0].value).toBe(400);
    expect(request.paths[1].parsed_changes[0].value).toBe(800);
  });

  it("attaches parsed_changes to futures so the decision can condition the model", () => {
    const request = buildFuturesRequest(
      "g1",
      baseline,
      "What if I save 2000 a month?",
      ["Target reached", "Downside outcome"],
      [{ metric: "monthly_contribution", operation: "set", value: 2000, unit: "CAD/month", frequency: null, scope: "goal_state", provenance: "USER_ASSUMPTION" }],
    );
    expect(request.parsed_changes).toHaveLength(1);
    expect(request.parsed_changes[0].metric).toBe("monthly_contribution");
  });

  it("uses more draws for deeper analysis", () => {
    expect(simulationConfigForView("deep", 1).minimum_draws).toBeGreaterThan(
      simulationConfigForView("simple", 1).minimum_draws,
    );
  });
});
