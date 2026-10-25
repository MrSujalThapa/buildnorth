import type { ParameterEstimate, ParameterProfile } from "../../api/client";
import "./execution-profile.css";

const AREA_BY_ID: Record<string, { label: string; color: string }> = {
  weekly_applications: { label: "Career", color: "#2e86de" },
  weekly_study_hours: { label: "Education", color: "#f4d35e" },
  monthly_savings: { label: "Finance", color: "#ff9f1c" },
  weekly_running_km: { label: "Fitness", color: "#6a994e" },
  reading_minutes: { label: "Reading", color: "#c9184a" },
};
const FALLBACK = { label: "Other", color: "#9b9791" };

function areaFor(parameter: ParameterEstimate) {
  return AREA_BY_ID[parameter.id] ?? FALLBACK;
}

export function formatRaw(parameter: ParameterEstimate): string {
  if (parameter.raw_value == null) return "No observation in window";
  const value = Math.abs(parameter.raw_value) >= 100 ? Math.round(parameter.raw_value).toLocaleString() : String(Math.round(parameter.raw_value * 10) / 10);
  if (parameter.unit.includes("/month") && /^[A-Za-z]{3}\/|^currency/.test(parameter.unit)) return `${value} ${parameter.unit.replace("currency", "$")}`;
  return `${value} ${parameter.unit}`;
}

function formatDate(stamp: string | null | undefined): string | null {
  if (!stamp) return null;
  const date = new Date(stamp);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function sourceLabel(parameter: ParameterEstimate): string {
  const sources = parameter.source_types.length ? parameter.source_types.map((item) => item.replaceAll("_", " ")).join(", ") : "No source yet";
  return parameter.cohort === "workspace_seed" ? `${sources} · demo workspace` : sources;
}

/** Activity quantities (not behavior traits): latest reading per selected parameter. */
export function MeasuredParameterList({ profile }: { profile: ParameterProfile }) {
  if (!profile.parameters.length) {
    return <p className="quiet-copy">No measured parameters yet. Your selected parameters fill as matching observations arrive.</p>;
  }
  return (
    <ul className="measured-parameters" aria-label="Measured activity">
      {profile.parameters.map((item) => {
        const area = areaFor(item);
        const measured = item.status === "measured" && item.value != null;
        const observed = formatDate(item.last_observed_at);
        return (
          <li key={item.id} className={measured ? "" : "is-empty"} data-testid={`parameter-${item.id}`}>
            <div className="measured-parameter-head">
              <span className="measured-parameter-area" style={{ color: area.color }}>{area.label}</span>
              <span className="measured-parameter-name">{item.name}</span>
            </div>
            <strong className="measured-parameter-value">{measured ? formatRaw(item) : "Not measured"}</strong>
            <div className="measured-parameter-bar" aria-hidden="true">
              <span style={{ width: `${Math.round((measured ? item.value ?? 0 : 0) * 100)}%`, background: area.color }} />
            </div>
            <small>{measured ? `${sourceLabel(item)}${observed ? ` · ${observed}` : ""}` : "Add an observation to measure this"}</small>
          </li>
        );
      })}
    </ul>
  );
}
