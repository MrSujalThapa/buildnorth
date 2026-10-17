import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { toMarketCard } from "../adapters/marketViewModel";
import MarketsPage from "../components/market/MarketsPage";

export function MarketsRoute() {
  const navigate = useNavigate();
  const goals = useQuery({ queryKey: ["goals"], queryFn: ({ signal }) => api.goals(signal) });

  const historyQueries = useQueries({
    queries: (goals.data ?? []).map((goal) => ({
      queryKey: ["market-history", goal.goal_id],
      queryFn: ({ signal }: { signal?: AbortSignal }) => api.marketHistory(goal.goal_id, signal),
      enabled: Boolean(goal.goal_id),
    })),
  });

  const markets = useMemo(() => {
    if (!goals.data) return [];
    return goals.data.map((goal, index) => {
      const query = historyQueries[index];
      return {
        ...toMarketCard(goal, query?.data ?? []),
        historyUnavailable: Boolean(query?.isError),
      };
    });
  }, [goals.data, historyQueries]);

  if (goals.isLoading) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <p role="status">Loading markets from backend…</p>
        </section>
      </main>
    );
  }

  if (goals.isError) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <div className="unpriced-state">
            <strong>Markets unavailable</strong>
            <span>Could not reach GET /api/v1/goals.</span>
          </div>
        </section>
      </main>
    );
  }

  return (
    <MarketsPage
      markets={markets}
      onSelectMarket={(marketId) => { void navigate(`/goals/${marketId}`); }}
    />
  );
}
