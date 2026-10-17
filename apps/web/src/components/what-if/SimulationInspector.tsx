import { X } from "lucide-react";

import type { SimulationNarrative } from "../../adapters/simulationTypes";

type Props = {
  simulationId: number;
  narrative: SimulationNarrative;
  onClose: () => void;
};

export default function SimulationInspector({ simulationId, narrative, onClose }: Props) {
  return (
    <aside className="sim-inspector" aria-label="Selected simulated future">
      <header>
        <div>
          <p className="section-label">Simulated future</p>
          <h3>{narrative.outcomeValue}</h3>
          <span>Resulting odds</span>
        </div>
        <button type="button" onClick={onClose} aria-label="Clear selected simulation">
          <X size={18} strokeWidth={1.7} />
        </button>
      </header>

      <p className="sim-inspector-kicker">Hypothetical simulation ┬╖ not an exact prediction</p>
      <p className="sim-inspector-outcome">{narrative.headline}</p>

      <dl className="sim-inspector-facts">
        <div>
          <dt>Goal achieved</dt>
          <dd>{narrative.goalAchieved ? "Yes" : "No"}</dd>
        </div>
      </dl>
      <p className="sim-id">Fixture simulation {simulationId}</p>

      <h4>Timeline</h4>
      <ol className="sim-timeline">
        {narrative.timeline.map((item) => (
          <li key={`${item.month}-${item.event}`}>
            <span>Month {item.month}</span>
            <strong>{item.event}</strong>
          </li>
        ))}
      </ol>

      <h4>Assumptions realized</h4>
      <ul>
        {narrative.assumptions.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>

      <h4>External events</h4>
      <ul>
        {narrative.events.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </aside>
  );
}
