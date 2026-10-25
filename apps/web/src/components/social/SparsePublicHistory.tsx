import { useId } from "react";
import type { ChartPoint } from "../../adapters/templateTypes";
import { chartTrend } from "../market/chartTrend";
import "../market/wealthsimple-chart.css";
import { sparseGeometry } from "./sparseGeometry";

type Props = { history: ChartPoint[]; compact?: boolean };

const dateFormat = new Intl.DateTimeFormat("en", {
  month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
});

function formatOdds(value: number): string {
  return `${(Math.round(value * 10) / 10).toLocaleString()}%`;
}

/** One or two published observations, drawn with the area chart's step semantics. */
export default function SparsePublicHistory({ history, compact = false }: Props) {
  const rawId = useId();
  const gradientId = `sparse-gradient-${rawId.replace(/:/g, "")}`;
  const plotted = sparseGeometry(history);
  const label = plotted
    .map((point) => `${formatOdds(point.value)} published ${dateFormat.format(point.timestamp)}`)
    .join("; ");
  const first = plotted[0];
  const last = plotted[plotted.length - 1];
  if (!first || !last) return null;
  const line = plotted.length === 2
    ? `M ${first.x} ${first.y} H ${last.x} V ${last.y}`
    : "";
  const area = plotted.length === 2
    ? `${line} V 100 H ${first.x} Z`
    : "";

  return (
    <figure className={`sparse-chart${compact ? " is-compact" : ""}`} role="img" aria-label={label}>
      <div className={`sparse-chart-plot ws-chart trend-${chartTrend(plotted)}`} data-testid="sparse-chart-plot">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" focusable="false">
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--market-chart-accent, #299f96)" stopOpacity={0.42} />
              <stop offset="55%" stopColor="var(--market-chart-accent, #299f96)" stopOpacity={0.14} />
              <stop offset="100%" stopColor="var(--market-chart-accent, #299f96)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <line
            className="sparse-chart-guide"
            x1={0}
            x2={100}
            y1={last.y}
            y2={last.y}
            vectorEffect="non-scaling-stroke"
          />
          {area ? <path d={area} fill={`url(#${gradientId})`} stroke="none" /> : null}
          {line ? <path className="sparse-chart-line" d={line} vectorEffect="non-scaling-stroke" /> : null}
        </svg>
        {plotted.map((point, index) => (
          <span
            key={`${point.timestamp}-${index}`}
            className="sparse-chart-dot"
            style={{ left: `${point.x}%`, top: `${point.y}%` }}
            aria-hidden="true"
          />
        ))}
      </div>
      {!compact ? (
        <figcaption className="sparse-chart-caption">
          {plotted.map((point, index) => (
            <span key={`${point.timestamp}-${index}`}>
              <strong>{formatOdds(point.value)}</strong>
              <time dateTime={new Date(point.timestamp).toISOString()}>{dateFormat.format(point.timestamp)}</time>
            </span>
          ))}
          <em>{plotted.length === 1 ? "One published forecast so far. The line grows with each update." : "Two published forecasts so far."}</em>
        </figcaption>
      ) : null}
    </figure>
  );
}
