import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type Goal } from "../../api/client";
import { ProbabilityChart } from "./ProbabilityChart";
import { toMarketCardViewModel } from "./marketViewModel";

export function MarketTile({ goal }: { goal: Goal }) {
  const history = useQuery({ queryKey: ["market-history", goal.goal_id], queryFn: ({ signal }) => api.marketHistory(goal.goal_id, signal) });
  if (history.isError) {
    return (
      <li className="market-card-item">
        <div className="market-card">
          <div className="unpriced-state">
            <strong>History unavailable</strong>
            <span>Could not load published forecast history.</span>
          </div>
        </div>
      </li>
    );
  }
  const market = toMarketCardViewModel(goal, history.data ?? []);
  const signedReturn = market.todayReturn == null ? null : `${market.todayReturn >= 0 ? "+" : ""}${market.todayReturn.toFixed(1)}% today`;
  return (
    <li className="market-card-item">
      <Link className="market-card" to={`/goals/${market.id}`}>
        <div className="market-card-header">
          <div className="market-card-title-block">
            <div className="market-card-category">{market.category}</div>
            <h2>{market.title}</h2>
          </div>
          <div className="market-card-odds">{market.odds == null ? "—" : `${market.odds.toFixed(0)}%`}</div>
        </div>
        <div className={`market-card-return ${(market.todayReturn ?? 0) >= 0 ? "positive" : "negative"}`}>
          {signedReturn ?? "Needs more information"}
        </div>
        <div className="market-card-chart">
          <ProbabilityChart chartId={market.id} title={market.title} status={goal.forecast_status} series={market.history.map((point) => ({ t: point.timestamp, p: point.value / 100 }))} currentProbability={market.odds == null ? undefined : market.odds / 100}/>
        </div>
      </Link>
    </li>
  );
}
