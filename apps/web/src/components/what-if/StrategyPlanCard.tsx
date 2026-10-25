import { useEffect, useState } from "react";

import type { StrategyLever, StrategyPlan } from "../../api/client";

type Props = {
  plan: StrategyPlan;
  question: string;
  busy?: boolean;
  onRun?: (title: string, lever: StrategyLever, amount: number) => void;
};

function formatAmount(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export default function StrategyPlanCard({ plan, question, busy, onRun }: Props) {
  const lever = plan.levers[0];
  const [amount, setAmount] = useState<number>(plan.stated_quantity ?? lever?.suggested_values[1] ?? 1);

  useEffect(() => {
    setAmount(plan.stated_quantity ?? lever?.suggested_values[1] ?? 1);
  }, [lever, plan.stated_quantity]);

  if (!lever) return null;
  const headroom = lever.maximum != null && lever.baseline_value != null ? lever.maximum - lever.baseline_value : null;
  const valid = amount > 0 && (headroom == null || amount <= headroom);
  const run = (value: number) => {
    setAmount(value);
    onRun?.(`${question.trim() || plan.interpretation} (+${formatAmount(value)} ${lever.unit_label})`, lever, value);
  };

  return (
    <section className="strategy-plan" aria-label="Make this measurable" data-testid="strategy-plan">
      <header className="strategy-plan-head">
        <p className="section-label">{plan.modeled ? "Modeled as" : "Make it measurable"}</p>
        <h2>{plan.interpretation}</h2>
      </header>

      <div className="strategy-lever">
        <div className="strategy-lever-copy">
          <span className="strategy-lever-name">{lever.label}</span>
          <strong>
            {lever.baseline_value == null ? "—" : formatAmount(lever.baseline_value)} <small>{lever.unit} today</small>
          </strong>
          <p>{lever.mapping_note}</p>
        </div>
        <form
          className="strategy-lever-input"
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) run(amount);
          }}
        >
          <label htmlFor="strategy-amount">{lever.question}</label>
          <div className="strategy-amount-row">
            <span aria-hidden="true">+</span>
            <input
              id="strategy-amount"
              type="number"
              min={0}
              step="any"
              max={headroom ?? undefined}
              value={Number.isFinite(amount) ? amount : ""}
              onChange={(event) => setAmount(Number(event.target.value))}
            />
            <span className="strategy-unit">{lever.unit_label}</span>
            <button className="ui-button primary" type="submit" disabled={!valid || busy}>
              {plan.modeled ? "Re-run" : "Run scenario"}
            </button>
          </div>
          {lever.suggested_values.length ? (
            <div className="strategy-quick" role="group" aria-label="Quick amounts">
              {lever.suggested_values.map((value) => (
                <button
                  key={value}
                  type="button"
                  className={value === amount ? "is-selected" : ""}
                  disabled={busy}
                  onClick={() => run(value)}
                >
                  +{formatAmount(value)}
                </button>
              ))}
            </div>
          ) : null}
          {!valid && headroom != null && amount > headroom ? (
            <p className="strategy-warning">The model caps this lever at {formatAmount(lever.maximum ?? 0)} {lever.unit}.</p>
          ) : null}
        </form>
      </div>

      {plan.analysis.length ? (
        <dl className="strategy-analysis">
          {plan.analysis.map((item) => (
            <div key={item.heading}>
              <dt>{item.heading}</dt>
              <dd>{item.body}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {!plan.modeled ? (
        <p className="strategy-footnote">No probability change is assumed until you choose an amount.</p>
      ) : null}
    </section>
  );
}
