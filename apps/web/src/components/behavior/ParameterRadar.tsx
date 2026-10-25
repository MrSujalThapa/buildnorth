import { useState } from "react";
import type { ParameterEstimate, ParameterProfile } from "../../api/client";
import "./execution-profile.css";

const LIFE_AREA_BY_ID: Record<string, { label: string; color: string }> = {
  weekly_applications: { label: "Career", color: "#1f8f86" },
  weekly_study_hours: { label: "Education", color: "#5b6ee1" },
  monthly_savings: { label: "Finance", color: "#c58a14" },
  weekly_running_km: { label: "Fitness", color: "#d0573f" },
  reading_minutes: { label: "Personal", color: "#9a5bc4" },
};
const FALLBACK = { label: "Other", color: "#706d68" };

const SIZE = 520;
const CX = SIZE / 2;
const CY = SIZE / 2;
const RADIUS = 176;
/** Share of an axis's sector each life-area petal spans on either side of its spoke. */
const PETAL_HALF_WIDTH = 0.32;

function areaFor(parameter: ParameterEstimate) {
  return LIFE_AREA_BY_ID[parameter.id] ?? FALLBACK;
}

function polar(angle: number, magnitude: number) {
  return { x: CX + Math.cos(angle) * RADIUS * magnitude, y: CY + Math.sin(angle) * RADIUS * magnitude };
}

function angleFor(index: number, total: number) {
  return -Math.PI / 2 + (index / total) * Math.PI * 2;
}

function measuredValue(parameter: ParameterEstimate): number | null {
  return parameter.status === "measured" && parameter.value != null ? parameter.value : null;
}

function formatRaw(parameter: ParameterEstimate): string {
  if (parameter.raw_value == null) return "No observation in window";
  const value = Math.abs(parameter.raw_value) >= 100 ? Math.round(parameter.raw_value).toLocaleString() : String(Math.round(parameter.raw_value * 10) / 10);
  if (parameter.unit.includes("/month") && /^[A-Za-z]{3}\/|^currency/.test(parameter.unit)) return `${value} ${parameter.unit.replace("currency", "$")}`;
  return `${value} ${parameter.unit}`;
}

function formatDate(stamp: string | null | undefined): string | null {
  if (!stamp) return null;
  const date = new Date(stamp);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function sourceLabel(parameter: ParameterEstimate): string {
  if (!parameter.source_types.length) return "No source yet";
  return parameter.source_types.map((item) => item.replaceAll("_", " ")).join(", ");
}

/** One radar; every life area is its own colored series, drawn only where it was measured. */
export function ParameterRadar({ profile }: { profile: ParameterProfile }) {
  const parameters = profile.parameters;
  const [activeId, setActiveId] = useState<string | null>(null);
  const total = parameters.length;

  if (!total) {
    return (
      <section className="parameter-life-radar">
        <p className="muted">No measured parameters yet. Your selected axes will fill as matching observations arrive.</p>
      </section>
    );
  }

  const measured = parameters.filter((item) => measuredValue(item) != null);
  const sector = (Math.PI * 2) / Math.max(total, 3);
  const active = parameters.find((item) => item.id === activeId) ?? null;

  return (
    <section className="parameter-life-radar">
      <div className="life-radar-layout">
        <div className="life-radar-stage">
          <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={`Life-area radar: ${measured.length} of ${total} areas measured`}>
            {[0.25, 0.5, 0.75, 1].map((ring) => (
              <circle key={ring} className="radar-ring" cx={CX} cy={CY} r={RADIUS * ring} />
            ))}
            {parameters.map((item, index) => {
              const edge = polar(angleFor(index, total), 1);
              return <line key={`spoke-${item.id}`} className={measuredValue(item) == null ? "radar-spoke muted" : "radar-spoke"} x1={CX} y1={CY} x2={edge.x} y2={edge.y} />;
            })}
            {parameters.map((item, index) => {
              const value = measuredValue(item);
              if (value == null) return null;
              const angle = angleFor(index, total);
              const reach = Math.max(value, 0.04);
              const tip = polar(angle, reach);
              const left = polar(angle - sector * PETAL_HALF_WIDTH, reach * 0.62);
              const right = polar(angle + sector * PETAL_HALF_WIDTH, reach * 0.62);
              const area = areaFor(item);
              const dimmed = activeId != null && activeId !== item.id;
              return (
                <g
                  key={`series-${item.id}`}
                  className="life-radar-series"
                  data-testid={`life-series-${item.id}`}
                  style={{ opacity: dimmed ? 0.28 : 1 }}
                  onMouseEnter={() => setActiveId(item.id)}
                  onMouseLeave={() => setActiveId(null)}
                  onFocus={() => setActiveId(item.id)}
                  onBlur={() => setActiveId(null)}
                  tabIndex={0}
                  role="button"
                  aria-label={`${area.label}: ${item.name} ${formatRaw(item)}`}
                >
                  <polygon
                    points={`${CX},${CY} ${left.x},${left.y} ${tip.x},${tip.y} ${right.x},${right.y}`}
                    fill={area.color}
                    fillOpacity={0.22}
                    stroke={area.color}
                    strokeWidth={2}
                    strokeLinejoin="round"
                  />
                  <circle cx={tip.x} cy={tip.y} r={6} fill={area.color} />
                </g>
              );
            })}
            {parameters.map((item, index) => {
              const angle = angleFor(index, total);
              const labelPt = polar(angle, 1.2);
              const cos = Math.cos(angle);
              const anchor = cos > 0.35 ? "start" : cos < -0.35 ? "end" : "middle";
              const dy = Math.sin(angle) > 0.45 ? 16 : Math.sin(angle) < -0.45 ? -8 : 5;
              const area = areaFor(item);
              const measuredNow = measuredValue(item) != null;
              return (
                <text
                  key={`label-${item.id}`}
                  className="radar-label"
                  x={labelPt.x}
                  y={labelPt.y + dy}
                  textAnchor={anchor}
                  style={{ fill: measuredNow ? area.color : undefined }}
                >
                  {area.label}
                </text>
              );
            })}
          </svg>
          {active ? (
            <div className="life-radar-tooltip" role="status">
              <strong style={{ color: areaFor(active).color }}>{areaFor(active).label} · {active.name}</strong>
              <span>{formatRaw(active)}</span>
              <span>Source: {sourceLabel(active)}</span>
              {formatDate(active.last_observed_at) ? <span>Last observed {formatDate(active.last_observed_at)}</span> : null}
            </div>
          ) : null}
        </div>
        <ul className="life-radar-legend" aria-label="Life areas">
          {parameters.map((item) => {
            const area = areaFor(item);
            const value = measuredValue(item);
            const observed = formatDate(item.last_observed_at);
            return (
              <li
                key={item.id}
                className={value == null ? "is-empty" : activeId === item.id ? "is-active" : ""}
                onMouseEnter={() => setActiveId(item.id)}
                onMouseLeave={() => setActiveId(null)}
              >
                <i style={{ background: value == null ? "transparent" : area.color, borderColor: area.color }} aria-hidden="true" />
                <div>
                  <span className="life-radar-legend-area">{area.label}</span>
                  <span className="life-radar-legend-name">{item.name}</span>
                </div>
                <div className="life-radar-legend-value">
                  <strong>{value == null ? "Not measured" : formatRaw(item)}</strong>
                  <small>{value == null ? "Add an observation to fill this axis" : `${sourceLabel(item)}${observed ? ` · ${observed}` : ""}`}</small>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
      {measured.length ? null : (
        <p className="life-radar-note">Empty axes stay empty until a matching observation is stored.</p>
      )}
    </section>
  );
}
