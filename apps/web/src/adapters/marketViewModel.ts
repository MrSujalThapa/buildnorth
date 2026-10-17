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
  return `${goal.goal_type.replaceAll("_", " ")} · Deadline ${deadline} · ${goal.forecast_status}`;
}

export function toMarketCard(goal: Goal, history: MarketHistoryPoint[]): Market {
  const chart = historyToChart(history);
  const odds = chart.at(-1)?.value ?? null;
  const first = chart[0]?.value ?? null;
  const last = chart.at(-1)?.value ?? null;
  const prev = chart.length > 1 ? chart.at(-2)?.value : null;
  const todayReturn = last != null && prev != null ? last - prev : first != null && last != null ? last - first : null;
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
    icon: evidenceIcon(item.summary || item.metric),
  }));
}

export function toMarketDetail(goal: Goal, history: MarketHistoryPoint[], evidence: EvidenceEvent[]): Market {
  const base = toMarketCard(goal, history);
  return { ...base, events: evidenceToEvents(evidence) };
}
