import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import CollectionChart from "../components/market/CollectionChart";
import { api } from "../api/client";

export function CollectionDetailRoute() {
  const { collectionId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const collection = useQuery({
    queryKey: ["collection", collectionId],
    queryFn: ({ signal }) => api.collection(collectionId, signal),
    enabled: Boolean(collectionId),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteCollection(collectionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["goals"] });
      void navigate("/markets");
    },
  });

  if (collection.isLoading) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <p role="status">Loading collection…</p>
        </section>
      </main>
    );
  }

  if (collection.isError || !collection.data) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <div className="unpriced-state">
            <strong>Collection not found</strong>
            <span>This collection is unavailable.</span>
          </div>
        </section>
      </main>
    );
  }

  const view = collection.data;
  const progress = view.progress.value;
  return (
    <main className="markets-page">
      <section className="markets-shell">
        <button type="button" className="evidence-back" onClick={() => { void navigate("/markets"); }}>
          ← Back to markets
        </button>
        <header className="markets-header">
          <div className="markets-eyebrow">COLLECTION</div>
          <h1>{view.collection.name}</h1>
          <p>
            {view.collection.description || "A portfolio of related goals. The figure below is progress, not the chance that every goal completes."}
          </p>
        </header>
        <section className="collection-detail-chart">
          <div className="market-price">
            {progress == null ? "—" : `${Math.round(progress * 100)}%`}
          </div>
          <div className="market-price-hint">
            Collection progress · {view.progress.available}/{view.progress.total} goals measured
          </div>
          <CollectionChart series={view.series} />
          <p className="field-hint">{view.progress.methodology}</p>
        </section>
        <ul className="collection-goal-list">
          {view.collection.goal_ids.length === 0 ? (
            <li className="unpriced-state">
              <strong>No goals in this collection</strong>
              <span>Use Select on Markets to move goals here.</span>
            </li>
          ) : (
            view.series.map((item) => (
              <li key={item.goal_id}>
                <button type="button" onClick={() => { void navigate(`/goals/${item.goal_id}`); }}>
                  <i style={{ background: item.color }} />
                  {item.title}
                  {item.withheld ? " · withheld" : ""}
                </button>
              </li>
            ))
          )}
        </ul>
        <button type="button" className="secondary" onClick={() => remove.mutate()}>
          Delete collection (keeps goals)
        </button>
      </section>
    </main>
  );
}
