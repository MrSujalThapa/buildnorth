import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
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
  const markets = useInfiniteQuery({
    queryKey: ["public-markets", query, sort],
    retry: false,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => api.publicMarkets({
      q: query.trim() || undefined, sort, limit: 24, offset: pageParam,
    }, signal),
    getNextPageParam: (lastPage) => lastPage.items.length > 0 && lastPage.offset + lastPage.items.length < lastPage.total
      ? lastPage.offset + lastPage.items.length : undefined,
  });
  const creators = useQuery({
    queryKey: ["public-creators"],
    queryFn: ({ signal }) => api.publicCreators(signal),
  });
  const seen = new Set<string>();
  const items = (markets.data?.pages.flatMap((page) => page.items) ?? []).filter((item) => {
    if (seen.has(item.goal_id)) return false;
    seen.add(item.goal_id);
    return true;
  });
  const total = markets.data?.pages.at(-1)?.total;
  const people = creators.data?.items ?? [];

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
        {creators.isError ? <p role="alert">Could not load creators. <button type="button" onClick={() => void creators.refetch()}>Try again</button></p> : null}
        {people.length ? (
          <div className="creator-row" aria-label="Creators">
            {people.map((creator) => (
              <button
                key={creator.user_id}
                type="button"
                className="creator-chip"
                onClick={() => { void navigate(`/u/${creator.handle}`); }}
              >
                <span className="mini-avatar">{creator.has_photo ? <img src={api.publicPhotoUrl(creator.handle)} alt="" width={28} height={28} loading="lazy" /> : (creator.display_name || creator.handle).slice(0, 1).toUpperCase()}</span>
                {creator.display_name || creator.handle}
              </button>
            ))}
          </div>
        ) : null}
        {markets.isError && !markets.data ? (
          <div className="empty-social" role="alert"><h2>Could not load markets</h2><button type="button" className="secondary" onClick={() => void markets.refetch()}>Try again</button></div>
        ) : markets.isPending ? (
          <p role="status">Loading public markets&hellip;</p>
        ) : items.length === 0 ? (
          <div className="empty-social" role="status">
            <h2>{query.trim() ? "No matching markets" : "No public markets"}</h2>
            {query.trim() ? (
              <button type="button" className="secondary" onClick={() => setQuery("")}>Clear search</button>
            ) : <p>Publish a market from its page to make a blueprint discoverable.</p>}
          </div>
        ) : (
          <>
          <p className="discover-result-count" role="status">Showing {items.length} of {Math.max(total ?? items.length, items.length)} public markets</p>
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
          {markets.isFetchNextPageError ? (
            <p role="alert" className="discover-page-error">Could not load more markets. <button type="button" className="secondary" onClick={() => void markets.fetchNextPage()}>Try again</button></p>
          ) : markets.hasNextPage ? (
            <div className="discover-more"><button type="button" className="secondary" disabled={markets.isFetchingNextPage} onClick={() => void markets.fetchNextPage()}>{markets.isFetchingNextPage ? "Loading more\u2026" : "Load more"}</button></div>
          ) : null}
          </>
        )}
      </section>
    </main>
  );
}
