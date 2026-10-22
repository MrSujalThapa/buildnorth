import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { toMarketCard } from "../adapters/marketViewModel";
import MarketsPage from "../components/market/MarketsPage";

export function MarketsRoute() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const demoMode = searchParams.get("demo") === "1";
  const queryClient = useQueryClient();
  const dashboard = useQuery({
    queryKey: ["goals", "dashboard"],
    queryFn: ({ signal }) => api.goalsDashboard(signal),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    enabled: !demoMode,
  });
  const demo = useQuery({
    queryKey: ["demo-portfolio"],
    queryFn: ({ signal }) => api.demoPortfolio(signal),
    enabled: demoMode,
    staleTime: 5 * 60_000,
  });

  const source = demoMode ? demo.data : dashboard.data;
  const markets = useMemo(() => {
    const goals = source?.goals ?? [];
    const histories = source?.histories ?? {};
    return goals.map((goal) => ({
      ...toMarketCard(goal, histories[goal.goal_id] ?? [], { includeSyntheticDemo: demoMode }),
      historyUnavailable: false,
    }));
  }, [demoMode, source]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["goals"] });

  const createCollection = useMutation({
    mutationFn: (name: string) => api.createCollection({ name }),
    onSuccess: invalidate,
  });
  const archiveGoals = useMutation({
    mutationFn: (goalIds: string[]) => api.archiveGoals(goalIds),
    onSuccess: invalidate,
  });
  const moveGoals = useMutation({
    mutationFn: ({ collectionId, goalIds }: { collectionId: string; goalIds: string[] }) =>
      api.addGoalsToCollection(collectionId, goalIds),
    onSuccess: invalidate,
  });
  const deleteCollections = useMutation({
    mutationFn: (ids: string[]) => Promise.all(ids.map((id) => api.deleteCollection(id))),
    onSuccess: invalidate,
  });

  const loading = demoMode ? demo.isLoading && !demo.data : dashboard.isLoading && !dashboard.data;
  const errored = demoMode ? demo.isError && !demo.data : dashboard.isError && !dashboard.data;

  if (loading) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <p role="status">{demoMode ? "Loading demonstration markets…" : "Loading markets from backend…"}</p>
        </section>
      </main>
    );
  }

  if (errored) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <div className="unpriced-state">
            <strong>Markets unavailable</strong>
            <span>
              {demoMode
                ? "Could not reach GET /api/v1/profile/demo-portfolio."
                : "Could not reach GET /api/v1/goals/dashboard."}
            </span>
          </div>
        </section>
      </main>
    );
  }

  return (
    <MarketsPage
      markets={markets}
      collections={source?.collections ?? []}
      demoMode={demoMode}
      demoMessage={demoMode ? demo.data?.message : undefined}
      onToggleDemo={() => {
        const next = new URLSearchParams(searchParams);
        if (demoMode) next.delete("demo");
        else next.set("demo", "1");
        setSearchParams(next);
      }}
      onSelectMarket={(marketId) => {
        void navigate(`/goals/${marketId}${demoMode ? "?demo=1" : ""}`);
      }}
      onOpenCollection={(collectionId) => {
        void navigate(`/collections/${collectionId}${demoMode ? "?demo=1" : ""}`);
      }}
      onCreateCollection={(name) => createCollection.mutateAsync(name).then(() => undefined)}
      onArchiveGoals={(goalIds) => archiveGoals.mutateAsync(goalIds).then(() => undefined)}
      onDeleteCollections={(ids) => deleteCollections.mutateAsync(ids).then(() => undefined)}
      onMoveToCollection={(collectionId, goalIds) =>
        moveGoals.mutateAsync({ collectionId, goalIds }).then(() => undefined)
      }
    />
  );
}
