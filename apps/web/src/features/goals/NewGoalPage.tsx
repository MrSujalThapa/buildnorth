import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type WorkflowSnapshot } from "../../api/client";
import { AgentDebug, AgentProgress } from "../agents/AgentProgress";
import "./new-goal.css";

export function NewGoalPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [intent, setIntent] = useState("");
  const [snapshot, setSnapshot] = useState<WorkflowSnapshot | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const start = useMutation({
    mutationFn: () => api.startThread({ kind: "create_goal", intent }),
    onSuccess: (data) => {
      setSnapshot(data);
      setError(null);
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
      return api.resumeThread(snapshot.thread_id, body);
    },
    onSuccess: (data) => {
      setSnapshot(data);
      setError(null);
      setAnswers({});
      if (data.goal && (data.status === "completed" || data.status === "limited" || data.status === "withheld")) {
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
      {!interrupt ? (
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
      {error ? (
        <div className="notice" role="alert">
          <h2>Workflow unavailable</h2>
          <p>{error}</p>
          <Link to="/settings#inference-heading">Check inference settings</Link>
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
