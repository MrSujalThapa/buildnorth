import type { CSSProperties } from "react";

import { formatOutcome, formatOutcomeRange, targetLabel, type OutcomeScale } from "../../adapters/outcomeFormat";

export type OutcomeIntervalRow = {
  id: string;
  label: string;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  selected?: boolean;
};

type Props = {
  ariaLabel: string;
  rows: OutcomeIntervalRow[];
  scale: OutcomeScale;
};

/** 10th–90th percentile of simulated end values per option, on one shared axis in the goal's unit. */
export default function OutcomeIntervals({ ariaLabel, rows, scale }: Props) {
  const values = rows.flatMap((row) => [row.p10, row.p50, row.p90]).filter((value): value is number => value != null);
  if (!values.length) {
    return (
      <div className="outcome-intervals is-empty" role="note">
        No simulated outcomes yet.
      </div>
    );
  }
  if (scale.target != null) values.push(scale.target);
  const lowest = Math.min(...values);
  const highest = Math.max(...values);
  const pad = Math.max((highest - lowest) * 0.06, Math.abs(highest) * 1e-6, 1e-9);
  const min = lowest - pad;
  const span = highest + pad - min;
  const at = (value: number) => `${((value - min) / span) * 100}%`;
  const target = targetLabel(scale);
  const format = (value: number) => formatOutcome(value, scale.unit);

  return (
    <figure className="outcome-intervals" aria-label={ariaLabel}>
      <ul>
        {rows.map((row) => {
          const priced = row.p10 != null && row.p90 != null;
          const barStyle = priced
            ? ({ left: at(Math.min(row.p10!, row.p90!)), right: `calc(100% - ${at(Math.max(row.p10!, row.p90!))})` } as CSSProperties)
            : undefined;
          return (
            <li key={row.id} className={row.selected ? "selected" : undefined}>
              <span className="outcome-interval-label">{row.label}</span>
              <div className="outcome-interval-track">
                {scale.target != null ? <i className="outcome-interval-target" style={{ left: at(scale.target) }} /> : null}
                {priced ? <b className="outcome-interval-bar" style={barStyle} /> : null}
                {row.p50 != null ? <i className="outcome-interval-median" style={{ left: at(row.p50) }} /> : null}
              </div>
              <span className="outcome-interval-value">
                {priced ? formatOutcomeRange(row.p10, row.p90, scale.unit) : "Not priced"}
              </span>
            </li>
          );
        })}
      </ul>
      <figcaption>
        <span>{format(min + pad)}</span>
        <span>{target ? `${target} · bars span 8 in 10 simulated futures` : "Bars span 8 in 10 simulated futures"}</span>
        <span>{format(highest)}</span>
      </figcaption>
    </figure>
  );
}
