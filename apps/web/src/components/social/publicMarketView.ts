import type { PublicBlueprint, PublicMarketDetail, PublicMarketUpdate } from "../../api/client";

const longDate = new Intl.DateTimeFormat("en", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
const shortDate = new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

const COMPARISONS: Record<string, string> = {
  ">=": "At least", gte: "At least", at_least: "At least",
  ">": "More than", gt: "More than",
  "<=": "At most", lte: "At most", at_most: "At most",
  "<": "Less than", lt: "Less than",
  "==": "Exactly", "=": "Exactly", eq: "Exactly",
};

const TARGET_KEYS = ["target", "target_value", "threshold", "value", "amount", "seconds"] as const;
const HIDDEN_KEYS = new Set(["milestones", "strategy", "description", "metric", "operator", "unit", ...TARGET_KEYS]);

const OTHER_LABELS: Record<string, string> = {
  event: "Outcome", success_event: "Outcome", window: "Window", criteria: "Criteria", habit: "Habit", direction: "Direction",
};

export type CriteriaRow = { key: string; label: string; value: string };

export type PublicMarketStats = {
  latestOdds: number | null;
  changePoints: number | null;
  updates: number;
  stars: number;
  forks: number;
  targetDate: string | null;
};

export function formatLongDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? longDate.format(parsed) : null;
}

export function formatShortDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? shortDate.format(parsed) : null;
}

function humanize(value: string): string {
  const spaced = value.replaceAll("_", " ").trim();
  return spaced.replace(/^./, (first) => first.toUpperCase());
}

function valueText(value: unknown): string | null {
  if (typeof value === "string") return value.trim() ? value.replaceAll("_", " ") : null;
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) {
    const parts = value.map(valueText).filter((item): item is string => Boolean(item));
    return parts.length ? parts.join(", ") : null;
  }
  if (value && typeof value === "object") {
    const parts = Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => {
        const text = valueText(item);
        return text ? `${humanize(key)}: ${text}` : null;
      })
      .filter((item): item is string => Boolean(item));
    return parts.length ? parts.join("; ") : null;
  }
  return null;
}

function numberText(value: unknown): string | null {
  const numeric = typeof value === "number" ? value : typeof value === "string" ? Number(value.replaceAll(",", "")) : NaN;
  if (Number.isFinite(numeric) && (typeof value === "number" || /^[\d,.\s-]+$/.test(String(value)))) {
    return numeric.toLocaleString();
  }
  return valueText(value);
}

/** Success contract in reading order: Measure, Comparison, Target, Unit, then anything else public. */
export function criteriaRows(criteria: Record<string, unknown>): CriteriaRow[] {
  const rows: CriteriaRow[] = [];
  const metric = valueText(criteria.metric);
  if (metric) rows.push({ key: "metric", label: "Measure", value: humanize(metric) });
  const operator = typeof criteria.operator === "string" ? criteria.operator.trim().toLowerCase() : "";
  if (operator) rows.push({ key: "operator", label: "Comparison", value: COMPARISONS[operator] ?? operator });
  const targetKey = TARGET_KEYS.find((key) => criteria[key] != null && criteria[key] !== "");
  const target = targetKey ? numberText(criteria[targetKey]) : null;
  if (target) rows.push({ key: targetKey!, label: "Target", value: target });
  const unit = valueText(criteria.unit);
  if (unit) rows.push({ key: "unit", label: "Unit", value: unit });
  for (const [key, value] of Object.entries(criteria)) {
    if (HIDDEN_KEYS.has(key)) continue;
    const text = valueText(value);
    if (text) rows.push({ key, label: OTHER_LABELS[key] ?? humanize(key), value: humanize(text) });
  }
  return rows;
}

export function milestoneText(milestone: unknown): string | null {
  if (typeof milestone === "string") return milestone.trim() || null;
  if (milestone && typeof milestone === "object" && !Array.isArray(milestone)) {
    const value = milestone as Record<string, unknown>;
    const title = value.title ?? value.name ?? value.description;
    if (typeof title === "string" && title.trim()) return title;
  }
  return valueText(milestone);
}

export function blueprintHasContent(blueprint: PublicBlueprint): boolean {
  return Boolean(
    blueprint.deadline ||
      criteriaRows(blueprint.success_criteria).length ||
      blueprint.milestones.length ||
      blueprint.strategies.length,
  );
}

/** Headline numbers. Odds are only shown when the latest decision is published. */
export function publicMarketStats(market: PublicMarketDetail): PublicMarketStats {
  const published = market.forecast.status === "published";
  const first = market.history[0];
  const last = market.history[market.history.length - 1];
  const changePoints =
    published && first && last && market.history.length >= 2 ? (last.probability - first.probability) * 100 : null;
  return {
    latestOdds: published && market.latest_probability != null ? market.latest_probability * 100 : null,
    changePoints,
    updates: market.history.length,
    stars: market.star_count,
    forks: market.fork_count,
    targetDate: formatShortDate(market.blueprint.deadline),
  };
}

export function signedPoints(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "0.0 pts";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(1)} pts`;
}

export function categoryLabel(category: string): string {
  return humanize(category);
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** Published updates, newest last. Older API payloads only carry probability history. */
export function marketUpdates(market: PublicMarketDetail): PublicMarketUpdate[] {
  if (market.updates?.length) return market.updates;
  return market.history.map((point, index) => {
    const previous = index > 0 ? market.history[index - 1] : undefined;
    return {
      published_at: point.created_at,
      probability: point.probability,
      previous_probability: previous?.probability ?? null,
      change_points: previous ? Math.round((point.probability - previous.probability) * 1000) / 10 : null,
      kind: index === 0 ? "first_publication" : "update",
      receipt_recorded: false,
      evidence_total: null,
      new_evidence_count: null,
      retired_evidence_count: null,
      new_evidence_metrics: [],
      other_new_evidence_count: 0,
      model: null,
      model_change: null,
      status_change: null,
      definition_revised: false,
      deadline_changed: false,
    };
  });
}

/**
 * What the receipt recorded alongside an odds move. These describe what changed
 * between publications; they are not presented as the cause of the move.
 */
export function updateContext(update: PublicMarketUpdate): string[] {
  const parts: string[] = [];
  const metrics = update.new_evidence_metrics;
  const named = metrics.length
    ? `: ${metrics.join(", ")}${update.other_new_evidence_count ? ` + ${update.other_new_evidence_count} other` : ""}`
    : "";
  if (update.kind === "first_publication") {
    parts.push(
      update.evidence_total != null
        ? `First publication, ${plural(update.evidence_total, "evidence record", "evidence records")}${named}`
        : "First publication",
    );
  } else if (update.new_evidence_count != null) {
    parts.push(update.new_evidence_count > 0
      ? `${plural(update.new_evidence_count, "new evidence record", "new evidence records")}${named}`
      : "No new evidence");
  }
  if (update.retired_evidence_count) {
    parts.push(`${plural(update.retired_evidence_count, "record", "records")} superseded`);
  }
  if (update.model_change) parts.push(`Model ${update.model_change.previous} → ${update.model_change.current}`);
  if (update.status_change) parts.push(`Status ${update.status_change.previous} → ${update.status_change.current}`);
  if (update.definition_revised) parts.push("Goal definition revised");
  if (update.deadline_changed) parts.push("Deadline changed");
  if (!update.receipt_recorded && update.kind === "update") parts.push("Details not recorded for this update");
  return parts;
}
