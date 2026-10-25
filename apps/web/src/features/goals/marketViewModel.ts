import type { Goal, MarketHistoryPoint } from "../../api/client";
import { publishedHistoryPoints } from "../../adapters/marketViewModel";

export interface MarketCardViewModel {
  id: string;
  category: string;
  title: string;
  odds: number | null;
  todayReturn: number | null;
  history: { timestamp: number; value: number }[];
  historyUnavailable: boolean;
}

const CATEGORY_PATTERNS: Array<[RegExp, string]> = [
  [/waterloo|admission|school|university|degree|course/i, "Education"],
  [/offer|job|career|interview|employment|promotion/i, "Career"],
  [/startup|company|revenue|customer|founder/i, "Startup"],
  [/worth|wealth|saving|income|financial|money/i, "Finance"],
  [/10k|marathon|run|fitness|health|weight/i, "Personal"],
  [/competition|hackathon|tournament|award/i, "Competitions"],
];

export function marketCategory(goal: Goal): string {
  const searchable = goal.title;
  return CATEGORY_PATTERNS.find(([pattern]) => pattern.test(searchable))?.[1] ?? "Personal";
}

export function toMarketCardViewModel(goal: Goal, points: MarketHistoryPoint[]): MarketCardViewModel {
  const published = publishedHistoryPoints(points);
  const history = published.map((point) => ({
    timestamp: Date.parse(point.created_at!),
    value: point.probability * 100,
  }));
  const publication = goal.model_requirements?.last_publication;
  const withheld = publication && typeof publication === "object" && "status" in publication
    && publication.status === "withheld";
  const odds = withheld ? null : history.at(-1)?.value ?? null;
  const first = history[0]?.value;
  return {
    id: goal.goal_id,
    category: marketCategory(goal),
    title: goal.title,
    odds,
    historyUnavailable: points.some((point) => point.source_kind !== "synthetic_demo") && history.length === 0,
    todayReturn: odds != null && first != null ? odds - first : null,
    history,
  };
}
