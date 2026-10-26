import type { PublicBlueprint } from "../../api/client";
import { blueprintHasContent, criteriaRows, formatLongDate, milestoneText } from "./publicMarketView";

export default function PublicBlueprintDetails({ blueprint }: { blueprint: PublicBlueprint }) {
  const criteria = criteriaRows(blueprint.success_criteria);
  const milestones = blueprint.milestones
    .map(milestoneText)
    .filter((item): item is string => Boolean(item));
  const deadline = formatLongDate(blueprint.deadline);
  const tracked = (blueprint.tracked_metrics ?? []).map((item) => item.replaceAll("_", " "));
  const snapshot = formatLongDate(blueprint.snapshot_at);
  return (
    <section className="public-blueprint" aria-labelledby="public-blueprint-title">
      <h2 id="public-blueprint-title">Blueprint</h2>
      {!blueprintHasContent(blueprint) ? (
        <p className="quiet-copy">The creator has not published a goal definition yet.</p>
      ) : (
        <>
          {deadline && blueprint.deadline ? (
            <div className="public-blueprint-block">
              <h3>Target date</h3>
              <p className="public-blueprint-deadline"><time dateTime={blueprint.deadline}>{deadline}</time></p>
            </div>
          ) : null}
          {criteria.length ? (
            <div className="public-blueprint-block">
              <h3>What counts as success</h3>
              <dl className="criteria-list">
                {criteria.map((row) => <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}
              </dl>
            </div>
          ) : null}
          {blueprint.strategies.length ? (
            <div className="public-blueprint-block">
              <h3>Approach</h3>
              <ul className="public-milestones">{blueprint.strategies.map((row) => <li key={row}>{row}</li>)}</ul>
            </div>
          ) : null}
          {milestones.length ? (
            <div className="public-blueprint-block">
              <h3>Milestones</h3>
              <ol className="public-milestones">{milestones.map((row, index) => <li key={`${index}-${row}`}>{row}</li>)}</ol>
            </div>
          ) : null}
          {tracked.length ? (
            <div className="public-blueprint-block">
              <h3>Tracked metrics</h3>
              <p>{tracked.join(", ")}</p>
            </div>
          ) : null}
        </>
      )}
      <p className="public-blueprint-note">
        {snapshot ? <>Blueprint as published on {snapshot}. </> : null}
        Forking copies this blueprint into a new private market. Evidence and odds stay with the creator.
      </p>
    </section>
  );
}
