import { Link } from "react-router-dom";
import type { PublicMarketCard } from "../../api/client";
import MarketSparkline from "../market/MarketSparkline";

type Props = {
  items: PublicMarketCard[];
  empty: string;
};

export default function MarketRepoList({ items, empty }: Props) {
  if (!items.length) return <p className="quiet-copy" role="status">{empty}</p>;
  return (
    <div className="repo-list">
      {items.map((market) => (
        <Link key={market.goal_id} className="repo-row" to={`/m/${market.goal_id}`}>
          <div>
            <h3>
              {market.title}{" "}
              <span className="visibility-badge">{market.visibility === "public" ? "Public" : "Private"}</span>
            </h3>
            <p className="quiet-copy">{market.description || "No public description."}</p>
            <div className="repo-meta">
              <span>{market.category.replaceAll("_", " ")}</span>
              <span>{market.star_count} stars</span>
              <span>{market.fork_count} forks</span>
              {market.updated_at ? <span>Updated {market.updated_at.slice(0, 10)}</span> : null}
            </div>
          </div>
          <MarketSparkline
            history={market.history.map((point) => ({
              timestamp: Date.parse(point.created_at),
              value: point.probability * 100,
            }))}
            withheld={market.forecast.status === "withheld"}
          />
        </Link>
      ))}
    </div>
  );
}
