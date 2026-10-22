import { describe, expect, it } from "vitest";

import { comparePointsFromResult, toCompareOptions } from "../adapters/compareViewModel";

describe("comparePointsFromResult", () => {
  it("plots only backend quantiles", () => {
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
    expect(comparePointsFromResult({
      paths: options.map((option) => ({
        id: option.id,
        label: option.label,
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
      })),
      model_family: "finance",
      model_version: "1.0.0",
      seed: 1,
      run_id: "run",
    })).toBeUndefined();
  });
});
