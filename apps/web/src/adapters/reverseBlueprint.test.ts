import { describe, expect, it } from "vitest";

import type { ReverseBlueprint, ReverseBlueprintLeverChange, TargetSearchResult, WhatIfAssumption } from "../api/client";
import { toLeverFrontier } from "./compareViewModel";
import { blueprintFromPaths, blueprintFuturesPath, formatBlueprintValue, toBlueprintView } from "./reverseBlueprint";

const apps: ReverseBlueprintLeverChange = {
  lever_id: "weekly_application_rate",
  label: "Weekly applications",
  unit: "applications/week",
  baseline_value: 2,
  recommended_value: 40,
  change: 38,
  relative_change: 19,
  range_used: 0.79,
  effort: "heavy",
  description: "Raise weekly applications from 2 to 40 applications/week (+38 applications/week, 20.0× today)",
};

function makeBlueprint(overrides: Partial<ReverseBlueprint> = {}): ReverseBlueprint {
  return {
    target_probability: 0.9,
    baseline_probability: 0.74,
    modeled_probability: 0.891,
    delta_pp: 15.1,
    reachable: true,
    already_satisfied: false,
    headline: "To reach ~90%: raise weekly applications to 40 applications/week. Modeled odds 89%.",
    rationale: "The smallest change among 6 priced options that reaches 90% (within 1 pp).",
    lever_changes: [apps],
    actions: [],
    steps: [
      `${apps.description}.`,
      "Stick with it: these odds assume the change holds in about 72% of futures, so slipping more lowers them.",
      "Hold everything else at today's evidence, and log progress so the odds re-price.",
    ],
    tradeoffs: ["Weekly applications at 40 applications/week is a heavy lift; check it fits your week."],
    follow_through_probability: 0.72,
    max_modeled_probability: 0.9036,
    plateau: null,
    alternatives: [
      {
        id: "lever:weekly_application_rate:14",
        label: "Weekly applications at 14 applications/week",
        lever_changes: [{ ...apps, recommended_value: 14, change: 12, effort: "heavy" }],
        actions: [],
        modeled_probability: 0.8155,
        reaches_target: false,
        effort_score: 6,
        note: "Smaller change, 8 pp short of target.",
      },
      {
        id: "lever:weekly_application_rate:50",
        label: "Weekly applications at 50 applications/week",
        lever_changes: [{ ...apps, recommended_value: 50, change: 48, effort: "heavy" }],
        actions: [],
        modeled_probability: 0.9036,
        reaches_target: true,
        effort_score: 24,
        note: "Also reaches the target, with a larger change.",
      },
    ],
    tolerance_pp: 1,
    method: "reverse_blueprint@1.0.0",
    ...overrides,
  };
}

describe("toBlueprintView", () => {
  it("shows baseline, modeled odds and a pp delta for a reachable path", () => {
    const view = toBlueprintView(makeBlueprint());
    expect(view.status).toBe("reachable");
    expect(view.statusLabel).toBe("Reaches 89.1% (within 1 pp of 90%)");
    expect([view.baseline, view.modeled, view.delta, view.target]).toEqual(["74%", "89.1%", "+15 pp", "90%"]);
    expect(view.deltaTone).toBe("up");
    expect(view.followThrough).toBe("Assumes the change holds in 72% of futures");
  });

  it("renders lever changes as structured plan rows followed by the remaining steps", () => {
    const view = toBlueprintView(makeBlueprint());
    expect(view.plan).toHaveLength(3);
    expect(view.plan[0]).toEqual({
      kind: "change",
      change: { id: "weekly_application_rate", label: "Weekly applications", from: "2/week", to: "40/week", delta: "+38/week", effort: "heavy", effortLabel: "Heavy lift" },
    });
    expect(view.plan.slice(1).every((item) => item.kind === "step")).toBe(true);
  });

  it("reports the gap and plateau when the target is out of reach", () => {
    const view = toBlueprintView(
      makeBlueprint({
        reachable: false,
        modeled_probability: 0.58,
        delta_pp: 28,
        plateau: {
          lever_id: "weekly_application_rate",
          plateau_probability: 0.586,
          starts_at_value: 20,
          cause: "follow_through",
          explanation: "Odds level off near 59% from about 20 applications/week.",
        },
      }),
    );
    expect(view.status).toBe("short");
    expect(view.statusLabel).toBe("58% does not reach 90% (32 pp short)");
    expect(view.plateau).toEqual({ label: "Odds plateau near 58.6%", explanation: "Odds level off near 59% from about 20 applications/week." });
  });

  it("keeps the current plan without a delta when the target is already met", () => {
    const view = toBlueprintView(
      makeBlueprint({
        already_satisfied: true,
        target_probability: 0.5,
        modeled_probability: 0.74,
        delta_pp: 0,
        lever_changes: [{ ...apps, recommended_value: 2, change: 0, effort: "none" }],
        steps: ["Keep weekly applications at 2 applications/week.", "Hold everything else."],
        alternatives: [],
      }),
    );
    expect(view.status).toBe("met");
    expect(view.delta).toBeNull();
    expect(view.followThrough).toBeNull();
    expect(view.plan.map((item) => item.kind)).toEqual(["change", "step"]);
  });

  it("never presents 84% as reaching 90%", () => {
    const view = toBlueprintView(makeBlueprint({
      reachable: false,
      modeled_probability: 0.84,
      delta_pp: 10,
      tolerance_pp: 0.5,
    }));
    expect(view.status).toBe("short");
    expect(view.statusLabel).toBe("84% does not reach 90% (6 pp short)");
    expect(view.statusLabel).not.toMatch(/Reaches/);
  });

  it("formats alternatives without recomputing their odds", () => {
    const view = toBlueprintView(makeBlueprint());
    expect(view.alternatives.map((item) => [item.odds, item.reaches, item.effortLabel])).toEqual([
      ["81.6%", false, "Heavy lift"],
      ["90.4%", true, "Heavy lift"],
    ]);
  });
});

describe("blueprint helpers", () => {
  it("formats currency and rate levers", () => {
    expect(formatBlueprintValue({ lever_id: "flow", unit: "currency/month" }, 3350)).toBe("$3,350/month");
    expect(formatBlueprintValue({ lever_id: "flow", unit: "currency/month" }, -250)).toBe("−$250/month");
    expect(formatBlueprintValue(apps, 21)).toBe("21/week");
  });

  it("hands the recommended lever value to Futures", () => {
    const path = blueprintFuturesPath(makeBlueprint());
    expect(path?.cost).toBe(40);
    expect(path?.label).toBe("Weekly applications at 40/week");
    expect(path?.odds).toBeCloseTo(89.1);
  });

  it("is carried from the target search through the lever frontier", () => {
    const lever = { name: "weekly_application_rate", value: 2, minimum: 0, maximum: 50, step: 1, unit: "applications/week" } as WhatIfAssumption;
    const blueprint = makeBlueprint();
    const search = {
      target_probability: 0.9, current_probability: 0.74, gap_pp: 16, feasible: true, message: "", search_method: "x",
      run_id: null, receipt: {}, blueprint,
      paths: [{ label: "Submit 40 applications each week", action_ids: [], resulting_probability: 0.891,
        resource_cost: { hours_per_week: 0, money: 0, energy: 0 }, fragility_pp: null, valid_because: "",
        assumptions: [{ ...lever, value: 40 }] }],
    } as TargetSearchResult;
    const sweep = { paths: [{ id: "lever-weekly_application_rate-2", label: "2", primary_goal_probability: 0.74, fragility_pp: 0 }] } as never;
    const paths = toLeverFrontier(lever, sweep, search, (_, value) => `${value} applications/week`);
    expect(paths[0]?.label).toBe("40 applications/week is within 1 pp of the target");
    expect(blueprintFromPaths(paths)).toBe(blueprint);
    expect(blueprintFromPaths(toLeverFrontier(lever, sweep, { ...search, feasible: false }, String))).toBe(blueprint);
  });
});
