import type { ChartPoint } from "../../adapters/templateTypes";

type Props = { history: ChartPoint[]; compact?: boolean };

const dateFormat = new Intl.DateTimeFormat("en", {
  month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
});

export default function SparsePublicHistory({ history, compact = false }: Props) {
  const observations = history.slice(0, 2);
  const label = observations.map((point) =>
    `${Math.round(point.value * 10) / 10}% published ${dateFormat.format(point.timestamp)}`,
  ).join("; ");

  return (
    <div className={`sparse-public-history${compact ? " is-compact" : ""}`} role="img" aria-label={label}>
      {!compact ? <p className="sparse-public-heading">Published observations</p> : null}
      <div className="sparse-public-points" aria-hidden="true">
        {observations.map((point, index) => (
          <div className="sparse-public-point" key={`${point.timestamp}-${index}`}>
            <span className="sparse-public-dot" />
            <strong>{(Math.round(point.value * 10) / 10).toLocaleString()}%</strong>
            <time dateTime={new Date(point.timestamp).toISOString()}>{dateFormat.format(point.timestamp)}</time>
          </div>
        ))}
      </div>
      {!compact ? <p className="sparse-public-note">A trend appears after more forecasts are published.</p> : null}
    </div>
  );
}
