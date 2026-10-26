import { useEffect, useMemo, useState } from "react";

import type { StrategyInput, StrategyOption, StrategyPlan } from "../../api/client";

type Props = {
  plan: StrategyPlan;
  question: string;
  busy?: boolean;
  onRun?: (question: string, plan: StrategyPlan, optionId: string, inputs: Record<string, number>) => void;
};

function formatAmount(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function initialValues(option: StrategyOption | undefined, plan: StrategyPlan) {
  const values: Record<string, string> = {};
  for (const input of option?.inputs ?? []) {
    const stated = input.value ?? (input.key === "amount" ? plan.stated_quantity : null);
    const fallback = input.key === "amount" ? input.suggested_values[1] ?? input.suggested_values[0] : undefined;
    const value = stated ?? fallback;
    values[input.key] = value == null ? "" : String(value);
  }
  return values;
}

function inputError(input: StrategyInput, raw: string) {
  if (raw === "") return input.required ? "Required" : null;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) return "Enter a number of zero or more";
  if (input.key === "amount" && value <= 0) return "Enter an amount above zero";
  if (input.maximum != null && value > input.maximum) return `The model supports at most ${formatAmount(input.maximum)} ${input.unit}`;
  return null;
}

export default function StrategyPlanCard({ plan, question, busy, onRun }: Props) {
  const options = plan.options ?? [];
  const onlyOption = options.length === 1 ? options[0]?.id ?? null : null;
  const [optionId, setOptionId] = useState<string | null>(plan.selected_option ?? onlyOption);
  const option = options.find((item) => item.id === optionId);
  const [values, setValues] = useState<Record<string, string>>(() => initialValues(option, plan));

  useEffect(() => {
    setOptionId(plan.selected_option ?? onlyOption);
    // Options are rebuilt for each new question; re-seed from the new plan only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan.family, plan.interpretation]);

  useEffect(() => {
    setValues(initialValues(option, plan));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optionId, plan.family, plan.interpretation]);

  const errors = useMemo(
    () => Object.fromEntries((option?.inputs ?? []).map((input) => [input.key, inputError(input, values[input.key] ?? "")])),
    [option, values],
  );
  const valid = option != null && Object.values(errors).every((error) => error == null);
  const lever = plan.levers[0];

  const run = (next: Record<string, string>) => {
    if (!option) return;
    const inputs: Record<string, number> = {};
    for (const [key, raw] of Object.entries(next)) if (raw !== "") inputs[key] = Number(raw);
    onRun?.(question.trim() || plan.interpretation, plan, option.id, inputs);
  };

  const headLabel = plan.unpriced ? "Not modeled for this goal" : plan.modeled ? "Modeled as" : "Make it measurable";

  return (
    <section className="strategy-plan" aria-label="Make this measurable" data-testid="strategy-plan">
      <header className="strategy-plan-head">
        <p className="section-label">{headLabel}</p>
        <h2>{plan.interpretation}</h2>
      </header>

      {plan.affected_outcomes?.length ? (
        <p className="strategy-outcomes">
          <span>Can affect</span> {plan.affected_outcomes.join(" · ")}
        </p>
      ) : null}

      {lever && options.length ? (
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
              if (valid) run(values);
            }}
          >
            {options.length > 1 ? (
              <fieldset className="strategy-options">
                <legend>How should PlayItOut model it?</legend>
                {options.map((item) => (
                  <label key={item.id} className={`strategy-option${item.id === optionId ? " is-selected" : ""}`}>
                    <input
                      type="radio"
                      name="strategy-option"
                      value={item.id}
                      checked={item.id === optionId}
                      onChange={() => setOptionId(item.id)}
                    />
                    <span>
                      <strong>
                        {item.label}
                        {item.proxy ? <em className="strategy-proxy">Proxy</em> : null}
                      </strong>
                      <small>{item.description}</small>
                    </span>
                  </label>
                ))}
              </fieldset>
            ) : null}

            {option ? (
              option.inputs.map((input) => (
                <div className="strategy-field" key={input.key}>
                  <label htmlFor={`strategy-${input.key}`}>{input.label}</label>
                  <div className="strategy-amount-row">
                    {input.key === "amount" ? <span aria-hidden="true">+</span> : null}
                    <input
                      id={`strategy-${input.key}`}
                      type="number"
                      min={0}
                      step="any"
                      max={input.maximum ?? undefined}
                      value={values[input.key] ?? ""}
                      aria-invalid={errors[input.key] != null && values[input.key] !== ""}
                      onChange={(event) => setValues((prior) => ({ ...prior, [input.key]: event.target.value }))}
                    />
                    <span className="strategy-unit">{input.unit}</span>
                  </div>
                  {input.suggested_values.length ? (
                    <div className="strategy-quick" role="group" aria-label={`Quick values for ${input.label}`}>
                      {input.suggested_values.map((value) => (
                        <button
                          key={value}
                          type="button"
                          className={String(value) === values[input.key] ? "is-selected" : ""}
                          disabled={busy}
                          onClick={() => setValues((prior) => ({ ...prior, [input.key]: String(value) }))}
                        >
                          {input.key === "amount" ? "+" : ""}
                          {formatAmount(value)}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {errors[input.key] && values[input.key] !== "" ? <p className="strategy-warning">{errors[input.key]}</p> : null}
                </div>
              ))
            ) : (
              <p className="strategy-footnote">Choose an option to see what it needs.</p>
            )}

            {option ? (
              <div className="strategy-actions">
                <button className="strategy-run" type="submit" disabled={!valid || busy}>
                  {plan.modeled ? "Re-run" : "Run scenario"}
                </button>
                {option.proxy ? <span className="strategy-footnote">Result will be labeled as using the application proxy.</span> : null}
              </div>
            ) : null}
          </form>
        </div>
      ) : null}

      {plan.conflicts?.length ? (
        <ul className="strategy-conflicts" role="alert">
          {plan.conflicts.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}

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

      {plan.metrics_to_track?.length ? (
        <div className="strategy-track">
          <p className="section-label">Track to make it count</p>
          <ul>
            {plan.metrics_to_track.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {!plan.modeled ? (
        <p className="strategy-footnote">
          {plan.unpriced
            ? "No probability is attached. Logged evidence for these metrics is what can change the forecast."
            : "No probability change is assumed until you choose an option and give the inputs."}
        </p>
      ) : null}
    </section>
  );
}
