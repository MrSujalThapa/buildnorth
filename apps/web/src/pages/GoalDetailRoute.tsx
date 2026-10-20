import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, type WorkflowSnapshot } from "../api/client";
import { toMarketDetail } from "../adapters/marketViewModel";
import MarketDetailPage from "../components/market/MarketDetailPage";

export function GoalDetailRoute() {
  const { goalId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const initialSnapshot = (location.state as { snapshot?: WorkflowSnapshot } | null)?.snapshot ?? null;
  const [workflowSnapshot] = useState<WorkflowSnapshot | null>(initialSnapshot);
  const goal = useQuery({
    queryKey: ["goal", goalId],
    queryFn: ({ signal }) => api.goal(goalId, signal),
    enabled: Boolean(goalId),
  });
  const history = useQuery({
    queryKey: ["market-history", goalId],
    queryFn: ({ signal }) => api.marketHistory(goalId, signal),
    enabled: Boolean(goalId),
  });
  const evidence = useQuery({
    queryKey: ["evidence", goalId],
    queryFn: ({ signal }) => api.evidence(goalId, signal),
    enabled: Boolean(goalId),
  });

  if (goal.isLoading || history.isLoading) {
    return (
      <main className="market-page">
        <section className="market-shell">
          <p role="status">Loading market detail…</p>
        </section>
      </main>
    );
  }

  if (goal.isError || !goal.data) {
    return (
      <main className="market-page">
        <section className="market-shell">
          <div className="unpriced-state">
            <strong>Market not found</strong>
            <span>Goal {goalId} is unavailable.</span>
          </div>
        </section>
      </main>
    );
  }

  if (history.isError) {
    return (
      <main className="market-page">
        <section className="market-shell">
          <div className="unpriced-state">
            <strong>History unavailable</strong>
            <span>Could not load published forecast history for this goal.</span>
          </div>
        </section>
      </main>
    );
  }

  const market = toMarketDetail(goal.data, history.data ?? [], evidence.data ?? []);
  const withheld =
    workflowSnapshot?.critic?.decision === "withhold" || market.publication?.status === "withheld";

  return (
    <>
      <MarketDetailPage
        market={market}
        criticDecision={withheld ? "withhold" : workflowSnapshot?.critic?.decision}
        onBack={() => { void navigate("/markets"); }}
        onWhatIf={() => { void navigate(`/goals/${goalId}/what-if`); }}
        onEvidence={() => { void navigate(`/goals/${goalId}/evidence`); }}
      />
    </>
  );
}