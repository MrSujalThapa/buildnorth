import { useId, useState } from "react";
import "./execution-profile.css";
import { chartLabel, traitColor, traitSummary } from "./traitSummary";

export type BehaviorDimension = {
  key: string;
  label: string;
  value: number | null;
  display_percent: number | null;
  limited_evidence: boolean;
  confidence: string;
  provenance: {
    comparable_commitments: number;
    completed: number;
    recency_weighted_completion?: number | null;
    evidence_window_days?: number | null;
    sources: string[];
    n_eff: number;
    formula: string;
    details: string[];
  };
};

export type BehaviorProfile = {
  estimator_version: string;
  execution: {
    probability: number;
    n_eff: number;
    confidence: string;
    source: string;
    usable: boolean;
    notes: string[];
  };
  dimensions: BehaviorDimension[];
  disclaimer: string;
  evidence_sufficiency: string;
  n_raw: number;
  n_eff: number;
};

type Props = {
  profile: BehaviorProfile | null | undefined;
  compact?: boolean;
};

const SIZE = 560;
const CX = SIZE / 2;
const CY = SIZE / 2;
const RADIUS = 168;

function angleFor(index: number, total: number) {
  return -Math.PI / 2 + (index / total) * Math.PI * 2;
}

function point(index: number, total: number, magnitude: number) {
  const angle = angleFor(index, total);
  return {
    x: CX + Math.cos(angle) * RADIUS * magnitude,
    y: CY + Math.sin(angle) * RADIUS * magnitude,
  };
}

function labelAnchor(index: number, total: number) {
  const angle = angleFor(index, total);
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return {
    textAnchor: cos > 0.35 ? "start" : cos < -0.35 ? "end" : "middle",
    dy: sin > 0.45 ? 18 : sin < -0.45 ? -10 : 5,
  } as const;
}

function measured(item: BehaviorDimension): boolean {
  return !item.limited_evidence && item.value != null;
}

export function ExecutionProfileRadar({ profile, compact = false }: Props) {
  const uid = useId().replace(/:/g, "");
  const dimensions = profile?.dimensions ?? [];
  const firstMeasured = dimensions.find(measured)?.key ?? null;
  const [locked, setLocked] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [methodOpen, setMethodOpen] = useState(false);
  const activeKey = hover ?? locked ?? firstMeasured;
  const active = dimensions.find((item) => item.key === activeKey) ?? null;
  const activeIndex = dimensions.findIndex((item) => item.key === activeKey);
  const tooltipPt = activeIndex >= 0 ? point(activeIndex, dimensions.length, 0.55) : { x: CX, y: CY };

  if (!profile || !dimensions.length) {
    return (
      <section className={`execution-profile${compact ? " compact" : ""}`}>
        <p className="execution-empty">No verified commitments yet.</p>
      </section>
    );
  }

  const complete = dimensions.length >= 3 && dimensions.every(measured);
  const hasMeasurements = dimensions.some(measured);
  const outline = complete
    ? dimensions
        .map((item, index) => {
          const pt = point(index, dimensions.length, item.value ?? 0);
          return `${pt.x},${pt.y}`;
        })
        .join(" ")
    : "";

  function select(key: string) {
    setLocked(key);
    setMethodOpen(false);
  }

  return (
    <section className={`execution-profile${compact ? " compact" : ""}`}>
      {!hasMeasurements ? <p className="execution-empty">Your execution profile appears as planned actions are verified.</p> : null}
      {hasMeasurements && !complete ? <p className="execution-empty">Some traits need more observations.</p> : null}
      <div className="radar-stage">
        {dimensions.length >= 3 ? (
          <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="Follow-through profile radar">
            <defs>
              <filter id={`${uid}-glow`} x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="6" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              {dimensions.map((item, index) => {
                const next = (index + 1) % dimensions.length;
                const start = point(index, dimensions.length, complete ? (item.value ?? 0) : 1);
                const end = point(next, dimensions.length, complete ? (dimensions[next]?.value ?? 0) : 1);
                return (
                  <linearGradient
                    key={item.key}
                    id={`${uid}-edge-${index}`}
                    x1={start.x}
                    y1={start.y}
                    x2={end.x}
                    y2={end.y}
                    gradientUnits="userSpaceOnUse"
                  >
                    <stop offset="0%" stopColor={traitColor(item.key, index)} />
                    <stop offset="100%" stopColor={traitColor(dimensions[next]?.key ?? item.key, next)} />
                  </linearGradient>
                );
              })}
            </defs>
            {[0.25, 0.5, 0.75, 1].map((ring) => (
              <circle key={ring} className="radar-ring" cx={CX} cy={CY} r={RADIUS * ring} />
            ))}
            {dimensions.map((item, index) => {
              const edge = point(index, dimensions.length, 1);
              return (
                <line
                  key={`spoke-${item.key}`}
                  className={measured(item) ? "radar-spoke" : "radar-spoke muted"}
                  x1={CX}
                  y1={CY}
                  x2={edge.x}
                  y2={edge.y}
                />
              );
            })}
            {complete ? (
              <polygon className="radar-fill" points={outline} filter={`url(#${uid}-glow)`} />
            ) : null}
            {complete
              ? dimensions.map((item, index) => {
                  const next = (index + 1) % dimensions.length;
                  const start = point(index, dimensions.length, item.value ?? 0);
                  const end = point(next, dimensions.length, dimensions[next]?.value ?? 0);
                  return (
                    <line
                      key={`edge-${item.key}`}
                      className="radar-edge"
                      x1={start.x}
                      y1={start.y}
                      x2={end.x}
                      y2={end.y}
                      stroke={`url(#${uid}-edge-${index})`}
                    />
                  );
                })
              : null}
            {dimensions.map((item, index) => {
              if (!measured(item)) return null;
              const valuePt = point(index, dimensions.length, item.value ?? 0);
              const inner = point(index, dimensions.length, 0.08);
              if (complete) return null;
              return (
                <line
                  key={`bar-${item.key}`}
                  className="radar-bar"
                  x1={inner.x}
                  y1={inner.y}
                  x2={valuePt.x}
                  y2={valuePt.y}
                  stroke={traitColor(item.key, index)}
                />
              );
            })}
            {dimensions.map((item, index) => {
              const labelPt = point(index, dimensions.length, 1.28);
              const anchor = labelAnchor(index, dimensions.length);
              const selected = item.key === activeKey;
              const color = traitColor(item.key, index);
              return (
                <text
                  key={`label-${item.key}`}
                  className={selected ? "radar-label selected" : "radar-label"}
                  x={labelPt.x}
                  y={labelPt.y + anchor.dy}
                  textAnchor={anchor.textAnchor}
                  style={{ fill: measured(item) ? color : undefined }}
                >
                  {chartLabel(item.label)}
                </text>
              );
            })}
            {dimensions.map((item, index) => {
              if (!measured(item)) return null;
              const valuePt = point(index, dimensions.length, item.value ?? 0);
              const selected = item.key === activeKey;
              return (
                <g key={item.key}>
                  <circle
                    className="radar-hit"
                    cx={valuePt.x}
                    cy={valuePt.y}
                    r="18"
                    onMouseEnter={() => setHover(item.key)}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => select(item.key)}
                  />
                  <circle
                    className={selected ? "radar-node selected" : "radar-node"}
                    cx={valuePt.x}
                    cy={valuePt.y}
                    r={selected ? 8 : 6}
                    fill={traitColor(item.key, index)}
                  />
                </g>
              );
            })}
          </svg>
        ) : null}
        {active ? (
          <div
            className="radar-tooltip"
            style={{ left: `${(tooltipPt.x / SIZE) * 100}%`, top: `${(tooltipPt.y / SIZE) * 100}%` }}
            role="status"
          >
            <strong>{active.label}</strong>
            <em>{measured(active) && active.display_percent != null ? `${active.display_percent}%` : "—"}</em>
            <p>{traitSummary(active)}</p>
          </div>
        ) : null}
      </div>
      {active?.provenance.formula ? (
        <button type="button" className="radar-method" aria-expanded={methodOpen} onClick={() => setMethodOpen((open) => !open)}>
          {methodOpen ? "Hide method" : "How this is measured"}
        </button>
      ) : null}
      {methodOpen && active ? (
        <div className="execution-provenance">
          <p>{active.provenance.formula}</p>
          {active.provenance.details.length ? (
            <ul>
              {active.provenance.details.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
