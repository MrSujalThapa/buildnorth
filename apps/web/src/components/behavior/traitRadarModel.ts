import type { TraitEstimate, TraitSeries } from "../../api/client";

export const RADAR_SIZE = 600;
export const RADAR_CENTER = RADAR_SIZE / 2;
export const RADAR_RADIUS = 200;
export const RADAR_RINGS = [0.2, 0.4, 0.6, 0.8, 1];

/** Palette shared with the execution-profile (Details) radar. */
const SERIES_COLORS: Record<string, string> = {
  overall: "#2ec4b6",
  career: "#2e86de",
  personal: "#ff9f1c",
  relationships: "#e71d36",
  fitness: "#6a994e",
  reading: "#c9184a",
  coding: "#8e7cf0",
  school: "#f4d35e",
  work: "#4cc9f0",
  sports: "#90be6d",
  music: "#f15bb5",
};
const FALLBACK_COLORS = ["#2ec4b6", "#ff9f1c", "#2e86de", "#e71d36", "#6a994e", "#c9184a"];

export function seriesColor(id: string, index = 0): string {
  return SERIES_COLORS[id] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length] ?? "#2ec4b6";
}

export type RadarPoint = { traitId: string; index: number; value: number; x: number; y: number };

export type RadarSeriesShape = {
  id: string;
  label: string;
  color: string;
  points: RadarPoint[];
  missing: string[];
  mean: number | null;
};

export function axisAngle(index: number, total: number): number {
  return -Math.PI / 2 + (index / total) * Math.PI * 2;
}

export function polar(index: number, total: number, magnitude: number) {
  const angle = axisAngle(index, total);
  return {
    x: RADAR_CENTER + Math.cos(angle) * RADAR_RADIUS * magnitude,
    y: RADAR_CENTER + Math.sin(angle) * RADAR_RADIUS * magnitude,
  };
}

/** Ensures an Overall series exists, then orders it last so it draws on top. */
export function radarSeries(traits: TraitEstimate[], series: TraitSeries[]): RadarSeriesShape[] {
  const rows = series.some((row) => row.id === "overall")
    ? series
    : [{ id: "overall", label: "Overall", values: Object.fromEntries(traits.map((item) => [item.id, item.value])) }, ...series];
  const shapes = rows.map((row, rowIndex) => {
    const points: RadarPoint[] = [];
    const missing: string[] = [];
    traits.forEach((trait, index) => {
      const value = row.values[trait.id];
      if (value == null || !Number.isFinite(value)) {
        missing.push(trait.id);
        return;
      }
      const clamped = Math.min(1, Math.max(0, value));
      points.push({ traitId: trait.id, index, value: clamped, ...polar(index, traits.length, clamped) });
    });
    const mean = points.length ? points.reduce((sum, point) => sum + point.value, 0) / points.length : null;
    return { id: row.id, label: row.label, color: seriesColor(row.id, rowIndex), points, missing, mean };
  });
  return [...shapes.filter((shape) => shape.id !== "overall"), ...shapes.filter((shape) => shape.id === "overall")]
    .filter((shape) => shape.points.length > 0);
}

/** Polygon through measured axes only; an unmeasured axis is skipped, never drawn as zero. */
export function seriesPath(shape: RadarSeriesShape): string {
  if (!shape.points.length) return "";
  return shape.points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
}

export function percent(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}
