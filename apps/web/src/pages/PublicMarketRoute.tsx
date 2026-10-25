import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ChartPoint } from "../adapters/templateTypes";
import OddsExplorer from "../components/market/OddsExplorer";
import { ODDS_EXPLORER_RANGES } from "../components/market/marketRanges";
import { useAccount } from "../auth/AuthGate";
import { absoluteUrl, shareLink } from "../features/social/share";
import SparsePublicHistory from "../components/social/SparsePublicHistory";
import PublicBlueprintDetails from "../components/social/PublicBlueprintDetails";
import "../components/social/social.css";
import "../components/market/market-detail.css";

function historyPoints(points: { created_at: string; probability: number }[]): ChartPoint[] {
  return points.map((point) => ({ timestamp: Date.parse(point.created_at), value: point.probability * 100 }));
}

export function PublicMarketRoute() {
  const { goalId = "" } = useParams();
  const navigate = useNavigate();
  const account = useAccount();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [forkTitle, setForkTitle] = useState("");
  const [forkOpen, setForkOpen] = useState(false);
  const market = useQuery({
    queryKey: ["public-market", goalId],
    queryFn: ({ signal }) => api.publicMarket(goalId, signal),
    enabled: Boolean(goalId),
  });
  const star = useMutation({
    mutationFn: async () => {
      if (!market.data) return;
      return market.data.starred ? api.unstarMarket(goalId) : api.starMarket(goalId);
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["public-market", goalId] }); void queryClient.invalidateQueries({ queryKey: ["public-markets"] }); void queryClient.invalidateQueries({ queryKey: ["public-profile-stars"] }); void queryClient.invalidateQueries({ queryKey: ["own-profile-stars"] }); },
  });
  const fork = useMutation({
    mutationFn: () => api.forkMarket(goalId, {
      title: forkTitle.trim() || undefined,
      idempotency_key: `fork:${account?.user_id ?? "anon"}:${goalId}`,
    }),
    onSuccess: (result) => { void navigate(`/goals/${result.goal_id}`); },
  });

  if (market.isLoading) return <main className="public-market"><section className="public-market-shell"><p role="status">Loading public market…</p></section></main>;
  if (market.isError || !market.data) {
    return (
      <main className="public-market">
        <section className="public-market-shell">
          <h1>Market not found</h1>
          <p className="quiet-copy">This market is private or no longer published.</p>
        </section>
      </main>
    );
  }
  const item = market.data;
  const history = historyPoints(item.history);
  const isOwner = account?.user_id === item.creator.user_id;

  return (
    <main className="public-market market-page">
      <section className="public-market-shell market-shell">
        <p className="market-eyebrow">
          <Link to={`/u/${item.creator.handle}`}>{item.creator.display_name || item.creator.handle}</Link>
          {item.fork?.source_public && item.fork.source_handle ? (
            <> · Forked from <Link to={`/m/${item.fork.source_goal_id}`}>{item.fork.source_handle}/{item.fork.source_title}</Link></>
          ) : null}
        </p>
        <div className="market-heading">
          <div className="market-title-row">
            <h1>{item.title}</h1>
          </div>
        </div>
        <div className="public-actions">
          <button type="button" className="ui-button" disabled={star.isPending} onClick={() => star.mutate()}>
            {item.starred ? "Unstar" : "Star"} · {item.star_count}
          </button>
          <button type="button" className="ui-button ui-button-secondary" onClick={() => setForkOpen(true)}>Fork</button>
          <button
            type="button"
            className="ui-button ui-button-secondary"
            onClick={() => {
              void shareLink({ url: absoluteUrl(`/m/${item.goal_id}`), title: item.title })
                .then((mode) => setMessage(mode === "copied" ? "Link copied" : "Shared"))
                .catch(() => undefined);
            }}
          >
            Share
          </button>
          {isOwner ? <Link className="ui-button" to={`/goals/${item.goal_id}`}>Open as owner</Link> : null}
        </div>
        {star.isError ? <p role="alert">Could not update star. Try again.</p> : null}
        <section className="market-quote">
          {item.forecast.status === "withheld" ? (
            <><div className="market-price">Withheld</div><div className="market-price-hint">The public forecast is withheld.</div></>
          ) : item.latest_probability == null ? (
            <><div className="market-price">Not published</div><div className="market-price-hint">No public odds are available for this blueprint.</div></>
          ) : (
            <><div className="market-price">{(item.latest_probability * 100).toFixed(1)}%</div><div className="market-price-hint">Latest published odds</div></>
          )}
        </section>
        {history.length > 2 ? (
          <OddsExplorer history={history} ranges={ODDS_EXPLORER_RANGES} initialRange={ODDS_EXPLORER_RANGES.at(-1)} />
        ) : history.length ? (
          <SparsePublicHistory history={history} />
        ) : (
          <p className="quiet-copy" role="status">No published chart history.</p>
        )}
        <section className="public-events" aria-labelledby="public-events-title">
          <h2 id="public-events-title">Recent updates</h2>
          {item.history.length ? (
            <ol>
              {item.history.slice(-6).reverse().map((point, index, recent) => {
                const previous = recent[index + 1];
                const change = previous ? (point.probability - previous.probability) * 100 : null;
                return (
                  <li key={point.created_at}>
                    <time dateTime={point.created_at}>{new Date(point.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}</time>
                    <span>{previous ? "Forecast updated" : "Forecast published"}</span>
                    <strong>{(point.probability * 100).toFixed(1)}%</strong>
                    {change != null ? (
                      <span className={change >= 0 ? "is-up" : "is-down"}>{change >= 0 ? "+" : "−"}{Math.abs(change).toFixed(1)} pts</span>
                    ) : <span />}
                  </li>
                );
              })}
            </ol>
          ) : <p className="quiet-copy">No published forecast updates yet.</p>}
        </section>
        <PublicBlueprintDetails blueprint={item.blueprint} />
      </section>
      {forkOpen ? (
        <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="fork-title">
          <form
            className="confirm-card"
            onSubmit={(event) => {
              event.preventDefault();
              fork.mutate();
            }}
          >
            <h2 id="fork-title">Fork this market</h2>
            <p>Creates an independent private market on your account. Evidence and odds are not copied.</p>
            <label htmlFor="fork-name">Title</label>
            <input id="fork-name" className="ui-field" value={forkTitle} onChange={(event) => setForkTitle(event.target.value)} placeholder={item.title} />
            {fork.isError ? <p role="alert">Could not fork this market.</p> : null}
            <div className="composer-actions">
              <button type="submit" className="ui-button" disabled={fork.isPending}>{fork.isPending ? "Forking…" : "Create fork"}</button>
              <button type="button" className="secondary" onClick={() => setForkOpen(false)}>Cancel</button>
            </div>
          </form>
        </div>
      ) : null}
      {message ? <div className="share-toast" role="status">{message}</div> : null}
    </main>
  );
}
