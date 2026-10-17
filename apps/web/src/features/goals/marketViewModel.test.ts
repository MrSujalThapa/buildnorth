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
});
