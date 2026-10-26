import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type Goal,
  type ParsedInterventionChange,
  type StrategyChangesResponse,
  type StrategyPlan,
  type WhatIfAssumption,
  type WhatIfBaselineState,
  type WhatIfResult,
} from "../api/client";
import { simulationConfigForView } from "../adapters/whatIfRequests";
import { previewFromResult } from "../adapters/whatIfViewModel";
import type { Market, WhatIfPlan, WhatIfPreview, WhatIfView } from "../adapters/templateTypes";

type TuneValues = {
  current: number;
  target: number;
  periods: number;
  flow: number;
  growth: number;
  volatility: number;
  execution: number;
  action: number;
};

function assumptionMap(state: WhatIfBaselineState) {
  return Object.fromEntries(state.assumptions.map((item) => [item.name, item]));
}

function tuneValuesFromBaseline(state: WhatIfBaselineState): TuneValues {
  const byName = assumptionMap(state);
  return {
    current: state.current_value ?? 0,
    target: state.target_value ?? 0,
    periods: state.periods ?? 1,
    flow: byName.flow?.value ?? byName.weekly_application_rate?.value ?? 0,
    growth: byName.growth_mean?.value ?? 0,
    volatility: byName.growth_volatility?.value ?? 0,
    execution: byName.execution_probability?.value ?? 0.72,
    action: 0,
  };
}

export function useWhatIfSimulation(
  goal: Goal | undefined,
  market: Market | undefined,
  plan: WhatIfPlan,
  options?: { onScenarioPersisted?: () => void; analysisDepth?: WhatIfView },
) {
  const goalId = goal?.goal_id ?? "";
  const baseline = useQuery({
    queryKey: ["what-if-baseline", goalId],
    queryFn: ({ signal }) => api.baselineState(goalId, signal),
    enabled: Boolean(goalId),
  });
  const [values, setValues] = useState<TuneValues | null>(null);
  const [interpretationMessage, setInterpretationMessage] = useState<string | null>(null);
  const [lastParse, setLastParse] = useState<Awaited<ReturnType<typeof api.parseIntervention>> | null>(null);
  const pendingScenario = useRef<string | null>(null);
  const parseGeneration = useRef(0);
  const pricedChanges = useRef<ParsedInterventionChange[] | null>(null);
  const pricedTitle = useRef<string | null>(null);
  const pricedDepth = useRef<string | null>(null);
  const simulation = useMutation({ mutationFn: (body: Record<string, unknown>) => api.fastReprice(body) });
  const persistSimulation = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.simulateWhatIf(body),
  });
  const mutateScenario = simulation.mutate;
  const parseIntervention = useMutation({
    mutationFn: (text: string) => api.parseIntervention({ goal_id: goalId, text }),
  });
  const strategyChanges = useMutation({ mutationFn: api.strategyChanges });
  const [pricedOption, setPricedOption] = useState<StrategyChangesResponse | null>(null);

  useEffect(() => {
    parseGeneration.current += 1;
    setLastParse(null);
    setInterpretationMessage(null);
  }, [goalId]);

  useEffect(() => {
    if (!baseline.data?.priced) {
      setValues(null);
      return;
    }
    setValues(tuneValuesFromBaseline(baseline.data));
  }, [baseline.data]);

  const assumptions: WhatIfAssumption[] = useMemo(() => {
    if (!baseline.data?.priced || !values) return [];
    const flowKey = baseline.data.assumptions.some((item) => item.name === "weekly_application_rate")
      ? "weekly_application_rate"
      : "flow";
    return baseline.data.assumptions.map((item) => {
      if (!item.editable) return item;
      const live =
        item.name === flowKey
          ? values.flow
          : item.name === "growth_mean"
            ? values.growth
            : item.name === "growth_volatility"
              ? values.volatility
              : item.name === "execution_probability"
                ? plan.followThrough / 100
                : item.value;
      return { ...item, value: live };
    });
  }, [baseline.data, plan, values]);

  const scenarioResult = persistSimulation.data;

  const metric = goal?.success_definition?.metric;
  const targetDimension = typeof metric === "string" ? metric : "target";
  // default_intervention arrives untyped from the API, so only real strings are used.
  const readText = (value: unknown, fallback: string) =>
    typeof value === "string" && value ? value : fallback;
  const request = useMemo(() => {
    if (!values || !baseline.data?.priced || !goal) return null;
    const defaultIntervention = baseline.data.default_intervention ?? {};
    const explorationEffect = values.action === 0 ? null : values.action;
    return {
      goal_id: goal.goal_id,
      current_value: values.current,
      target_value: values.target,
      periods: values.periods,
      direction: baseline.data.direction,
      assumptions,
      parsed_changes: [],
      intervention: {
        id: readText(defaultIntervention.id, "primary-plan"),
        title: readText(defaultIntervention.title, "Scenario plan"),
        action_type: readText(defaultIntervention.action_type, "flow_change"),
        target_dimension: targetDimension,
        amount: 1,
        unit: "units/period",
        duration_periods: values.periods,
        effect_per_unit: explorationEffect,
        effect_source: explorationEffect == null ? null : "EXPLORATION_ASSUMPTION",
        diminishing_return: Number(defaultIntervention.diminishing_return ?? 0.04),
        cost: defaultIntervention.cost ?? { hours_per_week: planWeeklyHours(plan), money: 0, energy: 0 },
      },
      config: simulationConfigForView(options?.analysisDepth ?? "simple", baseline.data.config.seed),
    };
  }, [assumptions, baseline.data, goal, options?.analysisDepth, plan, targetDimension, values]);

  useEffect(() => {
    if (!request) return;
    const timer = window.setTimeout(() => mutateScenario(request), 180);
    return () => window.clearTimeout(timer);
  }, [request, mutateScenario]);

  const preview: WhatIfPreview | null = useMemo(() => {
    if (!market) return null;
    const comparison = previewFromResult(market, plan, baseline.data, simulation.data);
    const scenario = previewFromResult(market, plan, baseline.data, scenarioResult);
    return {
      ...scenario,
      currentOdds: scenarioResult ? scenario.currentOdds : comparison.currentOdds,
      scenarioOdds: scenarioResult?.priced ? scenario.scenarioOdds : null,
      improvementPoints: scenarioResult?.priced ? scenario.improvementPoints : null,
    };
  }, [baseline.data, market, plan, scenarioResult, simulation.data]);

  function runScenario(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    if (!request) {
      pendingScenario.current = trimmed;
      return;
    }
    pendingScenario.current = null;
    setInterpretationMessage(null);
    setPricedOption(null);
    const generation = ++parseGeneration.current;
    parseIntervention.mutate(trimmed, {
        onSuccess: (parsed) => {
        if (generation !== parseGeneration.current) return;
        setLastParse(parsed);
        const qualitative = parsed.request_kind && parsed.request_kind !== "quantitative_scenario";
        if (qualitative || !parsed.changes.length || parsed.pricing_status !== "PRICED") {
          persistSimulation.reset();
          if (parsed.insights?.length || parsed.confirmation_needed || parsed.strategy_plan) {
            setInterpretationMessage(null);
            return;
          }
          setInterpretationMessage(
            parsed.consumer_summary ||
              parsed.unsupported[0] ||
              parsed.limitations?.[0] ||
              "This action has no measured link to the goal's forecast. Try a specific modeled quantity, such as applications per week.",
          );
          return;
        }
        const selected = parsed.strategy_plan?.selected_option ?? "parsed";
        setPricedOption({
          option_id: selected,
          title: trimmed,
          changes: parsed.changes,
          assumptions_used: [],
          conflicts: [],
          proxy: selected === "as_applications",
        });
        const body = {
          ...request,
          parsed_changes: parsed.changes,
          intervention: { ...request.intervention, title: trimmed },
        };
        persistSimulation.mutate(body, {
          onSuccess: () => {
            options?.onScenarioPersisted?.();
          },
        });
      },
    });
  }

  /** Prices an option the user chose from a strategy plan; the backend builds the model changes. */
  function runStrategyOption(question: string, plan: StrategyPlan, optionId: string, inputs: Record<string, number>) {
    if (!request || !goal) return;
    setInterpretationMessage(null);
    strategyChanges.mutate(
      { goal_id: goal.goal_id, family: plan.family, option_id: optionId, text: question, inputs },
      {
        onSuccess: (resolved) => {
          const changes: ParsedInterventionChange[] = resolved.changes;
          setLastParse((prior) =>
            prior?.strategy_plan
              ? {
                  ...prior,
                  changes,
                  pricing_status: changes.length ? "PRICED" : "NOT_PRICED",
                  strategy_plan: {
                    ...prior.strategy_plan,
                    modeled: changes.length > 0,
                    selected_option: optionId,
                    stated_quantity: inputs.amount ?? null,
                    conflicts: resolved.conflicts,
                    needs: [],
                  },
                }
              : prior,
          );
          if (!changes.length) {
            pricedChanges.current = null;
            persistSimulation.reset();
            return;
          }
          pricedChanges.current = changes;
          pricedTitle.current = resolved.title;
          pricedDepth.current = `${request.config.minimum_draws}:${request.config.include_sensitivity}`;
          setPricedOption(resolved);
          persistSimulation.mutate(
            { ...request, parsed_changes: changes, intervention: { ...request.intervention, title: resolved.title } },
            { onSuccess: () => options?.onScenarioPersisted?.() },
          );
        },
      },
    );
  }

  useEffect(() => {
    const changes = pricedChanges.current;
    if (!request || !changes?.length) return;
    const depth = `${request.config.minimum_draws}:${request.config.include_sensitivity}`;
    if (pricedDepth.current === depth) return;
    pricedDepth.current = depth;
    persistSimulation.mutate({
      ...request,
      parsed_changes: changes,
      intervention: { ...request.intervention, title: pricedTitle.current || request.intervention.title },
    });
  }, [persistSimulation, request]);

  useEffect(() => {
    if (request && pendingScenario.current) {
      const text = pendingScenario.current;
      pendingScenario.current = null;
      runScenario(text);
    }
  }, [request]);

  return {
    baseline,
    values,
    setValues,
    parseIntervention,
    simulation,
    persistSimulation,
    scenarioResult,
    interpretationMessage,
    lastParse,
    preview,
    request,
    runScenario,
    runStrategyOption,
    strategyRunning: strategyChanges.isPending,
    pricedOption,
    assumptions,
  };
}

function planWeeklyHours(plan: WhatIfPlan) {
  return plan.effortHours * 7 + plan.cadence * 0.25;
}

export type { WhatIfResult, WhatIfBaselineState, TuneValues };
