import type { CompareOption, GoalPath, Market } from "./templateTypes";

export const SIMULATION_SEED = 20260829;
export const SIMULATION_COUNT = 5000;

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

type ClusterSpec = {
  id: string;
  label: string;
  short: string;
  weight: number;
  tone: ClusterTone;
  cx: number;
  cy: number;
  sx: number;
  sy: number;
  goalRate: number;
};

function mulberry32(seed: number) {
  let t = seed >>> 0;
  return () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(rand: () => number) {
  const u = Math.max(rand(), 1e-9);
  const v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function pickWeighted(rand: () => number, specs: ClusterSpec[]) {
  const total = specs.reduce((sum, spec) => sum + spec.weight, 0);
  let cursor = rand() * total;
  for (const spec of specs) {
    cursor -= spec.weight;
    if (cursor <= 0) {
      return spec;
    }
  }
  return specs[specs.length - 1];
}

function clusterSpecsForMarket(market: Market): ClusterSpec[] {
  if (market.category === "Startup") {
    return [
      { id: "fail-pre", label: "Fail before funding", short: "Fail early", weight: 28, tone: "negative", cx: 18, cy: 7, sx: 7, sy: 2.4, goalRate: 0.02 },
      { id: "raise-fail", label: "Raise, then fail", short: "Raise then fail", weight: 18, tone: "negative", cx: 34, cy: 18, sx: 8, sy: 4, goalRate: 0.08 },
      { id: "bootstrap", label: "Bootstrap into a sustainable business", short: "Bootstrap", weight: 22, tone: "positive", cx: 58, cy: 22, sx: 9, sy: 5, goalRate: 0.71 },
      { id: "raise-win", label: "Raise and reach meaningful success", short: "Raise + success", weight: 14, tone: "positive", cx: 82, cy: 28, sx: 8, sy: 6, goalRate: 0.94 },
      { id: "return-job", label: "Return to employment", short: "Return to a job", weight: 14, tone: "neutral", cx: 41, cy: 14, sx: 8, sy: 3.2, goalRate: 0.12 },
      { id: "other", label: "Other", short: "Other", weight: 4, tone: "neutral", cx: 50, cy: 20, sx: 18, sy: 10, goalRate: 0.35 },
    ];
  }

  if (market.category === "Career") {
    return [
      { id: "fde", label: "Land an FDE / applied AI offer", short: "FDE offer", weight: 32, tone: "positive", cx: 9, cy: 78, sx: 3.2, sy: 8, goalRate: 1 },
      { id: "swe", label: "Land a Big Tech SWE offer", short: "SWE offer", weight: 22, tone: "positive", cx: 11, cy: 86, sx: 3, sy: 6, goalRate: 1 },
      { id: "late", label: "Offer arrives later than planned", short: "Late offer", weight: 20, tone: "neutral", cx: 18, cy: 62, sx: 4, sy: 8, goalRate: 0.55 },
      { id: "none", label: "No offer before the deadline", short: "No offer", weight: 22, tone: "negative", cx: 22, cy: 28, sx: 5, sy: 9, goalRate: 0 },
      { id: "other", label: "Other", short: "Other", weight: 4, tone: "neutral", cx: 14, cy: 50, sx: 8, sy: 16, goalRate: 0.4 },
    ];
  }

  return [
    { id: "strong", label: "Strong outcome", short: "Strong", weight: 28, tone: "positive", cx: 78, cy: 18, sx: 8, sy: 6, goalRate: 0.92 },
    { id: "expected", label: "Expected outcome", short: "Expected", weight: 38, tone: "neutral", cx: 54, cy: 16, sx: 9, sy: 5, goalRate: 0.48 },
    { id: "mixed", label: "Mixed outcome", short: "Mixed", weight: 22, tone: "neutral", cx: 38, cy: 22, sx: 8, sy: 6, goalRate: 0.22 },
    { id: "weak", label: "Weak outcome", short: "Weak", weight: 12, tone: "negative", cx: 18, cy: 14, sx: 7, sy: 5, goalRate: 0.04 },
  ];
}

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

export function impactAxes(): { x: AxisSpec; y: AxisSpec; layout: CloudLayout } {
  return {
    layout: "beeswarm",
    x: {
      label: "Resulting odds",
      format: (value) => `${value.toFixed(0)}%`,
      min: 20,
      max: 92,
    },
    y: {
      label: "Likelihood",
      format: () => "",
      min: 0,
      max: 1,
    },
  };
}

export function compareAxes(market: Market): { x: AxisSpec; y: AxisSpec; layout: CloudLayout } {
  if (market.category === "Career") {
    return {
      layout: "scatter",
      x: {
        label: "Months to an offer",
        format: (value) => `${value.toFixed(1)} mo`,
        min: 2,
        max: 24,
      },
      y: {
        label: "Offer strength",
        format: (value) => `${Math.round(value)}`,
        min: 20,
        max: 100,
      },
    };
  }

  return {
    layout: "scatter",
    x: {
      label: "Ending outcome",
      format: (value) => `${Math.round(value)}%`,
      min: 8,
      max: 100,
    },
    y: {
      label: "Peak drawdown",
      format: (value) => `${Math.round(value)}%`,
      min: 4,
      max: 70,
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

function applyBeeswarm(points: SimulationPoint[], xMin: number, xMax: number) {
  const bins = 42;
  const buckets: SimulationPoint[][] = Array.from({ length: bins }, () => []);
  for (const point of points) {
    const ratio = (point.x - xMin) / Math.max(xMax - xMin, 1);
    const bin = clamp(Math.floor(ratio * bins), 0, bins - 1);
    buckets[bin]!.push(point);
  }

  buckets.forEach((bucket) => {
    bucket.sort((a, b) => a.id - b.id);
    const mid = (bucket.length - 1) / 2;
    bucket.forEach((point, index) => {
      const spread = Math.min(0.46, 0.04 + bucket.length / 140);
      point.y = 0.5 + ((index - mid) / Math.max(bucket.length, 1)) * spread * 2;
    });
  });
}

export function buildFutureSimulations(market: Market): {
  points: SimulationPoint[];
  clusters: SimulationCluster[];
} {
  const rand = mulberry32(SIMULATION_SEED + market.id.length * 17);
  const specs = clusterSpecsForMarket(market);
  const axes = futuresAxes(market);
  const points: SimulationPoint[] = [];

  for (let index = 0; index < SIMULATION_COUNT; index += 1) {
    const spec = pickWeighted(rand, specs)!;
    const x = clamp(spec.cx + gaussian(rand) * spec.sx, axes.x.min, axes.x.max);
    const y = clamp(spec.cy + gaussian(rand) * spec.sy, axes.y.min, axes.y.max);
    const goalHit = rand() < spec.goalRate;
    points.push({
      id: index + 1,
      x,
      y,
      clusterId: spec.id,
      goalHit,
      seed: Math.floor(rand() * 1_000_000),
    });
  }

  if (axes.layout === "beeswarm") {
    applyBeeswarm(points, axes.x.min, axes.x.max);
  }

  const clusters = specs.map((spec) => {
    const members = points.filter((point) => point.clusterId === spec.id);
    return {
      id: spec.id,
      label: spec.label,
      short: spec.short,
      probability: Math.round((members.length / points.length) * 100),
      tone: spec.tone,
      goalRate: members.filter((point) => point.goalHit).length / Math.max(members.length, 1),
    };
  });

  return { points, clusters };
}

export function buildImpactSimulations(currentOdds: number, scenarioOdds: number): SimulationPoint[] {
  const rand = mulberry32(SIMULATION_SEED + Math.round(scenarioOdds * 10));
  const points: SimulationPoint[] = [];

  for (let index = 0; index < SIMULATION_COUNT; index += 1) {
    const mix = rand();
    const center = mix < 0.18 ? currentOdds : mix > 0.82 ? scenarioOdds + 6 : scenarioOdds;
    const x = clamp(center + gaussian(rand) * (mix > 0.9 ? 9 : 4.2), 18, 94);
    points.push({
      id: index + 1,
      x,
      y: 0.5,
      clusterId: x >= scenarioOdds - 2 ? "helps" : "baseline",
      goalHit: x >= 70,
      seed: Math.floor(rand() * 1_000_000),
    });
  }

  applyBeeswarm(points, 18, 94);
  return points;
}

export function buildCompareSimulations(
  _market: Market,
  options: CompareOption[],
): SimulationPoint[] {
  const points: SimulationPoint[] = [];
  const perOption = SIMULATION_COUNT;

  options.forEach((option, optionIndex) => {
    const rand = mulberry32(SIMULATION_SEED + optionIndex * 97 + option.label.length);
    const odds = option.odds ?? 48;
    const spread = option.downside === "High" ? 9 : option.downside === "Medium" ? 7 : 5;

    for (let index = 0; index < perOption; index += 1) {
      points.push({
        id: points.length + 1,
        x: clamp(odds + gaussian(rand) * spread, 0, 100),
        y: clamp(0.5 + gaussian(rand) * 0.16, 0.04, 0.96),
        clusterId: option.id,
        optionId: option.id,
        goalHit: rand() < odds / 100,
        seed: Math.floor(rand() * 1_000_000),
      });
    }
  });

  return points;
}

export function buildPathSimulations(path: PathStrategy): SimulationPoint[] {
  const rand = mulberry32(SIMULATION_SEED + path.label.length * 13);
  const odds = path.odds ?? 50;
  const points: SimulationPoint[] = [];

  for (let index = 0; index < SIMULATION_COUNT; index += 1) {
    const x = clamp(18 + odds * 0.7 + gaussian(rand) * 8, 4, 100);
    points.push({
      id: index + 1,
      x,
      y: 0.5,
      clusterId: path.id,
      pathId: path.id,
      goalHit: rand() < odds / 100,
      seed: Math.floor(rand() * 1_000_000),
    });
  }

  applyBeeswarm(points, 4, 100);
  return points;
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

export function pathsForFrontier(market: Market): PathStrategy[] {
  const base = market.odds ?? 45;

  if (market.category === "Career") {
    return [
      {
        id: "fde",
        label: "FDE at an AI startup",
        odds: clamp(base + 9, 1, 97),
        requirement: "Applied AI projects and targeted founder outreach",
        subpaths: ["Early-stage startup", "Growth-stage startup", "Implementation FDE"],
        cost: 58,
        fragility: "Medium",
        onFrontier: true,
        variants: [
          { id: "fde-early", label: "Early-stage", odds: clamp(base + 8, 1, 97), cost: 62 },
          { id: "fde-growth", label: "Growth-stage", odds: clamp(base + 11, 1, 97), cost: 54 },
          { id: "fde-impl", label: "Implementation", odds: clamp(base + 7, 1, 97), cost: 49 },
        ],
      },
      {
        id: "applied-ai",
        label: "Applied AI engineer",
        odds: clamp(base + 6, 1, 97),
        requirement: "Agent systems depth and production integrations",
        subpaths: ["Agents", "AI platform", "Customer implementation"],
        cost: 64,
        fragility: "Medium",
        onFrontier: true,
        variants: [
          { id: "agents", label: "Agents / orchestration", odds: clamp(base + 7, 1, 97), cost: 68 },
          { id: "platform", label: "AI platform", odds: clamp(base + 5, 1, 97), cost: 71 },
        ],
      },
      {
        id: "big-tech",
        label: "Big Tech SWE",
        odds: clamp(base - 1, 1, 97),
        requirement: "Interview volume and stronger DSA consistency",
        subpaths: ["General SWE", "AI infrastructure", "Developer platform"],
        cost: 78,
        fragility: "High",
        onFrontier: false,
        variants: [
          { id: "swe-general", label: "General SWE", odds: clamp(base - 2, 1, 97), cost: 76 },
          { id: "swe-infra", label: "AI infrastructure", odds: clamp(base + 1, 1, 97), cost: 82 },
        ],
      },
      {
        id: "founding",
        label: "Founding engineer",
        odds: clamp(base - 5, 1, 97),
        requirement: "High-trust network and shipping evidence",
        subpaths: ["Funded seed", "Founder network", "Convert project traction"],
        cost: 86,
        fragility: "High",
        onFrontier: false,
        variants: [
          { id: "seed", label: "Join a funded seed", odds: clamp(base - 3, 1, 97), cost: 84 },
          { id: "network", label: "Founder network", odds: clamp(base - 6, 1, 97), cost: 72 },
        ],
      },
      {
        id: "startup-swe",
        label: "Startup SWE, later FDE",
        odds: clamp(base + 3, 1, 97),
        requirement: "Ship in production, then convert into customer-facing AI work",
        subpaths: ["Product SWE", "Forward-deployed rotation"],
        cost: 47,
        fragility: "Low",
        onFrontier: true,
        variants: [
          { id: "rotate", label: "Internal rotation", odds: clamp(base + 4, 1, 97), cost: 44 },
        ],
      },
    ];
  }

  if (market.category === "Startup") {
    return [
      {
        id: "corporate-save",
        label: "Keep the job, save aggressively",
        odds: clamp(base - 8, 1, 97),
        requirement: "High savings rate, slower product progress",
        subpaths: ["Nights and weekends", "Deferred leave"],
        cost: 28,
        fragility: "Low",
        onFrontier: true,
        variants: [
          { id: "nights", label: "Nights and weekends", odds: clamp(base - 10, 1, 97), cost: 24 },
          { id: "leave", label: "Deferred leave", odds: clamp(base - 4, 1, 97), cost: 36 },
        ],
      },
      {
        id: "own-startup",
        label: "Own startup, full-time",
        odds: clamp(base + 7, 1, 97),
        requirement: "Runway and full attention",
        subpaths: ["VC-backed", "Bootstrap", "Part-time then full-time"],
        cost: 74,
        fragility: "High",
        onFrontier: true,
        variants: [
          { id: "vc", label: "VC-backed", odds: clamp(base + 9, 1, 97), cost: 82 },
          { id: "boot", label: "Bootstrap", odds: clamp(base + 4, 1, 97), cost: 61 },
          { id: "ptft", label: "Part-time → full-time", odds: clamp(base + 2, 1, 97), cost: 48 },
        ],
      },
      {
        id: "early-equity",
        label: "Join an early startup for equity",
        odds: clamp(base + 3, 1, 97),
        requirement: "Compensation trade for ownership",
        subpaths: ["Seed", "Series A"],
        cost: 52,
        fragility: "Medium",
        onFrontier: true,
        variants: [
          { id: "seed-join", label: "Seed join", odds: clamp(base + 1, 1, 97), cost: 58 },
          { id: "a-join", label: "Series A join", odds: clamp(base + 5, 1, 97), cost: 46 },
        ],
      },
      {
        id: "career-invest",
        label: "High-income career plus investing",
        odds: clamp(base - 2, 1, 97),
        requirement: "Stable income, lower operational control",
        subpaths: ["Index-heavy", "Angel checks"],
        cost: 41,
        fragility: "Low",
        onFrontier: false,
        variants: [
          { id: "index", label: "Index-heavy", odds: clamp(base - 3, 1, 97), cost: 34 },
        ],
      },
    ];
  }

  return [
    {
      id: "consistent",
      label: "Consistent execution",
      odds: clamp(base + 7, 1, 97),
      requirement: "Repeatable weekly cadence",
      subpaths: ["Daily routine", "Weekly milestones"],
      cost: 36,
      fragility: "Low",
      onFrontier: true,
      variants: [{ id: "daily", label: "Daily routine", odds: clamp(base + 6, 1, 97), cost: 32 }],
    },
    {
      id: "sprint",
      label: "Focused sprint",
      odds: clamp(base + 10, 1, 97),
      requirement: "Higher short-term resource commitment",
      subpaths: ["4-week sprint", "8-week sprint"],
      cost: 68,
      fragility: "Medium",
      onFrontier: true,
      variants: [{ id: "eight", label: "8-week sprint", odds: clamp(base + 11, 1, 97), cost: 74 }],
    },
    {
      id: "support",
      label: "Add external support",
      odds: clamp(base + 5, 1, 97),
      requirement: "Mentor, coach, or stronger environment",
      subpaths: ["Mentorship", "Peer group"],
      cost: 44,
      fragility: "Low",
      onFrontier: true,
      variants: [{ id: "mentor", label: "Mentorship", odds: clamp(base + 6, 1, 97), cost: 48 }],
    },
  ];
}

export function optionCatalog(market: Market): CompareOption[] {
  const base = market.odds ?? 48;

  if (market.category === "Career") {
    return [
      {
        id: "fde-heavy",
        label: "FDE-heavy job search",
        odds: clamp(base + 9, 1, 97),
        downside: "Medium",
        time: "High",
        followThrough: 81,
        sensitivity: "Medium",
        note: "Concentrate on applied AI and customer-facing engineering roles.",
      },
      {
        id: "big-tech-heavy",
        label: "Big Tech-heavy job search",
        odds: clamp(base - 2, 1, 97),
        downside: "High",
        time: "High",
        followThrough: 76,
        sensitivity: "High",
        note: "Narrow the funnel and invest more in interview-specific prep.",
      },
      {
        id: "balanced",
        label: "Balanced search",
        odds: clamp(base + 5, 1, 97),
        downside: "Medium",
        time: "Medium",
        followThrough: 88,
        sensitivity: "Low",
        note: "Mix FDE, startup, and Big Tech while keeping prep steady.",
      },
      {
        id: "startup-only",
        label: "Startup-only search",
        odds: clamp(base + 3, 1, 97),
        downside: "Medium",
        time: "Medium",
        followThrough: 84,
        sensitivity: "Medium",
        note: "Prioritize shipping evidence and founder conversations.",
      },
    ];
  }

  if (market.category === "Startup") {
    return [
      {
        id: "quit",
        label: "Quit and build full-time",
        odds: clamp(base + 8, 1, 97),
        downside: "High",
        time: "High",
        followThrough: 71,
        sensitivity: "High",
        note: "Maximum focus, shortest runway.",
      },
      {
        id: "evenings",
        label: "Keep the internship, build nights",
        odds: clamp(base - 3, 1, 97),
        downside: "Low",
        time: "Medium",
        followThrough: 86,
        sensitivity: "Low",
        note: "Safer income, slower product progress.",
      },
      {
        id: "part-time",
        label: "Drop to part-time, then go full-time",
        odds: clamp(base + 4, 1, 97),
        downside: "Medium",
        time: "Medium",
        followThrough: 79,
        sensitivity: "Medium",
        note: "A staged transition with a defined review point.",
      },
    ];
  }

  return [
    {
      id: "steady",
      label: "Steady plan",
      odds: clamp(base + 4, 1, 97),
      downside: "Low",
      time: "Medium",
      followThrough: 91,
      sensitivity: "Low",
      note: "Keep the plan sustainable and repeatable.",
    },
    {
      id: "focused",
      label: "Focused push",
      odds: clamp(base + 8, 1, 97),
      downside: "Medium",
      time: "High",
      followThrough: 79,
      sensitivity: "Medium",
      note: "Trade more time for faster progress.",
    },
    {
      id: "aggressive",
      label: "Aggressive bet",
      odds: clamp(base + 11, 1, 97),
      downside: "High",
      time: "High",
      followThrough: 67,
      sensitivity: "High",
      note: "Highest upside, heaviest execution risk.",
    },
  ];
}

export function impactNarrative(point: SimulationPoint, formatX: (value: number) => string): SimulationNarrative {
  return {
    headline: `In this draw the plan prices at ${formatX(point.x)}.`,
    timeline: [
      { month: 2, event: "The stated plan is in motion" },
      { month: 8, event: point.goalHit ? "Goal odds stay in a successful band" : "Goal odds remain below the 70% target band" },
    ],
    assumptions: [
      "Follow-through stays near the stated percentage",
      "No multi-week pause in the plan",
      "The baseline market does not reprice from unrelated news",
    ],
    events: [
      point.goalHit ? "Execution holds through the horizon" : "Follow-through slips in the second half",
      "This is one Monte Carlo draw, not a predicted path",
    ],
    goalAchieved: point.goalHit,
    outcomeValue: formatX(point.x),
  };
}

export function narrativeFor(
  market: Market,
  point: SimulationPoint,
  clusters: SimulationCluster[],
  axes: { x: AxisSpec; y: AxisSpec },
): SimulationNarrative {
  const cluster = clusters.find((item) => item.id === point.clusterId);
  const rand = mulberry32(point.seed + 11);
  const month = (offset: number) => Math.max(1, Math.round(offset + rand() * 2));

  if (market.category === "Startup") {
    const valuation = Math.max(40, Math.round(point.x * 32));
    const headlines: Record<string, string> = {
      "fail-pre": `The company winds down before a raise. Personal net worth around $${valuation}k.`,
      "raise-fail": `A pre-seed happens, then the company fails. Ending position around $${valuation}k.`,
      bootstrap: `The company reaches a sustainable business. Ending net worth around $${valuation}k.`,
      "raise-win": `The company raises and reaches a $${(valuation / 10).toFixed(1)}M-scale outcome.`,
      "return-job": `The founder returns to employment. Ending net worth around $${valuation}k.`,
      other: `An uncommon path. Ending net worth around $${valuation}k.`,
    };

    return {
      headline: headlines[point.clusterId] ?? cluster?.label ?? "A sampled future",
      timeline: [
        { month: month(1), event: "Leaves the internship and starts full-time on the company" },
        { month: month(5), event: point.clusterId.includes("raise") ? "Raises a pre-seed" : "Ships the first paying workflow" },
        { month: month(12), event: point.goalHit ? "Revenue becomes repeatable" : "Growth stalls and runway tightens" },
        { month: month(18), event: point.clusterId === "return-job" ? "Accepts an engineering offer" : "Reaches the sampled terminal state" },
      ],
      assumptions: [
        "Runway lasts at least 10 months",
        "The founder does not take a second full-time job in year one",
        "Customer conversations continue weekly",
      ],
      events: [
        point.clusterId.includes("raise") ? "A seed investor says yes on the second attempt" : "No institutional round closes",
        point.goalHit ? "A design partner converts to paid" : "A key design partner churns",
      ],
      goalAchieved: point.goalHit,
      outcomeValue: axes.x.format(point.x),
    };
  }

  if (market.category === "Career") {
    const headlines: Record<string, string> = {
      fde: "An FDE / applied AI offer arrives before the deadline.",
      swe: "A Big Tech SWE offer arrives before the deadline.",
      late: "An offer arrives, but later than the planned window.",
      none: "No offer lands before the deadline.",
      other: "An uncommon career path in this sample.",
    };

    return {
      headline: headlines[point.clusterId] ?? cluster?.label ?? "A sampled future",
      timeline: [
        { month: month(1), event: "Search concentrates on the chosen role family" },
        { month: month(3), event: "Interview loop volume increases" },
        { month: Math.min(24, Math.max(3, Math.round(point.x))), event: point.goalHit ? "Offer is signed" : "The search is still open at the deadline" },
      ],
      assumptions: [
        "Weekly application cadence holds",
        "Interview prep stays above 6 hours a week",
        "No multi-month pause in the search",
      ],
      events: [
        point.goalHit ? "A hiring manager champions the loop" : "Two late-stage loops stall",
        `Offer quality in this draw: ${axes.y.format(point.y)}`,
      ],
      goalAchieved: point.goalHit,
      outcomeValue: axes.x.format(point.x),
    };
  }

  return {
    headline: cluster?.label ?? "A sampled future",
    timeline: [
      { month: month(2), event: "The plan is underway" },
      { month: month(8), event: point.goalHit ? "The sampled path reaches the goal" : "The sampled path misses the goal" },
    ],
    assumptions: ["Follow-through stays near the stated plan"],
    events: ["External conditions stay within the historical band used for this fixture"],
    goalAchieved: point.goalHit,
    outcomeValue: axes.x.format(point.x),
  };
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
