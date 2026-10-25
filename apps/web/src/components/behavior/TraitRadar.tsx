import { useId, useState } from "react";
import type { TraitEstimate, TraitSeries } from "../../api/client";
import {
  RADAR_CENTER,
  RADAR_RINGS,
  RADAR_SIZE,
  axisAngle,
  percent,
  polar,
  radarSeries,
  seriesPath,
} from "./traitRadarModel";
import "./trait-radar.css";

type Props = {
  traits: TraitEstimate[];
  series: TraitSeries[];
  sourceNote?: string | null;
};

export function pointsChange(item: TraitEstimate): number | null {
  if (item.value == null || item.previous_value == null) return null;
  return Math.round((item.value - item.previous_value) * 100);
}

function labelPlacement(index: number, total: number) {
  const angle = axisAngle(index, total);
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return {
    textAnchor: cos > 0.3 ? "start" : cos < -0.3 ? "end" : "middle",
    dy: sin > 0.5 ? 18 : sin < -0.5 ? -14 : 0,
  } as const;
}

/** One radar; every life area is an overlaid series on the same behavior axes. */
export function TraitRadar({ traits, series, sourceNote }: Props) {
  const uid = useId().replace(/:/g, "");
  const total = traits.length;
  const shapes = radarSeries(traits, series);
  const firstMeasured = traits.find((item) => item.value != null)?.id ?? traits[0]?.id ?? null;
  const [focusTrait, setFocusTrait] = useState<string | null>(null);
  const [focusSeries, setFocusSeries] = useState<string | null>(null);
  if (total < 3) return null;
  const activeTrait = traits.find((item) => item.id === (focusTrait ?? firstMeasured)) ?? null;
  const overall = shapes.find((shape) => shape.id === "overall");

  return (
    <section className="trait-radar" aria-label="Behavior profile">
      <div className="trait-radar-layout">
        <div className="trait-radar-stage">
          <svg
            viewBox={`0 0 ${RADAR_SIZE} ${RADAR_SIZE}`}
            role="img"
            aria-label={`Behavior radar with ${shapes.length} series: ${shapes.map((shape) => shape.label).join(", ")}`}
          >
            <defs>
              <filter id={`${uid}-glow`} x="-30%" y="-30%" width="160%" height="160%">
                <feGaussianBlur stdDeviation="5" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              <radialGradient id={`${uid}-floor`} cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="var(--trait-floor-center)" />
                <stop offset="100%" stopColor="var(--trait-floor-edge)" />
              </radialGradient>
            </defs>
            <polygon
              className="trait-floor"
              fill={`url(#${uid}-floor)`}
              points={traits.map((_, index) => {
                const pt = polar(index, total, 1);
                return `${pt.x},${pt.y}`;
              }).join(" ")}
            />
            {RADAR_RINGS.map((ring) => (
              <polygon
                key={ring}
                className={ring === 1 ? "trait-ring is-outer" : "trait-ring"}
                points={traits.map((_, index) => {
                  const pt = polar(index, total, ring);
                  return `${pt.x},${pt.y}`;
                }).join(" ")}
              />
            ))}
            {RADAR_RINGS.slice(0, -1).map((ring) => {
              const pt = polar(0, total, ring);
              return <text key={`tick-${ring}`} className="trait-tick" x={pt.x + 6} y={pt.y + 4}>{Math.round(ring * 100)}</text>;
            })}
            {traits.map((item, index) => {
              const edge = polar(index, total, 1);
              return (
                <line
                  key={`spoke-${item.id}`}
                  className={item.value == null ? "trait-spoke is-empty" : "trait-spoke"}
                  x1={RADAR_CENTER}
                  y1={RADAR_CENTER}
                  x2={edge.x}
                  y2={edge.y}
                />
              );
            })}
            {shapes.map((shape) => {
              const dimmed = focusSeries != null && focusSeries !== shape.id;
              const highlighted = focusSeries === shape.id || (focusSeries == null && shape.id === "overall");
              return (
                <g
                  key={shape.id}
                  className={`trait-series${dimmed ? " is-dimmed" : ""}${highlighted ? " is-highlighted" : ""}`}
                  style={{ color: shape.color }}
                  data-testid={`trait-series-${shape.id}`}
                >
                  {shape.points.length >= 3 ? (
                    <polygon className="trait-shape" points={seriesPath(shape)} filter={highlighted ? `url(#${uid}-glow)` : undefined} />
                  ) : shape.points.length === 2 ? (
                    <polyline className="trait-shape is-open" points={seriesPath(shape)} />
                  ) : null}
                  {shape.points.map((point) => {
                    const active = point.traitId === activeTrait?.id && (focusSeries == null || focusSeries === shape.id);
                    return (
                      <g key={point.traitId}>
                        <circle
                          className="trait-hit"
                          cx={point.x}
                          cy={point.y}
                          r={14}
                          onMouseEnter={() => { setFocusTrait(point.traitId); setFocusSeries(shape.id); }}
                          onMouseLeave={() => setFocusSeries(null)}
                        />
                        <circle className={active ? "trait-node is-active" : "trait-node"} cx={point.x} cy={point.y} r={active ? 6 : 4.5} />
                      </g>
                    );
                  })}
                </g>
              );
            })}
            {traits.map((item, index) => {
              const pt = polar(index, total, 1.13);
              const place = labelPlacement(index, total);
              const active = item.id === activeTrait?.id;
              return (
                <g
                  key={`label-${item.id}`}
                  className={active ? "trait-axis is-active" : "trait-axis"}
                  role="button"
                  tabIndex={0}
                  aria-pressed={active}
                  aria-label={`${item.name}, overall ${item.value == null ? "not enough evidence" : percent(item.value)}`}
                  onMouseEnter={() => setFocusTrait(item.id)}
                  onFocus={() => setFocusTrait(item.id)}
                  onClick={() => setFocusTrait(item.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setFocusTrait(item.id);
                    }
                  }}
                >
                  <text x={pt.x} y={pt.y + place.dy} textAnchor={place.textAnchor}>
                    <tspan className="trait-axis-name">{item.name}</tspan>
                    <tspan className="trait-axis-value" x={pt.x} dy={18}>{percent(item.value)}</tspan>
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
        <aside className="trait-radar-side">
          {activeTrait ? (
            <div className="trait-readout" aria-live="polite">
              <div className="trait-readout-head">
                <strong>{activeTrait.name}</strong>
                <span className="trait-readout-value" style={{ color: overall?.color }}>{percent(activeTrait.value)}</span>
              </div>
              <p className="trait-readout-meta">
                {activeTrait.value != null && activeTrait.interval
                  ? `Likely ${percent(activeTrait.interval[0])}–${percent(activeTrait.interval[1])} · ${activeTrait.observations} observation${activeTrait.observations === 1 ? "" : "s"}`
                  : `Not enough evidence yet · ${activeTrait.observations} observation${activeTrait.observations === 1 ? "" : "s"}`}
                {(() => {
                  const change = pointsChange(activeTrait);
                  return change != null && change !== 0
                    ? ` · ${change > 0 ? "+" : "−"}${Math.abs(change)} pts over ${Math.round(activeTrait.window_days ?? 28)} days`
                    : null;
                })()}
              </p>
              <p className="trait-readout-copy">{activeTrait.description} {activeTrait.measurement}</p>
              {activeTrait.forecast_use === "execution_probability" ? (
                <p className="trait-readout-meta">Used in forecasts as your probability of carrying out planned actions.</p>
              ) : null}
            </div>
          ) : null}
          <ul className="trait-legend" aria-label="Series">
            {[...shapes].reverse().map((shape) => {
              const value = activeTrait ? shape.points.find((point) => point.traitId === activeTrait.id)?.value ?? null : null;
              return (
                <li
                  key={shape.id}
                  className={focusSeries === shape.id ? "is-active" : ""}
                  onMouseEnter={() => setFocusSeries(shape.id)}
                  onMouseLeave={() => setFocusSeries(null)}
                >
                  <i style={{ background: shape.color, boxShadow: `0 0 10px ${shape.color}` }} aria-hidden="true" />
                  <span className="trait-legend-label">{shape.label}</span>
                  <span className="trait-legend-value">{activeTrait ? percent(value) : percent(shape.mean)}</span>
                </li>
              );
            })}
          </ul>
          {activeTrait ? (
            <p className="trait-legend-caption">
              {activeTrait.name} by life area. Areas with too few comparable commitments are left off that axis rather than drawn as zero.
            </p>
          ) : null}
          {sourceNote ? <p className="trait-source-note">{sourceNote}</p> : null}
        </aside>
      </div>
    </section>
  );
}
