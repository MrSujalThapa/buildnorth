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

const SIZE = 440;
const CX = SIZE / 2;
const CY = SIZE / 2;
const RADIUS = 132;

function point(index: number, total: number, magnitude: number) {
  const angle = -Math.PI / 2 + (index / total) * Math.PI * 2;
  return {
    x: CX + Math.cos(angle) * RADIUS * magnitude,
    y: CY + Math.sin(angle) * RADIUS * magnitude,
  };
}

function measured(item: BehaviorDimension): boolean {
  return !item.limited_evidence && item.value != null;
}

export function ExecutionProfileRadar({ profile, compact = false }: Props) {
  const gradientId = useId();
  const dimensions = profile?.dimensions ?? [];
  const firstMeasured = dimensions.find(measured)?.key ?? null;
  const [locked, setLocked] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [methodOpen, setMethodOpen] = useState(false);
  const activeKey = hover ?? locked ?? firstMeasured;
  const active = dimensions.find((item) => item.key === activeKey) ?? null;

  if (!profile || !dimensions.length) {
    return (
      <section className={`execution-profile${compact ? " compact" : ""}`}>
        <p className="execution-empty">No verified commitments yet.</p>
      </section>
    );
  }

  const complete = dimensions.length >= 3 && dimensions.every(measured);
  const hasMeasurements = dimensions.some(measured);
  const values = dimensions.map((item) => (measured(item) ? item.value ?? 0 : 0));

  return (
    <section className={`execution-profile${compact ? " compact" : ""}`}>
      {!hasMeasurements ? <p className="execution-empty">Your execution profile appears as planned actions are verified.</p> : null}
      {hasMeasurements && !complete ? <p className="execution-empty">Some traits need more observations.</p> : null}
      <div className="radar-stage">
        {dimensions.length >= 3 ? (
          <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="Follow-through profile radar">
            <defs>
              <radialGradient id={gradientId} cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="var(--app-ink, #161513)" stopOpacity="0.04" />
                <stop offset="100%" stopColor="var(--app-ink, #161513)" stopOpacity="0" />
              </radialGradient>
            </defs>
            <circle className="radar-halo" cx={CX} cy={CY} r={RADIUS} fill={`url(#${gradientId})`} />
            {[0.25, 0.5, 0.75, 1].map((ring) => (
              <polygon
                key={ring}
                className="radar-ring"
                points={dimensions
                  .map((_, index) => {
                    const pt = point(index, dimensions.length, ring);
                    return `${pt.x},${pt.y}`;
                  })
                  .join(" ")}
              />
            ))}
            {dimensions.map((_, index) => {
              const edge = point(index, dimensions.length, 1);
              return <line key={index} className="radar-spoke" x1={CX} y1={CY} x2={edge.x} y2={edge.y} />;
            })}
            {complete
              ? dimensions.map((item, index) => {
                  const next = (index + 1) % dimensions.length;
                  const start = point(index, dimensions.length, values[index] ?? 0);
                  const end = point(next, dimensions.length, values[next] ?? 0);
                  return (
                    <polygon
                      key={item.key}
                      className="radar-wedge"
                      points={`${CX},${CY} ${start.x},${start.y} ${end.x},${end.y}`}
                      fill={traitColor(item.key, index)}
                      stroke={traitColor(item.key, index)}
                    />
                  );
                })
              : null}
            {complete ? (
              <polygon
                className="radar-outline"
                points={values
                  .map((value, index) => {
                    const pt = point(index, values.length, value);
                    return `${pt.x},${pt.y}`;
                  })
                  .join(" ")}
              />
            ) : null}
            {dimensions.map((item, index) => {
              if (!measured(item)) return null;
              const valuePt = point(index, dimensions.length, item.value ?? 0);
              const selected = item.key === activeKey;
              return (
                <circle
                  key={item.key}
                  className={selected ? "radar-node selected" : "radar-node"}
                  cx={valuePt.x}
                  cy={valuePt.y}
                  r={selected ? 6.5 : 5}
                  fill={traitColor(item.key, index)}
                />
              );
            })}
          </svg>
        ) : null}
        {dimensions.length >= 3
          ? dimensions.map((item, index) => {
              const labelPt = point(index, dimensions.length, 1.38);
              return (
                <button
                  key={item.key}
                  type="button"
                  className={item.key === activeKey ? "radar-axis selected" : "radar-axis"}
                  style={{ left: `${(labelPt.x / SIZE) * 100}%`, top: `${(labelPt.y / SIZE) * 100}%` }}
                  aria-pressed={item.key === activeKey}
                  onMouseEnter={() => setHover(item.key)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(item.key)}
                  onBlur={() => setHover(null)}
                  onClick={() => {
                    setLocked(item.key);
                    setMethodOpen(false);
                  }}
                >
                  <i style={{ background: traitColor(item.key, index) }} />
                  {chartLabel(item.label)}
                </button>
              );
            })
          : null}
      </div>
      {active ? (
        <article className="radar-detail" aria-live="polite">
          <header>
            <h3>{active.label}</h3>
            <strong>{measured(active) && active.display_percent != null ? `${active.display_percent}%` : "—"}</strong>
          </header>
          <p>{traitSummary(active)}</p>
          {active.provenance.formula ? (
            <button type="button" className="radar-method" aria-expanded={methodOpen} onClick={() => setMethodOpen((open) => !open)}>
              {methodOpen ? "Hide method" : "How this is measured"}
            </button>
          ) : null}
          {methodOpen ? (
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
        </article>
      ) : null}
    </section>
  );
}
