import { useState } from "react";
import type { ParameterEstimate, ParameterProfile } from "../../api/client";
import "./trait-radar.css";

const SIZE = 520;
const CENTER = SIZE / 2;
const RADIUS = 170;
const RINGS = [0.25, 0.5, 0.75, 1];

function point(index: number, total: number, value: number) {
  const theta = -Math.PI / 2 + index * 2 * Math.PI / total;
  return { x: CENTER + Math.cos(theta) * RADIUS * value, y: CENTER + Math.sin(theta) * RADIUS * value };
}

function labelPosition(index: number, total: number) {
  const theta = -Math.PI / 2 + index * 2 * Math.PI / total;
  const cos = Math.cos(theta);
  const sin = Math.sin(theta);
  return { textAnchor: cos > 0.3 ? "end" : cos < -0.3 ? "start" : "middle", dy: sin > 0.5 ? 16 : sin < -0.5 ? -8 : -14 } as const;
}

function rawValue(item: ParameterEstimate): string {
  if (item.raw_value == null) return "—";
  return `${Number(item.raw_value.toFixed(1)).toLocaleString()} ${item.unit}`;
}

export function ParameterRadar({ profile }: { profile: ParameterProfile }) {
  const parameters = profile.parameters;
  const total = parameters.length;
  const [focused, setFocused] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  const active = parameters.find((item) => item.id === focused)
    ?? parameters.find((item) => item.value != null)
    ?? parameters[0];
  if (total < 3) return <p className="profile-radar-pending">Select at least three parameters.</p>;
  const measured = parameters.filter((item) => item.value != null);
  const complete = measured.length === total;
  const points = parameters.map((item, index) => point(index, total, item.value ?? 0));
  return (
    <section className="trait-radar" aria-label="Measured parameter profile">
      {measured.length === 0 ? <p className="profile-radar-pending">No measured parameters yet. Your selected axes will fill as matching observations arrive.</p> : null}
      <div className="trait-radar-stage">
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={`Parameter radar: ${parameters.map((item) => `${item.name} ${rawValue(item)}`).join(", ")}`}>
          {RINGS.map((ring) => <polygon key={ring} className="trait-ring" points={parameters.map((_, index) => {
            const p = point(index, total, ring); return `${p.x},${p.y}`;
          }).join(" ")} />)}
          {parameters.map((item, index) => {
            const p = point(index, total, 1);
            return <line key={`spoke-${item.id}`} className={item.value == null ? "trait-spoke is-empty" : "trait-spoke"} x1={CENTER} y1={CENTER} x2={p.x} y2={p.y} />;
          })}
          <g className="trait-series" style={{ color: "var(--trait-overall)" }}>
            {complete ? <polygon className="trait-shape" points={points.map((p) => `${p.x},${p.y}`).join(" ")} /> : parameters.map((item, index) => {
              const next = (index + 1) % total;
              if (item.value == null || parameters[next]?.value == null) return null;
              return <line key={`edge-${item.id}`} className="trait-edge" x1={points[index]!.x} y1={points[index]!.y} x2={points[next]!.x} y2={points[next]!.y} />;
            })}
            {parameters.map((item, index) => item.value == null ? null : <circle key={`node-${item.id}`} className="trait-node" cx={points[index]!.x} cy={points[index]!.y} r={5} />)}
          </g>
          {parameters.map((item, index) => {
            const p = point(index, total, 1.18);
            const position = labelPosition(index, total);
            const labelX = position.textAnchor === "end" ? SIZE - 8 : position.textAnchor === "start" ? 8 : p.x;
            return <g key={item.id} className={item.id === active?.id ? "trait-axis is-active" : "trait-axis"} role="button" tabIndex={0}
              aria-label={`${item.name}, ${rawValue(item)}`} aria-pressed={item.id === active?.id}
              onMouseEnter={() => setFocused(item.id)} onFocus={() => setFocused(item.id)} onClick={() => setFocused(item.id)}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setFocused(item.id); } }}>
              <text x={labelX} y={p.y + position.dy} textAnchor={position.textAnchor}>
                <tspan className="trait-axis-name">{item.name}</tspan>
              </text>
            </g>;
          })}
        </svg>
      </div>
      {active ? <div className="trait-readout" aria-live="polite">
        <div className="trait-readout-head"><strong>{active.name}</strong><span className="trait-readout-value">{rawValue(active)}</span></div>
        <p className="trait-readout-meta">{active.observation_count} matching observation{active.observation_count === 1 ? "" : "s"} · last {active.window_days} days</p>
        <button type="button" className="markets-select" aria-expanded={details} onClick={() => setDetails((open) => !open)}>{details ? "Hide details" : "Details"}</button>
        {details ? <p className="trait-readout-copy">{active.metric} · {active.aggregation === "sum_increments" ? "sum of dated additions" : "latest measured period"} · {active.normalization} · Sources: {active.source_types.join(", ") || "none"}</p> : null}
      </div> : null}
    </section>
  );
}
