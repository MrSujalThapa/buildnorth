import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, type WorkflowSnapshot } from "../api/client";
import { absoluteUrl, shareLink } from "../features/social/share";
import { isCourseStandingGoal } from "../adapters/courseGrade";
import { currentForecastStatus, toMarketDetail } from "../adapters/marketViewModel";
import CourseStandingPanel from "../components/market/CourseStandingPanel";
import MarketDetailPage from "../components/market/MarketDetailPage";
import "../components/social/social.css";

export function GoalDetailRoute() {
  const { goalId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const location = useLocation();
  const initialSnapshot = (location.state as { snapshot?: WorkflowSnapshot } | null)?.snapshot ?? null;
  const [workflowSnapshot] = useState<WorkflowSnapshot | null>(initialSnapshot);
  const [evidenceAnswers, setEvidenceAnswers] = useState<Record<string, string>>({});
  const [publishOpen, setPublishOpen] = useState(false);
  const [shareNote, setShareNote] = useState<string | null>(null);
  const continuation = useQuery({
    queryKey: ["goal-evidence-continuation", goalId],
    queryFn: ({ signal }) => api.goalEvidenceContinuation(goalId, signal),
    enabled: Boolean(goalId),
    refetchInterval: (query) => ["evidence_pending", "evidence_running"].includes(query.state.data?.status ?? "") ? 2000 : false,
  });
  const retryEvidence = useMutation({
    mutationFn: (threadId: string) => api.retryGoalEvidence(threadId),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["goal-evidence-continuation", goalId] }); },
  });
  const resumeEvidence = useMutation({
    mutationFn: (threadId: string) => api.resumeThreadAsync(threadId, { answers: evidenceAnswers }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["goal-evidence-continuation", goalId] }); },
  });
  useEffect(() => {
    if (["completed", "limited", "withheld"].includes(continuation.data?.status ?? "")) {
      void queryClient.invalidateQueries({ queryKey: ["goal", goalId] });
      void queryClient.invalidateQueries({ queryKey: ["market-history", goalId] });
      void queryClient.invalidateQueries({ queryKey: ["evidence", goalId] });
    }
  }, [continuation.data?.status, goalId, queryClient]);
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
  const social = useQuery({
    queryKey: ["market-social", goalId],
    queryFn: ({ signal }) => api.marketSocial(goalId, signal),
    enabled: Boolean(goalId),
  });
  const publish = useMutation({
    mutationFn: (visibility: "public" | "private") => api.setMarketVisibility(goalId, visibility),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["market-social", goalId] });
      void queryClient.invalidateQueries({ queryKey: ["goals"] });
      setPublishOpen(false);
    },
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
  const latestWorkflow = continuation.data ?? workflowSnapshot;
  const status = currentForecastStatus(
    latestWorkflow ? { status: latestWorkflow.status, critic_decision: latestWorkflow.critic?.decision } : null,
    market.publication?.status,
  );
  market.currentForecastStatus = continuation.isError ? "unavailable" : status;
  if (market.currentForecastStatus !== "published") market.odds = null;

  return (
    <>
      <MarketDetailPage
        market={market}
        criticDecision={status === "withheld" ? "withhold" : latestWorkflow?.critic?.decision}
        onBack={() => { void navigate("/markets"); }}
        onWhatIf={() => { void navigate(`/goals/${goalId}/what-if`); }}
        onEvidence={() => { void navigate(`/goals/${goalId}/evidence`); }}
        onShare={() => {
          void api.shareMarket(goalId).then((result) => {
            if (!result.shareable) {
              setShareNote(result.reason ?? "Publish this market before sharing.");
              setPublishOpen(true);
              return;
            }
            return shareLink({ url: result.url ?? absoluteUrl(`/m/${goalId}`), title: market.title }).then((mode) => {
              setShareNote(mode === "copied" ? "Link copied" : "Shared");
            });
          }).catch(() => setShareNote("Could not share this market."));
        }}
      >
        <div className="public-actions">
          <button type="button" className="secondary-action" onClick={() => setPublishOpen(true)}>
            {social.data?.visibility === "public" ? "Public" : "Private"} · Visibility
          </button>
        </div>
        {isCourseStandingGoal(goal.data) ? <CourseStandingPanel /> : null}
        {latestWorkflow?.status === "evidence_pending" || latestWorkflow?.status === "evidence_running" ? (
          <div role="status">
            <p>Goal saved. Evidence interpretation is pending; no new odds have been published.</p>
            {latestWorkflow.status === "evidence_pending" ? (
              <button type="button" disabled={retryEvidence.isPending} onClick={() => retryEvidence.mutate(latestWorkflow.thread_id)}>
                Start evidence interpretation
              </button>
            ) : null}
          </div>
        ) : null}
        {latestWorkflow?.status === "evidence_failed" ? (
          <div className="notice" role="alert">
            <p>Goal saved, but evidence interpretation failed. No new odds were published.</p>
            <button type="button" disabled={retryEvidence.isPending} onClick={() => retryEvidence.mutate(latestWorkflow.thread_id)}>
              Retry evidence interpretation
            </button>
            {retryEvidence.isError ? <p>Retry could not be started. Reload and try again.</p> : null}
          </div>
        ) : null}
        {latestWorkflow?.status === "needs_input" && latestWorkflow.interrupt?.type === "confirm_evidence" ? (
          <form className="notice" onSubmit={(event) => { event.preventDefault(); resumeEvidence.mutate(latestWorkflow.thread_id); }}>
            <p>{latestWorkflow.interrupt.message}</p>
            {latestWorkflow.interrupt.questions.map((question) => (
              <label key={question.id} htmlFor={`evidence-${question.id}`}>
                {question.question}
                <input id={`evidence-${question.id}`} value={evidenceAnswers[question.id] ?? ""}
                  onChange={(event) => setEvidenceAnswers((current) => ({ ...current, [question.id]: event.target.value }))} />
              </label>
            ))}
            <button type="submit" disabled={resumeEvidence.isPending}>Continue evidence interpretation</button>
            {resumeEvidence.isError ? <p role="alert">Could not continue. Please try again.</p> : null}
          </form>
        ) : null}
      </MarketDetailPage>
      {publishOpen ? (
        <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="publish-title">
          <div className="confirm-card">
            <h2 id="publish-title">{social.data?.visibility === "public" ? "Make this market private?" : "Publish this market?"}</h2>
            {social.data?.visibility === "public" ? (
              <p>Public links, marketplace listing, and profile appearance stop immediately. Existing forks stay independent.</p>
            ) : (
              <p>
                Publishing shares the title, public blueprint, and authorized chart history. Private evidence, emails, uploads, and tokens stay private.
              </p>
            )}
            {publish.isError ? <p role="alert">Visibility could not be updated.</p> : null}
            <div className="composer-actions">
              <button
                type="button"
                className="ui-button"
                disabled={publish.isPending}
                onClick={() => publish.mutate(social.data?.visibility === "public" ? "private" : "public")}
              >
                {social.data?.visibility === "public" ? "Make private" : "Publish"}
              </button>
              <button type="button" className="secondary" onClick={() => setPublishOpen(false)}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}
      {shareNote ? <div className="share-toast" role="status">{shareNote}</div> : null}
    </>
  );
}
