import { useState } from "react";
import { Plus, X } from "lucide-react";

import type { CompareOption, Market, WhatIfView } from "../../adapters/templateTypes";
import {
  distributionStats,
  representativesFor,
  type SimulationPoint,
} from "../../adapters/simulations";
import SimulationCloud, { type CloudSeries } from "./SimulationCloud";
import ProbabilityDistribution from "./ProbabilityDistribution";

type Props = {
  market: Market;
  view: WhatIfView;
  options?: CompareOption[];
  comparePoints?: SimulationPoint[];
  loading?: boolean;
  priced?: boolean;
  message?: string | null;
  selectedIds: string[];
  onSelectedIdsChange: (ids: string[]) => void;
  isolatedId: string | null;
  onIsolate: (id: string | null) => void;
  selectedSimulation: SimulationPoint | null;
  onSelectSimulation: (point: SimulationPoint | null) => void;
};

export default function CompareOptionsView({
  market,
  view,
  options: optionsProp,
  comparePoints,
  loading = false,
  priced = true,
  message,
  selectedIds,
  onSelectedIdsChange,
  isolatedId,
  onIsolate,
  selectedSimulation,
  onSelectSimulation,
}: Props) {
  const catalog = optionsProp ?? [];
  const [customLabel, setCustomLabel] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const selected = catalog.filter((option) => selectedIds.includes(option.id));
  const available = catalog.filter((option) => !selectedIds.includes(option.id));
  const leader = [...selected].sort((a, b) => (b.odds ?? 0) - (a.odds ?? 0))[0];
  const points = comparePoints ?? [];
  const visiblePoints = isolatedId
    ? points.filter((point) => point.optionId === isolatedId)
    : points;
  const reps = representativesFor(visiblePoints);

  if (!priced) {
    return (
      <div className="mode-stage">
        <section className="composer" aria-label={`Compare options for ${market.title}`}>
          <div className="composer-intro">
            <p className="section-label">Compare</p>
            <h2>Which option looks strongest for this goal?</h2>
          </div>
        </section>
        <div className="unpriced-state">
          <strong>Comparison unavailable</strong>
          <span>{message ?? "Add the missing state or evidence required to price this goal."}</span>
        </div>
      </div>
    );
  }

  if (loading && !catalog.length) {
    return (
      <div className="mode-stage">
        <p role="status">Pricing comparison options from backend…</p>
      </div>
    );
  }

  if (!catalog.length) {
    return (
      <div className="mode-stage">
        <div className="unpriced-state">
          <strong>No comparison paths returned</strong>
          <span>{message ?? "Backend did not return priced comparison paths for this goal."}</span>
        </div>
      </div>
    );
  }

  const series: CloudSeries[] = selected.map((option) => ({
    id: option.id,
    label: option.label,
    points: points.filter((point) => point.optionId === option.id),
    tone:
      isolatedId === option.id || (!isolatedId && leader?.id === option.id)
        ? "aqua"
        : "neutral",
    visible: isolatedId ? isolatedId === option.id : true,
  }));

  function removeOption(id: string) {
    if (selectedIds.length <= 2) {
      return;
    }
    onSelectedIdsChange(selectedIds.filter((item) => item !== id));
    if (isolatedId === id) {
      onIsolate(null);
    }
  }

  function addOption(option: CompareOption) {
    if (selectedIds.length >= 4) {
      return;
    }
    onSelectedIdsChange([...selectedIds, option.id]);
    setPickerOpen(false);
  }

  function addCustom() {
    const match = catalog.find(
      (option) => option.label.toLowerCase() === customLabel.trim().toLowerCase(),
    );
    if (match) {
      addOption(match);
      setCustomLabel("");
      return;
    }
    if (available[0]) {
      addOption(available[0]);
      setCustomLabel("");
    }
  }

  return (
    <div className={view === "deep" ? "mode-stage deep" : "mode-stage"}>
      <section className="composer" aria-label={`Compare options for ${market.title}`}>
        <div className="composer-intro">
          <p className="section-label">Compare</p>
          <h2>Which option looks strongest for this goal?</h2>
        </div>
      </section>

      <section className="option-picker" aria-label="Options to compare">
        {selected.map((option, index) => (
          <div key={option.id} className={option.id === leader?.id ? "option-chip selected" : "option-chip"}>
            <span>Option {String.fromCharCode(65 + index)}</span>
            <strong>{option.label}</strong>
            <button
              type="button"
              aria-label={`Remove ${option.label}`}
              disabled={selectedIds.length <= 2}
              onClick={() => removeOption(option.id)}
            >
              <X size={14} strokeWidth={1.8} />
            </button>
          </div>
        ))}

        {selectedIds.length < 4 ? (
          <div className="add-option">
            <button type="button" className="text-action" onClick={() => setPickerOpen(!pickerOpen)}>
              <Plus size={15} strokeWidth={1.8} /> Add option
            </button>
            {pickerOpen ? (
              <div className="option-menu">
                {available.map((option) => (
                  <button key={option.id} type="button" onClick={() => addOption(option)}>
                    {option.label}
                    <span>Suggested</span>
                  </button>
                ))}
                <label>
                  <span>Or describe one</span>
                  <input
                    name="custom-compare-option"
                    autoComplete="off"
                    value={customLabel}
                    onChange={(event) => setCustomLabel(event.target.value)}
                    placeholder="e.g. founding engineer search…"
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        addCustom();
                      }
                    }}
                  />
                </label>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {view === "simple" ? (
        <section className="compare-simple">
          <div className="compare-leader">
            <span>Strongest on goal odds</span>
            <strong>{leader?.label ?? "—"}</strong>
            <em>{leader?.odds == null ? "—" : `${leader.odds.toFixed(0)}%`}</em>
          </div>

          <div className="compare-strips">
            {selected.map((option) => {
              const optionPoints = points.filter((point) => point.optionId === option.id);
              const stats = distributionStats(optionPoints);
              const isLeader = option.id === leader?.id;
              return (
                <button
                  key={option.id}
                  type="button"
                  className={isLeader ? "compare-strip selected" : "compare-strip"}
                  onClick={() => onIsolate(isolatedId === option.id ? null : option.id)}
                >
                  <header>
                    <h3>{option.label}</h3>
                    <strong>{option.odds == null ? "—" : `${option.odds.toFixed(0)}%`}</strong>
                  </header>
                  <ProbabilityDistribution
                    compact
                    ariaLabel={`${option.label} resulting odds distribution`}
                    series={[{ id: option.id, label: option.label, points: optionPoints, selected: isLeader }]}
                  />
                  <dl>
                    <div><dt>Likely range</dt><dd>{stats.p10.toFixed(0)}–{stats.p90.toFixed(0)}%</dd></div>
                    <div><dt>Downside</dt><dd>{option.downside}</dd></div>
                    <div><dt>Time</dt><dd>{option.time}</dd></div>
                  </dl>
                  <p>{option.note}</p>
                </button>
              );
            })}
          </div>
        </section>
      ) : (
        <section className="deep-workspace compare-deep">
          <div className="series-toggles" aria-label="Option visibility">
            {selected.map((option) => (
              <button
                key={option.id}
                type="button"
                className={isolatedId === option.id || (!isolatedId && option.id === leader?.id) ? "selected" : ""}
                onClick={() => onIsolate(isolatedId === option.id ? null : option.id)}
              >
                {option.label}
              </button>
            ))}
            {isolatedId ? (
              <button type="button" className="text-action" onClick={() => onIsolate(null)}>
                Show overlap
              </button>
            ) : null}
          </div>

          <div className="deep-primary">
            <div className="viz-block">
              <div className="panel-head tight">
                <div>
                  <p className="section-label">Distribution overlap</p>
                  <h2>How the resulting odds differ</h2>
                </div>
                <span className="meta">{visiblePoints.length.toLocaleString()} backend draws</span>
              </div>
              <ProbabilityDistribution
                ariaLabel="Overlay of resulting odds distributions for selected options"
                series={series.filter((item) => item.visible).map((item) => ({ id: item.id, label: item.label, points: item.points, selected: item.tone === "aqua" }))}
              />
            </div>
            {selectedSimulation ? (
              <aside className="quiet-panel">
                <p className="section-label">Selected draw</p>
                <p className="quiet-copy">
                  Resulting odds {selectedSimulation.y.toFixed(0)}% · resource cost{" "}
                  {selectedSimulation.x.toFixed(1)} h/wk
                </p>
                <button type="button" className="text-action" onClick={() => onSelectSimulation(null)}>
                  Clear selection
                </button>
              </aside>
            ) : (
              <aside className="quiet-panel">
                <p className="section-label">Tradeoff</p>
                <ul className="stack-list">
                  {selected.map((option) => (
                    <li key={option.id}>
                      <span>{option.label}</span>
                      <strong>{option.odds?.toFixed(0)}%</strong>
                    </li>
                  ))}
                </ul>
                <p className="quiet-copy">Aqua marks the isolated or leading option. Gray is overlap. Tails show execution risk, not color-coded categories.</p>
              </aside>
            )}
          </div>
          <div className="deep-secondary compare-samples">
            <article className="viz-block">
              <div className="panel-head tight"><div><p className="section-label">Sampled futures</p><h3>Inspect overlap and tails</h3></div></div>
              <SimulationCloud
                ariaLabel="Selectable comparison simulation samples"
                layout="beeswarm"
                xAxis={{ label: "Resulting odds", format: (value) => `${value.toFixed(0)}%`, min: 0, max: 100 }}
                yAxis={{ label: "Likelihood", format: () => "", min: 0, max: 1 }}
                selectedId={selectedSimulation?.id ?? null}
                onSelect={onSelectSimulation}
                representatives={reps}
                series={series}
              />
            </article>
          </div>
        </section>
      )}
    </div>
  );
}
