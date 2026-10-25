import { describe, expect, it } from "vitest";
import {
  ODDS_EXPLORER_RANGES,
  filterHistoryForRange,
  rangeWindow,
  type MarketRange,
} from "./marketRanges";

const hour = 60 * 60 * 1000;
const day = 24 * hour;
const oneDay: MarketRange = { label: "1D", amount: 1, unit: "day" };
const oneWeek: MarketRange = { label: "1W", amount: 1, unit: "week" };

describe("Odds Explorer ranges", () => {
  it("exposes 1D 1W 1M 1Y ALL", () => {
    expect(ODDS_EXPLORER_RANGES.map((range) => range.label)).toEqual(["1D", "1W", "1M", "1Y", "ALL"]);
  });

  it("never collapses a single publication to a zero-width chart", () => {
    const published = Date.parse("2026-10-01T12:00:00Z");
    const points = filterHistoryForRange([{ timestamp: published, value: 42 }], oneDay, published);
    expect(points.length).toBeGreaterThanOrEqual(2);
    expect(points[points.length - 1]!.timestamp - points[0]!.timestamp).toBeGreaterThan(0);
    expect(points.every((point) => point.value === 42)).toBe(true);
  });

  it("carries the standing forecast into a window with no updates and labels it", () => {
    const now = Date.parse("2026-10-25T00:00:00Z");
    const history = [
      { timestamp: now - 20 * day, value: 20 },
      { timestamp: now - 10 * day, value: 40 },
    ];
    const window = rangeWindow(history, oneDay, now);
    expect(window.updates).toBe(0);
    expect(window.standing?.value).toBe(40);
    expect(window.points).toEqual([
      { timestamp: now - day, value: 40, carried: true },
      { timestamp: now, value: 40, carried: true },
    ]);
  });

  it("is relative to now, so older publications do not appear inside a short window", () => {
    const now = Date.parse("2026-10-25T00:00:00Z");
    const history = [
      { timestamp: now - 9 * day, value: 30 },
      { timestamp: now - 3 * day, value: 55 },
      { timestamp: now - 1 * day, value: 61 },
    ];
    const window = rangeWindow(history, oneWeek, now);
    expect(window.updates).toBe(2);
    expect(window.points[0]).toEqual({ timestamp: now - 7 * day, value: 30, carried: true });
    expect(window.points.filter((point) => !point.carried).map((point) => point.value)).toEqual([55, 61]);
    expect(window.points[window.points.length - 1]).toEqual({ timestamp: now, value: 61, carried: true });
  });

  it("ALL starts at the first publication", () => {
    const now = Date.parse("2026-10-25T00:00:00Z");
    const history = [
      { timestamp: now - 9 * day, value: 30 },
      { timestamp: now - 3 * day, value: 55 },
    ];
    const window = rangeWindow(history, { label: "ALL", unit: "all" }, now);
    expect(window.points[0]).toEqual(history[0]);
    expect(window.updates).toBe(2);
  });
});
