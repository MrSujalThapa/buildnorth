import { Link } from "react-router-dom";
import type { PublicMarketCard } from "../../api/client";
import { lifeCategoryFromTitle } from "../../features/goals/marketViewModel";
import MarketSparkline from "../market/MarketSparkline";
import { VisibilityBadge } from "../market/VisibilityControl";

type Props = {
  items: PublicMarketCard[];
  empty: string;
};

function forecastLabel(market: PublicMarketCard): string {
  if (market.forecast.status === "withheld") return "Withheld";
  if (market.forecast.status === "unpublished" || market.latest_probability == null) {
    return "Unpriced";
  }
  return `${Math.round(market.latest_probability * 100)}% last published`;
}

export default function MarketRepoList({ items, empty }: Props) {
  if (!items.length) return <p className="quiet-copy" role="status">{empty}</p>;
  return (
    <div className="repo-list">
      {items.map((market) => (
        <Link key={market.goal_id} className="repo-row" to={`/m/${market.goal_id}`}>
          <div className="repo-copy">
            <h3>
              {market.title}{" "}
              <VisibilityBadge visibility={market.visibility === "public" ? "public" : "private"} />
            </h3>
            {market.description ? <p className="quiet-copy">{market.description}</p> : null}
            <div className="repo-meta">
              <span>{lifeCategoryFromTitle(market.title)}</span>
              <span>{forecastLabel(market)}</span>
              <span>{market.star_count} stars</span>
              <span>{market.fork_count} forks</span>
              {market.updated_at ? <span>Updated {market.updated_at.slice(0, 10)}</span> : null}
            </div>
          </div>
          <div className="repo-chart">
            <MarketSparkline
              history={market.history.map((point) => ({
                timestamp: Date.parse(point.created_at),
                value: point.probability * 100,
              }))}
              withheld={market.forecast.status === "withheld"}
            />
          </div>
        </Link>
      ))}
    </div>
  );
}
