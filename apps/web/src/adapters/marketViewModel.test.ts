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

  it("keeps historical points but withholds stale current odds", () => {
    const points = [{ probability: 0.15, created_at: "2026-10-20T12:00:00Z" }] as MarketHistoryPoint[];
    const card = toMarketCard(goal, points, { status: "withheld", critic_decision: "withhold" });
    expect(card.currentForecastStatus).toBe("withheld");
    expect(card.odds).toBeNull();
    expect(card.history).toHaveLength(1);
  });

  it("honors a withheld publication even without a creation snapshot", () => {
    const withheldGoal = {
      ...goal, model_requirements: { last_publication: { status: "withheld" } },
    } as Goal;
    const points = [{ probability: 0.15, created_at: "2026-10-20T12:00:00Z" }] as MarketHistoryPoint[];
    expect(toMarketCard(withheldGoal, points).odds).toBeNull();
  });

  it.each(["evidence_pending", "evidence_running", "evidence_failed"])(
    "does not show old odds while %s",
    (status) => {
      const points = [{ probability: 0.15, created_at: "2026-10-20T12:00:00Z" }] as MarketHistoryPoint[];
      const card = toMarketCard(goal, points, { status, critic_decision: null });
      expect(card.odds).toBeNull();
      expect(card.currentForecastStatus).toBe(status === "evidence_running" ? "evidence_pending" : status);
    },
  );
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
