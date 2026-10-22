import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import CollectionChart from "../components/market/CollectionChart";
import { api } from "../api/client";
import "../components/market/markets.css";

export function CollectionDetailRoute() {
  const { collectionId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [name, setName] = useState("");
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const collection = useQuery({
    queryKey: ["collection", collectionId],
    queryFn: ({ signal }) => api.collection(collectionId, signal),
    enabled: Boolean(collectionId),
  });
  const goals = useQuery({
    queryKey: ["goals", "list"],
    queryFn: ({ signal }) => api.goals(signal),
    enabled: editing,
  });
  const save = useMutation({
    mutationFn: () => api.patchCollection(collectionId, { name: name.trim(), goal_ids: memberIds }),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: ["collection", collectionId] });
      void queryClient.invalidateQueries({ queryKey: ["goals", "dashboard"] });
    },
  });
  const renameSuggestion = useMutation({
    mutationFn: () => api.patchCollection(collectionId, { name: "Personal" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["collection", collectionId] });
      void queryClient.invalidateQueries({ queryKey: ["goals", "dashboard"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteCollection(collectionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["goals"] });
      void navigate("/markets");
    },
  });

  if (collection.isLoading) return <main className="markets-page"><section className="markets-shell"><p role="status">Loading collection…</p></section></main>;

  const view = collection.data;
  if (!view) return <main className="markets-page"><section className="markets-shell"><p role="alert">Collection unavailable.</p></section></main>;
  const hasHistory = view.series.some((item) => item.points.length > 0);
  const hasTrajectory = view.series.some((item) => item.points.length > 1);
  const startEditing = () => {
    setName(view.collection.name);
    setMemberIds(view.collection.goal_ids);
    setEditing(true);
  };
  return (
    <main className="markets-page collection-detail-page">
      <section className="markets-shell">
        <button type="button" className="evidence-back" onClick={() => { void navigate("/markets"); }}>← Your outcomes</button>
        <header className="markets-header">
          <h1>{view.collection.name}</h1>
          <div className="markets-toolbar">
            <button type="button" className="markets-select" onClick={startEditing}>Edit</button>
            <button type="button" className="markets-select" onClick={() => setConfirmDelete(true)}>Delete</button>
          </div>
        </header>
        {view.collection.name === "Acceptance test collection" ? <div className="collection-rename-offer"><span>Rename this collection to Personal?</span><button type="button" className="markets-select" disabled={renameSuggestion.isPending} onClick={() => renameSuggestion.mutate()}>Rename</button>{renameSuggestion.isError ? <span role="alert">Personal already exists, or the rename could not be saved.</span> : null}</div> : null}
        <section className={`collection-detail-chart${hasHistory ? hasTrajectory ? "" : " is-sparse" : " is-empty"}`} aria-label="Collection odds">
          <div className="market-price">{view.portfolio_odds == null ? "—" : `${view.portfolio_odds.toFixed(0)}%`}</div>
          <div className="market-price-hint">{view.change_pp == null ? "—" : `${view.change_pp >= 0 ? "+" : ""}${view.change_pp.toFixed(1)} percentage points today`}</div>
          {hasHistory ? <CollectionChart series={view.series} interactive /> : null}
        </section>
        <details className="collection-details">
          <summary>Goals and calculation</summary>
          <p>{view.portfolio_methodology} {view.priced_goals} of {view.total_goals} goals have published odds.</p>
          <ul className="collection-goal-list">
            {view.series.map((item) => (
              <li key={item.goal_id}>
                <button type="button" onClick={() => { void navigate(`/goals/${item.goal_id}`); }}>
                  <i style={{ background: item.color }} />{item.title}
                  {item.points.at(-1) ? ` · ${item.points.at(-1)!.value.toFixed(1)}%` : " · —"}
                </button>
              </li>
            ))}
          </ul>
        </details>
      </section>
      {editing ? (
        <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="edit-collection-title">
          <form className="confirm-card collection-editor" onSubmit={(event) => { event.preventDefault(); if (name.trim()) save.mutate(); }}>
            <h2 id="edit-collection-title">Edit collection</h2>
            <label htmlFor="edit-collection-name">Name</label>
            <input id="edit-collection-name" name="collection_name" className="ui-field" value={name} onChange={(event) => setName(event.target.value)} maxLength={80} />
            <fieldset>
              <legend>Goals</legend>
              {goals.data?.map((goal) => <label key={goal.goal_id} className="collection-editor-goal ui-choice"><input type="checkbox" checked={memberIds.includes(goal.goal_id)} onChange={() => setMemberIds((current) => current.includes(goal.goal_id) ? current.filter((id) => id !== goal.goal_id) : [...current, goal.goal_id])} />{goal.title}</label>)}
            </fieldset>
            {save.isError ? <p role="alert">Could not save collection. Check the name and try again.</p> : null}
            <div className="composer-actions"><button type="submit" className="ui-button" disabled={save.isPending || !name.trim()}>Save</button><button type="button" className="secondary ui-button ui-button-secondary" onClick={() => setEditing(false)}>Cancel</button></div>
          </form>
        </div>
      ) : null}
      {confirmDelete ? (
        <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="delete-collection-title">
          <div className="confirm-card"><h2 id="delete-collection-title">Delete {view.collection.name}?</h2><p>Your goals, evidence and history will stay.</p>
            {remove.isError ? <p role="alert">Could not delete collection.</p> : null}
            <div className="composer-actions"><button type="button" className="danger" disabled={remove.isPending} onClick={() => remove.mutate()}>Delete collection</button><button type="button" className="secondary" onClick={() => setConfirmDelete(false)}>Cancel</button></div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
