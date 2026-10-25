import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ChartPoint } from "../adapters/templateTypes";
import OddsExplorer from "../components/market/OddsExplorer";
import { ODDS_EXPLORER_RANGES } from "../components/market/marketRanges";
import { useAccount } from "../auth/AuthGate";
import { absoluteUrl, shareLink } from "../features/social/share";
import "../components/social/social.css";
import "../components/market/market-detail.css";

function historyPoints(points: { created_at: string; probability: number }[]): ChartPoint[] {
  return points.map((point) => ({ timestamp: Date.parse(point.created_at), value: point.probability * 100 }));
}

function CriteriaList({ value }: { value: unknown }) {
  if (value == null || value === "") {
    return <p className="quiet-copy">No public success criteria.</p>;
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return <p>{String(value)}</p>;
  }
  if (Array.isArray(value)) {
    return (
      <ul>
        {value.map((item, index) => (
          <li key={index}>{typeof item === "string" ? item : JSON.stringify(item)}</li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    return (
      <dl className="criteria-list">
        {entries.map(([key, item]) => (
          <div key={key}>
            <dt>{key.replaceAll("_", " ")}</dt>
            <dd>{typeof item === "string" || typeof item === "number" ? String(item) : JSON.stringify(item)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return <p className="quiet-copy">No public success criteria.</p>;
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
    <main className="public-market">
      <section className="public-market-shell">
        <p className="quiet-copy">
          <Link to={`/u/${item.creator.handle}`}>{item.creator.display_name || item.creator.handle}</Link>
          {item.fork?.source_public && item.fork.source_handle ? (
            <> · Forked from <Link to={`/m/${item.fork.source_goal_id}`}>{item.fork.source_handle}/{item.fork.source_title}</Link></>
          ) : null}
        </p>
        <h1>{item.title}</h1>
        <p className="quiet-copy">{item.blueprint.description || item.description || "A public PlayItOut market blueprint."}</p>
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
          {isOwner ? <Link className="ui-button ui-button-secondary" to={`/goals/${item.goal_id}`}>Open as owner</Link> : null}
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
        {history.length ? (
          <OddsExplorer history={history} ranges={ODDS_EXPLORER_RANGES} initialRange={ODDS_EXPLORER_RANGES.at(-1)} />
        ) : (
          <p className="quiet-copy" role="status">No published chart history.</p>
        )}
        <section className="market-section">
          <h2>Success criteria</h2>
          <CriteriaList value={item.blueprint.success_criteria} />
        </section>
        {item.blueprint.milestones.length ? (
          <section className="market-section">
            <h2>Milestones</h2>
            <ul>{item.blueprint.milestones.map((milestone, index) => <li key={index}>{typeof milestone === "string" ? milestone : JSON.stringify(milestone)}</li>)}</ul>
          </section>
        ) : null}
        {item.blueprint.strategies.length ? (
          <section className="market-section">
            <h2>Strategy</h2>
            {item.blueprint.strategies.map((row) => <p key={row}>{row}</p>)}
          </section>
        ) : null}
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
