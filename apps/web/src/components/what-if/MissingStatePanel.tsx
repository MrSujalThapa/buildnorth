import { useState } from "react";

import type { Priceability } from "../../api/client";

type Props = {
  priceability: Priceability;
  onSubmit: (entries: { key: string; label: string; value: number; unit: string }[]) => void;
  onAddEvidence: () => void;
  onConnectSource: () => void;
  submitting?: boolean;
};

/**
 * Replaces the bare "not priced yet" state with the specific inputs the model family
 * declared it needs, so the user can supply them without knowing anything about the
 * forecasting pipeline.
 */
export default function MissingStatePanel({
  priceability,
  onSubmit,
  onAddEvidence,
  onConnectSource,
  submitting,
}: Props) {
  const [values, setValues] = useState<Record<string, string>>({});

  if (priceability.status === "NOT_PRICED" && !priceability.missing.length) {
    return (
      <div className="empty-state">
        <strong>{priceability.headline}</strong>
        <span>{priceability.reason}</span>
      </div>
    );
  }

  const entries = priceability.missing
    .map((item) => ({
      key: item.key,
      label: item.label,
      unit: item.unit,
      value: Number(values[item.key]),
    }))
    .filter((item) => values[item.key] !== undefined && values[item.key] !== "" && Number.isFinite(item.value));

  return (
    <div className="missing-state">
      <div className="missing-state-head">
        <strong>{priceability.headline}</strong>
        <span>
          We will not invent these numbers, so the goal stays unpriced until they arrive.
        </span>
      </div>

      <ul className="missing-state-list">
        {priceability.missing.map((item) => (
          <li key={item.key}>
            <div className="missing-state-copy">
              <div className="tune-label">{item.label}</div>
              <div className="tune-helper">{item.why}</div>
            </div>
            <label className="exact-value">
              <input
                type="number"
                inputMode="decimal"
                placeholder={item.example ?? ""}
                aria-label={item.label}
                value={values[item.key] ?? ""}
                onChange={(event) =>
                  setValues((current) => ({ ...current, [item.key]: event.target.value }))
                }
              />
              <span>{item.unit}</span>
            </label>
          </li>
        ))}
      </ul>

      {priceability.satisfied.length ? (
        <p className="meta">
          Already known: {priceability.satisfied.map((item) => item.label).join(", ")}.
        </p>
      ) : null}

      <div className="missing-state-actions">
        <button
          className="primary-action"
          type="button"
          disabled={!entries.length || submitting}
          onClick={() => onSubmit(entries)}
        >
          {submitting ? "Pricing…" : "Price with these values"}
        </button>
        <button className="text-action" type="button" onClick={onAddEvidence}>
          Add evidence
        </button>
        <button className="text-action" type="button" onClick={onConnectSource}>
          Connect a source
        </button>
      </div>
    </div>
  );
}
