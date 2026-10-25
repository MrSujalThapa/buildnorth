import { useEffect, useMemo, useRef, useState } from "react";

import { ArrowLeft, X } from "lucide-react";

import type { Goal, PathComparisonResult, ScenarioDistribution, WhatIfBaselineState, WhatIfExploration, WhatIfResult } from "../../api/client";

import { futuresFromDistribution, toCompareOptions } from "../../adapters/compareViewModel";
import { formatProbabilityPercent } from "../../adapters/formatProbability";

import { type PathStrategy } from "../../adapters/simulations";

import { toImpactViewModel } from "../../adapters/impactViewModel";

import type { SimulationPoint } from "../../adapters/simulationTypes";

import type { CompareOption, Market, WhatIfMode, WhatIfPlan, WhatIfPreview, WhatIfView } from "../../adapters/templateTypes";

import {

  defaultPlanForMarket,

  defaultQuestionForMarket,

  previewFromResult,

} from "../../adapters/whatIfViewModel";

import { primaryLever } from "../../adapters/whatIfRequests";
import { useWhatIfSimulation } from "../../hooks/useWhatIfSimulation";

import CompareOptionsView from "./CompareOptionsView";

import ImpactWorkspace from "./ImpactWorkspace";

import PathsToGoalView from "./PathsToGoalView";

import PossibleFuturesView from "./PossibleFuturesView";

import WhatIfModeNav from "./WhatIfModeNav";
import { ExecutionProfileRadar } from "../behavior/ExecutionProfileRadar";

import "./what-if.css";



type Props = {

  market: Market;

  goal: Goal;

  plan: WhatIfPlan;

  onPlanChange: (plan: WhatIfPlan) => void;

  mode: WhatIfMode;

  view: WhatIfView;

  onModeChange: (mode: WhatIfMode) => void;

  onViewChange: (view: WhatIfView) => void;

  baseline?: WhatIfBaselineState;

  explorations?: WhatIfExploration[];

  onExplorationsRefresh?: () => void;

  compareOptions?: CompareOption[];

  compareResult?: PathComparisonResult;

  compareLoading?: boolean;

  compareError?: string | null;

  futuresDistribution?: ScenarioDistribution;

  futuresLoading?: boolean;

  futuresError?: string | null;

  pathStrategies?: PathStrategy[];

  pathsLoading?: boolean;

  pathsError?: string | null;

  pathsMessage?: string | null;

  /** Name of the lever plotted on the Reverse frontier's x-axis. */
  pathsAxisLabel?: string | null;

  /** Futures question that restates a Reverse path as a stated quantity. */
  futuresQuestionForPath?: (path: PathStrategy) => string;

  onRunCompare?: (paths?: { id: string; label: string }[]) => void;

  onRunFutures?: (decision: string) => void;

  onRunPaths?: (targetProbability: number) => void;

  defaultQuestion?: string;

  onBack: () => void;

  onSubmitMissingState?: (
    entries: { key: string; label: string; value: number; unit: string }[],
  ) => void;

  submittingState?: boolean;

  stateError?: string | null;

  onAddEvidence?: () => void;

  onConnectSource?: () => void;

  previewFromApi: (result: WhatIfResult | undefined) => WhatIfPreview;

  theme?: "light" | "dark";

};



export function scenarioErrorMessage(error: unknown): string | null {
  if (!error) return null;
  const raw = error instanceof Error ? error.message : "unknown error";
  const detail = raw.replace(/^API request failed \((.*)\)$/s, "$1");
  return `Couldn't run this scenario: ${detail}`;
}

export function tuneCopyForMarket(category: string) {

  if (category === "Career") {

    return {

      effortLabel: "Interview prep",

      effortHelper: "Focused practice each day",

      effortUnit: "hrs / day",

      cadenceLabel: "Applications",

      cadenceHelper: "Targeted applications each week",

      cadenceUnit: "/ week",

    };

  }

  if (category === "Startup") {

    return {

      effortLabel: "Build time",

      effortHelper: "Focused product work each day",

      effortUnit: "hrs / day",

      cadenceLabel: "User conversations",

      cadenceHelper: "Conversations with real users each week",

      cadenceUnit: "/ week",

    };

  }

  return {

    effortLabel: "Focused time",

    effortHelper: "Time deliberately spent on this goal",

    effortUnit: "hrs / day",

    cadenceLabel: "Sessions",

    cadenceHelper: "Meaningful sessions each week",

    cadenceUnit: "/ week",

  };

}



export default function WhatIfPage({

  market,

  goal,

  plan,

  onPlanChange,

  mode,

  view,

  onModeChange,

  onViewChange,

  baseline,

  explorations = [],

  onExplorationsRefresh,

  compareOptions: compareOptionsProp,

  compareResult,

  compareLoading = false,

  compareError,

  futuresDistribution,

  futuresLoading = false,

  futuresError,

  pathStrategies,

  pathsLoading = false,

  pathsError,

  pathsMessage,

  pathsAxisLabel,

  futuresQuestionForPath,

  onRunCompare,

  onRunFutures,

  onRunPaths,

  defaultQuestion,

  onBack,

  onSubmitMissingState,

  submittingState,

  stateError,

  onAddEvidence,

  onConnectSource,

  previewFromApi,

  theme = "light",

}: Props) {

  const catalog = useMemo(
    () => compareOptionsProp ?? toCompareOptions(baseline, compareResult),
    [baseline, compareOptionsProp, compareResult],
  );

  const [question, setQuestion] = useState(defaultQuestion ?? defaultQuestionForMarket(market));

  const [decision, setDecision] = useState(

    market.category === "Startup"

      ? "What if I quit my internship and work on my startup full time?"

      : market.category === "Career"

        ? "What if I focus my search on FDE and applied AI roles?"

        : "What if I commit to the higher-upside path?",

  );

  const [detailsOpen, setDetailsOpen] = useState(false);

  const [selectedSimulation, setSelectedSimulation] = useState<SimulationPoint | null>(null);

  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);

  const [selectedPathId, setSelectedPathId] = useState<string | null>(null);

  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(null);

  const [pathContext, setPathContext] = useState<string | null>(null);

  const [compareIds, setCompareIds] = useState<string[]>(() => catalog.slice(0, 2).map((item) => item.id));

  const [isolatedId, setIsolatedId] = useState<string | null>(null);

  const [targetOdds, setTargetOdds] = useState(() =>
    Math.min(99, Math.max(85, Math.ceil((market.odds ?? 80) + 5))),
  );



  const simulation = useWhatIfSimulation(goal, market, plan, {
    onScenarioPersisted: onExplorationsRefresh,
    analysisDepth: view,
  });

  const futuresSimulation = useMemo(
    () => futuresFromDistribution(futuresDistribution),
    [futuresDistribution],
  );

  const baselinePriced = baseline?.priced ?? false;
  const priceabilityMessage = baseline?.priceability?.reason ?? baseline?.priceability?.headline;

  const preview =

    simulation.preview ??

    previewFromApi(simulation.scenarioResult) ??

    previewFromResult(market, plan, baseline, simulation.scenarioResult);

  const impact = useMemo(

    () => toImpactViewModel(preview, simulation.scenarioResult, baseline),

    [baseline, preview, simulation.scenarioResult],

  );



  const compareRef = useRef(onRunCompare);

  const futuresRef = useRef(onRunFutures);

  const pathsRef = useRef(onRunPaths);

  compareRef.current = onRunCompare;

  futuresRef.current = onRunFutures;

  pathsRef.current = onRunPaths;



  useEffect(() => {

    setSelectedSimulation(null);

    setSelectedClusterId(null);

  }, [mode]);



  useEffect(() => {

    if (!detailsOpen) return;

    const closeOnEscape = (event: KeyboardEvent) => {

      if (event.key === "Escape") setDetailsOpen(false);

    };

    window.addEventListener("keydown", closeOnEscape);

    return () => window.removeEventListener("keydown", closeOnEscape);

  }, [detailsOpen]);



  useEffect(() => {
    const ids = catalog.map((item) => item.id);
    setCompareIds((current) => {
      const kept = current.filter((id) => ids.includes(id));
      if (kept.length >= 2) return kept;
      return ids.slice(0, 2);
    });
  }, [catalog]);

  // Suggested allocations without a measured effect cannot be priced. In
  // particular, do not race an unpriceable automatic run against custom paths
  // after changing analysis depth.
  useEffect(() => {
    if (mode !== "compare" || compareResult || compareLoading) return;
    if (primaryLever(baseline)) compareRef.current?.();
  }, [baseline, compareLoading, compareResult, mode]);



  useEffect(() => {

    if (mode !== "paths" || !baseline?.priced) return;

    const timer = window.setTimeout(() => pathsRef.current?.(targetOdds / 100), 600);

    return () => window.clearTimeout(timer);

  }, [mode, targetOdds, baseline?.priced]);



  const copy = tuneCopyForMarket(market.category);


  function changeMode(next: WhatIfMode) {

    onModeChange(next);

    onViewChange("simple");

    setSelectedSimulation(null);

    setSelectedClusterId(null);

    if (next !== "futures") {

      setPathContext(null);

    }

  }



  function runImpact() {

    if (!question.trim()) return;

    simulation.runScenario(question);

  }



  function seePathFutures(path: PathStrategy) {

    setPathContext(path.label);

    const handoff = futuresQuestionForPath?.(path) ?? `What if I take the ${path.label} path?`;
    setDecision(handoff);
    onModeChange("futures");
    futuresRef.current?.(handoff);

    setSelectedSimulation(null);

  }



  function detailsHeading() {

    if (mode === "impact") return "Change assumptions";

    if (mode === "futures") return "Future assumptions";

    if (mode === "compare") return "Shared & option assumptions";

    return "Path constraints";

  }



  return (

    <main className={`what-if-page theme-${theme}`}>

      <section className="what-if-shell">

        <header className="what-if-header">

          <button className="icon-button" type="button" onClick={onBack} aria-label="Back to market">

            <ArrowLeft size={22} strokeWidth={1.7} />

          </button>

          <div className="what-if-heading-copy">

            <p>What if</p>

            <h1>{market.title}</h1>

          </div>

          <div className="what-if-header-actions">

            <button className="text-button" type="button" onClick={() => setDetailsOpen(true)}>

              Details

            </button>

          </div>

        </header>



        <div className="what-if-navigation-row">

          <WhatIfModeNav mode={mode} onChange={changeMode} />

          <div className="view-switch" role="tablist" aria-label="What If view">

            <button

              type="button"

              role="tab"

              aria-selected={view === "simple"}

              className={view === "simple" ? "selected" : ""}

              onClick={() => onViewChange("simple")}

            >

              Simple

            </button>

            <button

              type="button"

              role="tab"

              aria-selected={view === "deep"}

              className={view === "deep" ? "selected" : ""}

              onClick={() => onViewChange("deep")}

            >

              Deeper analysis

            </button>

          </div>

        </div>



        <div className="mode-frame">

          {mode === "impact" ? (

            <ImpactWorkspace

              market={market}

              view={view}

              plan={plan}

              preview={preview}

              impact={impact}

              question={question}

              copy={copy}

              running={
                simulation.simulation.isPending ||
                simulation.parseIntervention.isPending ||
                simulation.persistSimulation.isPending
              }

              runError={scenarioErrorMessage(
                simulation.parseIntervention.error ?? simulation.persistSimulation.error,
              ) ?? (simulation.lastParse?.insights?.length || simulation.lastParse?.strategy_plan ? null : simulation.interpretationMessage) ??
                (simulation.scenarioResult && !simulation.scenarioResult.priced
                  ? simulation.scenarioResult.message ?? "This action cannot be priced from the current evidence."
                  : null)}
              publishedOdds={market.odds}
              history={market.history}
              parseResult={simulation.lastParse}
              onRunPlannedChange={simulation.runPlannedChange}

              onQuestionChange={setQuestion}

              onRun={runImpact}

              onPlanChange={onPlanChange}

              onReset={() => onPlanChange(defaultPlanForMarket(market))}

              onOpenDetails={() => setDetailsOpen(true)}

              selectedSimulation={selectedSimulation}

              onSelectSimulation={setSelectedSimulation}

              priceability={baseline?.priceability}

              onSubmitMissingState={onSubmitMissingState}

              submittingState={submittingState}

              stateError={stateError}

              onAddEvidence={onAddEvidence}

              onConnectSource={onConnectSource}

            />

          ) : null}



          {mode === "futures" ? (

            <PossibleFuturesView

              view={view}

              decision={decision}

              pathLabel={pathContext}

              onDecisionChange={setDecision}

              onRun={() => futuresRef.current?.(decision)}

              loading={futuresLoading}

              priced={baselinePriced && !futuresError && futuresDistribution?.priced !== false}

              message={futuresError ?? futuresDistribution?.message ?? null}

              selectedClusterId={selectedClusterId}

              onSelectCluster={setSelectedClusterId}

              scenarios={futuresSimulation}

              outcomeScale={impact.outcomeScale}

            />

          ) : null}



          {mode === "compare" ? (

            <CompareOptionsView

              market={market}

              view={view}

              options={catalog}

              outcomeScale={impact.outcomeScale}

              loading={compareLoading}

              priced={baselinePriced && !compareError}

              message={compareError ?? priceabilityMessage}

              selectedIds={compareIds.length >= 2 ? compareIds : catalog.slice(0, 2).map((item) => item.id)}

              onSelectedIdsChange={setCompareIds}

              isolatedId={isolatedId}

              onIsolate={setIsolatedId}

              onComparePaths={(paths) => compareRef.current?.(paths)}

            />

          ) : null}



          {mode === "paths" ? (

            <PathsToGoalView

              market={market}

              view={view}

              paths={pathStrategies}

              loading={pathsLoading}

              priced={baselinePriced && !pathsError}

              message={pathsError ?? pathsMessage ?? priceabilityMessage}

              selectedPathId={selectedPathId}

              selectedVariantId={selectedVariantId}

              targetOdds={targetOdds}

              onSelectPath={setSelectedPathId}

              onSelectVariant={setSelectedVariantId}

              onTargetOddsChange={setTargetOdds}

              onSeeFutures={seePathFutures}

              selectedSimulation={selectedSimulation}

              onSelectSimulation={setSelectedSimulation}

              onFind={() => pathsRef.current?.(targetOdds / 100)}

              xAxisLabel={pathsAxisLabel ?? undefined}

            />

          ) : null}

        </div>



        <section className="past-what-ifs">

          <div className="past-heading">

            <h2>Past What Ifs</h2>

            <div className="past-heading-actions"><span>{explorations.length}</span></div>

          </div>

          {explorations.length ? (
            <ul className="past-list">
              {explorations.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className="past-item-button"
                    onClick={() => {
                      if (item.intervention_title) {
                        setQuestion(item.intervention_title);
                        onModeChange("impact");
                        onViewChange("simple");
                      }
                    }}
                  >
                  <div>
                    <strong>{item.intervention_title ?? "Saved exploration"}</strong>
                    <span className="meta">
                      {item.created_at ? new Date(item.created_at).toLocaleDateString() : "Saved run"}
                      {" · saved result"}
                    </span>
                    {item.scenario_probability == null ? (
                      <span className="meta">Not priced</span>
                    ) : null}
                  </div>
                  <div className="past-metrics">
                    <span>
                      {formatProbabilityPercent(
                        item.baseline_probability != null ? item.baseline_probability * 100 : null,
                      )}{" "}
                      →{" "}
                      {formatProbabilityPercent(
                        item.scenario_probability != null ? item.scenario_probability * 100 : null,
                      )}
                    </span>
                    {item.expected_uplift_pp != null ? (
                      <span>
                        {item.expected_uplift_pp >= 0 ? "+" : ""}
                        {item.expected_uplift_pp.toFixed(1)} pts
                      </span>
                    ) : null}
                  </div>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="past-empty">Run a scenario to save an exploration here.</div>
          )}

        </section>

      </section>



      {detailsOpen ? (

        <div className="details-backdrop" role="presentation" onMouseDown={() => setDetailsOpen(false)}>

          <aside

            className="details-drawer"

            onMouseDown={(event) => event.stopPropagation()}

            role="dialog"

            aria-modal="true"

            aria-label="Scenario details"

          >

            <header>

              <div>

                <p className="section-label">Details</p>

                <h2>{detailsHeading()}</h2>

              </div>

              <button type="button" className="icon-button" onClick={() => setDetailsOpen(false)} aria-label="Close details">

                <X size={18} strokeWidth={1.7} />

              </button>

            </header>



            <section>

              <h3>What this takes</h3>

              <div className="metric-row three">

                <div><span>Time</span><strong>{preview.weeklyHours} hrs / week</strong></div>

                <div><span>Duration</span><strong>{plan.durationWeeks} weeks</strong></div>

                <div><span>Assumed follow-through</span><strong>{plan.followThrough}%</strong></div>

              </div>

            </section>

            <ExecutionProfileRadar
              compact
              profile={simulation.simulation.data?.behavior_profile ?? null}
            />

            <section>

              <h3>Opportunity cost</h3>

              <p>{preview.tradeoff}</p>

            </section>



            <section>

              <h3>Assumptions</h3>

              <div className="drawer-controls">

                <label>

                  <span>

                    {mode === "futures" ? "Time committed" : mode === "paths" ? "Available hours" : copy.effortLabel}

                    <strong>{plan.effortHours} {copy.effortUnit}</strong>

                  </span>

                  <input

                    type="range"

                    min="0"

                    max="6"

                    step="0.25"

                    value={plan.effortHours}

                    onChange={(event) => onPlanChange({ ...plan, effortHours: Number(event.target.value) })}

                  />

                </label>

                <label>

                  <span>

                    {mode === "futures" ? "Funding / activity assumption" : copy.cadenceLabel}

                    <strong>{plan.cadence} {copy.cadenceUnit}</strong>

                  </span>

                  <input

                    type="range"

                    min="0"

                    max="30"

                    value={plan.cadence}

                    onChange={(event) => onPlanChange({ ...plan, cadence: Number(event.target.value) })}

                  />

                </label>

                <label>

                  <span>Assumed follow-through<strong>{plan.followThrough}%</strong></span>

                  <input

                    type="range"

                    min="20"

                    max="100"

                    value={plan.followThrough}

                    onChange={(event) => onPlanChange({ ...plan, followThrough: Number(event.target.value) })}

                  />

                </label>

                <label>

                  <span>{mode === "paths" ? "Deadline" : "Duration"}<strong>{plan.durationWeeks} weeks</strong></span>

                  <input

                    type="range"

                    min="1"

                    max="24"

                    value={plan.durationWeeks}

                    onChange={(event) => onPlanChange({ ...plan, durationWeeks: Number(event.target.value) })}

                  />

                </label>

              </div>

            </section>



            {mode === "compare" ? (

              <section>

                <h3>Option-specific assumptions</h3>

                <p>Each selected option keeps its own activity level and downside profile. Shared hours, deadline, and follow-through update every distribution.</p>

              </section>

            ) : null}



          </aside>

        </div>

      ) : null}

    </main>
  );
}
