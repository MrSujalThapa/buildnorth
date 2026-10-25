import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api, type PublicMarketCard } from "../../api/client";
import { lifeCategoryFromTitle } from "../../features/goals/marketViewModel";
import MarketSparkline from "../market/MarketSparkline";
import "../social/social.css";

function chartPoints(market: PublicMarketCard) {
  return market.history.map((point) => ({
    timestamp: Date.parse(point.created_at),
    value: point.probability * 100,
  }));
}

const LIFE_AREAS = ["Career", "Education", "Fitness", "Finance", "Startup", "Relationships", "Personal"] as const;

export default function SocialPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("newest");
  const [area, setArea] = useState<string>("all");
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
  const visible = useMemo(
    () => items.filter((item) => area === "all" || lifeCategoryFromTitle(item.title) === area),
    [area, items],
  );
  const total = markets.data?.pages.at(-1)?.total;
  const people = creators.data?.items ?? [];

  return (
    <main className="discover-page">
      <section className="discover-shell">
        <header className="discover-header">
          <div>
            <p className="discover-kicker">Marketplace</p>
            <h1>Discover</h1>
          </div>
        </header>
        <div className="discover-tools">
          <input
            className="ui-field"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search public markets"
            aria-label="Search public markets"
          />
          <select className="ui-field" value={sort} onChange={(event) => setSort(event.target.value)} aria-label="Sort markets">
            <option value="newest">Recently published</option>
            <option value="stars">Most starred</option>
            <option value="forks">Most forked</option>
          </select>
          {query.trim() || area !== "all" ? (
            <button type="button" className="ui-button ui-button-secondary" onClick={() => { setQuery(""); setArea("all"); }}>
              Clear filters
            </button>
          ) : null}
        </div>
        <div className="discover-areas" role="tablist" aria-label="Life area">
          <button type="button" role="tab" aria-selected={area === "all"} className={area === "all" ? "is-active" : ""} onClick={() => setArea("all")}>All</button>
          {LIFE_AREAS.map((label) => (
            <button key={label} type="button" role="tab" aria-selected={area === label} className={area === label ? "is-active" : ""} onClick={() => setArea(label)}>
              {label}
            </button>
          ))}
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
        ) : visible.length === 0 ? (
          <div className="empty-social" role="status">
            <h2>{query.trim() || area !== "all" ? "No matching markets" : "No public markets"}</h2>
            {query.trim() || area !== "all" ? (
              <button type="button" className="ui-button ui-button-secondary" onClick={() => { setQuery(""); setArea("all"); }}>Clear filters</button>
            ) : <p>No public markets are listed yet.</p>}
          </div>
        ) : (
          <>
          <p className="discover-result-count" role="status">Showing {visible.length} of {Math.max(total ?? items.length, items.length)} public markets</p>
          <div className="discover-grid">
            {visible.map((market) => (
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
                <div className="discover-card-body">
                  <span className="discover-category">{lifeCategoryFromTitle(market.title)}</span>
                  <h2>{market.title}</h2>
                  {market.description ? <p>{market.description}</p> : null}
                  <div className="discover-meta">
                    <span className="discover-owner">
                      <span className="mini-avatar">{market.creator.has_photo ? <img src={api.publicPhotoUrl(market.creator.handle)} alt="" width={22} height={22} loading="lazy" /> : (market.creator.display_name || market.creator.handle).slice(0, 1).toUpperCase()}</span>
                      {market.creator.display_name || market.creator.handle}
                    </span>
                    <span>{market.latest_probability == null ? "Unpriced" : `${Math.round(market.latest_probability * 100)}%`}</span>
                    <span>{market.star_count} stars</span>
                    <span>{market.fork_count} forks</span>
                  </div>
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
