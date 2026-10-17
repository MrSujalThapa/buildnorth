import type { Goal, MarketHistoryPoint } from "../../api/client";

export interface MarketCardViewModel {
  id: string;
  category: string;
  title: string;
  odds: number | null;
  todayReturn: number | null;
  history: { timestamp: number; value: number }[];
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
  const published = points.filter((point) => point.source_kind !== "synthetic_demo");
  const history = published.map((point, index) => ({
    timestamp: point.created_at ? Date.parse(point.created_at) : index,
    value: point.probability * 100,
  }));
  const odds = history.at(-1)?.value ?? null;
  const first = history[0]?.value;
  return {
    id: goal.goal_id,
    category: marketCategory(goal),
    title: goal.title,
    odds,
    todayReturn: odds != null && first != null ? odds - first : null,
    history,
  };
}
