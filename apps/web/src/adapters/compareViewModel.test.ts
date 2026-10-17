import { describe, expect, it } from "vitest";

import { comparePointsFromResult } from "../adapters/compareViewModel";

describe("comparePointsFromResult", () => {
  it("builds cloud points from backend path quantiles", () => {
    const points = comparePointsFromResult({
      paths: [
        {
          id: "a",
          label: "Option A",
          primary_goal_probability: 0.42,
          expected_outcome: 0.42,
          median: 0.4,
          p10: 0.3,
          p90: 0.5,
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
    expect(points?.length).toBeGreaterThan(0);
    expect(points?.every((point) => point.optionId === "a")).toBe(true);
    expect(points?.some((point) => Math.abs(point.y - 42) < 2)).toBe(true);
  });
});
