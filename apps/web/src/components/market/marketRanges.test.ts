import { describe, expect, it } from "vitest";
import {
  ODDS_EXPLORER_RANGES,
  filterHistoryForRange,
  type MarketRange,
} from "./marketRanges";

const day = 24 * 60 * 60 * 1000;

describe("Odds Explorer ranges", () => {
  it("exposes 1D 1W 1M 1Y ALL", () => {
    expect(ODDS_EXPLORER_RANGES.map((range) => range.label)).toEqual([
      "1D",
      "1W",
      "1M",
      "1Y",
      "ALL",
    ]);
  });

  it("keeps a single receipt in 1D instead of interpolating extra points", () => {
    const history = [{ timestamp: Date.parse("2026-10-01T12:00:00Z"), value: 42 }];
    const range: MarketRange = { label: "1D", amount: 1, unit: "day" };
    const filtered = filterHistoryForRange(history, range);
    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.value).toBe(42);
  });

  it("does not invent points when the window is empty besides the latest receipt", () => {
    const latest = Date.parse("2026-10-18T00:00:00Z");
    const history = [
      { timestamp: latest - 20 * day, value: 20 },
      { timestamp: latest, value: 40 },
    ];
    const range: MarketRange = { label: "1D", amount: 1, unit: "day" };
    const filtered = filterHistoryForRange(history, range);
    expect(filtered).toEqual([{ timestamp: latest, value: 40 }]);
  });
});
