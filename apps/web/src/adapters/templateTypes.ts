/** Presentation types matching approved template @ d5b59ec — populated from API, never fixtures. */

export type ChartPoint = {
  timestamp: number;
  value: number;
};

export type MarketEvent = {
  id: string;
  label: string;
  impact: number | null;
  occurredAt: string;
  timestamp?: number;
  icon: "code" | "x" | "rocket" | "people" | "book";
};

export type ChartMarker = {
  timestamp: number;
  label: string;
};

export type Market = {
  id: string;
  title: string;
  category: string;
  meta: string;
  createdAt: number;
  deadlineAt: number;
  odds: number | null;
  todayReturn: number | null;
  totalReturn: number | null;
  events: MarketEvent[];
  history: ChartPoint[];
  historyUnavailable?: boolean;
  modelFamily?: string;
  modelExplanation?: string;
  unpricedReason?: string;
};

export type WhatIfMode = "impact" | "futures" | "compare" | "paths";
export type WhatIfView = "simple" | "deep";

export type WhatIfPlan = {
  effortHours: number;
  cadence: number;
  followThrough: number;
  durationWeeks: number;
};

export type OutcomePoint = {
  step: number;
  low: number;
  likely: number;
  high: number;
};

export type WhatIfPreview = {
  currentOdds: number | null;
  scenarioOdds: number | null;
  improvementPoints: number | null;
  possibleLow: number | null;
  possibleHigh: number | null;
  chanceHelps: number | null;
  weeklyHours: number;
  outcome: OutcomePoint[];
  tradeoff: string;
};

export type FutureOutcome = {
  id: string;
  label: string;
  probability: number | null;
  tone: "positive" | "neutral" | "negative";
};

export type CompareOption = {
  id: string;
  label: string;
  odds: number | null;
  downside: "Low" | "Medium" | "High";
  time: "Low" | "Medium" | "High";
  followThrough: number;
  sensitivity: "Low" | "Medium" | "High";
  note: string;
};

export type GoalPath = {
  id: string;
  label: string;
  odds: number | null;
  requirement: string;
  subpaths: string[];
};

export type DistributionBin = {
  lower: number;
  upper: number;
  mass: number;
};

export type SavedWhatIf = {
  id: string;
  marketId: string;
  mode: WhatIfMode;
  question: string;
  summary: string;
  plan?: WhatIfPlan;
  createdAt: number;
};
