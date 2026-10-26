import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { formatQuantity, isOpen, latestObservation, outcomeFor, PLAN_STATE_LABEL, planState } from "../../adapters/planAdoption";
import { api, type PlannedCommitment } from "../../api/client";

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function PlanRow({
  plan,
  observations,
  now,
  onObserve,
  evaluating,
  evaluation,
}: {
  plan: PlannedCommitment;
  observations: Parameters<typeof planState>[1];
  now: Date;
  onObserve: (plan: PlannedCommitment, status: "completed" | "partial" | "missed" | "cancelled", actual?: number) => void;
  evaluating?: boolean;
  evaluation?: { scenario: number | null; baseline: number | null };
}) {
  const [actual, setActual] = useState("");
  const state = planState(plan, observations, now);
  const latest = latestObservation(plan, observations);
  const context = plan.plan_context;
  const open = isOpen(state);

  return (
    <article className={`goal-plan is-${state}`} data-testid="goal-plan">
      <header>
        <p className="section-label">{PLAN_STATE_LABEL[state]}</p>
        <h3>{plan.action}</h3>
        <p>
          {formatQuantity(plan.planned_quantity)} {plan.unit} between{" "}
          {new Date(plan.window_start).toLocaleDateString(undefined, { month: "short", day: "numeric" })} and{" "}
          {new Date(plan.window_end).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
        </p>
      </header>
      {context ? (
        <dl>
          <div>
            <dt>When you applied it</dt>
            <dd>{percent(context.scenario_probability)}</dd>
          </div>
          <div>
            <dt>Re-evaluated today</dt>
            <dd>{evaluating ? "…" : percent(evaluation?.scenario)}</dd>
          </div>
        </dl>
      ) : null}
      {context?.assumptions_used.length ? <p className="goal-plan-note">{context.assumptions_used[0]}</p> : null}
      {context?.proxy ? <p className="goal-plan-note">Uses the application proxy you chose.</p> : null}
      {latest && latest.status !== "unknown" ? (
        <p className="goal-plan-note">
          Last check-in: {latest.status}
          {latest.actual_quantity != null ? ` (${formatQuantity(latest.actual_quantity)} ${plan.unit})` : ""}.
        </p>
      ) : null}
      {open ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const outcome = outcomeFor(plan, Number(actual));
            onObserve(plan, outcome.status, outcome.actual_quantity);
            setActual("");
          }}
        >
          <label>
            How much did you actually do?
            <input type="number" min={0} step="any" value={actual} onChange={(event) => setActual(event.target.value)} required />
            <span>{plan.unit}</span>
          </label>
          <div className="goal-plan-actions">
            <button type="submit">Log what happened</button>
            <button type="button" onClick={() => onObserve(plan, "cancelled")}>Abandon</button>
            <Link to={`/goals/${plan.goal_id}/evidence`}>Add other evidence</Link>
          </div>
        </form>
      ) : (
        <p>
          <Link to={`/goals/${plan.goal_id}/evidence`}>Log related evidence</Link>
        </p>
      )}
    </article>
  );
}

export default function GoalPlansPanel({ goalId }: { goalId: string }) {
  const queryClient = useQueryClient();
  const now = new Date();
  const plans = useQuery({
    queryKey: ["goal-plans", goalId],
    queryFn: () => api.listPlans(goalId),
    enabled: Boolean(goalId),
  });
  const evaluate = useQuery({
    queryKey: ["goal-plan-evals", goalId, plans.data?.commitments.map((item) => item.id).join(",")],
    enabled: Boolean(plans.data?.commitments.some((item) => item.plan_context?.changes.length)),
    queryFn: async () => {
      const rows = await Promise.all(
        (plans.data?.commitments ?? [])
          .filter((item) => item.plan_context?.changes.length)
          .map(async (item) => {
            const result = await api.evaluatePlan({
              goal_id: goalId,
              changes: item.plan_context!.changes.map((change) => ({
                metric: change.metric,
                operation: change.operation,
                value: change.value,
                unit: change.unit,
                frequency: change.frequency ?? null,
                scope: "goal_state",
                provenance: "USER_ASSUMPTION",
              })),
            });
            return [item.id, { scenario: result.scenario_probability, baseline: result.baseline_probability }] as const;
          }),
      );
      return Object.fromEntries(rows);
    },
  });
  const observe = useMutation({
    mutationFn: (args: { plan: PlannedCommitment; status: "completed" | "partial" | "missed" | "cancelled"; actual?: number }) =>
      api.observePlan(goalId, args.plan.id, {
        status: args.status,
        actual_quantity: args.status === "cancelled" ? null : args.actual ?? 0,
        observed_at: new Date().toISOString(),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["goal-plans", goalId] }),
  });

  const items = plans.data?.commitments ?? [];
  if (!items.length) return null;

  return (
    <section className="goal-plans" id="plans" aria-labelledby="goal-plans-title">
      <header>
        <p className="section-label">Plans</p>
        <h2 id="goal-plans-title">What you said you would do</h2>
        <p>These are planned actions, not evidence. Observed check-ins stay separate from the published forecast until you log them as evidence.</p>
      </header>
      {items.map((plan) => (
        <PlanRow
          key={plan.id}
          plan={plan}
          observations={plans.data?.observations ?? []}
          now={now}
          evaluating={evaluate.isFetching}
          evaluation={evaluate.data?.[plan.id]}
          onObserve={(item, status, actual) => observe.mutate({ plan: item, status, actual })}
        />
      ))}
      {observe.isError ? <p role="alert">{observe.error.message}</p> : null}
    </section>
  );
}
