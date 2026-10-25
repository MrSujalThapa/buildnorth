import type { PublicBlueprint } from "../../api/client";

const labels: Record<string, string> = {
  event: "Outcome", success_event: "Outcome", metric: "Measure", target: "Target",
  target_value: "Target value", threshold: "Threshold", unit: "Unit", window: "Window",
  operator: "Comparison", description: "Definition", criteria: "Criteria", habit: "Habit",
};

function readable(key: string): string {
  return labels[key] ?? key.replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase());
}

function valueText(value: unknown): string | null {
  if (typeof value === "string") return value.replaceAll("_", " ");
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(valueText).filter((item): item is string => item !== null).join(", ");
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item != null && item !== "")
      .map(([key, item]) => `${readable(key)}: ${valueText(item) ?? ""}`)
      .join("; ");
  }
  return null;
}

function milestoneText(milestone: unknown): string {
  if (typeof milestone === "string") return milestone;
  if (milestone && typeof milestone === "object" && !Array.isArray(milestone)) {
    const value = milestone as Record<string, unknown>;
    const title = value.title ?? value.name ?? value.description;
    if (typeof title === "string" && title.trim()) return title;
  }
  return valueText(milestone) ?? "Milestone";
}

export default function PublicBlueprintDetails({ blueprint }: { blueprint: PublicBlueprint }) {
  const criteria = Object.entries(blueprint.success_criteria)
    .filter(([key, value]) => key !== "milestones" && key !== "strategy" && value != null && value !== "");
  return (
    <section className="public-blueprint" aria-labelledby="public-blueprint-title">
      <h2 id="public-blueprint-title">Blueprint</h2>
      <p className="quiet-copy">The creator's published goal definition. Your fork starts private, with its own evidence and forecasts.</p>
      {blueprint.deadline ? (
        <p className="public-blueprint-deadline">Target date: <time dateTime={blueprint.deadline}>{new Intl.DateTimeFormat("en", {
          month: "long", day: "numeric", year: "numeric", timeZone: "UTC",
        }).format(new Date(blueprint.deadline))}</time></p>
      ) : null}
      <div className="public-blueprint-sections">
        <div>
          <h3>What counts as success</h3>
          {criteria.length ? (
            <dl className="criteria-list">
              {criteria.map(([key, value]) => <div key={key}><dt>{readable(key)}</dt><dd>{valueText(value)}</dd></div>)}
            </dl>
          ) : <p className="quiet-copy">No public success criteria are available for this blueprint.</p>}
        </div>
        {blueprint.milestones.length ? (
          <div>
            <h3>Milestones</h3>
            <ol className="public-milestones">{blueprint.milestones.map((milestone, index) => <li key={index}>{milestoneText(milestone)}</li>)}</ol>
          </div>
        ) : null}
        {blueprint.strategies.length ? (
          <div>
            <h3>Published approach</h3>
            <ul className="public-milestones">{blueprint.strategies.map((row) => <li key={row}>{row}</li>)}</ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}
