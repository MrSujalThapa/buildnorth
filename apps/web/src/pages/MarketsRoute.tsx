import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { absoluteUrl, shareLink } from "../features/social/share";
import { toMarketCard } from "../adapters/marketViewModel";
import MarketsPage from "../components/market/MarketsPage";

export function MarketsRoute() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const dashboard = useQuery({
    queryKey: ["goals", "dashboard"],
    queryFn: ({ signal }) => api.goalsDashboard(signal),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  const source = dashboard.data;
  const markets = useMemo(() => {
    const goals = source?.goals ?? [];
    const histories = source?.histories ?? {};
    return goals.map((goal) => ({
      ...toMarketCard(goal, histories[goal.goal_id] ?? [], source?.creation_states?.[goal.goal_id]),
      historyUnavailable: false,
    }));
  }, [source]);

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

  if (dashboard.isLoading && !dashboard.data) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <p role="status">Loading your outcomes…</p>
        </section>
      </main>
    );
  }

  if (dashboard.isError && !dashboard.data) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <div className="unpriced-state">
            <strong>Outcomes unavailable</strong>
            <span>Could not load your goals. Check your connection and try again.</span>
          </div>
        </section>
      </main>
    );
  }

  return (
    <MarketsPage
      markets={markets}
      collections={source?.collections ?? []}
      onSelectMarket={(marketId) => {
        void navigate(`/goals/${marketId}`);
      }}
      onOpenCollection={(collectionId) => {
        void navigate(`/collections/${collectionId}`);
      }}
      onCreateCollection={(name) => createCollection.mutateAsync(name).then(() => undefined)}
      onArchiveGoals={(goalIds) => archiveGoals.mutateAsync(goalIds).then(() => undefined)}
      onDeleteCollections={(ids) => deleteCollections.mutateAsync(ids).then(() => undefined)}
      onMoveToCollection={(collectionId, goalIds) =>
        moveGoals.mutateAsync({ collectionId, goalIds }).then(() => undefined)
      }
      onShareMarkets={async (goalIds) => {
        const goalId = goalIds[0];
        if (!goalId) return;
        const result = await api.shareMarket(goalId);
        if (!result.shareable) {
          window.alert(result.reason ?? "Publish this market before sharing a public link.");
          return;
        }
        await shareLink({
          url: result.url ?? absoluteUrl(`/m/${goalId}`),
          title: markets.find((market) => market.id === goalId)?.title ?? "PlayItOut market",
        });
      }}
    />
  );
}
