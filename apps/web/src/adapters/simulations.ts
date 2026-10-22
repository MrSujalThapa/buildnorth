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
};

export function futuresAxes(market: Market): { x: AxisSpec; y: AxisSpec; layout: CloudLayout } {
  if (market.category === "Startup") {
    return {
      layout: "scatter",
      x: {
        label: "Ending net worth",
        format: (value) => `$${Math.round(value * 32)}k`,
        min: 0,
        max: 100,
      },
      y: {
        label: "Months to resolution",
        unit: "mo",
        format: (value) => `${Math.round(value)} mo`,
        min: 2,
        max: 42,
      },
    };
  }

  if (market.category === "Career") {
    return {
      layout: "scatter",
      x: {
        label: "Months to resolution",
        unit: "mo",
        format: (value) => `${value.toFixed(1)} mo`,
        min: 1,
        max: 28,
      },
      y: {
        label: "Offer strength",
        format: (value) => `${Math.round(value)}`,
        min: 8,
        max: 100,
      },
    };
  }

  return {
    layout: "beeswarm",
    x: {
      label: "Goal progress",
      format: (value) => `${Math.round(value)}%`,
      min: 0,
      max: 100,
    },
    y: {
      label: "Likelihood",
      format: () => "",
      min: 0,
      max: 1,
    },
  };
}

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

export function representativesFor(points: SimulationPoint[]): RepresentativePoint[] {
  if (!points.length) {
    return [];
  }

  const sorted = [...points].sort((a, b) => a.x - b.x);
  const at = (ratio: number) =>
    sorted[Math.min(sorted.length - 1, Math.floor(ratio * (sorted.length - 1)))] ?? sorted[0]!;

  return [
    { kind: "downside", label: "Important downside", point: at(0.1) },
    { kind: "likely", label: "Most likely", point: at(0.5) },
    { kind: "upside", label: "Strong upside", point: at(0.9) },
  ];
}

export function clusterCentroids(points: SimulationPoint[], clusters: SimulationCluster[]) {
  return clusters
    .map((cluster) => {
      const members = points.filter((point) => point.clusterId === cluster.id);
      if (!members.length) {
        return null;
      }
      const x = members.reduce((sum, point) => sum + point.x, 0) / members.length;
      const y = members.reduce((sum, point) => sum + point.y, 0) / members.length;
      return { ...cluster, x, y, count: members.length };
    })
    .filter((item): item is SimulationCluster & { x: number; y: number; count: number } => item !== null)
    .sort((a, b) => b.count - a.count);
}

export function distributionStats(points: SimulationPoint[]) {
  if (!points.length) {
    return { p10: 0, p50: 0, p90: 0, goalRate: 0 };
  }

  const sorted = [...points].sort((a, b) => a.x - b.x);
  const at = (ratio: number) =>
    sorted[Math.min(sorted.length - 1, Math.floor(ratio * (sorted.length - 1)))]?.x ?? 0;
  return {
    p10: at(0.1),
    p50: at(0.5),
    p90: at(0.9),
    goalRate: points.filter((point) => point.goalHit).length / points.length,
  };
}
