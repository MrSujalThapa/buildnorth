import { useId, useState } from "react";
import "./execution-profile.css";

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

const SIZE = 220;
const CX = SIZE / 2;
const CY = SIZE / 2;
const RADIUS = 78;

function point(index: number, total: number, magnitude: number) {
  const angle = -Math.PI / 2 + (index / total) * Math.PI * 2;
  return {
    x: CX + Math.cos(angle) * RADIUS * magnitude,
    y: CY + Math.sin(angle) * RADIUS * magnitude,
  };
}

export function ExecutionProfileRadar({ profile, compact = false }: Props) {
  const gradientId = useId();
  const [openKey, setOpenKey] = useState<string | null>(null);
  const dimensions = profile?.dimensions ?? [];
  if (!profile || !dimensions.length) {
    return (
      <section className={`execution-profile${compact ? " compact" : ""}`}>
        <header>
          <p className="section-label">Execution profile</p>
          <h3>Follow-through</h3>
        </header>
        <p className="execution-empty">Limited evidence — no personal follow-through estimate yet.</p>
      </section>
    );
  }

  const values = dimensions.map((item) => (item.limited_evidence || item.value == null ? 0 : item.value));
  const outline = values
    .map((value, index) => {
      const pt = point(index, values.length, value);
      return `${pt.x},${pt.y}`;
    })
    .join(" ");

  return (
    <section className={`execution-profile${compact ? " compact" : ""}`}>
      <header>
        <p className="section-label">Execution profile</p>
        <h3>Observed follow-through</h3>
        <p className="execution-disclaimer">{profile.disclaimer}</p>
      </header>
      <div className="execution-layout">
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="Follow-through profile radar">
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="var(--what-if-accent, #5ec8bd)" stopOpacity="0.18" />
              <stop offset="100%" stopColor="var(--what-if-accent, #5ec8bd)" stopOpacity="0.04" />
            </linearGradient>
          </defs>
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
          <polygon className="radar-fill" points={outline} fill={`url(#${gradientId})`} />
          <polygon className="radar-outline" points={outline} />
          {dimensions.map((item, index) => {
            const labelPt = point(index, dimensions.length, 1.28);
            const valuePt = point(index, dimensions.length, item.limited_evidence || item.value == null ? 0 : item.value);
            return (
              <g key={item.key}>
                <circle className="radar-node" cx={valuePt.x} cy={valuePt.y} r="3.2" />
                <text className="radar-label" x={labelPt.x} y={labelPt.y} textAnchor="middle">
                  {item.label}
                </text>
              </g>
            );
          })}
        </svg>
        <aside>
          <p className="execution-sufficiency">
            Evidence: <strong>{profile.evidence_sufficiency}</strong>
            <span>
              {profile.n_raw} trials · n_eff {profile.n_eff.toFixed(1)}
            </span>
          </p>
          <ul>
            {dimensions.map((item) => (
              <li key={item.key}>
                <button type="button" onClick={() => setOpenKey(openKey === item.key ? null : item.key)}>
                  <span>{item.label}</span>
                  <strong>{item.limited_evidence || item.display_percent == null ? "Limited evidence" : `${item.display_percent}%`}</strong>
                </button>
                {openKey === item.key ? (
                  <div className="execution-provenance">
                    <p>{item.provenance.formula}</p>
                    <ul>
                      {item.provenance.details.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </section>
  );
}
