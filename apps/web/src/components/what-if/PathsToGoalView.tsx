import { useState } from "react";

import type { Market, WhatIfView } from "../../adapters/templateTypes";
import {
  pathAxes,
  type PathStrategy,
  type SimulationPoint,
} from "../../adapters/simulations";
import SimulationCloud from "./SimulationCloud";
type Props = {
  market: Market;
  view: WhatIfView;
  paths?: PathStrategy[];
  loading?: boolean;
  priced?: boolean;
  message?: string | null;
  selectedPathId: string | null;
  selectedVariantId: string | null;
  targetOdds: number;
  onSelectPath: (id: string) => void;
  onSelectVariant: (id: string | null) => void;
  onTargetOddsChange: (value: number) => void;
  onSeeFutures: (path: PathStrategy) => void;
  selectedSimulation: SimulationPoint | null;
  onSelectSimulation: (point: SimulationPoint | null) => void;
  onFind?: () => void;
};

export default function PathsToGoalView({
  market,
  view,
  paths: pathsProp,
  loading = false,
  priced = true,
  message,
  selectedPathId,
  selectedVariantId,
  targetOdds,
  onSelectPath,
  onSelectVariant,
  onTargetOddsChange,
  onSeeFutures,
  onFind,
}: Props) {
  const paths = pathsProp ?? [];
  const loadingPaths = loading || pathsProp === undefined;
  const axes = pathAxes(market);
  const selected = paths.find((path) => path.id === selectedPathId) ?? paths[0];
  const [finding, setFinding] = useState(false);
  const selectedVariant = selected?.variants.find((item) => item.id === selectedVariantId);
  const pathPoints: SimulationPoint[] = paths.map((path, index) => ({
    id: index + 1,
    x: path.cost,
    y: path.odds ?? 0,
    clusterId: path.id,
    pathId: path.id,
    goalHit: (path.odds ?? 0) >= targetOdds,
    seed: index,
  }));

  const variantPoints: SimulationPoint[] = selected
    ? selected.variants.map((variant, index) => ({
        id: 100 + index,
        x: variant.cost,
        y: variant.odds,
        clusterId: selected.id,
        pathId: variant.id,
        goalHit: variant.odds >= targetOdds,
        seed: index,
      }))
    : [];

  const selectedPointId = selectedVariant
    ? variantPoints.find((point) => point.pathId === selectedVariant.id)?.id ?? null
    : pathPoints.find((point) => point.pathId === selected?.id)?.id ?? null;

  const feasible = paths.filter((path) => (path.odds ?? 0) >= targetOdds);

  return (
    <div className={view === "deep" ? "mode-stage deep" : "mode-stage"}>
      <section className="composer">
        <div className="composer-intro">
          <h2>What would move the odds?</h2>
        </div>
      </section>

      {!priced ? (
        <div className="unpriced-state">
          <strong>Paths unavailable</strong>
          <span>{message ?? "Price the baseline before searching for paths."}</span>
        </div>
      ) : null}

      {priced && loadingPaths ? <p role="status">Searching backend paths for {targetOdds}% target…</p> : null}

      {priced && !loadingPaths && !paths.length ? (
        <div className="past-empty">
          {message ?? "No feasible paths met this target. Lower the target odds or add evidence."}
        </div>
      ) : null}

      {priced && paths.length ? (
      <section className={view === "deep" ? "paths-workspace deep" : "paths-workspace"}>
        {view === "simple" ? (
          <div className="paths-simple">
            <div className="paths-answer">
              <span>Highest modeled odds</span>
              <strong>{paths[0]?.label ?? "—"}</strong>
              <em>{paths[0]?.odds == null ? "—" : `${paths[0].odds.toFixed(0)}%`}</em>
            </div>
            <ol className="ranked-paths">
              {paths.map((path, index) => (
                <li key={path.id}>
                  <button type="button" onClick={() => onSelectPath(path.id)} className={selected?.id === path.id ? "selected" : ""}>
                    <span className="path-rank">{index + 1}</span>
                    <div><h3>{path.label}</h3><p>{path.requirement}</p></div>
                    <strong>{path.odds == null ? "—" : `${path.odds.toFixed(0)}%`}</strong>
                    <small>Relative effort {path.cost}</small>
                  </button>
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <>
        <div className="target-row">
          <label>
            <span>Target odds</span>
            <strong>{targetOdds}%</strong>
            <input
              type="range"
              min={40}
              max={85}
              value={targetOdds}
              onChange={(event) => onTargetOddsChange(Number(event.target.value))}
              aria-label="Target odds"
            />
          </label>
          <button
            type="button"
            className="primary-action compact"
            onClick={() => {
              setFinding(true);
              onFind?.();
            }}
          >
            Find feasible paths
          </button>
          <span className="meta">
            {finding
              ? `${feasible.length} path${feasible.length === 1 ? "" : "s"} sit on or above ${targetOdds}%`
              : "Horizontal line is the target. Points above it clear the bar."}
          </span>
        </div>

        <div className="deep-primary">
          <div className="viz-block">
            <div className="panel-head tight">
              <div>
                <p className="section-label">Strategy frontier</p>
                <h2>Each point is a path you could take, not a random simulation</h2>
              </div>
            </div>
            <SimulationCloud
              ariaLabel="Paths to goal frontier"
              layout="scatter"
              xAxis={axes.x}
              yAxis={axes.y}
              selectedId={selectedPointId}
              onSelect={(point) => {
                if (!point) {
                  return;
                }
                const path = paths.find((item) => item.id === point.pathId);
                const variant = selected?.variants.find((item) => item.id === point.pathId);
                if (path) {
                  onSelectPath(path.id);
                  onSelectVariant(null);
                } else if (variant) {
                  onSelectVariant(variant.id);
                }
              }}
              targetY={targetOdds}
              targetLabel={`${targetOdds}% target`}
              series={[
                {
                  id: "paths",
                  label: "Strategies",
                  points: pathPoints,
                  tone: "neutral",
                  visible: true,
                },
                {
                  id: "selected",
                  label: selected?.label ?? "Selected",
                  points: pathPoints.filter((point) => point.pathId === selected?.id),
                  tone: "aqua",
                  visible: true,
                },
                {
                  id: "variants",
                  label: "Variants",
                  points: variantPoints,
                  tone: "muted",
                  visible: Boolean(selected),
                },
              ]}
            />
            <ul className="path-annotations">
              {paths.map((path) => (
                <li key={path.id}>
                  <button
                    type="button"
                    className={path.id === selected?.id ? "selected" : ""}
                    onClick={() => {
                      onSelectPath(path.id);
                      onSelectVariant(null);
                    }}
                  >
                    <strong>{path.label}</strong>
                    <span>{path.odds == null ? "—" : `${path.odds.toFixed(0)}%`}</span>
                    {path.onFrontier ? <em>Frontier</em> : <em>Dominated</em>}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          {selected ? (
            <aside className="path-detail">
              <p className="section-label">Selected path</p>
              <h3>{selectedVariant?.label ?? selected.label}</h3>
              <p className="path-odds">
                {(selectedVariant?.odds ?? selected.odds ?? 0).toFixed(0)}%
              </p>
              <p>{selected.requirement}</p>
              <p className="quiet-copy">
                Effort {selectedVariant?.cost ?? selected.cost} · Fragility {selected.fragility}
                {selected.onFrontier ? " · On the frontier" : " · Dominated by a cheaper or stronger path"}
              </p>

              <div className="variant-list">
                <p className="section-label">Variants</p>
                {selected.variants.map((variant) => (
                  <button
                    key={variant.id}
                    type="button"
                    className={variant.id === selectedVariantId ? "selected" : ""}
                    onClick={() => onSelectVariant(variant.id === selectedVariantId ? null : variant.id)}
                  >
                    <span>{variant.label}</span>
                    <strong>{variant.odds}%</strong>
                  </button>
                ))}
              </div>

              <button
                type="button"
                className="primary-action"
                onClick={() => onSeeFutures(selected)}
              >
                See how this could play out
              </button>
            </aside>
          ) : null}
        </div>

        {selected ? (
          <div className="deep-secondary paths-deep-extra">
            <article>
              <p className="section-label">Constraints</p>
              <p>Resource budget is relative. Paths to the right demand more time, reputation, or runway than paths to the left.</p>
            </article>
            <article>
              <p className="section-label">Robustness</p>
              <p>{selected.label} is {selected.fragility.toLowerCase()} fragility. Variants stay attached to the selected strategy instead of opening a tree.</p>
            </article>
          </div>
        ) : null}
          </>
        )}
      </section>
      ) : null}
    </div>
  );
}
