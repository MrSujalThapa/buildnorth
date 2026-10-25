import type { FutureScenario } from "../../adapters/compareViewModel";
import { formatOutcomeRange, type OutcomeScale } from "../../adapters/outcomeFormat";
import type { WhatIfView } from "../../adapters/templateTypes";
import WealthsimpleAreaChart, { type ProbabilityBranch } from "../market/WealthsimpleAreaChart";
import OutcomeIntervals from "./OutcomeIntervals";
import { FUTURE_SERIES_COLORS, WORSE_SERIES_COLOR } from "./seriesColors";
import { ScenarioComposer } from "./ScenarioComposer";

type Props = {
  view: WhatIfView;
  decision: string;
  pathLabel?: string | null;
  onDecisionChange: (value: string) => void;
  onRun: () => void;
  loading?: boolean;
  priced?: boolean;
  message?: string | null;
  selectedClusterId: string | null;
  onSelectCluster: (id: string | null) => void;
  scenarios?: FutureScenario[];
  outcomeScale: OutcomeScale;
};

function share(scenario: FutureScenario | undefined): string {
  return scenario?.probability == null ? "—" : `${scenario.probability}%`;
}

const HORIZON_TICKS = [
  { value: 0, label: "Today" },
  { value: 1, label: "Goal deadline" },
];

function FuturesChart({
  scenarios,
  selectedId,
  onSelect,
}: {
  scenarios: FutureScenario[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  let paletteIndex = 0;
  const branches: ProbabilityBranch[] = scenarios
    .filter((scenario) => scenario.probability != null)
    .map((scenario) => {
      const color =
        scenario.tone === "negative"
          ? WORSE_SERIES_COLOR
          : FUTURE_SERIES_COLORS[paletteIndex++ % FUTURE_SERIES_COLORS.length]!;
      return {
        id: scenario.id,
        label: scenario.label,
        color,
        points: [
          { timestamp: 0, value: scenario.probability! },
          { timestamp: 1, value: scenario.probability! },
        ],
      };
    });
  return (
    <div className="futures-chart" role="group" aria-label="Possible future scenarios">
      <div className="futures-chart-plot">
        <WealthsimpleAreaChart
          data={[]}
          branches={branches}
          lineOnly
          percentAxis
          showTimeAxis
          xTicks={HORIZON_TICKS}
          interactive={false}
          highlightedBranchId={selectedId}
          onBranchSelect={onSelect}
          scenarioRegionLabel="Share of simulated futures"
        />
      </div>
      <p className="what-if-chart-caption">
        Each line is the share of simulated futures that end in that outcome by the deadline. The engine prices a single horizon, so the lines are level rather than a modeled path.
      </p>
    </div>
  );
}

export default function PossibleFuturesView({
  view,
  decision,
  pathLabel,
  onDecisionChange,
  onRun,
  loading = false,
  priced = true,
  message,
  selectedClusterId,
  onSelectCluster,
  scenarios: scenariosProp,
  outcomeScale,
}: Props) {
  const scenarios = scenariosProp ?? [];
  const binaryEvent = (outcomeScale.unit ?? "").trim().toLowerCase() === "event";
  const mostLikely = [...scenarios].sort((a, b) => (b.probability ?? -1) - (a.probability ?? -1))[0];
  const strongChance = scenarios
    .filter((scenario) => scenario.tone === "positive")
    .reduce((sum, scenario) => sum + (scenario.probability ?? 0), 0);
  const selected = scenarios.find((scenario) => scenario.id === selectedClusterId);
  const hasResults = priced && scenarios.some((scenario) => scenario.probability !== null);
  const rangeFor = (scenario: FutureScenario) =>
    binaryEvent ? "—" : formatOutcomeRange(scenario.outcome?.p10 ?? null, scenario.outcome?.p90 ?? null, outcomeScale.unit);
  const intervalRows = scenarios
    .filter((scenario) => !binaryEvent && scenario.outcome && (scenario.probability ?? 0) > 0)
    .map((scenario) => ({
      id: scenario.id,
      label: scenario.label,
      p10: scenario.outcome?.p10 ?? null,
      p50: scenario.outcome?.p50 ?? null,
      p90: scenario.outcome?.p90 ?? null,
      selected: scenario.id === (selectedClusterId ?? mostLikely?.id),
    }));
  const toggle = (id: string) => onSelectCluster(selectedClusterId === id ? null : id);

  return (
    <div className={view === "deep" ? "mode-stage deep" : "mode-stage"}>
      <ScenarioComposer
        id="future-decision"
        label={pathLabel ? `Futures if you take ${pathLabel}` : "Decision to explore"}
        value={decision}
        onChange={onDecisionChange}
        onSubmit={onRun}
        busy={loading}
        submitLabel="Map futures"
        placeholder="What if this happens?"
      />

      {!priced ? (
        <div className="unpriced-state">
          <strong>Futures unavailable</strong>
          <span>{message ?? "Price the baseline goal before mapping futures."}</span>
        </div>
      ) : null}

      {priced && loading && !hasResults ? (
        <p role="status">Running backend scenario simulation…</p>
      ) : null}

      {priced && !loading && !hasResults ? (
        <div className="past-empty">
          {message ?? "Ask a question to see the outcomes this goal can estimate."}
        </div>
      ) : null}

      {hasResults ? (
        <section className={view === "deep" ? "futures-workspace deep" : "futures-workspace"}>
          {view === "simple" ? (
            <div className="futures-simple">
              <div className="futures-answer">
                <span>Most likely way this plays out</span>
                <strong>{mostLikely?.label ?? "—"}</strong>
                <em>{share(mostLikely)}</em>
              </div>
              <FuturesChart scenarios={scenarios} selectedId={selectedClusterId} onSelect={toggle} />
              <div className="futures-selection" aria-live="polite">
                <span>{selected?.label ?? "Select a scenario"}</span>
                <p>
                  {selected
                    ? `${share(selected)} of modeled futures match this outcome.${!binaryEvent && selected.outcome ? ` Likely result ${rangeFor(selected)}.` : ""}`
                    : "Choose a scenario to see how often it happens and where it finishes."}
                </p>
              </div>
            </div>
          ) : (
            <>
              <div className="futures-summary">
                <div>
                  <span>Most likely</span>
                  <strong>{mostLikely?.label ?? "—"}</strong>
                  <em>{share(mostLikely)}</em>
                </div>
                <div>
                  <span>Favourable scenarios</span>
                  <strong>{strongChance}%</strong>
                </div>
              </div>

              <FuturesChart scenarios={scenarios} selectedId={selectedClusterId} onSelect={toggle} />

              <div className="deep-primary">
                <div className="viz-block">
                  <div className="panel-head tight">
                    <div>
                      <p className="section-label">Outcome spread</p>
                      <h2>Where each scenario finishes</h2>
                    </div>
                  </div>
                  {intervalRows.length ? (
                    <OutcomeIntervals ariaLabel="Simulated result range per scenario" rows={intervalRows} scale={outcomeScale} />
                  ) : (
                    <p className="quiet-copy">{binaryEvent ? "This goal is an event, so outcomes are offer/no offer categories rather than fractional event counts." : "The model returned scenario weights without result quantiles."}</p>
                  )}
                </div>

                <aside className="quiet-panel">
                  <p className="section-label">Scenario families</p>
                  <ul className="cluster-list">
                    {scenarios.map((scenario) => (
                      <li key={scenario.id}>
                        <button
                          type="button"
                          className={selectedClusterId === scenario.id ? "selected" : ""}
                          onClick={() => toggle(scenario.id)}
                        >
                          <span>{scenario.label}</span>
                          <strong>{share(scenario)}</strong>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <p className="quiet-copy">
                    {!binaryEvent && selected?.outcome
                      ? `${selected.label}: likely result ${rangeFor(selected)}.`
                      : "Percentages are the share of simulated futures in each scenario."}
                  </p>
                </aside>
              </div>

              <div className="deep-secondary">
                <article>
                  <p className="section-label">Provenance</p>
                  <p>Scenario weights and result ranges come from the backend numerical engine, not local fixtures.</p>
                </article>
              </div>
            </>
          )}
        </section>
      ) : null}
    </div>
  );
}
