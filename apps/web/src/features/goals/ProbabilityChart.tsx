import type { ForecastStatus } from "../../api/client";
import { forecastStatusLabel, formatChangePp, formatProbability } from "./labels";

export interface ProbabilityPoint {
  t: number;
  p: number;
}

export interface ProbabilityChartProps {
  chartId: string;
  title: string;
  status: ForecastStatus;
  series?: ProbabilityPoint[];
  currentProbability?: number;
  changePp?: number;
  targetProbability?: number;
}

const WIDTH = 640;
const HEIGHT = 175;
const PAD = { top: 10, right: 2, bottom: 0, left: 2 };

function xOf(point: ProbabilityPoint, series: ProbabilityPoint[]): number {
  const inner = WIDTH - PAD.left - PAD.right;
  const min = series[0]?.t ?? 0;
  const max = series.at(-1)?.t ?? min;
  if (max === min) return PAD.left;
  return PAD.left + ((point.t - min) / (max - min)) * inner;
}

function yOf(probability: number, series: ProbabilityPoint[]): number {
  const inner = HEIGHT - PAD.top - PAD.bottom;
  const values = series.map((point) => point.p);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, 0.01);
  const low = min - range * 0.24;
  const high = max + range * 0.1;
  return PAD.top + (1 - (probability - low) / (high - low)) * inner;
}

function isPricedMarket(series: ProbabilityPoint[] | undefined, currentProbability: number | undefined): boolean {
  return Boolean(series && series.length >= 2 && currentProbability != null);
}

export function ProbabilityChart({
  chartId,
  title,
  status,
  series = [],
  currentProbability,
  changePp,
  targetProbability,
}: ProbabilityChartProps) {
  const priced = isPricedMarket(series, currentProbability);
  const titleId = `${chartId}-chart-title`;
  const descId = `${chartId}-chart-desc`;
  const description = priced
    ? `Probability history for ${title}. Current odds ${formatProbability(currentProbability ?? 0)}. Forecast ${forecastStatusLabel(status)}.`
    : `Probability history for ${title}. Market is not priced. No probability series is shown. Forecast ${forecastStatusLabel(status)}.`;

  const line = priced
    ? series.map((point) => `${xOf(point, series).toFixed(1)},${yOf(point.p, series).toFixed(1)}`).join(" ")
    : "";
  const area = priced ? `${PAD.left},${HEIGHT} ${line} ${WIDTH - PAD.right},${HEIGHT}` : "";
  const gradientId = `${chartId.replace(/[^a-zA-Z0-9_-]/g, "")}-area-gradient`;

  return (
    <figure className={`chart-surface${priced ? "" : " is-unpriced"}`}>
      <svg
        className="chart-svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-labelledby={`${titleId} ${descId}`}
      >
        <title id={titleId}>{`Probability chart: ${title}`}</title>
        <desc id={descId}>{description}</desc>
        <defs><linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#63b8b1" stopOpacity=".52"/><stop offset="24%" stopColor="#78c1bb" stopOpacity=".4"/><stop offset="50%" stopColor="#a8d5d1" stopOpacity=".24"/><stop offset="75%" stopColor="#d5e9e6" stopOpacity=".1"/><stop offset="100%" stopColor="var(--surface)" stopOpacity="0"/></linearGradient></defs>
        {targetProbability != null ? (
          <line
            className="chart-target"
            x1={PAD.left}
            x2={WIDTH - PAD.right}
            y1={yOf(targetProbability, series)}
            y2={yOf(targetProbability, series)}
          />
        ) : null}
        {priced ? <polygon className="chart-area" points={area} fill={`url(#${gradientId})`} /> : null}
        {priced ? <polyline className="chart-line" data-testid="probability-line" fill="none" points={line} /> : null}
      </svg>
      <figcaption className="visually-hidden">
        <span>{priced ? formatProbability(currentProbability ?? 0) : "Not priced"}</span>
        <span>{forecastStatusLabel(status)}</span>
        {priced && changePp != null ? <span>{formatChangePp(changePp)}</span> : null}
      </figcaption>
    </figure>
  );
}
