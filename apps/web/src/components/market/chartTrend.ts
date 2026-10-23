import type { ChartPoint } from "../../adapters/templateTypes";

export type ChartTrend = "positive" | "negative" | "neutral";

export function chartTrend(points: ChartPoint[]): ChartTrend {
  if (points.length < 2) return "neutral";
  const first = points[0];
  const last = points[points.length - 1];
  if (!first || !last || !Number.isFinite(first.value) || !Number.isFinite(last.value)) return "neutral";
  const delta = last.value - first.value;
  return Math.abs(delta) < 0.0001 ? "neutral" : delta > 0 ? "positive" : "negative";
}

export function chartPointChange(points: ChartPoint[]): number | null {
  if (chartTrend(points) === "neutral" && points.length < 2) return null;
  const first = points[0];
  const last = points[points.length - 1];
  return first && last ? last.value - first.value : null;
}
