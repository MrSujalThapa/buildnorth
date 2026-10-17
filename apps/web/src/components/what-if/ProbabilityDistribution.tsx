import { useId, useMemo } from "react";

import type { SimulationPoint } from "../../adapters/simulationTypes";

export type DistributionSeries = {
  id: string;
  label: string;
  points: SimulationPoint[];
  selected?: boolean;
};

type Props = {
  ariaLabel: string;
  series: DistributionSeries[];
  currentOdds?: number | null;
  compact?: boolean;
};

const WIDTH = 720;
const HEIGHT = 250;
const LEFT = 42;
const RIGHT = 18;
const TOP = 20;
const BOTTOM = 38;

function percentile(values: number[], ratio: number): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor((sorted.length - 1) * ratio)] ?? 0;
}

function linePath(points: Array<{ x: number; y: number }>) {
  return points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
}

export default function ProbabilityDistribution({ ariaLabel, series, currentOdds, compact = false }: Props) {
  const fillId = `distribution-${useId().replace(/:/g, "")}`;
  const chart = useMemo(() => {
    const values = series.flatMap((item) => item.points.map((point) => point.x));
    const min = Math.max(0, Math.floor((Math.min(...values, currentOdds ?? 100) - 5) / 5) * 5);
    const max = Math.min(100, Math.ceil((Math.max(...values, currentOdds ?? 0) + 5) / 5) * 5);
    const span = Math.max(max - min, 1);
    const bins = compact ? 30 : 42;
    const distributions = series.map((item) => {
      const rawCounts = Array.from({ length: bins }, () => 0);
      item.points.forEach((point) => {
        const index = Math.min(bins - 1, Math.max(0, Math.floor(((point.x - min) / span) * bins)));
        rawCounts[index] = (rawCounts[index] ?? 0) + 1;
      });
      const counts = rawCounts.map((_, index) => {
        const neighborhood = rawCounts.slice(Math.max(0, index - 2), Math.min(bins, index + 3));
        return neighborhood.reduce((sum, count) => sum + count, 0) / neighborhood.length;
      });
      return { ...item, counts, values: item.points.map((point) => point.x) };
    });
    const peak = Math.max(1, ...distributions.flatMap((item) => item.counts));
    const xFor = (value: number) => LEFT + ((value - min) / span) * (WIDTH - LEFT - RIGHT);
    const curves = distributions.map((item) => ({
      ...item,
      path: linePath(item.counts.map((count, index) => ({
        x: LEFT + ((index + 0.5) / bins) * (WIDTH - LEFT - RIGHT),
        y: HEIGHT - BOTTOM - (count / peak) * (HEIGHT - TOP - BOTTOM),
      }))),
      median: percentile(item.values, 0.5),
      low: percentile(item.values, 0.1),
      high: percentile(item.values, 0.9),
    }));
    return { min, max, xFor, curves };
  }, [compact, currentOdds, series]);

  return (
    <div className={compact ? "probability-distribution compact" : "probability-distribution"}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={ariaLabel}>
        <defs>
          <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--what-if-accent)" stopOpacity="0.32" />
            <stop offset="100%" stopColor="var(--what-if-accent)" stopOpacity="0.03" />
          </linearGradient>
        </defs>
        <line x1={LEFT} x2={WIDTH - RIGHT} y1={HEIGHT - BOTTOM} y2={HEIGHT - BOTTOM} className="distribution-axis" />
        {chart.curves.map((curve, index) => (
          <g key={curve.id} className={curve.selected ? "distribution-series selected" : "distribution-series"}>
            {series.length === 1 ? <path d={`${curve.path} L${WIDTH - RIGHT},${HEIGHT - BOTTOM} L${LEFT},${HEIGHT - BOTTOM} Z`} fill={`url(#${fillId})`} /> : null}
            <path d={curve.path} className={`distribution-line tone-${index}`} />
            <line x1={chart.xFor(curve.median)} x2={chart.xFor(curve.median)} y1={TOP + 8} y2={HEIGHT - BOTTOM} className="distribution-median" />
          </g>
        ))}
        {currentOdds != null ? <line x1={chart.xFor(currentOdds)} x2={chart.xFor(currentOdds)} y1={TOP} y2={HEIGHT - BOTTOM} className="distribution-current" /> : null}
        {!compact ? (
          <>
            <text x={LEFT} y={HEIGHT - 10}>{chart.min}%</text>
            <text x={(LEFT + WIDTH - RIGHT) / 2} y={HEIGHT - 10} textAnchor="middle">Resulting odds</text>
            <text x={WIDTH - RIGHT} y={HEIGHT - 10} textAnchor="end">{chart.max}%</text>
            <text x={12} y={TOP} className="distribution-y">Likelihood</text>
          </>
        ) : null}
      </svg>
      <div className="visually-hidden">
        {chart.curves.map((curve) => `${curve.label}: most likely ${curve.median.toFixed(0)}%, likely range ${curve.low.toFixed(0)} to ${curve.high.toFixed(0)}%.`).join(" ")}
      </div>
    </div>
  );
}
