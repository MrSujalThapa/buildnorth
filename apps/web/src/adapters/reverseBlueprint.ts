import type { ReverseBlueprint, ReverseBlueprintLeverChange } from "../api/client";
import type { PathStrategy } from "./simulations";

export type BlueprintStatus = "met" | "reachable" | "short";

export type BlueprintChangeView = {
  id: string;
  label: string;
  from: string;
  to: string;
  delta: string;
  effort: ReverseBlueprintLeverChange["effort"];
  effortLabel: string;
};

export type BlueprintAlternativeView = {
  id: string;
  label: string;
  odds: string;
  oddsValue: number;
  reaches: boolean;
  note: string | null;
  effortLabel: string;
};

export type BlueprintPlanActionView = {
  order: number;
  behavior: string;
  quantity: string;
  timeline: string;
  effort: ReverseBlueprintLeverChange["effort"];
  effortLabel: string;
  constraint: string;
  requiresEvidence: boolean;
};

export type BlueprintPlanItem =
  | { kind: "action"; action: BlueprintPlanActionView }
  | { kind: "change"; change: BlueprintChangeView }
  | { kind: "step"; text: string };

export type BlueprintView = {
  status: BlueprintStatus;
  statusLabel: string;
  headline: string;
  rationale: string;
  target: string;
  baseline: string;
  modeled: string | null;
  delta: string | null;
  deltaTone: "up" | "down" | "flat";
  changes: BlueprintChangeView[];
  /** Ordered plan: each lever change as a structured row, then the remaining steps as text. */
  plan: BlueprintPlanItem[];
  tradeoffs: string[];
  followThrough: string | null;
  plateau: { label: string; explanation: string } | null;
  alternatives: BlueprintAlternativeView[];
  tolerance: string;
  unpriced: { label: string; measurement: string }[];
  missing: string[];
  followThroughSource: string | null;
};

const EFFORT_LABELS: Record<ReverseBlueprintLeverChange["effort"], string> = {
  none: "No change",
  light: "Light lift",
  moderate: "Moderate lift",
  heavy: "Heavy lift",
};

function percent(probability: number): string {
  const points = probability * 100;
  const rounded = Math.abs(points - Math.round(points)) < 0.05 ? Math.round(points) : Math.round(points * 10) / 10;
  return `${rounded}%`;
}

function signedPoints(pp: number): string {
  const rounded = Math.round(pp);
  if (rounded === 0) return "±0 pp";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded)} pp`;
}

export function formatBlueprintValue(change: Pick<ReverseBlueprintLeverChange, "lever_id" | "unit">, value: number): string {
  const magnitude = Math.abs(value);
  const digits = magnitude >= 100 ? Math.round(magnitude).toLocaleString("en-US") : String(Math.round(magnitude * 10) / 10);
  const sign = value < 0 ? "−" : "";
  if (change.unit.startsWith("currency")) return `${sign}$${digits}/month`;
  if (change.lever_id === "weekly_application_rate") return `${sign}${digits}/week`;
  return `${sign}${digits} ${change.unit}`;
}

function changeView(change: ReverseBlueprintLeverChange): BlueprintChangeView {
  const sign = change.change > 0 ? "+" : change.change < 0 ? "−" : "±";
  return {
    id: change.lever_id,
    label: change.label,
    from: formatBlueprintValue(change, change.baseline_value),
    to: formatBlueprintValue(change, change.recommended_value),
    delta: `${sign}${formatBlueprintValue(change, Math.abs(change.change))}`,
    effort: change.effort,
    effortLabel: EFFORT_LABELS[change.effort],
  };
}

function statusOf(blueprint: ReverseBlueprint): BlueprintStatus {
  if (blueprint.already_satisfied) return "met";
  return blueprint.reachable ? "reachable" : "short";
}

function statusLabel(blueprint: ReverseBlueprint, status: BlueprintStatus): string {
  const target = percent(blueprint.target_probability);
  const modeled = blueprint.modeled_probability == null ? null : percent(blueprint.modeled_probability);
  const tolerance = blueprint.tolerance_pp;
  if (status === "met") return `Already at or above ${target}`;
  if (status === "reachable") {
    if (modeled && blueprint.modeled_probability! + 1e-9 < blueprint.target_probability) {
      return `Reaches ${modeled} (within ${tolerance} pp of ${target})`;
    }
    return `Reaches ${modeled ?? target}`;
  }
  const best = blueprint.modeled_probability ?? blueprint.baseline_probability;
  const gap = Math.max(0, Math.round((blueprint.target_probability - best) * 1000) / 10);
  return `${modeled ?? percent(best)} does not reach ${target} (${gap} pp short)`;
}

function heaviest(changes: ReverseBlueprintLeverChange[]): ReverseBlueprintLeverChange["effort"] {
  const order: ReverseBlueprintLeverChange["effort"][] = ["none", "light", "moderate", "heavy"];
  return changes.reduce<ReverseBlueprintLeverChange["effort"]>(
    (worst, item) => (order.indexOf(item.effort) > order.indexOf(worst) ? item.effort : worst),
    "none",
  );
}

export function toBlueprintView(blueprint: ReverseBlueprint): BlueprintView {
  const status = statusOf(blueprint);
  const delta = blueprint.delta_pp;
  const plateau = blueprint.plateau;
  const changes = blueprint.lever_changes.map(changeView);
  const actions = blueprint.plan_actions ?? [];
  const plan: BlueprintPlanItem[] = actions.length
    ? actions.map((item) => ({
        kind: "action" as const,
        action: {
          order: item.order,
          behavior: item.behavior,
          quantity: item.quantity_label,
          timeline: item.timeline,
          effort: item.effort,
          effortLabel: EFFORT_LABELS[item.effort],
          constraint: item.constraint,
          requiresEvidence: item.requires_evidence,
        },
      }))
    : [
        ...changes.map((change) => ({ kind: "change" as const, change })),
        ...blueprint.steps.slice(blueprint.lever_changes.length).map((text) => ({ kind: "step" as const, text })),
      ];
  return {
    status,
    statusLabel: statusLabel(blueprint, status),
    headline: blueprint.headline,
    rationale: blueprint.rationale,
    target: percent(blueprint.target_probability),
    baseline: percent(blueprint.baseline_probability),
    modeled: blueprint.modeled_probability == null ? null : percent(blueprint.modeled_probability),
    delta: delta == null || status === "met" ? null : signedPoints(delta),
    deltaTone: delta == null || Math.round(delta) === 0 ? "flat" : delta > 0 ? "up" : "down",
    changes,
    plan,
    tradeoffs: blueprint.tradeoffs,
    followThrough:
      blueprint.follow_through_probability == null || status === "met"
        ? null
        : `Assumes the change holds in ${percent(blueprint.follow_through_probability)} of futures`,
    plateau: plateau
      ? {
          label:
            plateau.cause === "lever_range"
              ? "Lever range runs out"
              : `Odds plateau near ${percent(plateau.plateau_probability)}`,
          explanation: plateau.explanation,
        }
      : null,
    alternatives: blueprint.alternatives.map((item) => ({
      id: item.id,
      label: item.label,
      odds: percent(item.modeled_probability),
      oddsValue: item.modeled_probability * 100,
      reaches: item.reaches_target,
      note: item.note,
      effortLabel: EFFORT_LABELS[heaviest(item.lever_changes)],
    })),
    tolerance: `within ${blueprint.tolerance_pp} pp`,
    unpriced: (blueprint.unpriced_recommendations ?? []).map((item) => ({
      label: item.label,
      measurement: item.measurement,
    })),
    missing: blueprint.missing_capabilities ?? [],
    followThroughSource: blueprint.follow_through_source ?? null,
  };
}

/** The blueprint a search result carries, if the API sent one. */
export function blueprintFromPaths(paths: PathStrategy[] | undefined): ReverseBlueprint | null {
  return paths?.find((path) => path.blueprint)?.blueprint ?? null;
}

/** A path for "See how this could play out", set at the blueprint's primary lever value. */
export function blueprintFuturesPath(blueprint: ReverseBlueprint): PathStrategy | null {
  const primary = blueprint.lever_changes[0];
  if (!primary || blueprint.modeled_probability == null) return null;
  const label = [
    ...blueprint.lever_changes.map((item) => `${item.label} at ${formatBlueprintValue(item, item.recommended_value)}`),
    ...blueprint.actions.map((item) => item.title),
  ].join(" + ");
  return {
    id: "blueprint",
    label,
    odds: blueprint.modeled_probability * 100,
    requirement: blueprint.rationale,
    subpaths: blueprint.actions.map((item) => item.title),
    cost: primary.recommended_value,
    fragility: "Medium",
    onFrontier: true,
    variants: [],
  };
}
