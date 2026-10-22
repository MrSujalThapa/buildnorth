import { useState } from "react";
import type { TraitEstimate, TraitSeries } from "../../api/client";
import "./trait-radar.css";

type Props = {
  traits: TraitEstimate[];
  series: TraitSeries[];
};

const SIZE = 520;
const CENTER = SIZE / 2;
const RADIUS = 170;
const RINGS = [0.25, 0.5, 0.75, 1];

const SERIES_COLORS: Record<string, string> = {
  overall: "var(--trait-overall)",
  career: "var(--trait-career)",
  personal: "var(--trait-personal)",
  relationships: "var(--trait-relationships)",
};

export function seriesColor(id: string): string {
  return SERIES_COLORS[id] ?? "var(--trait-overall)";
}

function angle(index: number, total: number): number {
  return -Math.PI / 2 + (index / total) * Math.PI * 2;
}

function at(index: number, total: number, magnitude: number) {
  const theta = angle(index, total);
  return { x: CENTER + Math.cos(theta) * RADIUS * magnitude, y: CENTER + Math.sin(theta) * RADIUS * magnitude };
}

function anchor(index: number, total: number) {
  const theta = angle(index, total);
  const cos = Math.cos(theta);
  const sin = Math.sin(theta);
  return {
    textAnchor: cos > 0.3 ? "start" : cos < -0.3 ? "end" : "middle",
    dy: sin > 0.5 ? 16 : sin < -0.5 ? -8 : 5,
  } as const;
}

export function pointsChange(item: TraitEstimate): number | null {
  if (item.value == null || item.previous_value == null) return null;
  return Math.round((item.value - item.previous_value) * 100);
}

function percent(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function Readout({ item, series }: { item: TraitEstimate; series: TraitSeries[] }) {
  const change = pointsChange(item);
  const contexts = series.filter((row) => row.id !== "overall");
  return (
    <div className="trait-readout" aria-live="polite">
      <div className="trait-readout-head">
        <strong>{item.name}</strong>
        <span className="trait-readout-value">{percent(item.value)}</span>
      </div>
      {item.value != null && item.interval ? (
        <p className="trait-readout-meta">
          Likely {percent(item.interval[0])}–{percent(item.interval[1])}
          {change != null && change !== 0 ? ` · ${change > 0 ? "+" : "−"}${Math.abs(change)} pts over ${Math.round(item.window_days ?? 28)} days` : null}
          {` · ${item.observations} observation${item.observations === 1 ? "" : "s"}`}
        </p>
      ) : (
        <p className="trait-readout-meta">
          Not enough evidence yet · {item.observations} observation{item.observations === 1 ? "" : "s"}
        </p>
      )}
      {contexts.length ? (
        <p className="trait-readout-contexts">
          {contexts.map((row) => (
            <span key={row.id}>
              <i style={{ background: seriesColor(row.id) }} aria-hidden="true" />
              {row.label} {percent(row.values[item.id])}
            </span>
          ))}
        </p>
      ) : null}
      <p className="trait-readout-copy">{item.description} {item.measurement}</p>
      {item.forecast_use === "execution_probability" ? (
        <p className="trait-readout-copy">Used in forecasts as your probability of carrying out planned actions.</p>
      ) : null}
    </div>
  );
}

export function TraitRadar({ traits, series }: Props) {
  const total = traits.length;
  const firstMeasured = traits.find((item) => item.value != null)?.id ?? traits[0]?.id ?? null;
  const [focused, setFocused] = useState<string | null>(null);
  const activeId = focused && traits.some((item) => item.id === focused) ? focused : firstMeasured;
  const active = traits.find((item) => item.id === activeId) ?? null;
  const overlay = series.length > 1;
  if (total < 3) return null;

  return (
    <section className="trait-radar" aria-label="Behavior profile">
      <div className="trait-radar-stage">
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={`Radar of ${traits.map((item) => `${item.name} ${percent(item.value)}`).join(", ")}`}>
          {RINGS.map((ring) => (
            <polygon
              key={ring}
              className="trait-ring"
              points={traits.map((_, index) => {
                const pt = at(index, total, ring);
                return `${pt.x},${pt.y}`;
              }).join(" ")}
            />
          ))}
          {traits.map((item, index) => {
            const edge = at(index, total, 1);
            return (
              <line
                key={`spoke-${item.id}`}
                className={item.value == null ? "trait-spoke is-empty" : "trait-spoke"}
                x1={CENTER}
                y1={CENTER}
                x2={edge.x}
                y2={edge.y}
              />
            );
          })}
          {!overlay
            ? traits.map((item, index) => {
                if (item.value == null || !item.interval) return null;
                const low = at(index, total, item.interval[0]);
                const high = at(index, total, item.interval[1]);
                return <line key={`band-${item.id}`} className="trait-band" x1={low.x} y1={low.y} x2={high.x} y2={high.y} />;
              })
            : null}
          {series.map((row) => {
            const values = traits.map((item) => row.values[item.id] ?? null);
            const complete = values.every((value) => value != null);
            const color = seriesColor(row.id);
            const points = values.map((value, index) => at(index, total, value ?? 0));
            return (
              <g key={row.id} className="trait-series" style={{ color }}>
                {complete ? (
                  <polygon
                    className={overlay ? "trait-shape is-overlay" : "trait-shape"}
                    points={points.map((pt) => `${pt.x},${pt.y}`).join(" ")}
                  />
                ) : (
                  values.map((value, index) => {
                    const nextIndex = (index + 1) % total;
                    const next = values[nextIndex];
                    if (value == null || next == null) return null;
                    const start = points[index];
                    const end = points[nextIndex];
                    if (!start || !end) return null;
                    return <line key={`edge-${index}`} className="trait-edge" x1={start.x} y1={start.y} x2={end.x} y2={end.y} />;
                  })
                )}
                {values.map((value, index) => {
                  const pt = points[index];
                  const item = traits[index];
                  if (value == null || !pt || !item) return null;
                  return (
                    <circle
                      key={`node-${item.id}`}
                      className={item.id === activeId ? "trait-node is-active" : "trait-node"}
                      cx={pt.x}
                      cy={pt.y}
                      r={item.id === activeId ? 5.5 : 4}
                    />
                  );
                })}
              </g>
            );
          })}
          {traits.map((item, index) => {
            const pt = at(index, total, 1.17);
            const place = anchor(index, total);
            return (
              <g
                key={`label-${item.id}`}
                className={item.id === activeId ? "trait-axis is-active" : "trait-axis"}
                role="button"
                tabIndex={0}
                aria-pressed={item.id === activeId}
                aria-label={`${item.name}, ${item.value == null ? "not enough evidence" : percent(item.value)}`}
                onMouseEnter={() => setFocused(item.id)}
                onFocus={() => setFocused(item.id)}
                onClick={() => setFocused(item.id)}
              >
                <text x={pt.x} y={pt.y + place.dy} textAnchor={place.textAnchor}>
                  <tspan className="trait-axis-name">{item.name}</tspan>
                  <tspan className="trait-axis-value" x={pt.x} dy={17}>{percent(item.value)}</tspan>
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      {overlay ? (
        <ul className="trait-legend" aria-label="Contexts">
          {series.map((row) => (
            <li key={row.id}>
              <i style={{ background: seriesColor(row.id) }} aria-hidden="true" />
              {row.label}
            </li>
          ))}
        </ul>
      ) : null}
      {active ? <Readout item={active} series={series} /> : null}
    </section>
  );
}
