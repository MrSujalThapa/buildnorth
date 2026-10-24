import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { publishedHistoryPoints, toMarketDetail } from "../adapters/marketViewModel";
import { api, type WorkflowSnapshot } from "../api/client";
import { EvidenceSourceWorkspace, formatProbability } from "../features/goals/EvidenceSourceWorkspace";

export function EvidenceRoute() {
  const { goalId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const initialSnapshot = (location.state as { snapshot?: WorkflowSnapshot } | null)?.snapshot ?? null;

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

  const latestProbability = publishedHistoryPoints(history.data ?? []).at(-1)?.probability ?? null;

  if (goal.isLoading || history.isLoading) {
    return (
      <main className="evidence-page">
        <div className="evidence-shell">
          <p role="status">Loading evidence workspace…</p>
        </div>
      </main>
    );
  }

  if (goal.isError || !goal.data) {
    return (
      <main className="evidence-page">
        <div className="evidence-shell">
          <div className="unpriced-state">
            <strong>Goal not found</strong>
            <span>Goal {goalId} is unavailable.</span>
          </div>
        </div>
      </main>
    );
  }

  if (history.isError) {
    return (
      <main className="evidence-page">
        <div className="evidence-shell">
          <div className="unpriced-state">
            <strong>History unavailable</strong>
            <span>Could not load published forecast history for this goal.</span>
          </div>
        </div>
      </main>
    );
  }

  const publication = toMarketDetail(goal.data, history.data ?? [], []).publication;

  return (
    <EvidenceSourceWorkspace
      goalId={goalId}
      goalTitle={goal.data.title}
      forecastLabel={publication?.status === "withheld" ? "Withheld" : formatProbability(latestProbability)}
      onBack={() => {
        void navigate(`/goals/${goalId}`);
      }}
      initialSnapshot={initialSnapshot}
    />
  );
}
