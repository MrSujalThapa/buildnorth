import type { ReverseBlueprint } from "../api/client";
import type { GoalPath, Market } from "./templateTypes";

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

export type PathStrategy = GoalPath & {
  cost: number;
  fragility: "Low" | "Medium" | "High";
  onFrontier: boolean;
  variants: Array<{
    id: string;
    label: string;
    odds: number;
    cost: number;
  }>;
  /** Reverse search blueprint, carried on the first path of a search result. */
  blueprint?: ReverseBlueprint | null;
};

export function pathAxes(market?: Market): { x: AxisSpec; y: AxisSpec } {
  return {
    x: {
      label: market?.category === "Startup" ? "Runway & hours/week" : market?.category === "Career" ? "Hours/week" : "Weekly effort",
      format: (value) => market?.category === "Career" ? `${Math.round(value / 4)} hrs/wk` : `${Math.round(value)}`,
      min: 8,
      max: 96,
    },
    y: {
      label: "Chance of reaching the goal",
      format: (value) => `${Math.round(value)}%`,
      min: 20,
      max: 92,
    },
  };
}

