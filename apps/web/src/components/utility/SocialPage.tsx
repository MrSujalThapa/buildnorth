import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type PublicMarketCard } from "../../api/client";
import MarketSparkline from "../market/MarketSparkline";
import "../social/social.css";

function chartPoints(market: PublicMarketCard) {
  return market.history.map((point) => ({
    timestamp: Date.parse(point.created_at),
    value: point.probability * 100,
  }));
}

export default function SocialPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("newest");
  const markets = useQuery({
    queryKey: ["public-markets", query, sort],
    queryFn: ({ signal }) => api.publicMarkets({ q: query || undefined, sort }, signal),
  });
  const creators = useQuery({
    queryKey: ["public-creators"],
    queryFn: ({ signal }) => api.publicCreators(signal),
  });
  const items = markets.data?.items ?? [];
  const people = creators.data?.items ?? [];
  const empty = useMemo(() => !markets.isLoading && items.length === 0, [markets.isLoading, items.length]);

  return (
    <main className="discover-page">
      <section className="discover-shell">
        <header className="discover-header">
          <div>
            <h1>Discover</h1>
            <p>Public PlayItOut markets you can inspect, star, and fork. Private goals stay private.</p>
          </div>
        </header>
        <div className="discover-tools">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search public markets"
            aria-label="Search public markets"
          />
          <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label="Sort markets">
            <option value="newest">Recently published</option>
            <option value="stars">Most starred</option>
            <option value="forks">Most forked</option>
          </select>
        </div>
        {people.length ? (
          <div className="creator-row" aria-label="Creators">
            {people.map((creator) => (
              <button
                key={creator.user_id}
                type="button"
                className="creator-chip"
                onClick={() => { void navigate(`/u/${creator.handle}`); }}
              >
                <span className="mini-avatar">{(creator.display_name || creator.handle).slice(0, 1).toUpperCase()}</span>
                {creator.display_name || creator.handle}
              </button>
            ))}
          </div>
        ) : null}
        {empty ? (
          <div className="empty-social" role="status">
            <h2>No public markets</h2>
            <p>Publish a market from its page to make a blueprint discoverable. Nothing here is invented.</p>
          </div>
        ) : (
          <div className="discover-grid">
            {items.map((market) => (
              <button
                key={market.goal_id}
                type="button"
                className="discover-card"
                onClick={() => { void navigate(`/m/${market.goal_id}`); }}
              >
                <div className={`discover-card-chart${market.history.length ? "" : " is-empty"}`}>
                  <MarketSparkline
                    history={chartPoints(market)}
                    withheld={market.forecast.status === "withheld"}
                  />
                </div>
                <h2>{market.title}</h2>
                <div className="discover-meta">
                  <span>{market.creator.display_name || market.creator.handle}</span>
                  <span>{market.category.replaceAll("_", " ")}</span>
                  <span>{market.latest_probability == null ? "Odds unpublished" : `${Math.round(market.latest_probability * 100)}%`}</span>
                  <span>{market.star_count} stars</span>
                  <span>{market.fork_count} forks</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
