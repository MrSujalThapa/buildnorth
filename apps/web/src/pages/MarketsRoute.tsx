import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
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

  const markets = useMemo(() => {
    const goals = dashboard.data?.goals ?? [];
    const histories = dashboard.data?.histories ?? {};
    return goals.map((goal) => ({
      ...toMarketCard(goal, histories[goal.goal_id] ?? []),
      historyUnavailable: false,
    }));
  }, [dashboard.data]);

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

  if (dashboard.isLoading && !dashboard.data) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <p role="status">Loading markets from backend…</p>
        </section>
      </main>
    );
  }

  if (dashboard.isError && !dashboard.data) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <div className="unpriced-state">
            <strong>Markets unavailable</strong>
            <span>Could not reach GET /api/v1/goals/dashboard.</span>
          </div>
        </section>
      </main>
    );
  }

  return (
    <MarketsPage
      markets={markets}
      collections={dashboard.data?.collections ?? []}
      onSelectMarket={(marketId) => { void navigate(`/goals/${marketId}`); }}
      onOpenCollection={(collectionId) => { void navigate(`/collections/${collectionId}`); }}
      onCreateCollection={(name) => createCollection.mutateAsync(name).then(() => undefined)}
      onArchiveGoals={(goalIds) => archiveGoals.mutateAsync(goalIds).then(() => undefined)}
      onMoveToCollection={(collectionId, goalIds) =>
        moveGoals.mutateAsync({ collectionId, goalIds }).then(() => undefined)
      }
    />
  );
}
