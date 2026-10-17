import { useMemo, useState, type CSSProperties } from "react";
import { RotateCcw } from "lucide-react";

import type { ImpactViewModel } from "../../adapters/impactViewModel";
import { formatProbabilityPercent } from "../../adapters/formatProbability";
import { DEFAULT_IMPACT_AXES, type SimulationPoint } from "../../adapters/simulationTypes";
import type { Market, WhatIfPlan, WhatIfPreview, WhatIfView } from "../../adapters/templateTypes";
import type { Priceability } from "../../api/client";
import MissingStatePanel from "./MissingStatePanel";
import OutcomeRangeChart from "./OutcomeRangeChart";
import ProbabilityDistribution from "./ProbabilityDistribution";
import SimulationCloud from "./SimulationCloud";

type TuneCopy = {
  effortLabel: string;
  effortHelper: string;
  effortUnit: string;
  cadenceLabel: string;
  cadenceHelper: string;
  cadenceUnit: string;
};

type Props = {
  market: Market;
  view: WhatIfView;
  plan: WhatIfPlan;
  preview: WhatIfPreview;
  impact: ImpactViewModel;
  question: string;
  suggestions: string[];
  copy: TuneCopy;
  onQuestionChange: (value: string) => void;
  onRun: () => void;
  onPlanChange: (plan: WhatIfPlan) => void;
  onReset: () => void;
  onOpenDetails: () => void;
  selectedSimulation: SimulationPoint | null;
  onSelectSimulation: (point: SimulationPoint | null) => void;
  running?: boolean;
  priceability?: Priceability | null;
  onSubmitMissingState?: (
    entries: { key: string; label: string; value: number; unit: string }[],
  ) => void;
  onAddEvidence?: () => void;
  onConnectSource?: () => void;
  submittingState?: boolean;
  stateError?: string | null;
};

function TuneSlider({
  label,
  helper,
  value,
  min,
  max,
  step,
  unit,
  onChange,
}: {
  label: string;
  helper: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  onChange: (value: number) => void;
}) {
  const progress = ((value - min) / Math.max(max - min, 1)) * 100;
  const sliderStyle = { "--slider-progress": `${progress}%` } as CSSProperties;

  return (
    <div className="tune-control">
      <div className="tune-control-top">
        <div>
          <div className="tune-label">{label}</div>
          <div className="tune-helper">{helper}</div>
        </div>
        <label className="exact-value">
          <input
            type="number"
            min={min}
            max={max}
            step={step}
            value={value}
            onChange={(event) => {
              const next = Number(event.target.value);
              if (!Number.isNaN(next)) {
                onChange(Math.min(max, Math.max(min, next)));
              }
            }}
          />
          <span>{unit}</span>
        </label>
      </div>
      <input
        className="tune-range"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        style={sliderStyle}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-label={label}
      />
    </div>
  );
}

export default function ImpactWorkspace({
  market,
  view,
  plan,
  preview,
  impact,
  question,
  suggestions,
  copy,
  onQuestionChange,
  onRun,
  onPlanChange,
  onReset,
  onOpenDetails,
  selectedSimulation,
  onSelectSimulation,
  running,
  priceability,
  onSubmitMissingState,
  onAddEvidence,
  onConnectSource,
  submittingState,
  stateError,
}: Props) {
  const [receiptOpen, setReceiptOpen] = useState(false);
  const axes = DEFAULT_IMPACT_AXES;
  const points = impact.distributionPoints;
  const stats = impact.stats;
  const resultPositive = (preview.improvementPoints ?? 0) >= 0;
  const deltaTone =
    preview.improvementPoints === null ? "neutral" : resultPositive ? "positive" : "negative";
  // The slider position is what the user asked for, not an estimate. Only show a
  // follow-through figure once the behaviour model actually returned one.
  const followThroughLabel =
    impact.followThroughPercent === null
      ? "—"
      : `${impact.followThroughPercent.toFixed(0)}%`;

  const distributionSeries = useMemo(
    () => [{ id: "change", label: "With this change", points, selected: true }],
    [points],
  );

  const unpriced = preview.currentOdds === null || !points.length;
  let unpricedPanel;
  if (priceability && priceability.status !== "PRICED" && onSubmitMissingState) {
    unpricedPanel = (
      <MissingStatePanel
        priceability={priceability}
        submitting={submittingState}
        onSubmit={onSubmitMissingState}
        onAddEvidence={() => onAddEvidence?.()}
        onConnectSource={() => onConnectSource?.()}
        error={stateError}
      />
    );
  } else if (preview.currentOdds !== null) {
    // The baseline priced; there is simply no scenario to draw yet.
    unpricedPanel = (
      <div className="empty-state">
        <strong>Your baseline odds are priced</strong>
        <span>Describe an action above and run the scenario to see where your odds could land.</span>
      </div>
    );
  } else {
    unpricedPanel = (
      <div className="empty-state">
        <strong>This scenario isn’t priced yet</strong>
        <span>Add evidence and run a priced baseline before showing a numerical outcome range.</span>
      </div>
    );
  }

  return (
    <div className={view === "deep" ? "mode-stage deep" : "mode-stage"}>
      <section className="composer">
        <label htmlFor="impact-question">What are you considering?</label>
        <div className="composer-row">
          <input
            id="impact-question"
            name="impact-question"
            autoComplete="off"
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onRun();
            }}
            placeholder="What if I change the plan…"
          />
          <button className="primary-action" type="button" onClick={onRun} disabled={running}>
            Run scenario
          </button>
        </div>
        <div className="suggestion-row">
          {suggestions.map((suggestion) => (
            <button key={suggestion} type="button" onClick={() => onQuestionChange(suggestion)}>
              {suggestion.replace(/^What if I /i, "")}
            </button>
          ))}
        </div>
      </section>

      {view === "simple" ? (
        <section className="impact-workspace">
          <aside className="tune-panel">
            <div className="panel-head">
              <div>
                <p className="section-label">Tune the plan</p>
                <h2>Make it realistic</h2>
              </div>
              <button className="text-action" type="button" onClick={onReset}>
                <RotateCcw size={14} strokeWidth={1.8} /> Reset
              </button>
            </div>
            <div className="tune-controls">
              <TuneSlider label={copy.effortLabel} helper={copy.effortHelper} value={plan.effortHours} min={0} max={6} step={0.25} unit={copy.effortUnit} onChange={(effortHours) => onPlanChange({ ...plan, effortHours })} />
              <TuneSlider label={copy.cadenceLabel} helper={copy.cadenceHelper} value={plan.cadence} min={0} max={30} step={1} unit={copy.cadenceUnit} onChange={(cadence) => onPlanChange({ ...plan, cadence })} />
              <TuneSlider label="How likely are you to stick with this?" helper="Be realistic, not optimistic" value={plan.followThrough} min={20} max={100} step={1} unit="%" onChange={(followThrough) => onPlanChange({ ...plan, followThrough })} />
              <TuneSlider label="How long will you do it?" helper="The period you expect to keep the plan" value={plan.durationWeeks} min={1} max={24} step={1} unit="weeks" onChange={(durationWeeks) => onPlanChange({ ...plan, durationWeeks })} />
            </div>
            <div className="metric-row three">
              <div><span>Time</span><strong>{preview.weeklyHours} hrs / week</strong></div>
              <div><span>Duration</span><strong>{plan.durationWeeks} weeks</strong></div>
              <div><span>Follow-through</span><strong>{plan.followThrough}%</strong></div>
            </div>
          </aside>

          <section className="result-panel">
            <div className="result-topline">
              <div className="odds-pair">
                <div><span>Current odds</span><strong>{formatProbabilityPercent(preview.currentOdds)}</strong></div>
                <div className="odds-arrow" aria-hidden="true">→</div>
                <div><span>Realistic resulting odds</span><strong>{formatProbabilityPercent(preview.scenarioOdds)}</strong></div>
              </div>
              <div className={`delta ${deltaTone}`}>
                <strong>
                  {preview.improvementPoints === null
                    ? preview.scenarioOdds === null
                      ? "—"
                      : "Unpriced"
                    : `${preview.improvementPoints >= 0 ? "+" : ""}${preview.improvementPoints.toFixed(1)} pts`}
                </strong>
                <span>possible change</span>
              </div>
            </div>

            <div className="panel-head tight">
              <div>
                <p className="section-label">Where your odds could land</p>
                <h2>Resulting odds across {impact.drawCount?.toLocaleString() ?? "simulated"} futures</h2>
              </div>
            </div>

            <div className="result-chart">
              {unpriced ? (
                unpricedPanel
              ) : (
                <ProbabilityDistribution
                  ariaLabel="Likelihood of resulting odds after this change"
                  currentOdds={preview.currentOdds}
                  series={distributionSeries}
                />
              )}
            </div>

            <div className="metric-row four">
              <div><span>If fully executed</span><strong>{formatProbabilityPercent(impact.fullExecutionOdds)}</strong></div>
              <div><span>Estimated follow-through</span><strong>{followThroughLabel}</strong></div>
              <div><span>Likely range</span><strong>{points.length ? `${stats.p10.toFixed(0)}–${stats.p90.toFixed(0)}%` : "—"}</strong></div>
              <button type="button" className="text-action" onClick={onOpenDetails}>Details</button>
            </div>
          </section>
        </section>
      ) : (
        <section className="deep-workspace impact-deep">
          <div className="execution-strip" aria-label="Execution comparison">
            <div><span>Current odds</span><strong>{formatProbabilityPercent(preview.currentOdds)}</strong></div>
            <div><span>If fully executed</span><strong>{formatProbabilityPercent(impact.fullExecutionOdds)}</strong></div>
            <div><span>Estimated follow-through</span><strong>{followThroughLabel}</strong></div>
            <div className="selected-metric">
              <span>Realistic resulting odds</span>
              <strong>{formatProbabilityPercent(preview.scenarioOdds)}</strong>
            </div>
          </div>

          <div className="deep-primary">
            <div className="viz-block">
              <div className="panel-head tight">
                <div>
                  <p className="section-label">Final outcome</p>
                  <h2>Where your odds could land</h2>
                </div>
                <span className="meta">{impact.metaLabel}</span>
              </div>
              {points.length ? (
                <ProbabilityDistribution
                  ariaLabel="Likelihood distribution of resulting odds"
                  currentOdds={preview.currentOdds}
                  series={[{ id: "plan", label: "This plan", points, selected: true }]}
                />
              ) : (
                unpricedPanel
              )}
            </div>

            <aside className="quiet-panel">
              <p className="section-label">What changes this answer most?</p>
              <div className="sensitivity-bars">
                {impact.sensitivity.length ? (
                  impact.sensitivity.map((item) => (
                    <button key={item.label} type="button" onClick={onOpenDetails}>
                      <span>{item.label}</span>
                      <i style={{ width: `${Math.min(100, item.swingPp * 11)}%` }} />
                      <strong>{item.swingPp.toFixed(1)} pts</strong>
                    </button>
                  ))
                ) : (
                  <div className="empty-state compact"><span>Sensitivity unavailable until a priced simulation returns.</span></div>
                )}
              </div>
              <p className="quiet-copy">{preview.tradeoff}</p>
            </aside>
          </div>

          <div className="deep-secondary impact-supporting">
            <article className="viz-block">
              <div className="panel-head tight">
                <div><p className="section-label">Simulated futures</p><h3>Select a representative future</h3></div>
                <span className="meta">{impact.drawCount ? `Sampled from ${impact.drawCount.toLocaleString()} draws` : "Unavailable"}</span>
              </div>
              {impact.simulationCloudAvailable && points.length ? (
                <SimulationCloud
                  ariaLabel="Sampled simulated futures"
                  layout="beeswarm"
                  xAxis={axes.x}
                  yAxis={axes.y}
                  selectedId={selectedSimulation?.id ?? null}
                  onSelect={onSelectSimulation}
                  representatives={impact.representatives}
                  series={[{ id: "plan", label: "This plan", points, tone: "aqua", visible: true }]}
                />
              ) : (
                <div className="empty-state compact">
                  <strong>Representative futures unavailable</strong>
                  <span>The backend has not exposed retained draw trajectories yet. Distribution and fan charts still reflect aggregate bins.</span>
                </div>
              )}
            </article>
            <article className="viz-block fan-support">
              <div className="panel-head tight"><div><p className="section-label">Over time</p><h3>How the range could evolve</h3></div></div>
              {preview.outcome.length ? (
                <OutcomeRangeChart data={preview.outcome} currentOdds={preview.currentOdds ?? 0} />
              ) : (
                <div className="empty-state compact"><span>Fan chart unavailable until the backend returns a time fan.</span></div>
              )}
            </article>
            <article>
              <p className="section-label">Technical receipt</p>
              <button type="button" className="text-action" onClick={() => setReceiptOpen(!receiptOpen)}>
                {receiptOpen ? "Hide" : "Show"} model details
              </button>
              {receiptOpen ? (
                <ul className="stack-list compact">
                  <li><span>Model</span><strong>{impact.modelLabel ?? "Unavailable"}</strong></li>
                  <li><span>Draws</span><strong>{impact.drawCount?.toLocaleString() ?? "—"}</strong></li>
                  <li><span>Seed</span><strong>{impact.seed ?? "—"}</strong></li>
                  <li><span>LLM calls</span><strong>{impact.llmCalls ?? 0} for repricing</strong></li>
                  <li><span>Goal</span><strong>{market.title}</strong></li>
                </ul>
              ) : null}
            </article>
          </div>
        </section>
      )}
    </div>
  );
}
