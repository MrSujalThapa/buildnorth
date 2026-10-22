import { describe, expect, it } from "vitest";

import { toCompareOptions } from "../adapters/compareViewModel";
import type { WhatIfBaselineState } from "../api/client";

describe("toCompareOptions", () => {
  it("keeps outcome quantiles in the goal's unit, separate from the odds", () => {
    const options = toCompareOptions({ target_unit: "USD" } as WhatIfBaselineState, {
      paths: [
        {
          id: "a",
          label: "Option A",
          primary_goal_probability: 0.42,
          expected_outcome: 91000,
          median: 90500,
          p10: 84000,
          p90: 97250,
          downside_probability: 0.2,
          fragility_pp: 4,
          resource_cost: { hours_per_week: 6, money: 0, energy: 1 },
          execution_probability: 0.7,
          model_status: "PRICED",
        },
      ],
      model_family: "finance",
      model_version: "1.0.0",
      seed: 1,
      run_id: "run",
    });
    expect(options[0]?.odds).toBeCloseTo(42);
    expect(options[0]?.outcome).toEqual({ p10: 84000, p50: 90500, p90: 97250 });
    expect(options[0]?.note).toContain("$90,500");
    expect(options[0]?.note).not.toContain("%");
  });

  it("does not turn an unpriced path into 0%", () => {
    const options = toCompareOptions(undefined, {
      paths: [
        {
          id: "missing",
          label: "Unsupported",
          primary_goal_probability: null,
          expected_outcome: null,
          median: null,
          p10: null,
          p90: null,
          downside_probability: null,
          fragility_pp: null,
          resource_cost: { hours_per_week: 4, money: 0, energy: 1 },
          execution_probability: null,
          model_status: "NOT_PRICED",
        },
      ],
      model_family: "finance",
      model_version: "1.0.0",
      seed: 1,
      run_id: "run",
    });
    expect(options[0]?.odds).toBeNull();
    expect(options[0]?.outcome).toBeNull();
  });
});
