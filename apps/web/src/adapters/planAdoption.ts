import type {
  AdoptPlanBody,
  CommitmentObservation,
  ParsedInterventionChange,
  PlannedCommitment,
  StrategyChangesResponse,
  WhatIfResult,
} from "../api/client";

const DAY_MS = 86_400_000;
const WEEKS_PER_MONTH = 52 / 12;
const MAX_ACTION = 160;
const MAX_UNIT = 40;
const MAX_DOMAIN = 80;

type Period = "day" | "week" | "month";

function periodOf(change: ParsedInterventionChange): Period {
  const stated = (change.frequency ?? change.unit.split("/").pop() ?? "").trim().toLowerCase();
  if (stated.startsWith("d")) return "day";
  if (stated.startsWith("m")) return "month";
  return "week";
}

function unitNoun(change: ParsedInterventionChange) {
  const noun = (change.unit.split("/")[0] ?? "").replace(/_/g, " ").replace(/\s+count$/, "").trim();
  return (noun === "currency" ? "dollars" : noun || "units").slice(0, MAX_UNIT);
}

function actionText(title: string) {
  const action = title.trim().replace(/^what\s*if\s*(i\s+)?/i, "").replace(/\?$/, "");
  const text = action ? `${action.charAt(0).toUpperCase()}${action.slice(1)}` : "Planned change";
  return text.slice(0, MAX_ACTION);
}

export type PlanDraft = {
  body: AdoptPlanBody;
  summary: string;
  decrease: boolean;
};

/** Turns a priced What If into a plan to store. Returns null when nothing was priced. */
export function draftPlan(args: {
  priced: StrategyChangesResponse | null;
  result: WhatIfResult | undefined;
  domain: string;
  durationWeeks: number;
  start: Date;
}): PlanDraft | null {
  const { priced, result } = args;
  const lead = priced?.changes.find((item) => item.operation !== "set");
  if (!priced || !lead || !result?.priced || result.scenario_probability == null) return null;
  const period = periodOf(lead);
  const weeks = Math.max(1, Math.round(args.durationWeeks));
  const periods = period === "month" ? Math.max(1, Math.round(weeks / WEEKS_PER_MONTH)) : period === "day" ? weeks * 7 : weeks;
  const perPeriod = Math.abs(lead.value);
  const decrease = lead.operation === "subtract";
  const end = new Date(args.start.getTime() + weeks * 7 * DAY_MS);
  const noun = unitNoun(lead);
  return {
    decrease,
    summary: `${decrease ? "−" : "+"}${formatQuantity(perPeriod)} ${noun} per ${period} for ${periods} ${period}${periods === 1 ? "" : "s"}`,
    body: {
      domain: (args.domain || "general").slice(0, MAX_DOMAIN),
      action: actionText(priced.title),
      planned_quantity: perPeriod * periods,
      unit: noun,
      window_start: args.start.toISOString(),
      window_end: end.toISOString(),
      plan_context: {
        title: priced.title.slice(0, 240),
        option_id: priced.option_id,
        proxy: priced.proxy,
        changes: priced.changes.map(({ metric, operation, value, unit, frequency }) => ({ metric, operation, value, unit, frequency })),
        quantity_per_period: perPeriod,
        period,
        duration_periods: periods,
        baseline_probability: result.baseline_probability ?? null,
        scenario_probability: result.scenario_probability ?? null,
        execution_probability: result.execution_probability ?? null,
        assumptions_used: priced.assumptions_used.slice(0, 6),
        priced_at: new Date().toISOString(),
      },
    },
  };
}

export type PlanState = "planned" | "active" | "due" | "completed" | "partial" | "missed" | "abandoned";

export const PLAN_STATE_LABEL: Record<PlanState, string> = {
  planned: "Planned",
  active: "In progress",
  due: "Check in",
  completed: "Completed",
  partial: "Partly done",
  missed: "Missed",
  abandoned: "Abandoned",
};

export function latestObservation(plan: PlannedCommitment, observations: CommitmentObservation[]) {
  return observations
    .filter((item) => item.commitment_id === plan.id)
    .reduce<CommitmentObservation | null>((latest, item) => (!latest || item.version > latest.version ? item : latest), null);
}

export function planState(plan: PlannedCommitment, observations: CommitmentObservation[], now: Date): PlanState {
  const latest = latestObservation(plan, observations);
  if (latest && latest.status !== "unknown") {
    return latest.status === "cancelled" ? "abandoned" : latest.status;
  }
  const time = now.getTime();
  if (time < new Date(plan.window_start).getTime()) return "planned";
  if (time > new Date(plan.window_end).getTime()) return "due";
  return "active";
}

export function isOpen(state: PlanState) {
  return state === "planned" || state === "active" || state === "due";
}

/** Outcome for a check-in: the reported total against the planned total. */
export function outcomeFor(plan: PlannedCommitment, actual: number) {
  if (!(actual > 0)) return { status: "missed" as const, actual_quantity: 0 };
  if (actual >= plan.planned_quantity) return { status: "completed" as const, actual_quantity: actual };
  return { status: "partial" as const, actual_quantity: actual };
}

export function formatQuantity(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}
