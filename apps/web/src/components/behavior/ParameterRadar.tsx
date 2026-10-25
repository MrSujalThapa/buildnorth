import { useEffect, useMemo, useState } from "react";
import type { ParameterEstimate, ParameterProfile } from "../../api/client";
import { ExecutionProfileRadar, type BehaviorDimension, type BehaviorProfile } from "./ExecutionProfileRadar";
import "./execution-profile.css";

const CATEGORY_BY_ID: Record<string, string> = {
  weekly_applications: "career",
  weekly_study_hours: "education",
  monthly_savings: "finance",
  weekly_running_km: "fitness",
  reading_minutes: "personal_development",
};

function categoryFor(parameter: ParameterEstimate): string {
  return CATEGORY_BY_ID[parameter.id] ?? "other";
}

function categoryLabel(raw: string): string {
  const labels: Record<string, string> = {
    career: "Career",
    education: "Education",
    fitness: "Fitness",
    health: "Health",
    personal: "Personal development",
    personal_development: "Personal development",
    finance: "Finance",
    startup: "Startup",
    entrepreneurship: "Startup",
    relationships: "Relationships",
    social: "Relationships",
    other: "Other",
  };
  return labels[raw] ?? raw.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function asDimension(parameter: ParameterEstimate): BehaviorDimension {
  const sources = parameter.source_types.length ? parameter.source_types : ["unobserved"];
  const details: string[] = [];
  if (parameter.raw_value != null) {
    details.push(`Current ${parameter.raw_value} ${parameter.unit}`);
  }
  details.push(`${parameter.observation_count} observations in ${parameter.window_days} days`);
  details.push(`${parameter.metric} · ${parameter.aggregation}`);
  return {
    key: parameter.id,
    label: parameter.name,
    value: parameter.value,
    display_percent: parameter.value == null ? null : Math.round(parameter.value * 100),
    limited_evidence: parameter.status !== "measured",
    confidence: parameter.status === "measured" ? "medium" : "insufficient",
    provenance: {
      comparable_commitments: parameter.observation_count,
      completed: parameter.observation_count,
      sources,
      n_eff: parameter.observation_count,
      formula: `${parameter.metric} · ${parameter.aggregation} (${parameter.unit})`,
      details,
    },
  };
}

function asProfile(parameters: ParameterEstimate[]): BehaviorProfile {
  const dimensions = parameters.map(asDimension);
  const measured = parameters.filter((item) => item.status === "measured");
  const nEff = measured.reduce((sum, item) => sum + item.observation_count, 0);
  return {
    estimator_version: "parameter_profile@1.0.0",
    execution: {
      probability: 0,
      n_eff: nEff,
      confidence: measured.length ? "medium" : "insufficient",
      source: measured.length ? "FITTED" : "UNOBSERVED",
      usable: measured.length > 0,
      notes: [],
    },
    dimensions,
    disclaimer:
      "Axes are the parameters you selected. Values come from stored observations, not invented personality scores.",
    evidence_sufficiency: measured.length ? "low" : "insufficient",
    n_raw: nEff,
    n_eff: nEff,
  };
}

export function ParameterRadar({ profile }: { profile: ParameterProfile }) {
  const parameters = profile.parameters;
  const groups = useMemo(() => {
    const byCategory = new Map<string, ParameterEstimate[]>();
    for (const parameter of parameters) {
      const key = categoryFor(parameter);
      const list = byCategory.get(key) ?? [];
      list.push(parameter);
      byCategory.set(key, list);
    }
    return [...byCategory.entries()]
      .map(([id, items]) => ({
        id,
        label: categoryLabel(id),
        items,
        measured: items.filter((item) => item.status === "measured").length,
      }))
      .sort((a, b) => b.measured - a.measured || a.label.localeCompare(b.label));
  }, [parameters]);

  const [category, setCategory] = useState(groups[0]?.id ?? "");
  useEffect(() => {
    if (!groups.some((group) => group.id === category)) {
      setCategory(groups[0]?.id ?? "");
    }
  }, [category, groups]);

  if (!parameters.length) {
    return (
      <section className="execution-profile-radar parameter-life-radar">
        <p className="muted">
          No measured parameters yet. Your selected axes will fill as matching observations arrive.
        </p>
      </section>
    );
  }

  const active = groups.find((group) => group.id === category) ?? groups[0];
  if (!active) {
    return null;
  }
  return (
    <section className="parameter-life-radar">
      {groups.length > 1 ? (
        <div className="parameter-life-radar-tabs" role="tablist" aria-label="Life area">
          {groups.map((group) => (
            <button
              key={group.id}
              type="button"
              role="tab"
              aria-selected={group.id === active.id}
              className={group.id === active.id ? "is-active" : ""}
              onClick={() => setCategory(group.id)}
            >
              {group.label}
              <span>{group.measured}/{group.items.length}</span>
            </button>
          ))}
        </div>
      ) : null}
      <p className="parameter-life-radar-lede">
        {active.label}: selected measurements only. Empty axes stay empty until observations arrive.
      </p>
      <ExecutionProfileRadar profile={asProfile(active.items)} />
    </section>
  );
}
