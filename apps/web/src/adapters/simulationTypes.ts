/** Presentation types for SimulationCloud / ProbabilityDistribution — no fixture generators. */

export type ClusterTone = "positive" | "neutral" | "negative";

export type SimulationCluster = {
  id: string;
  label: string;
  short: string;
  probability: number;
  tone: ClusterTone;
  goalRate: number;
};

export type SimulationPoint = {
  id: number;
  x: number;
  y: number;
  clusterId: string;
  optionId?: string;
  pathId?: string;
  goalHit: boolean;
  seed: number;
};

export type AxisSpec = {
  label: string;
  unit?: string;
  format: (value: number) => string;
  min: number;
  max: number;
};

export type CloudLayout = "scatter" | "beeswarm";

export type RepresentativeKind = "likely" | "upside" | "downside";

export type RepresentativePoint = {
  kind: RepresentativeKind;
  label: string;
  point: SimulationPoint;
};

export type SimulationNarrative = {
  headline: string;
  timeline: Array<{ month: number; event: string }>;
  assumptions: string[];
  events: string[];
  goalAchieved: boolean;
  outcomeValue: string;
};

export type PathStrategy = {
  id: string;
  label: string;
  odds: number | null;
  requirement: string;
  subpaths: string[];
  cost: number;
  fragility: "Low" | "Medium" | "High";
  onFrontier: boolean;
  variants: Array<{ id: string; label: string; odds: number; cost: number }>;
};

export const DEFAULT_IMPACT_AXES = {
  x: {
    label: "Resulting odds",
    format: (value: number) => `${value.toFixed(0)}%`,
    min: 0,
    max: 100,
  },
  y: {
    label: "Execution",
    format: (value: number) => `${value.toFixed(0)}%`,
    min: 0,
    max: 100,
  },
} satisfies { x: AxisSpec; y: AxisSpec };
