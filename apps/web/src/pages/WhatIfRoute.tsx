import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type ScenarioDistribution } from "../api/client";
import { toCompareOptions, toLeverFrontier } from "../adapters/compareViewModel";
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
  buildLeverSweepRequest,
  buildTargetSearchRequest,
  formatLeverValue,
  leverAxisTitle,
  leverLadder,
  primaryLever,
} from "../adapters/whatIfRequests";
import WhatIfPage from "../components/what-if/WhatIfPage";

const PARSE_TIMEOUT_MS = 15_000;
const INTERPRET_TIMEOUT_MS = 45_000;
const SIMULATION_TIMEOUT_MS = 60_000;
/** Lever settings priced for the Reverse frontier. */
const FRONTIER_POINTS = 7;

function withTimeout<T>(promise: Promise<T>, ms: number, step: string): Promise<T> {
  let timer = 0;
  const timeout = new Promise<never>((_, reject) => {
    timer = window.setTimeout(() => reject(new Error(`${step} took longer than ${Math.round(ms / 1000)}s. Try again.`)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => window.clearTimeout(timer));
}

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
  const viewRef = useRef(view);
  viewRef.current = view;

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
    mutationFn: async (extra?: { id: string; label: string }[]) => {
      const state = baselineRef.current;
      if (!state?.priced) return null;
      const extraPaths = await Promise.all(
        (extra ?? []).map(async (path) => {
          const stated = await withTimeout(api.parseDecision({ goal_id: goalId, text: path.label }), PARSE_TIMEOUT_MS, "Reading this option");
          let changes = stated.changes ?? [];
          if (!changes.length) {
            const parsed = await withTimeout(api.parseIntervention({ goal_id: goalId, text: path.label }), INTERPRET_TIMEOUT_MS, "Interpreting this option");
            changes = parsed.pricing_status === "PRICED" ? parsed.changes : [];
          }
          return { id: path.id, label: path.label, parsed_changes: changes };
        }),
      );
      const request = buildCompareRequest(goalId, state, extraPaths, viewRef.current);
      if (!Array.isArray(request.paths) || request.paths.length < 2) {
        return {
          paths: [],
          model_family: state.model_family,
          model_version: state.model_version,
          seed: state.config.seed,
          run_id: null,
        };
      }
      return withTimeout(api.comparePaths(request), SIMULATION_TIMEOUT_MS, "Comparing options");
    },
  });

  const futures = useMutation({
    mutationFn: async (decision: string) => {
      const state = baselineRef.current;
      if (!state?.priced) return null;
      const parsedDecision = await withTimeout(
        api.parseDecision({ goal_id: goalId, text: decision }),
        PARSE_TIMEOUT_MS,
        "Reading the decision",
      );
      if (!parsedDecision.scenario_labels.length) {
        return {
          priced: false,
          message: "This question doesn’t map to outcomes this goal can estimate.",
          outcomes: [],
          other_probability: 0,
          evidence_basis: [],
          model_version: "unsupported",
          run_id: null,
        };
      }
      return withTimeout(
        api.possibleFutures(
          buildFuturesRequest(
            goalId,
            state,
            decision,
            parsedDecision.scenario_labels,
            parsedDecision.changes ?? [],
            viewRef.current,
          ),
        ),
        SIMULATION_TIMEOUT_MS,
        "Simulating futures",
      );
    },
  });

  const paths = useMutation({
    mutationFn: async (targetProbability: number) => {
      const state = baselineRef.current;
      if (!state?.priced) return null;
      const lever = primaryLever(state);
      if (!lever) {
        return {
          search: null,
          sweep: null,
          lever: null,
          message:
            "This goal has no adjustable weekly quantity in its model, so there is nothing to solve for. Use Change to test a specific action.",
        };
      }
      const [search, sweep] = await Promise.all([
        withTimeout(
          api.targetSearch(buildTargetSearchRequest(goalId, state, targetProbability, viewRef.current)),
          SIMULATION_TIMEOUT_MS,
          "Searching for paths",
        ),
        withTimeout(
          api.comparePaths(
            buildLeverSweepRequest(goalId, state, lever, leverLadder(lever, FRONTIER_POINTS), viewRef.current),
          ),
          SIMULATION_TIMEOUT_MS,
          "Pricing lever settings",
        ),
      ]);
      return { search, sweep, lever, message: search.message };
    },
  });

  const compareOptions = useMemo<CompareOption[] | undefined>(() => {
    if (!compare.data?.paths.length) return undefined;
    return toCompareOptions(baseline.data, compare.data);
  }, [baseline.data, compare.data]);

  const pathStrategies = useMemo<PathStrategy[] | undefined>(
    () => (paths.data?.lever && paths.data.sweep ? toLeverFrontier(paths.data.lever, paths.data.sweep, paths.data.search, formatLeverValue) : undefined),
    [paths.data],
  );
  const leverAxisLabel = paths.data?.lever ? leverAxisTitle(paths.data.lever) : null;

  const resetAll = useRef<() => void>(() => undefined);
  resetAll.current = () => {
    compare.reset();
    futures.reset();
    paths.reset();
  };
  useEffect(() => {
    resetAll.current();
    setMode("impact");
    setPlan(null);
  }, [goalId]);

  const futuresDistribution = useMemo<ScenarioDistribution | undefined>(
    () => futures.data ?? undefined,
    [futures.data],
  );

  const compareIssue = compare.isError
    ? `Could not compare these paths: ${compare.error instanceof Error ? compare.error.message : "try again"}`
    : compare.data && (compare.data.paths.length === 0 || compare.data.paths.every((path) => path.primary_goal_probability == null))
      ? "These paths could not be priced from the current goal state. Try a measurable action or add evidence."
      : null;

  const onRunCompare = useCallback(
    (extra?: { id: string; label: string }[]) => {
      compare.mutate(extra);
    },
    [compare],
  );

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
      onModeChange={(nextMode) => {
        if (nextMode === mode) return;
        resetAll.current();
        setMode(nextMode);
      }}
      onViewChange={(nextView) => {
        if (nextView === view) return;
        // Results carry the draw count and sensitivity settings from the view
        // in which they ran. Never present a Simple result as Deeper analysis.
        resetAll.current();
        setView(nextView);
      }}
      baseline={baseline.data}
      explorations={explorations.data ?? []}
      onExplorationsRefresh={() => {
        void queryClient.invalidateQueries({ queryKey: ["what-if-explorations", goalId] });
      }}
      compareOptions={compareOptions}
      compareResult={compare.data ?? undefined}
      compareLoading={compare.isPending}
      compareError={compareIssue}
      futuresDistribution={futuresDistribution}
      futuresLoading={futures.isPending}
      futuresError={futures.isError ? `Could not map futures: ${futures.error instanceof Error ? futures.error.message : "try again"}` : null}
      pathStrategies={pathStrategies}
      pathsLoading={paths.isPending}
      pathsError={paths.isError ? `Could not search for paths: ${paths.error instanceof Error ? paths.error.message : "try again"}` : null}
      pathsMessage={paths.data?.message ?? null}
      pathsAxisLabel={leverAxisLabel}
      futuresQuestionForPath={(path) => {
        const lever = paths.data?.lever;
        if (!lever) return `What if I take the ${path.label} path?`;
        const value = Math.round(path.cost * 100) / 100;
        return lever.name === "weekly_application_rate"
          ? `What if I submit ${value} applications per week?`
          : `What if I contribute $${Math.round(value)} per month?`;
      }}
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
