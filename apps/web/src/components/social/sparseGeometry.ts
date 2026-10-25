import type { ChartPoint } from "../../adapters/templateTypes";

const X_PAD = 6;
const TOP_PAD = 14;
const BOTTOM_PAD = 8;

export type SparsePoint = ChartPoint & { x: number; y: number };

/**
 * Places the last one or two published observations in a 0–100 box.
 * The value domain mirrors WealthsimpleAreaChart so a sparse market reads like a short
 * version of a dense one. A single observation sits at the right edge (latest).
 */
export function sparseGeometry(history: ChartPoint[]): SparsePoint[] {
  const points = history.slice(-2);
  if (!points.length) return [];
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, 1);
  const lo = min - range * 0.24;
  const hi = max + range * 0.1;
  const first = points[0]!;
  const last = points[points.length - 1]!;
  const span = last.timestamp - first.timestamp;
  const y = (value: number) => TOP_PAD + (1 - (value - lo) / (hi - lo)) * (100 - TOP_PAD - BOTTOM_PAD);
  const x = (point: ChartPoint, index: number) => {
    if (points.length < 2) return 100 - X_PAD;
    const share = span > 0 ? (point.timestamp - first.timestamp) / span : index;
    return X_PAD + share * (100 - X_PAD * 2);
  };
  return points.map((point, index) => ({ ...point, x: x(point, index), y: y(point.value) }));
}
