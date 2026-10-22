import { useMemo } from "react";

import type { Market, WhatIfView } from "../../adapters/templateTypes";
import {
  clusterCentroids,
  distributionStats,
  futuresAxes,
  representativesFor,
  type SimulationCluster,
  type SimulationPoint,
} from "../../adapters/simulations";
import SimulationCloud, { type CloudSeries } from "./SimulationCloud";
import SimulationInspector from "./SimulationInspector";
import { ScenarioComposer } from "./ScenarioComposer";

type Props = {
  market: Market;
  view: WhatIfView;
  decision: string;
  pathLabel?: string | null;
  onDecisionChange: (value: string) => void;
  onRun: () => void;
  loading?: boolean;
  priced?: boolean;
  message?: string | null;
  selectedSimulation: SimulationPoint | null;
  onSelectSimulation: (point: SimulationPoint | null) => void;
  selectedClusterId: string | null;
  onSelectCluster: (id: string | null) => void;
  apiClusters?: SimulationCluster[];
  apiPoints?: SimulationPoint[];
};

export default function PossibleFuturesView({
  market,
  view,
  decision,
  pathLabel,
  onDecisionChange,
  onRun,
  loading = false,
  priced = true,
  message,
  selectedSimulation,
  onSelectSimulation,
  selectedClusterId,
  onSelectCluster,
  apiClusters,
  apiPoints,
}: Props) {
  const points = apiPoints ?? [];
  const clusters = apiClusters ?? [];
  const axes = useMemo(() => futuresAxes(market), [market]);
  const centroids = useMemo(() => clusterCentroids(points, clusters), [clusters, points]);
  const visiblePoints = selectedClusterId
    ? points.filter((point) => point.clusterId === selectedClusterId)
    : points;
  const reps = useMemo(() => representativesFor(visiblePoints), [visiblePoints]);
  const stats = useMemo(() => distributionStats(visiblePoints), [visiblePoints]);
  const mostLikely = [...clusters].sort((a, b) => b.probability - a.probability)[0];
  const strongChance = clusters
    .filter((cluster) => cluster.tone === "positive")
    .reduce((sum, cluster) => sum + cluster.probability, 0);
  const selectedCluster = clusters.find((cluster) => cluster.id === selectedClusterId);
  const hasResults = clusters.length > 0 && points.length > 0;

  const series: CloudSeries[] = [
    {
      id: "futures",
      label: pathLabel ? `Futures if ${pathLabel}` : "Possible futures",
      points: visiblePoints,
      tone: "aqua",
      visible: true,
    },
  ];

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
              <em>{mostLikely ? `${mostLikely.probability}%` : "—"}</em>
            </div>
            <div className="scenario-distribution" aria-label="Possible future scenarios">
              {clusters.map((cluster) => (
                <button
                  key={cluster.id}
                  type="button"
                  className={selectedClusterId === cluster.id ? "selected" : ""}
                  onClick={() => onSelectCluster(selectedClusterId === cluster.id ? null : cluster.id)}
                >
                  <span>{cluster.label}</span>
                  <strong>{cluster.probability}%</strong>
                  <i style={{ width: `${cluster.probability}%` }} aria-hidden="true" />
                </button>
              ))}
            </div>
            <div className="futures-selection" aria-live="polite">
              <span>{selectedCluster?.label ?? "Select a scenario"}</span>
              <p>{selectedCluster ? `Conditional goal odds: ${Math.round(selectedCluster.goalRate * 100)}%. Open Deeper Analysis to inspect representative futures and the downside inside this scenario.` : "Choose a scenario to see its conditional odds and assumptions."}</p>
            </div>
          </div>
        ) : (
          <>
        <div className="futures-summary">
          <div>
            <span>Most likely</span>
            <strong>{mostLikely?.label ?? "—"}</strong>
            <em>{mostLikely ? `${mostLikely.probability}%` : "—"}</em>
          </div>
          <div>
            <span>Strong upside region</span>
            <strong>{strongChance}%</strong>
          </div>
          <div>
            <span>Goal success in this sample</span>
            <strong>{Math.round(stats.goalRate * 100)}%</strong>
          </div>
        </div>

        <div className="deep-primary">
          <div className="viz-block">
            <div className="panel-head tight">
              <div>
                <p className="section-label">Simulation cloud</p>
                <h2>{visiblePoints.length.toLocaleString()} sampled futures</h2>
              </div>
              <span className="meta">Backend distribution · each dot is one hypothetical draw</span>
            </div>
            <SimulationCloud
              ariaLabel="Possible futures simulation cloud"
              layout={axes.layout}
              xAxis={axes.x}
              yAxis={axes.y}
              selectedId={selectedSimulation?.id ?? null}
              onSelect={onSelectSimulation}
              representatives={reps}
              clusters={centroids}
              series={series}
            />
          </div>

          {selectedSimulation ? (
            <SimulationInspector
              simulationId={selectedSimulation.id}
              narrative={{
                headline: selectedCluster?.label ?? "Selected future",
                timeline: [],
                assumptions: message ? [message] : [],
                events: [],
                goalAchieved: selectedSimulation.goalHit,
                outcomeValue: `${selectedSimulation.y.toFixed(0)}%`,
              }}
              onClose={() => onSelectSimulation(null)}
            />
          ) : (
            <aside className="quiet-panel">
              <p className="section-label">Scenario families</p>
              <ul className="cluster-list">
                {clusters.map((cluster) => (
                  <li key={cluster.id}>
                    <button
                      type="button"
                      className={selectedClusterId === cluster.id ? "selected" : ""}
                      onClick={() =>
                        onSelectCluster(selectedClusterId === cluster.id ? null : cluster.id)
                      }
                    >
                      <span>{cluster.label}</span>
                      <strong>{cluster.probability}%</strong>
                    </button>
                  </li>
                ))}
              </ul>
              {selectedCluster ? (
                <p className="quiet-copy">
                  Goal success inside this family: {Math.round(selectedCluster.goalRate * 100)}%.
                </p>
              ) : (
                <p className="quiet-copy">Select a family or any dot. Representative markers are median, p10, and p90 — not lucky draws.</p>
              )}
            </aside>
          )}
        </div>

          <div className="deep-secondary">
            <article>
              <p className="section-label">Distribution</p>
              <ul className="stack-list">
                <li><span>p10</span><strong>{axes.x.format(stats.p10)}</strong></li>
                <li><span>p50</span><strong>{axes.x.format(stats.p50)}</strong></li>
                <li><span>p90</span><strong>{axes.x.format(stats.p90)}</strong></li>
              </ul>
            </article>
            <article>
              <p className="section-label">Provenance</p>
              <p>Scenario weights and draws come from the backend numerical engine, not local fixtures.</p>
            </article>
          </div>
          </>
        )}
      </section>
      ) : null}
    </div>
  );
}
