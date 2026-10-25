import { GitFork, X } from "lucide-react";
import { Link } from "react-router-dom";
import type { ForkProvenance, Goal } from "../../api/client";
import { criteriaRows, formatLongDate, milestoneText } from "./publicMarketView";

type Props = {
  fork: ForkProvenance;
  goal: Goal;
  onEvidence: () => void;
  onWhatIf: () => void;
  onDismiss: () => void;
};

const FIELD_LABELS: Record<string, string> = {
  title: "title",
  deadline: "deadline",
  success_criteria: "success criteria",
  description: "description",
  milestones: "milestones",
  strategy: "approach",
  category: "category",
  forecast_spec: "model setup",
};

export default function ForkedBlueprintPanel({ fork, goal, onEvidence, onWhatIf, onDismiss }: Props) {
  const criteria = criteriaRows(goal.success_definition ?? {});
  const deadline = formatLongDate(goal.deadline);
  const rawMilestones = goal.success_definition?.milestones;
  const milestones = (Array.isArray(rawMilestones) ? rawMilestones : [])
    .map(milestoneText)
    .filter((item): item is string => Boolean(item));
  const carried = (fork.carried_fields ?? []).map((field) => FIELD_LABELS[field]).filter(Boolean);
  const source = fork.source_public && fork.source_handle
    ? <Link to={`/m/${fork.source_goal_id}`}>@{fork.source_handle}/{fork.source_title}</Link>
    : <span>a public blueprint</span>;

  return (
    <section className="forked-panel" aria-labelledby="forked-panel-title">
      <header className="forked-panel-head">
        <h2 id="forked-panel-title"><GitFork size={15} aria-hidden="true" /> Forked from {source}</h2>
        <button type="button" className="forked-panel-close" onClick={onDismiss} aria-label="Dismiss fork summary">
          <X size={15} aria-hidden="true" />
        </button>
      </header>
      <p className="forked-panel-copy">
        This is your private copy{carried.length ? <> with the {carried.join(", ")}</> : null}. Odds start fresh once you add your own evidence.
      </p>
      <dl className="forked-panel-facts">
        {deadline ? <div><dt>Target date</dt><dd>{deadline}</dd></div> : null}
        {criteria.map((row) => <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}
        {milestones.length ? <div><dt>Milestones</dt><dd>{milestones.join(" · ")}</dd></div> : null}
      </dl>
      <div className="forked-panel-actions">
        <button type="button" className="ui-button" onClick={onEvidence}>Add evidence</button>
        <button type="button" className="ui-button ui-button-secondary" onClick={onWhatIf}>Explore What If</button>
      </div>
    </section>
  );
}
