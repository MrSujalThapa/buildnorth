import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api, type StrategyTrial } from "../../api/client";
import "./next-move.css";

export function StrategyLearningPanel({ goalId }: { goalId: string }) {
  const queryClient = useQueryClient();
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ["strategy-learning", goalId] }); };
  const context = useQuery({
    queryKey: ["strategy-learning", goalId],
    queryFn: ({ signal }) => api.strategyLearning(goalId, signal),
    enabled: Boolean(goalId),
  });
  const generate = useMutation({
    mutationFn: () => api.generateStrategyRecommendation(goalId),
    onSuccess: refresh,
  });
  const feedback = useMutation({
    mutationFn: (body: { recommendationId: string; decision: "accepted" | "declined" }) =>
      api.strategyRecommendationFeedback(goalId, body.recommendationId, body.decision),
    onSuccess: refresh,
  });
  const outcome = useMutation({
    mutationFn: (body: { recommendationId: string; attempted: boolean }) =>
      api.strategyRecommendationOutcome(goalId, body.recommendationId, body.attempted),
    onSuccess: refresh,
  });

  const trials = context.data?.past_trials ?? [];
  const generated = generate.data;
  const pending =
    trials.find((trial) => trial.decision === "pending") ??
    (generated?.decision === "pending" &&
    !trials.some((trial) => trial.recommendation_id === generated.recommendation_id)
      ? generated
      : undefined);
  const awaitingOutcome = pending
    ? undefined
    : trials.find((trial) => trial.decision === "accepted" && (!trial.outcome_status || trial.outcome_status === "not_observed"));
  const latest = trials[0];

  return (
    <section className="next-move" aria-labelledby="next-move-heading">
      <header>
        <p className="next-move-kicker">Your next move</p>
        {!pending && !awaitingOutcome ? (
          <button type="button" className="ui-button" disabled={generate.isPending} onClick={() => generate.mutate()}>
            {generate.isPending ? "Thinking…" : trials.length ? "Suggest another" : "Suggest a next move"}
          </button>
        ) : null}
      </header>
      {context.isError ? <p role="alert">Your past moves could not be loaded.</p> : null}
      {pending ? (
        <MoveCard trial={pending}>
          <button type="button" className="ui-button" disabled={feedback.isPending} onClick={() => feedback.mutate({ recommendationId: pending.recommendation_id, decision: "accepted" })}>
            Accept
          </button>
          <button type="button" className="ui-button ui-button-secondary" disabled={feedback.isPending} onClick={() => feedback.mutate({ recommendationId: pending.recommendation_id, decision: "declined" })}>
            Dismiss
          </button>
        </MoveCard>
      ) : awaitingOutcome ? (
        <MoveCard trial={awaitingOutcome} status="Accepted. Did you do it?">
          <button type="button" className="ui-button" disabled={outcome.isPending} onClick={() => outcome.mutate({ recommendationId: awaitingOutcome.recommendation_id, attempted: true })}>
            I did it
          </button>
          <button type="button" className="ui-button ui-button-secondary" disabled={outcome.isPending} onClick={() => outcome.mutate({ recommendationId: awaitingOutcome.recommendation_id, attempted: false })}>
            Didn’t get to it
          </button>
        </MoveCard>
      ) : (
        <h2 id="next-move-heading" className="next-move-empty">
          {latest ? `Last move: ${latest.action}` : "No move suggested yet."}
        </h2>
      )}
      {generate.isError ? <p role="alert">{generate.error instanceof Error ? generate.error.message : "Could not suggest a move."}</p> : null}
      {feedback.isError || outcome.isError ? <p role="alert">Your answer could not be saved. Try again.</p> : null}
      <details className="next-move-details">
        <summary>Details</summary>
        <p>
          {context.data?.note ?? "Recording what you tried helps PlayItOut learn which moves fit you. It is not proof that a move caused an outcome."}
        </p>
      </details>
    </section>
  );
}

function MoveCard({ trial, status, children }: { trial: StrategyTrial; status?: string; children: ReactNode }) {
  return (
    <div className="next-move-card">
      {status ? <p className="next-move-status" role="status">{status}</p> : null}
      <h2 id="next-move-heading">{trial.action}</h2>
      {trial.why_now ? <p>{trial.why_now}</p> : null}
      {trial.next_step ? <p><strong>First step:</strong> {trial.next_step}</p> : null}
      <div className="next-move-actions">{children}</div>
    </div>
  );
}
