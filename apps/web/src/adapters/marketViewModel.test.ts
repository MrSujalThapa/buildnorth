import { afterEach, describe, expect, it, vi } from "vitest";
import type { EvidenceEvent, Goal, MarketHistoryPoint } from "../api/client";
import { evidenceToEvents, toMarketCard } from "./marketViewModel";

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

  it("reports the most recent revision separately from today's change", () => {
    vi.setSystemTime(new Date("2026-10-20T18:00:00Z"));
    const points = [
      { probability: 0.1, created_at: "2026-10-12T12:00:00Z" },
      { probability: 0.18, created_at: "2026-10-14T12:00:00Z" },
    ] as MarketHistoryPoint[];
    const card = toMarketCard(goal, points);
    expect(card.todayReturn).toBeNull();
    expect(card.lastRevision?.change).toBeCloseTo(8);
    expect(card.lastRevision?.at).toBe(Date.parse("2026-10-14T12:00:00Z"));
  });

  it("compares a current-day publication to the preceding snapshot", () => {
    vi.setSystemTime(new Date("2026-10-20T18:00:00Z"));
    const points = [
      { probability: 0.1, created_at: "2026-10-19T12:00:00Z" },
      { probability: 0.15, created_at: "2026-10-20T12:00:00Z" },
    ] as MarketHistoryPoint[];
    expect(toMarketCard(goal, points).todayReturn).toBeCloseTo(5);
  });

  it("never shows synthetic history as published odds", () => {
    const points = [
      { probability: 0.4, created_at: "2026-10-01T12:00:00Z", source_kind: "synthetic_demo" },
      { probability: 0.5, created_at: "2026-10-20T12:00:00Z", source_kind: "synthetic_demo" },
    ] as MarketHistoryPoint[];
    expect(toMarketCard(goal, points).history).toEqual([]);
  });
});

it("shows extracted reading values without assigning unsupported event-level odds", () => {
  const event = (metric: string, numeric_value: number | null): EvidenceEvent => ({
    event_type: "observation", domain: "reading", metric, numeric_value,
    categorical_value: null, unit: null, observed_at: "2026-10-20T12:00:00Z",
    source_type: "mcp_sync", summary: metric,
  });
  const events = evidenceToEvents([event("books_read_count", 6), event("reading_minutes", 50)]);
  expect(events.map((item) => item.label)).toEqual(["Read for 50 minutes", "6 books read"]);
  expect(events.every((item) => item.impact === null)).toBe(true);
});
