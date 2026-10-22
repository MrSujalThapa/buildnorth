import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type ScenarioDistribution } from "../api/client";
import { toCompareOptions, toPathStrategies } from "../adapters/compareViewModel";
import { toMarketDetail } from "../adapters/marketViewModel";
import type { PathStrategy } from "../adapters/simulations";
import type { CompareOption, WhatIfMode, WhatIfPlan, WhatIfView } from "../adapters/templateTypes";
import {
  defaultPlanForMarket,
  defaultQuestionForMarket,
  previewFromResult,
} from "../adapters/whatIfViewModel";
import {
  buildCompareRequest,
  buildFuturesRequest,
  buildTargetSearchRequest,
} from "../adapters/whatIfRequests";
import WhatIfPage from "../components/what-if/WhatIfPage";

export function WhatIfRoute() {
  const { goalId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<WhatIfMode>("impact");
  const [view, setView] = useState<WhatIfView>("simple");

  const goal = useQuery({
    queryKey: ["goal", goalId],
    queryFn: ({ signal }) => api.goal(goalId, signal),
    enabled: Boolean(goalId),
  });
  const history = useQuery({
    queryKey: ["market-history", goalId],
    queryFn: ({ signal }) => api.marketHistory(goalId, signal),
    enabled: Boolean(goalId),
  });
  const evidence = useQuery({
    queryKey: ["evidence", goalId],
    queryFn: ({ signal }) => api.evidence(goalId, signal),
    enabled: Boolean(goalId),
  });
  const baseline = useQuery({
    queryKey: ["what-if-baseline", goalId],
    queryFn: ({ signal }) => api.baselineState(goalId, signal),
    enabled: Boolean(goalId),
  });
  const explorations = useQuery({
    queryKey: ["what-if-explorations", goalId],
    queryFn: ({ signal }) => api.whatIfExplorations(goalId, signal),
    enabled: Boolean(goalId),
  });

  const market = useMemo(() => {
    if (!goal.data) return null;
    return toMarketDetail(goal.data, history.data ?? [], evidence.data ?? []);
  }, [evidence.data, goal.data, history.data]);

  const [plan, setPlan] = useState<WhatIfPlan | null>(null);
  const effectivePlan = plan ?? (market ? defaultPlanForMarket(market) : null);

  const baselineRef = useRef(baseline.data);
  baselineRef.current = baseline.data;

  // Entering a missing state value must reprice on its own: the user should never have
  // to know a baseline forecast exists, let alone trigger one.
  const manualState = useMutation({
    mutationFn: (entries: { key: string; label: string; value: number; unit: string }[]) =>
      api.addManualState(goalId, entries),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["evidence", goalId] }),
        queryClient.invalidateQueries({ queryKey: ["what-if-baseline", goalId] }),
        queryClient.invalidateQueries({ queryKey: ["what-if-explorations", goalId] }),
        queryClient.invalidateQueries({ queryKey: ["market-history", goalId] }),
        queryClient.invalidateQueries({ queryKey: ["goal", goalId] }),
      ]);
    },
  });

  const compare = useMutation({
    mutationFn: () => {
      const state = baselineRef.current;
      if (!state?.priced) return Promise.resolve(null);
      return api.comparePaths(buildCompareRequest(goalId, state));
    },
  });

  const futures = useMutation({
    mutationFn: async (decision: string) => {
      const state = baselineRef.current;
      if (!state?.priced) return null;
      const parsed = await api.parseDecision({ goal_id: goalId, text: decision });
      if (!parsed.scenario_labels.length) {
        return {
          priced: true,
          message: "This question doesn’t map to outcomes this goal can estimate.",
          outcomes: [],
          other_probability: 0,
          evidence_basis: [],
          model_version: "unsupported",
          run_id: null,
        };
      }
      return api.possibleFutures(buildFuturesRequest(goalId, state, decision, parsed.scenario_labels));
    },
  });

  const paths = useMutation({
    mutationFn: (targetProbability: number) => {
      const state = baselineRef.current;
      if (!state?.priced) return Promise.resolve(null);
      return api.targetSearch(buildTargetSearchRequest(goalId, state, targetProbability));
    },
  });

  const compareOptions = useMemo<CompareOption[] | undefined>(() => {
    if (!compare.data?.paths.length) return undefined;
    return toCompareOptions(baseline.data, compare.data);
  }, [baseline.data, compare.data]);

  const pathStrategies = useMemo<PathStrategy[] | undefined>(
    () => toPathStrategies(paths.data ?? undefined),
    [paths.data],
  );

  const futuresDistribution = useMemo<ScenarioDistribution | undefined>(
    () => futures.data ?? undefined,
    [futures.data],
  );

  const onRunCompare = useCallback(() => {
    compare.mutate();
  }, [compare]);

  const onRunFutures = useCallback(
    (decision: string) => {
      futures.mutate(decision);
    },
    [futures],
  );

  const onRunPaths = useCallback(
    (targetProbability: number) => {
      paths.mutate(targetProbability);
    },
    [paths],
  );

  if (history.isError) {
    return (
      <main className="what-if-page">
        <div className="unpriced-state">
          <strong>History unavailable</strong>
          <span>Could not load published forecast history for this goal.</span>
        </div>
      </main>
    );
  }

  if (goal.isLoading || !goal.data || !market || !effectivePlan) {
    return (
      <main className="what-if-page">
        <p role="status">Loading What If workspace…</p>
      </main>
    );
  }

  return (
    <WhatIfPage
      market={market}
      goal={goal.data}
      plan={effectivePlan}
      onPlanChange={setPlan}
      mode={mode}
      view={view}
      onModeChange={setMode}
      onViewChange={setView}
      baseline={baseline.data}
      explorations={explorations.data ?? []}
      onExplorationsRefresh={() => {
        void queryClient.invalidateQueries({ queryKey: ["what-if-explorations", goalId] });
      }}
      compareOptions={compareOptions}
      compareResult={compare.data ?? undefined}
      compareLoading={compare.isPending}
      futuresDistribution={futuresDistribution}
      futuresLoading={futures.isPending}
      pathStrategies={pathStrategies}
      pathsLoading={paths.isPending}
      pathsMessage={paths.data?.message ?? null}
      onRunCompare={onRunCompare}
      onRunFutures={onRunFutures}
      onRunPaths={onRunPaths}
      defaultQuestion={defaultQuestionForMarket(market)}
      onSubmitMissingState={(entries) => manualState.mutate(entries)}
      submittingState={manualState.isPending}
      stateError={
        manualState.data && !manualState.data.priced
          ? manualState.data.reason
          : manualState.error instanceof Error
            ? manualState.error.message
            : null
      }
      onAddEvidence={() => { void navigate(`/goals/${goalId}?add=evidence`); }}
      onConnectSource={() => { void navigate(`/goals/${goalId}?add=source`); }}
      onBack={() => { void navigate(`/goals/${goalId}`); }}
      previewFromApi={(result) => previewFromResult(market, effectivePlan, baseline.data, result)}
    />
  );
}
