import type { EvidenceEvent, Goal, MarketHistoryPoint } from "../api/client";
import type { ChartPoint, Market, MarketEvent } from "./templateTypes";

const CATEGORY_PATTERNS: Array<[RegExp, string]> = [
  [/waterloo|admission|school|university|degree|course/i, "Education"],
  [/offer|job|career|interview|employment|promotion|fde|swe/i, "Career"],
  [/startup|company|revenue|customer|founder|mrr|fundraising/i, "Startup"],
  [/worth|wealth|saving|income|financial|money|net/i, "Finance"],
  [/10k|marathon|run|fitness|health|weight|threshold/i, "Personal"],
  [/competition|hackathon|tournament|award/i, "Competitions"],
];

export function marketCategory(goal: Goal): string {
  const searchable = `${goal.title} ${goal.goal_type}`;
  return CATEGORY_PATTERNS.find(([pattern]) => pattern.test(searchable))?.[1] ?? "Personal";
}

export function publishedHistoryPoints(points: MarketHistoryPoint[]): MarketHistoryPoint[] {
  return points.filter((point) => point.source_kind !== "synthetic_demo");
}

function historyToChart(points: MarketHistoryPoint[]): ChartPoint[] {
  return publishedHistoryPoints(points).map((point, index) => ({
    timestamp: point.created_at ? Date.parse(point.created_at) : index,
    value: point.probability * 100,
  }));
}

function formatMeta(goal: Goal): string {
  const deadline = new Date(goal.deadline).toLocaleDateString("en-CA", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  return `Deadline ${deadline} · ${goal.forecast_status.toLowerCase()}`;
}

export function toMarketCard(goal: Goal, history: MarketHistoryPoint[]): Market {
  const published = publishedHistoryPoints(history);
  const chart = historyToChart(history);
  const odds = chart.at(-1)?.value ?? null;
  const first = chart[0]?.value ?? null;
  const last = chart.at(-1)?.value ?? null;
  const startOfDay = new Date();
  startOfDay.setUTCHours(0, 0, 0, 0);
  const beforeToday = published.filter((point) => point.created_at && Date.parse(point.created_at) < startOfDay.getTime()).at(-1);
  const todayReturn = last != null && beforeToday ? last - beforeToday.probability * 100 : null;
  const totalReturn = first != null && last != null ? last - first : null;

  return {
    id: goal.goal_id,
    title: goal.title,
    category: marketCategory(goal),
    meta: formatMeta(goal),
    createdAt: chart[0]?.timestamp ?? Date.now(),
    deadlineAt: Date.parse(goal.deadline),
    odds,
    todayReturn,
    totalReturn,
    events: [],
    history: chart,
  };
}

function evidenceIcon(summary: string): MarketEvent["icon"] {
  const blob = summary.toLowerCase();
  if (blob.includes("leetcode") || blob.includes("code")) return "code";
  if (blob.includes("fail") || blob.includes("reject")) return "x";
  if (blob.includes("ship") || blob.includes("release")) return "rocket";
  if (blob.includes("application") || blob.includes("recruit")) return "people";
  if (blob.includes("book") || blob.includes("read")) return "book";
  return "rocket";
}

export function evidenceToEvents(items: EvidenceEvent[]): MarketEvent[] {
  return items.slice(-6).reverse().map((item, index) => ({
    id: `${item.metric}-${index}`,
    label: item.summary || item.metric,
    impact: null,
    occurredAt: new Date(item.observed_at).toLocaleDateString("en-CA", { month: "short", day: "numeric" }),
    timestamp: Date.parse(item.observed_at),
    icon: evidenceIcon(item.summary || item.metric),
  }));
}

function stringField(value: object, key: string): string | undefined {
  const found: unknown = Object.getOwnPropertyDescriptor(value, key)?.value;
  return typeof found === "string" ? found : undefined;
}

function stringList(value: object, key: string): string[] {
  const found: unknown = Object.getOwnPropertyDescriptor(value, key)?.value;
  return Array.isArray(found) ? found.filter((item): item is string => typeof item === "string") : [];
}

function firstPrimitiveKind(value: object): string | undefined {
  const found: unknown = Object.getOwnPropertyDescriptor(value, "primitives")?.value;
  if (!Array.isArray(found) || found.length === 0) {
    return undefined;
  }
  const first: unknown = found[0];
  return first !== null && typeof first === "object" ? stringField(first, "kind") : undefined;
}

export function toMarketDetail(goal: Goal, history: MarketHistoryPoint[], evidence: EvidenceEvent[]): Market {
  const base = toMarketCard(goal, history);
  const raw: unknown = goal.model_requirements?.forecast_spec;
  const spec = raw && typeof raw === "object" ? raw : null;
  const family = spec ? stringField(spec, "family") : undefined;
  const primitive = spec ? firstPrimitiveKind(spec) : undefined;
  const unpriced = spec ? stringList(spec, "unpriced_reasons") : [];
  const reasons = unpriced.length ? unpriced : spec ? stringList(spec, "limitations") : [];
  const explanation = family
    ? primitive
      ? `Modeled as ${family.replaceAll("_", " ")} using the ${primitive.replaceAll("_", " ")} primitive.`
      : `Modeled as ${family.replaceAll("_", " ")}.`
    : undefined;
  const publicationRaw = goal.model_requirements?.last_publication;
  const publication =
    publicationRaw && typeof publicationRaw === "object"
      ? {
          status: stringField(publicationRaw, "status") ?? "unknown",
          category: stringField(publicationRaw, "category") ?? null,
          reason: stringField(publicationRaw, "reason") ?? null,
          issues: stringList(publicationRaw, "issues"),
          required_actions: stringList(publicationRaw, "required_actions"),
        }
      : undefined;
  return {
    ...base,
    events: evidenceToEvents(evidence),
    modelFamily: family,
    modelExplanation: explanation,
    unpricedReason: base.odds == null ? (publication?.reason ?? reasons[0]) : undefined,
    publication,
  };
}
