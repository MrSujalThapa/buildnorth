import { useMemo, useState } from "react";
import type {
  Goal, MarketHistoryPoint, ParseInterventionResult, PathComparisonResult,
  ScenarioDistribution, TargetSearchResult, WhatIfBaselineState, WhatIfResult,
} from "../../api/client";
import { futuresFromDistribution, toCompareOptions, toPathStrategies } from "../../adapters/compareViewModel";
import { toImpactViewModel } from "../../adapters/impactViewModel";
import { toMarketDetail } from "../../adapters/marketViewModel";
import type { WhatIfMode, WhatIfView } from "../../adapters/templateTypes";
import { defaultPlanForMarket, previewFromResult } from "../../adapters/whatIfViewModel";
import ImpactWorkspace from "./ImpactWorkspace";
import PossibleFuturesView from "./PossibleFuturesView";
import CompareOptionsView from "./CompareOptionsView";
import PathsToGoalView from "./PathsToGoalView";
import { tuneCopyForMarket } from "./WhatIfPage";
import "./what-if.css";

/** The same four data-driven visual components mounted by the website. */
export type WhatIfVisualPayload = {
  goal: Goal;
  history: MarketHistoryPoint[];
  baseline: WhatIfBaselineState;
  mode: WhatIfMode;
  view: WhatIfView;
  question: string;
  scenario?: WhatIfResult | null;
  interpretation?: ParseInterventionResult | null;
  futures?: ScenarioDistribution | null;
  comparison?: PathComparisonResult | null;
  targetSearch?: TargetSearchResult | null;
  targetProbability?: number | null;
  state?: "ready" | "pending" | "failed" | "unpriced";
  message?: string | null;
};

export type WhatIfVisualRequest = {
  goal_id: string;
  mode: WhatIfMode;
  view: WhatIfView;
  question: string;
  target_probability?: number;
  alternatives?: string[];
};

export function WhatIfVisualEmbed({
  payload, onRequest,
}: {
  payload: WhatIfVisualPayload;
  onRequest?: (request: WhatIfVisualRequest) => void;
}) {
  const market = useMemo(
    () => toMarketDetail(payload.goal, payload.history, []),
    [payload.goal, payload.history],
  );
  const [question, setQuestion] = useState(payload.question);
  const [plan, setPlan] = useState(() => defaultPlanForMarket(market));
  const [selectedCluster, setSelectedCluster] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedVariant, setSelectedVariant] = useState<string | null>(null);
  const [selectedOptions, setSelectedOptions] = useState<string[]>([]);
  const [isolatedOption, setIsolatedOption] = useState<string | null>(null);
  const [target, setTarget] = useState(Math.round((payload.targetProbability ?? 0.85) * 100));
  const preview = previewFromResult(market, plan, payload.baseline, payload.scenario ?? undefined);
  const impact = toImpactViewModel(preview, payload.scenario ?? undefined, payload.baseline);
  const options = toCompareOptions(payload.baseline, payload.comparison ?? undefined);
  const paths = toPathStrategies(payload.targetSearch ?? undefined);
  const request = (mode: WhatIfMode, value: string, target_probability?: number, alternatives?: string[]) => onRequest?.({
    goal_id: payload.goal.goal_id, mode, view: payload.view,
    question: value, target_probability, alternatives,
  });

  return (
    <main className="what-if-page mcp-what-if" data-goal-id={payload.goal.goal_id}
      data-mode={payload.mode} data-view={payload.view}>
      <div className="what-if-shell">
        <header className="mcp-what-if-heading">
          <span className="section-label">What If · {payload.mode === "paths" ? "Reverse" : payload.mode === "impact" ? "Change" : payload.mode}</span>
          <h1>{payload.goal.title}</h1>
          <p>{payload.view === "deep" ? "Deeper analysis" : "Simple analysis"} · Hypothetical results never change published odds.</p>
        </header>
        {payload.state === "pending" ? <p role="status">Running the backend analysis…</p> : null}
        {payload.state === "failed" ? <p role="alert">{payload.message ?? "Analysis failed."}</p> : null}
        {payload.mode === "impact" ? <ImpactWorkspace
          key={payload.goal.goal_id} market={market} view={payload.view} plan={plan}
          preview={preview} impact={impact} question={question}
          copy={tuneCopyForMarket(market.category)} onQuestionChange={setQuestion}
          onRun={() => request("impact", question)} onPlanChange={setPlan}
          onReset={() => setPlan(defaultPlanForMarket(market))} onOpenDetails={() => {}}
          selectedSimulation={null} onSelectSimulation={() => {}}
          publishedOdds={market.odds} history={market.history}
          parseResult={payload.interpretation ?? null}
          running={payload.state === "pending"}
          runError={payload.state === "failed" || payload.state === "unpriced" ? payload.message : null}
          priceability={payload.baseline.priceability}
        /> : null}
        {payload.mode === "futures" ? <PossibleFuturesView
          view={payload.view} decision={question} onDecisionChange={setQuestion}
          onRun={() => request("futures", question)}
          loading={payload.state === "pending"} priced={payload.baseline.priced && payload.futures?.priced !== false}
          message={payload.message ?? payload.futures?.message}
          selectedClusterId={selectedCluster} onSelectCluster={setSelectedCluster}
          scenarios={futuresFromDistribution(payload.futures ?? undefined)}
          outcomeScale={impact.outcomeScale}
        /> : null}
        {payload.mode === "compare" ? <CompareOptionsView
          market={market} view={payload.view} options={options} outcomeScale={impact.outcomeScale}
          loading={payload.state === "pending"} priced={payload.baseline.priced}
          message={payload.message}
          selectedIds={selectedOptions.length >= 2 ? selectedOptions : options.slice(0, 2).map((item) => item.id)}
          onSelectedIdsChange={setSelectedOptions} isolatedId={isolatedOption} onIsolate={setIsolatedOption}
          onComparePaths={(alternatives) => request(
            "compare", "Compare these alternatives", undefined, alternatives.map((item) => item.label),
          )}
        /> : null}
        {payload.mode === "paths" ? <PathsToGoalView
          market={market} view={payload.view} paths={paths}
          loading={payload.state === "pending"} priced={payload.baseline.priced}
          message={payload.message} selectedPathId={selectedPath} selectedVariantId={selectedVariant}
          targetOdds={target} onSelectPath={setSelectedPath} onSelectVariant={setSelectedVariant}
          onTargetOddsChange={setTarget} onSeeFutures={() => request("futures", question)}
          selectedSimulation={null} onSelectSimulation={() => {}}
          onFind={() => request("paths", question, target / 100)}
        /> : null}
      </div>
    </main>
  );
}
