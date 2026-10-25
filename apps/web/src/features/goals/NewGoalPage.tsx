import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type WorkflowSnapshot } from "../../api/client";
import { AgentDebug, AgentProgress } from "../agents/AgentProgress";
import "./new-goal.css";

const PENDING_GOAL_THREAD = "playitout:pending-goal-thread";

function failureMessage(snapshot: WorkflowSnapshot): string {
  if (snapshot.goal && snapshot.debug?.goal_committed === true) {
    return "Your goal was saved, but evidence processing stopped. You can open the goal and try updating it later.";
  }
  return snapshot.debug?.failure_code === "workflow_timeout"
    ? "This attempt timed out. Check your inference settings, then try again."
    : "The agent workflow failed. Check inference settings and try again.";
}

export function NewGoalPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [intent, setIntent] = useState("");
  const [snapshot, setSnapshot] = useState<WorkflowSnapshot | null>(null);
  const [threadId, setThreadId] = useState(() => sessionStorage.getItem(PENDING_GOAL_THREAD));
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const thread = useQuery({
    queryKey: ["new-goal-thread", threadId],
    queryFn: () => api.getThread(threadId!),
    enabled: Boolean(threadId),
    refetchInterval: (query) =>
      ["running", "evidence_pending", "evidence_running"].includes(String(query.state.data?.status ?? ""))
        ? 2000
        : false,
  });

  useEffect(() => {
    const data = thread.data;
    if (!data || data.thread_id !== threadId) return;
    setSnapshot(data);
    if (data.status === "failed") setError(failureMessage(data));
    if (["completed", "limited", "withheld", "failed", "cancelled"].includes(data.status)) {
      sessionStorage.removeItem(PENDING_GOAL_THREAD);
      setThreadId(null);
    }
    if (data.goal && ["evidence_pending", "evidence_running", "evidence_failed", "completed", "limited", "withheld"].includes(data.status)) {
      void queryClient.invalidateQueries({ queryKey: ["goals"] });
      void queryClient.invalidateQueries({ queryKey: ["goals", "dashboard"] });
      void navigate(`/goals/${data.goal.goal_id}`, { state: { snapshot: data } });
    }
  }, [navigate, queryClient, thread.data, threadId]);

  const start = useMutation({
    mutationFn: () => api.startThreadAsync({ kind: "create_goal", intent }),
    onSuccess: (data) => {
      setSnapshot(data);
      sessionStorage.setItem(PENDING_GOAL_THREAD, data.thread_id);
      setThreadId(data.thread_id);
      setError(null);
      if (data.status === "failed") {
        setError(failureMessage(data));
        return;
      }
      if (data.status === "completed" || data.status === "limited" || data.status === "withheld") {
        void queryClient.invalidateQueries({ queryKey: ["goals"] });
        void queryClient.invalidateQueries({ queryKey: ["goals", "dashboard"] });
        if (data.goal) void navigate(`/goals/${data.goal.goal_id}`, { state: { snapshot: data } });
      }
    },
    onError: (caught) => setError(caught instanceof Error ? caught.message : "The agent workflow could not start."),
  });

  const resume = useMutation({
    mutationFn: (body: { answers?: Record<string, string>; confirmed?: boolean; cancelled?: boolean }) => {
      if (!snapshot) throw new Error("missing thread");
      return api.resumeThreadAsync(snapshot.thread_id, body);
    },
    onSuccess: (data) => {
      setSnapshot(data);
      sessionStorage.setItem(PENDING_GOAL_THREAD, data.thread_id);
      setThreadId(data.thread_id);
      setError(null);
      setAnswers({});
      if (data.status === "failed") {
        setError(failureMessage(data));
        return;
      }
      if (data.goal && ["evidence_pending", "evidence_running", "evidence_failed", "completed", "limited", "withheld"].includes(data.status)) {
        void queryClient.invalidateQueries({ queryKey: ["goals"] });
        void queryClient.invalidateQueries({ queryKey: ["goals", "dashboard"] });
        void navigate(`/goals/${data.goal.goal_id}`, { state: { snapshot: data } });
      }
    },
    onError: (caught) => setError(caught instanceof Error ? caught.message : "Could not continue this workflow."),
  });

  const interrupt = snapshot?.interrupt;
  const busy = start.isPending || resume.isPending;

  return (
    <section className="goal-composer" aria-labelledby="new-goal-title">
      <div className="page-heading">
        <div>
          <h1 id="new-goal-title">New market</h1>
          <p>Describe an outcome. The system will formalize it before anything is priced.</p>
        </div>
      </div>
      {!interrupt && snapshot?.status !== "running" && !(snapshot?.status === "failed" && snapshot.debug?.goal_committed === true) ? (
        <form
          className="composer-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (intent.trim().length >= 8) start.mutate();
          }}
        >
          <label htmlFor="intent">What should happen?</label>
          <textarea
            id="intent"
            name="intent"
            rows={5}
            value={intent}
            onChange={(event) => setIntent(event.target.value)}
            placeholder="I want to receive an SWE/FDE offer from one of my target companies by August 2027."
          />
          <button type="submit" disabled={busy || intent.trim().length < 8}>
            {busy ? "Understanding goal…" : "Create market"}
          </button>
        </form>
      ) : null}
      <AgentProgress snapshot={snapshot} />
      {snapshot?.status === "running" ? <p className="field-hint" role="status">Working on your goal…</p> : null}
      {thread.isError ? <p className="field-hint" role="alert">Could not check progress. Reload this page to try again.</p> : null}
      {error ? (
        <div className="notice" role="alert">
          <h2>Workflow unavailable</h2>
          <p>{error}</p>
          <div className="notice-actions">
            {snapshot?.status === "failed" && snapshot.goal && snapshot.debug?.goal_committed === true ? (
              <Link to={`/goals/${snapshot.goal.goal_id}`}>Open saved goal</Link>
            ) : null}
            <Link to="/settings#inference-heading">Check inference settings</Link>
          </div>
        </div>
      ) : null}
      {interrupt?.type === "clarification" ? (
        <form
          className="composer-form"
          onSubmit={(event) => {
            event.preventDefault();
            resume.mutate({ answers });
          }}
        >
          <p>{interrupt.message}</p>
          {interrupt.questions.map((question) => (
            <label key={question.id} htmlFor={question.id}>
              {question.question}
              <input
                id={question.id}
                value={answers[question.id] ?? ""}
                onChange={(event) => setAnswers((current) => ({ ...current, [question.id]: event.target.value }))}
              />
              <span className="field-hint">{question.why_needed}</span>
            </label>
          ))}
          <div className="composer-actions">
            <button type="submit" disabled={busy}>
              Continue
            </button>
            <button type="button" className="secondary" onClick={() => resume.mutate({ cancelled: true })}>
              Cancel
            </button>
          </div>
        </form>
      ) : null}
      {interrupt?.type === "confirm_contract" && interrupt.proposal ? (
        <div className="contract-preview">
          <h2>Proposed contract</h2>
          <p>{String(interrupt.proposal.title)}</p>
          <p className="market-kicker">
            {String(interrupt.proposal.goal_type)} · {String(interrupt.proposal.success_metric)}{" "}
            {String(interrupt.proposal.success_operator)} {String(interrupt.proposal.success_target)} · by{" "}
            {String(interrupt.proposal.deadline)}
          </p>
          <div className="composer-actions">
            <button type="button" disabled={busy} onClick={() => resume.mutate({ confirmed: true })}>
              Confirm
            </button>
            <button type="button" className="secondary" onClick={() => resume.mutate({ cancelled: true })}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
      <AgentDebug snapshot={snapshot} />
    </section>
  );
}
