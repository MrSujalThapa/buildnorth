import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAccount } from "../auth/AuthGate";
import ContributionHeatmap from "../components/social/ContributionHeatmap";
import MarketRepoList from "../components/social/MarketRepoList";
import "../components/social/social.css";

export function PublicProfileRoute() {
  const { handle = "" } = useParams();
  const account = useAccount();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"overview" | "markets" | "stars">("overview");
  const [query, setQuery] = useState("");
  const [graph, setGraph] = useState<"followers" | "following" | null>(null);
  const profile = useQuery({
    queryKey: ["public-profile", handle],
    queryFn: ({ signal }) => api.publicProfile(handle, signal),
    enabled: Boolean(handle),
  });
  const markets = useQuery({
    queryKey: ["public-profile-markets", handle, query],
    queryFn: ({ signal }) => api.publicProfileMarkets(handle, { q: query || undefined }, signal),
    enabled: Boolean(handle),
  });
  const stars = useQuery({
    queryKey: ["public-profile-stars", handle],
    queryFn: ({ signal }) => api.publicProfileStars(handle, signal),
    enabled: Boolean(handle) && tab === "stars",
  });
  const people = useQuery({
    queryKey: ["public-follow-graph", handle, graph],
    queryFn: ({ signal }) => api.publicFollowGraph(handle, graph ?? "followers", signal),
    enabled: Boolean(handle && graph),
  });
  const follow = useMutation({
    mutationFn: async () => {
      if (!profile.data) return;
      return profile.data.following ? api.unfollowProfile(handle) : api.followProfile(handle);
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["public-profile", handle] }); void queryClient.invalidateQueries({ queryKey: ["public-follow-graph", handle] }); },
  });

  if (profile.isLoading) return <main className="profile-social"><section className="profile-social-shell"><p role="status">Loading profile…</p></section></main>;
  if (profile.isError || !profile.data) return <main className="profile-social"><section className="profile-social-shell"><p role="alert">Profile unavailable.</p></section></main>;

  const creator = profile.data.creator;
  const display = creator.display_name || creator.handle;
  const isSelf = account?.user_id === creator.user_id;

  return (
    <main className="profile-social">
      <section className="profile-social-shell">
        <header className="profile-head">
          <div className="profile-card" style={{ width: "100%" }}>
            <div className="profile-avatar">{creator.has_photo ? <img src={api.publicPhotoUrl(creator.handle)} alt="" width={96} height={96} /> : display.slice(0, 1).toUpperCase()}</div>
            <div className="profile-identity">
              <h2>{display}</h2>
              <span>@{creator.handle}</span>
              {creator.bio ? <p>{creator.bio}</p> : null}
              <div className="follow-counts">
                <button type="button" onClick={() => setGraph("followers")}>{profile.data.follower_count} followers</button>
                <button type="button" onClick={() => setGraph("following")}>{profile.data.following_count} following</button>
              </div>
            </div>
            {isSelf ? (
              <Link className="secondary" to="/profile">Edit profile</Link>
            ) : (
              <button type="button" className="secondary" disabled={follow.isPending} onClick={() => follow.mutate()}>
                {profile.data.following ? "Unfollow" : "Follow"}
              </button>
            )}
          </div>
          {follow.isError ? <p role="alert">Could not update follow. Try again.</p> : null}
        </header>
        <nav className="profile-tabs" aria-label="Profile sections">
          <button type="button" className={tab === "overview" ? "is-active" : ""} onClick={() => setTab("overview")}>Overview</button>
          <button type="button" className={tab === "markets" ? "is-active" : ""} onClick={() => setTab("markets")}>Markets</button>
          <button type="button" className={tab === "stars" ? "is-active" : ""} onClick={() => setTab("stars")}>Stars</button>
        </nav>
        {tab === "overview" ? (
          <>
            <ContributionHeatmap days={profile.data.activity} total={profile.data.contribution_total} />
            <h2>Public markets</h2>
            {markets.isError ? <p role="alert">Could not load markets. <button type="button" onClick={() => void markets.refetch()}>Try again</button></p> : markets.isLoading ? <p role="status">Loading markets&hellip;</p> : <MarketRepoList items={markets.data?.items ?? []} empty="No public markets yet." />}
          </>
        ) : null}
        {tab === "markets" ? (
          <>
            <input className="repo-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a market…" aria-label="Find a market" />
            {markets.isError ? <p role="alert">Could not load markets. <button type="button" onClick={() => void markets.refetch()}>Try again</button></p> : markets.isLoading ? <p role="status">Loading markets&hellip;</p> : <MarketRepoList items={markets.data?.items ?? []} empty="No public markets match that search." />}
          </>
        ) : null}
        {tab === "stars" ? (
          stars.isError ? <p role="alert">Could not load stars. <button type="button" onClick={() => void stars.refetch()}>Try again</button></p> : stars.isLoading ? <p role="status">Loading stars&hellip;</p> : <MarketRepoList items={stars.data?.items ?? []} empty="No public starred markets." />
        ) : null}
      </section>
      {graph ? (
        <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="follow-graph-title">
          <div className="confirm-card">
            <h2 id="follow-graph-title">{graph === "followers" ? "Followers" : "Following"}</h2>
            <ul>
              {(people.data?.items ?? []).map((item) => (
                <li key={item.creator.user_id}>
                  <Link to={`/u/${item.creator.handle}`} onClick={() => setGraph(null)}>
                    {item.creator.display_name || item.creator.handle}
                  </Link>
                </li>
              ))}
            </ul>
            {people.isError ? <p role="alert">Could not load people. <button type="button" onClick={() => void people.refetch()}>Try again</button></p> : people.isLoading ? <p role="status">Loading people&hellip;</p> : !people.data?.items.length ? <p className="quiet-copy">No one here yet.</p> : null}
            <button type="button" className="secondary" onClick={() => setGraph(null)}>Close</button>
          </div>
        </div>
      ) : null}
    </main>
  );
}
