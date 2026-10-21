import { afterEach, describe, expect, it, vi } from "vitest";
import type { Goal, MarketHistoryPoint } from "../api/client";
import { toMarketCard } from "./marketViewModel";

const goal = {
  goal_id: "goal-1",
  title: "Read 20 books",
  goal_type: "threshold",
  deadline: "2026-12-31T00:00:00Z",
  forecast_status: "EXPLORATORY",
  state_dimensions: [],
} as Goal;

describe("market card daily change", () => {
  afterEach(() => vi.useRealTimers());

  it("shows a dash for stale history rather than an invented zero", () => {
    vi.setSystemTime(new Date("2026-10-20T18:00:00Z"));
    const points = [
      { probability: 0.1, created_at: "2026-10-18T12:00:00Z" },
      { probability: 0.1, created_at: "2026-10-19T12:00:00Z" },
    ] as MarketHistoryPoint[];
    expect(toMarketCard(goal, points).todayReturn).toBeNull();
  });

  it("compares a current-day publication to the preceding snapshot", () => {
    vi.setSystemTime(new Date("2026-10-20T18:00:00Z"));
    const points = [
      { probability: 0.1, created_at: "2026-10-19T12:00:00Z" },
      { probability: 0.15, created_at: "2026-10-20T12:00:00Z" },
    ] as MarketHistoryPoint[];
    expect(toMarketCard(goal, points).todayReturn).toBeCloseTo(5);
  });
});
