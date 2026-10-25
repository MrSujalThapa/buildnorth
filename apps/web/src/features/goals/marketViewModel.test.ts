import { describe, expect, it } from "vitest";
import type { Goal, MarketHistoryPoint } from "../../api/client";
import { toMarketCardViewModel } from "./marketViewModel";

const goal: Goal = {
  goal_id: "goal-1",
  title: "Receive a Big Tech offer",
  goal_type: "deadline_event",
  deadline: "2027-01-01T00:00:00Z",
  forecast_status: "ANCHORED",
  state_dimensions: [],
};

describe("toMarketCardViewModel", () => {
  it("maps real history and a human domain category without exposing model type", () => {
    const points = [
      { probability: 0.42, created_at: "2026-08-01T00:00:00Z" },
      { probability: 0.51, created_at: "2026-08-02T00:00:00Z" },
    ] as MarketHistoryPoint[];
    const view = toMarketCardViewModel(goal, points);
    expect(view.category).toBe("Career");
    expect(view.odds).toBe(51);
    expect(view.todayReturn).toBeCloseTo(9);
    expect(view.history.map((point) => point.value)).toEqual([42, 51]);
  });

  it("keeps an unpriced market empty", () => {
    expect(toMarketCardViewModel(goal, []).odds).toBeNull();
    expect(toMarketCardViewModel(goal, []).history).toEqual([]);
  });

  it("does not treat synthetic_demo points as published odds", () => {
    const points = [
      {
        id: "demo-1",
        probability: 0.41,
        forecast_status: "EXPLORATORY",
        evidence_watermark: "none",
        model_family: "demo",
        model_version: "ui",
        assumption_hash: "demo",
        simulation_run_id: null,
        source_kind: "synthetic_demo",
        created_at: "2026-08-01T00:00:00Z",
      },
    ] as MarketHistoryPoint[];
    expect(toMarketCardViewModel(goal, points).odds).toBeNull();
    expect(toMarketCardViewModel(goal, points).history).toEqual([]);
  });

  it("uses the latest dated receipt and keeps withheld history historical", () => {
    const points = [
      { id: "b", probability: 0.6, created_at: "2026-08-02T00:00:00Z" },
      { id: "a", probability: 0.4, created_at: "2026-08-01T00:00:00Z" },
      { id: "b", probability: 0.6, created_at: "2026-08-02T00:00:00Z" },
      { id: "bad", probability: Number.NaN, created_at: "2026-08-03T00:00:00Z" },
    ] as MarketHistoryPoint[];
    const view = toMarketCardViewModel(goal, points);
    expect(view.odds).toBe(60);
    expect(view.history.map((point) => point.value)).toEqual([40, 60]);
    const withheld = toMarketCardViewModel({ ...goal, model_requirements: { last_publication: { status: "withheld" } } } as Goal, points);
    expect(withheld.odds).toBeNull();
    expect(withheld.history).toEqual(view.history);
  });
});
