import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { GitFork, Share2, Star } from "lucide-react";
import { api } from "../api/client";
import type { ChartPoint } from "../adapters/templateTypes";
import OddsExplorer from "../components/market/OddsExplorer";
import { ODDS_EXPLORER_RANGES } from "../components/market/marketRanges";
import { VisibilityBadge } from "../components/market/VisibilityControl";
import { useAccount } from "../auth/AuthGate";
import { absoluteUrl, shareLink } from "../features/social/share";
import SparsePublicHistory from "../components/social/SparsePublicHistory";
import PublicBlueprintDetails from "../components/social/PublicBlueprintDetails";
import {
  categoryLabel,
  formatShortDate,
  publicMarketStats,
  signedPoints,
} from "../components/social/publicMarketView";
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
    onSuccess: (result) => { void navigate(`/goals/${result.goal_id}?forked=1`); },
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
  const stats = publicMarketStats(item);
  const creatorName = item.creator.display_name || item.creator.handle;
  const description = item.blueprint.description || item.description;
  const published = formatShortDate(item.published_at);
  const forkedFrom = item.fork?.source_public && item.fork.source_handle ? item.fork : null;

  return (
    <main className="public-market market-page">
      <section className="public-market-shell pm-shell">
        <header className="pm-header">
          <div className="pm-creator">
            <span className="mini-avatar" aria-hidden="true">
              {item.creator.has_photo
                ? <img src={api.publicPhotoUrl(item.creator.handle)} alt="" width={28} height={28} loading="lazy" />
                : creatorName.slice(0, 1).toUpperCase()}
            </span>
            <Link to={`/u/${item.creator.handle}`} className="pm-handle">@{item.creator.handle}</Link>
            {forkedFrom ? (
              <span className="pm-forked">
                <GitFork size={13} aria-hidden="true" /> forked from{" "}
                <Link to={`/m/${forkedFrom.source_goal_id}`}>@{forkedFrom.source_handle}/{forkedFrom.source_title}</Link>
              </span>
            ) : null}
          </div>
          <div className="pm-title-row">
            <h1>{item.title}</h1>
            <VisibilityBadge visibility={item.visibility === "public" ? "public" : "private"} />
          </div>
          <div className="pm-actions">
            <button type="button" className="pm-action" aria-pressed={item.starred} disabled={star.isPending} onClick={() => star.mutate()}>
              <Star size={15} aria-hidden="true" fill={item.starred ? "currentColor" : "none"} />
              <span>{item.starred ? "Starred" : "Star"}</span>
              <span className="pm-action-count">{item.star_count}</span>
            </button>
            <button type="button" className="pm-action" onClick={() => setForkOpen(true)}>
              <GitFork size={15} aria-hidden="true" />
              <span>Fork</span>
              <span className="pm-action-count">{item.fork_count}</span>
            </button>
            <button
              type="button"
              className="pm-action"
              onClick={() => {
                void shareLink({ url: absoluteUrl(`/m/${item.goal_id}`), title: item.title })
                  .then((mode) => setMessage(mode === "copied" ? "Link copied" : "Shared"))
                  .catch(() => undefined);
              }}
            >
              <Share2 size={15} aria-hidden="true" />
              <span>Share</span>
            </button>
            {isOwner ? <Link className="pm-action pm-action-owner" to={`/goals/${item.goal_id}`}>Open as owner</Link> : null}
          </div>
          {star.isError ? <p role="alert">Could not update star. Try again.</p> : null}
        </header>

        <dl className="pm-stats">
          <div className="pm-stat pm-stat-lead">
            <dt>Latest odds</dt>
            <dd>
              {stats.latestOdds != null
                ? `${stats.latestOdds.toFixed(1)}%`
                : item.forecast.status === "withheld" ? "Withheld" : "Unpriced"}
            </dd>
          </div>
          <div className="pm-stat">
            <dt>Since first publication</dt>
            <dd className={stats.changePoints == null ? "" : stats.changePoints >= 0 ? "is-up" : "is-down"}>
              {stats.changePoints == null ? "—" : signedPoints(stats.changePoints)}
            </dd>
          </div>
          <div className="pm-stat"><dt>Updates</dt><dd>{stats.updates}</dd></div>
          <div className="pm-stat"><dt>Stars</dt><dd>{stats.stars}</dd></div>
          <div className="pm-stat"><dt>Forks</dt><dd>{stats.forks}</dd></div>
          <div className="pm-stat"><dt>Target date</dt><dd>{stats.targetDate ?? "—"}</dd></div>
        </dl>

        <div className="pm-layout">
          <div className="pm-main">
            <section className="pm-chart" aria-label="Published odds history">
              {history.length >= 2 ? (
                <OddsExplorer history={history} ranges={ODDS_EXPLORER_RANGES} initialRange={ODDS_EXPLORER_RANGES.at(-1)} />
              ) : history.length === 1 ? (
                <div className="pm-sparse-frame"><SparsePublicHistory history={history} /></div>
              ) : (
                <p className="pm-chart-empty" role="status">
                  {item.forecast.status === "withheld"
                    ? "The latest forecast was withheld, so no odds are public."
                    : "No forecast has been published for this market yet."}
                </p>
              )}
            </section>
            <section className="public-events" aria-labelledby="public-events-title">
              <h2 id="public-events-title">Recent updates</h2>
              {item.history.length ? (
                <ol>
                  {item.history.slice(-6).reverse().map((point, index, recent) => {
                    const previous = recent[index + 1];
                    const change = previous ? (point.probability - previous.probability) * 100 : null;
                    return (
                      <li key={point.created_at}>
                        <time dateTime={point.created_at}>{formatShortDate(point.created_at)}</time>
                        <span>{previous || item.history.length > recent.length ? "Forecast updated" : "Forecast published"}</span>
                        <strong>{(point.probability * 100).toFixed(1)}%</strong>
                        {change != null ? (
                          <span className={change >= 0 ? "is-up" : "is-down"}>{signedPoints(change)}</span>
                        ) : <span />}
                      </li>
                    );
                  })}
                </ol>
              ) : <p className="quiet-copy">No published forecast updates yet.</p>}
            </section>
          </div>

          <aside className="pm-side">
            <section className="pm-about" aria-labelledby="pm-about-title">
              <h2 id="pm-about-title">About</h2>
              {description ? <p className="pm-about-copy">{description}</p> : null}
              <dl className="pm-facts">
                <div><dt>Category</dt><dd>{categoryLabel(item.blueprint.category || item.category)}</dd></div>
                <div><dt>Creator</dt><dd><Link to={`/u/${item.creator.handle}`}>{creatorName}</Link></dd></div>
                {published ? (
                  <div><dt>Published</dt><dd>{published}</dd></div>
                ) : item.visibility !== "public" ? (
                  <div><dt>Visibility</dt><dd>Private, only you can see it</dd></div>
                ) : null}
                {forkedFrom ? (
                  <div><dt>Forked from</dt><dd><Link to={`/m/${forkedFrom.source_goal_id}`}>@{forkedFrom.source_handle}/{forkedFrom.source_title}</Link></dd></div>
                ) : null}
              </dl>
            </section>
            <PublicBlueprintDetails blueprint={item.blueprint} />
          </aside>
        </div>
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
            <p>Creates a private market on your account with this blueprint: target, deadline, success criteria, and model setup. Evidence and odds are not copied.</p>
            <label htmlFor="fork-name">Title</label>
            <input id="fork-name" className="ui-field" value={forkTitle} onChange={(event) => setForkTitle(event.target.value)} placeholder={item.title} />
            {fork.isError ? <p role="alert">Could not fork this market.</p> : null}
            <div className="composer-actions">
              <button type="submit" className="ui-button" disabled={fork.isPending}>{fork.isPending ? "Forking…" : "Create fork"}</button>
              <button type="button" className="ui-button ui-button-secondary" onClick={() => setForkOpen(false)}>Cancel</button>
            </div>
          </form>
        </div>
      ) : null}
      {message ? <div className="share-toast" role="status">{message}</div> : null}
    </main>
  );
}
