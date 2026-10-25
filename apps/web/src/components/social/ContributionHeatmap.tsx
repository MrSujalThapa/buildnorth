import { useMemo, useState } from "react";

type Props = {
  days: { day: string; count: number }[];
  total: number;
  publicView?: boolean;
};

const WEEKDAYS = ["", "Mon", "", "Wed", "", "Fri", ""];

function levelFor(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0;
  const ratio = count / max;
  if (ratio > 0.75) return 4;
  if (ratio > 0.5) return 3;
  if (ratio > 0.25) return 2;
  return 1;
}

function enumerateDays(end: Date): Date[] {
  const days: Date[] = [];
  const cursor = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), end.getUTCDate()));
  const start = new Date(cursor);
  start.setUTCDate(start.getUTCDate() - 364);
  start.setUTCDate(start.getUTCDate() - start.getUTCDay());
  for (let stamp = start.getTime(); stamp <= cursor.getTime(); stamp += 86_400_000) {
    days.push(new Date(stamp));
  }
  return days;
}

function iso(day: Date): string {
  return day.toISOString().slice(0, 10);
}

export default function ContributionHeatmap({ days, total, publicView = false }: Props) {
  const [tip, setTip] = useState<string | null>(null);
  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of days) map.set(item.day.slice(0, 10), item.count);
    return map;
  }, [days]);
  const cells = useMemo(() => enumerateDays(new Date()), []);
  const max = Math.max(1, ...days.map((item) => item.count));
  const weeks: Date[][] = [];
  for (let index = 0; index < cells.length; index += 7) weeks.push(cells.slice(index, index + 7));
  const monthMarks = weeks.flatMap((week, index) => {
    const first = week[0];
    if (!first) return [];
    const prev = weeks[index - 1]?.[0];
    if (prev && prev.getUTCMonth() === first.getUTCMonth()) return [];
    return [{
      index,
      label: first.toLocaleString("en-CA", { month: "short", timeZone: "UTC" }),
    }];
  });

  return (
    <section className="heatmap" aria-label="Recorded goal activity">
      <header className="heatmap-header">
        <h2>Activity</h2>
        <p>{total} recorded events in the last year</p>
      </header>
      <p className="heatmap-scope">{publicView ? "Only events on public markets appear here." : "Market creation, publication and accepted evidence appear here."}</p>
      <div className="heatmap-scroll">
        <div className="heatmap-months" aria-hidden="true">
          <div className="heatmap-month-track">
            {monthMarks.map((mark, index) => (
              <span key={`${mark.label}-${mark.index}`} className={index % 2 ? "mobile-month-hidden" : undefined} style={{ ["--week-index" as string]: mark.index }}>
                {mark.label}
              </span>
            ))}
          </div>
        </div>
        <div className="heatmap-body">
          <div className="heatmap-weekdays" aria-hidden="true">
            {WEEKDAYS.map((label, index) => (
              <span key={`${label}-${index}`}>{label}</span>
            ))}
          </div>
          <div className="heatmap-grid" role="list">
            {weeks.map((week, weekIndex) => (
              <div className="heatmap-week" key={weekIndex}>
                {week.map((day) => {
                  const key = iso(day);
                  const count = counts.get(key) ?? 0;
                  const level = levelFor(count, max);
                  return (
                    <button
                      type="button"
                      role="listitem"
                      key={key}
                      className={`heatmap-cell level-${level}`}
                      aria-label={`${count} recorded events on ${key}`}
                      onMouseEnter={() => setTip(`${count} on ${key}`)}
                      onMouseLeave={() => setTip(null)}
                      onFocus={() => setTip(`${count} on ${key}`)}
                      onBlur={() => setTip(null)}
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>
      <footer className="heatmap-legend">
        <span>{tip ?? "Less"}</span>
        <span className="heatmap-cell level-0" aria-hidden="true" />
        <span className="heatmap-cell level-1" aria-hidden="true" />
        <span className="heatmap-cell level-2" aria-hidden="true" />
        <span className="heatmap-cell level-3" aria-hidden="true" />
        <span className="heatmap-cell level-4" aria-hidden="true" />
        <span>More</span>
      </footer>
    </section>
  );
}
