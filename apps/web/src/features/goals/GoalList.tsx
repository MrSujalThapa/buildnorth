import type { Goal } from "../../api/client";
import { MarketTile } from "./MarketTile";

export function GoalList({ goals }: { goals: Goal[] }) {
  return (
    <ul className="markets-grid" aria-label="Tracked goals">
      {goals.map((goal) => <MarketTile key={goal.goal_id} goal={goal} />)}
    </ul>
  );
}
