import { afterEach, describe, expect, it, vi } from "vitest";
import type { EvidenceEvent, Goal, MarketHistoryPoint } from "../api/client";
import { evidenceToEvents, publishedHistoryPoints, toMarketCard } from "./marketViewModel";

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

it("sorts and deduplicates real receipts before choosing current odds", () => {
  const points = [
    { id: "later", probability: 0.7, created_at: "2026-10-20T12:00:00Z" },
    { id: "early", probability: 0.4, created_at: "2026-10-18T12:00:00Z" },
    { id: "later", probability: 0.7, created_at: "2026-10-20T12:00:00Z" },
    { id: "invalid-date", probability: 0.8, created_at: "not-a-date" },
    { id: "invalid-odds", probability: 1.4, created_at: "2026-10-21T12:00:00Z" },
  ] as MarketHistoryPoint[];
  expect(publishedHistoryPoints(points).map((point) => point.id)).toEqual(["early", "later"]);
  const card = toMarketCard(goal, points);
  expect(card.odds).toBe(70);
  expect(card.history.map((point) => point.value)).toEqual([40, 70]);
  expect(card.history.every((point) => Number.isFinite(point.timestamp))).toBe(true);
});

it("distinguishes unusable dated history from no published history", () => {
  const invalid = [{ id: "receipt", probability: 0.5, created_at: null }] as MarketHistoryPoint[];
  expect(toMarketCard(goal, invalid).historyUnavailable).toBe(true);
  expect(toMarketCard(goal, []).historyUnavailable).toBe(false);
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
