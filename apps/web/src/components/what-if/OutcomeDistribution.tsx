import type { OutcomeBin } from "../../adapters/impactViewModel";
import { formatOutcome, targetLabel, type OutcomeScale } from "../../adapters/outcomeFormat";

type Props = {
  ariaLabel: string;
  bins: OutcomeBin[];
  scale: OutcomeScale;
  median?: number | null;
  low?: number | null;
  high?: number | null;
};

const WIDTH = 720;
const HEIGHT = 250;
const LEFT = 18;
const RIGHT = 18;
const TOP = 30;
const BOTTOM = 38;

function meetsTarget(bin: OutcomeBin, scale: OutcomeScale): boolean {
  if (scale.target == null) return false;
  const center = (bin.lower + bin.upper) / 2;
  return scale.direction === "at_most" ? center <= scale.target : center >= scale.target;
}

/** Histogram of simulated end values in the goal's unit; bars that meet the target are highlighted. */
export default function OutcomeDistribution({ ariaLabel, bins, scale, median = null, low = null, high = null }: Props) {
  if (!bins.length) {
    return (
      <div className="probability-distribution is-empty" role="note">
        Outcome range unavailable for this scenario.
      </div>
    );
  }

  const edges = bins.flatMap((bin) => [bin.lower, bin.upper]);
  if (scale.target != null) edges.push(scale.target);
  const lowest = Math.min(...edges);
  const highest = Math.max(...edges);
  const pad = Math.max((highest - lowest) * 0.04, Math.abs(highest) * 1e-6, 1e-9);
  const min = lowest - pad;
  const max = highest + pad;
  const xFor = (value: number) => LEFT + ((value - min) / (max - min)) * (WIDTH - LEFT - RIGHT);
  const density = bins.map((bin) => bin.mass / Math.max(bin.upper - bin.lower, 1e-12));
  const peak = Math.max(...density, 1e-12);
  const plotHeight = HEIGHT - TOP - BOTTOM;
  const target = targetLabel(scale);
  const format = (value: number) => formatOutcome(value, scale.unit);
  const targetX = scale.target == null ? null : xFor(scale.target);

  return (
    <div className="probability-distribution outcome-distribution">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={ariaLabel}>
        <line x1={LEFT} x2={WIDTH - RIGHT} y1={HEIGHT - BOTTOM} y2={HEIGHT - BOTTOM} className="distribution-axis" />
        {bins.map((bin, index) => {
          const x = xFor(bin.lower);
          const width = Math.max(xFor(bin.upper) - x - 1, 1);
          const height = ((density[index] ?? 0) / peak) * plotHeight;
          return (
            <rect
              key={`${bin.lower}-${bin.upper}`}
              x={x}
              y={HEIGHT - BOTTOM - height}
              width={width}
              height={height}
              rx={2}
              className={meetsTarget(bin, scale) ? "outcome-bar meets" : "outcome-bar"}
            />
          );
        })}
        {median != null ? (
          <line x1={xFor(median)} x2={xFor(median)} y1={TOP} y2={HEIGHT - BOTTOM} className="distribution-median" />
        ) : null}
        {targetX != null && target ? (
          <>
            <line x1={targetX} x2={targetX} y1={TOP - 12} y2={HEIGHT - BOTTOM} className="distribution-current" />
            <text
              x={targetX}
              y={TOP - 16}
              textAnchor={targetX > WIDTH * 0.75 ? "end" : targetX < WIDTH * 0.25 ? "start" : "middle"}
              className="outcome-target-label"
            >
              {target}
            </text>
          </>
        ) : null}
        <text x={LEFT} y={HEIGHT - 10}>{format(min + pad)}</text>
        <text x={WIDTH - RIGHT} y={HEIGHT - 10} textAnchor="end">{format(max - pad)}</text>
      </svg>
      <p className="visually-hidden">
        {median != null ? `Median simulated result ${format(median)}. ` : ""}
        {low != null && high != null ? `Eight in ten futures land between ${format(low)} and ${format(high)}. ` : ""}
        {target ?? ""}
      </p>
    </div>
  );
}
