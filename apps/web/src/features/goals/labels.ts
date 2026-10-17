import type { ForecastStatus, Goal } from "../../api/client";

const GOAL_TYPE_LABELS: Record<Goal["goal_type"], string> = {
  deadline_event: "Deadline event",
  threshold: "Threshold",
  continuous_target: "Continuous target",
  habit: "Habit",
  multi_outcome: "Multi outcome",
};

const STATUS_LABELS: Record<ForecastStatus, string> = {
  EXPLORATORY: "Exploratory",
  ANCHORED: "Anchored",
  CALIBRATED: "Calibrated",
};

export function goalTypeLabel(type: Goal["goal_type"]): string {
  return GOAL_TYPE_LABELS[type];
}

export function forecastStatusLabel(status: ForecastStatus): string {
  return STATUS_LABELS[status];
}

export function formatDeadline(iso: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso));
}

export function formatProbability(value: number): string {
  return new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 0 }).format(value);
}

export function formatChangePp(value: number): string {
  const formatted = new Intl.NumberFormat(undefined, {
    signDisplay: "exceptZero",
    maximumFractionDigits: 1,
    minimumFractionDigits: Number.isInteger(value) ? 0 : 1,
  }).format(value);
  return `${formatted} pp`;
}
