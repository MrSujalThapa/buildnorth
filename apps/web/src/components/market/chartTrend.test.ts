import { describe, expect, it } from "vitest";
import type { ChartPoint } from "../../adapters/templateTypes";
import { chartPointChange, chartTrend } from "./chartTrend";

const series = (...values: number[]): ChartPoint[] => values.map((value, index) => ({ timestamp: index, value }));

describe("displayed market trend", () => {
  it("uses the first and last visible points", () => {
    expect(chartTrend(series(20, 80, 30))).toBe("positive");
    expect(chartPointChange(series(20, 80, 30))).toBe(10);
    expect(chartTrend(series(40, 90, 25))).toBe("negative");
  });

  it("keeps unchanged and sparse history neutral", () => {
    expect(chartTrend(series(30, 45, 30))).toBe("neutral");
    expect(chartPointChange(series(30, 45, 30))).toBe(0);
    expect(chartTrend(series(30))).toBe("neutral");
    expect(chartPointChange(series(30))).toBeNull();
  });
});
