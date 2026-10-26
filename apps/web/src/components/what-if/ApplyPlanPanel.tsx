import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { draftPlan } from "../../adapters/planAdoption";
import { api, type StrategyChangesResponse, type WhatIfResult } from "../../api/client";

type Props = {
  goalId: string;
  domain: string;
  priced: StrategyChangesResponse | null;
  result: WhatIfResult | undefined;
  durationWeeks: number;
};

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export default function ApplyPlanPanel({ goalId, domain, priced, result, durationWeeks }: Props) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [weeks, setWeeks] = useState(durationWeeks);
  const [start, setStart] = useState(() => new Date().toISOString().slice(0, 10));
  const startDate = new Date(`${start}T00:00:00`);
  const draft = draftPlan({ priced, result, domain, durationWeeks: weeks, start: Number.isNaN(startDate.getTime()) ? new Date() : startDate });
  const adopt = useMutation({
    mutationFn: () => api.adoptPlan(goalId, draft!.body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["goal-plans", goalId] }),
  });

  if (!draft) return null;
  const context = draft.body.plan_context;

  if (adopt.isSuccess) {
    return (
      <section className="apply-plan is-saved" aria-live="polite">
        <p className="section-label">Planned</p>
        <p>
          Saved “{draft.body.action}” as a plan. It is not progress until you log what you actually did.{" "}
          <Link to={`/goals/${goalId}#plans`}>Track it on the goal page</Link>
        </p>
      </section>
    );
  }

  return (
    <section className="apply-plan" aria-label="Apply this plan">
      {!open ? (
        <div className="apply-plan-row">
          <div>
            <p className="section-label">Ready to try it?</p>
            <p className="apply-plan-copy">Save this scenario as a plan, then check in with what you really did.</p>
          </div>
          <button type="button" className="apply-plan-button" onClick={() => setOpen(true)}>
            Apply this plan
          </button>
        </div>
      ) : (
        <form
          className="apply-plan-form"
          onSubmit={(event) => {
            event.preventDefault();
            adopt.mutate();
          }}
        >
          <p className="section-label">Apply this plan</p>
          <h3>{draft.summary}</h3>
          <div className="apply-plan-fields">
            <label>
              Start
              <input type="date" value={start} onChange={(event) => setStart(event.target.value)} required />
            </label>
            <label>
              For
              <span className="apply-plan-weeks">
                <input type="number" min={1} max={104} value={weeks} onChange={(event) => setWeeks(Number(event.target.value) || 1)} />
                weeks
              </span>
            </label>
          </div>
          <dl className="apply-plan-odds">
            <div><dt>Odds today</dt><dd>{percent(context.baseline_probability)}</dd></div>
            <div><dt>If you follow this plan</dt><dd>{percent(context.scenario_probability)}</dd></div>
            <div><dt>Follow-through used</dt><dd>{percent(context.execution_probability)}</dd></div>
          </dl>
          {context.assumptions_used.length || context.proxy ? (
            <ul className="apply-plan-assumptions">
              {context.proxy ? <li>Uses the application proxy you chose for cold email.</li> : null}
              {context.assumptions_used.map((item) => <li key={item}>{item}</li>)}
            </ul>
          ) : null}
          <p className="apply-plan-note">
            The odds above are a conditional model scenario that assumes the change holds until your deadline, whatever length you
            plan here. Your published forecast only moves when evidence of what you did arrives.
          </p>
          {adopt.isError ? <p className="scenario-error" role="alert">{adopt.error.message}</p> : null}
          <div className="apply-plan-actions">
            <button type="submit" className="apply-plan-button" disabled={adopt.isPending}>
              {adopt.isPending ? "Saving…" : "Save plan"}
            </button>
            <button type="button" className="text-action" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </form>
      )}
    </section>
  );
}
