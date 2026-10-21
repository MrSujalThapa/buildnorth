import { useMemo, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CollectionSeries } from "../../api/client";

type Props = {
  series: CollectionSeries[];
  interactive?: boolean;
};

function merge(series: CollectionSeries[]) {
  const stamps = new Set<number>();
  const mapped = series.map((item) => ({
    ...item,
    values: item.points
      .map((point) => ({
        timestamp: typeof point.timestamp === "number" ? point.timestamp : Date.parse(String(point.timestamp ?? "")),
        value: point.value,
      }))
      .filter((point) => Number.isFinite(point.timestamp)),
  }));
  for (const item of mapped) {
    for (const point of item.values) stamps.add(point.timestamp);
  }
  const rows = [...stamps].sort((left, right) => left - right).map((timestamp) => {
    const row: Record<string, number | null> = { timestamp };
    for (const item of mapped) {
      const match = item.values.find((point) => point.timestamp === timestamp);
      row[item.goal_id] = match?.value ?? null;
    }
    return row;
  });
  return { rows, mapped };
}

export default function CollectionChart({ series, interactive = true }: Props) {
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const { rows, mapped } = useMemo(() => merge(series), [series]);
  const visible = mapped.filter((item) => !hidden[item.goal_id]);
  const values = visible.flatMap((item) => item.values.map((point) => point.value));
  const low = values.length ? Math.min(...values) : 0;
  const high = values.length ? Math.max(...values) : 100;
  const padding = Math.max(3, (high - low) * 0.18);
  const domain: [number, number] = [Math.max(0, low - padding), Math.min(100, high + padding)];

  if (!rows.length) {
    return <div className="collection-chart-empty">No published odds to chart yet.</div>;
  }

  return (
    <div className="collection-chart">
      <div className="collection-chart-plot">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 8, left: 8, bottom: 4 }}>
            <XAxis dataKey="timestamp" hide />
            <YAxis hide domain={domain} />
            <Tooltip
              cursor={{ stroke: "var(--app-border)" }}
              content={({ payload, label }) => {
                if (!payload?.length) return null;
                const date = new Date(Number(label)).toLocaleDateString("en-CA", {
                  month: "short",
                  day: "numeric",
                });
                return (
                  <div className="collection-tooltip">
                    <strong>{date}</strong>
                    {payload.map((entry) => {
                      const item = mapped.find((row) => row.goal_id === entry.dataKey);
                      if (!item || entry.value == null) return null;
                      return (
                        <span key={item.goal_id} style={{ color: item.color }}>
                          {item.title}: {Number(entry.value).toFixed(1)}%
                        </span>
                      );
                    })}
                  </div>
                );
              }}
            />
            {visible.map((item) => (
              <Line
                key={item.goal_id}
                type="monotone"
                dataKey={item.goal_id}
                stroke={item.color}
                strokeWidth={2}
                dot={item.points.length === 1 ? { r: 4 } : false}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {interactive ? (
        <ul className="collection-legend">
          {mapped.map((item) => (
            <li key={item.goal_id}>
              <button
                type="button"
                className={hidden[item.goal_id] ? "is-off" : undefined}
                onClick={() => setHidden((current) => ({ ...current, [item.goal_id]: !current[item.goal_id] }))}
              >
                <i style={{ background: item.color }} />
                {item.title}
                {item.withheld ? " · withheld" : ""}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
