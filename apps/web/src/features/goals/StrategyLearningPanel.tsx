import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type StrategyTrial } from "../../api/client";

export function StrategyLearningPanel({ goalId }: { goalId: string }) {
  const queryClient = useQueryClient();
  const context = useQuery({
    queryKey: ["strategy-learning", goalId],
    queryFn: ({ signal }) => api.strategyLearning(goalId, signal),
    enabled: Boolean(goalId),
  });
  const generate = useMutation({
    mutationFn: () => api.generateStrategyRecommendation(goalId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["strategy-learning", goalId] });
    },
  });
  const feedback = useMutation({
    mutationFn: (body: { recommendationId: string; decision: "accepted" | "declined" }) =>
      api.strategyRecommendationFeedback(goalId, body.recommendationId, body.decision),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["strategy-learning", goalId] });
    },
  });

  const trials = context.data?.past_trials ?? [];
  const pending =
    trials.find((trial) => trial.decision === "pending") ??
    (generate.data?.decision === "pending" ? generate.data : undefined);

  return (
    <section className="notice" aria-labelledby="strategy-learning-heading">
      <h2 id="strategy-learning-heading">Strategy feedback</h2>
      <p>
        {context.data?.note ??
          "Observed association is not evidence that a recommendation caused an outcome."}
      </p>
      {context.isError ? <p role="alert">Strategy history could not be loaded.</p> : null}
      {pending ? <TrialCard trial={pending} onFeedback={feedback.mutate} busy={feedback.isPending} /> : null}
      {!pending && trials[0] ? (
        <p>
          Latest: {trials[0].action} ({trials[0].decision}
          {trials[0].outcome_status && trials[0].outcome_status !== "not_observed"
            ? ` · ${trials[0].outcome_status}`
            : ""}
          )
        </p>
      ) : null}
      {trials.length === 0 && !context.isLoading ? <p>No strategy trials yet for this goal.</p> : null}
      {generate.isError ? <p role="alert">{generate.error instanceof Error ? generate.error.message : "Could not generate a recommendation."}</p> : null}
      {feedback.isError ? <p role="alert">Feedback could not be saved.</p> : null}
      <button type="button" disabled={generate.isPending || Boolean(pending)} onClick={() => generate.mutate()}>
        {generate.isPending ? "Generating…" : pending ? "Decide on the current recommendation first" : "Suggest a next step"}
      </button>
    </section>
  );
}

function TrialCard({
  trial,
  onFeedback,
  busy,
}: {
  trial: StrategyTrial;
  onFeedback: (body: { recommendationId: string; decision: "accepted" | "declined" }) => void;
  busy: boolean;
}) {
  return (
    <div>
      <p>{trial.action}</p>
      {trial.why_now ? <p>{trial.why_now}</p> : null}
      {trial.next_step ? <p>Next: {trial.next_step}</p> : null}
      <div className="composer-actions">
        <button
          type="button"
          disabled={busy}
          onClick={() => onFeedback({ recommendationId: trial.recommendation_id, decision: "accepted" })}
        >
          I’ll try this
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => onFeedback({ recommendationId: trial.recommendation_id, decision: "declined" })}
        >
          Not now
        </button>
      </div>
    </div>
  );
}
