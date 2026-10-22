import { useState } from "react";
import type { TraitOption } from "../../api/client";
import {
  MAX_PARAMETERS,
  MIN_PARAMETERS,
  customDraftError,
  customParameterId,
  moveRow,
  rowsFromSelection,
  selectionPayload,
  type ParameterRow,
} from "./parameterSelection";

type Props = {
  selected: string[];
  options: TraitOption[];
  saving: boolean;
  error: string | null;
  onSave: (payload: ReturnType<typeof selectionPayload>) => void;
  onCancel: () => void;
};

export function ParameterEditor({ selected, options, saving, error, onSave, onCancel }: Props) {
  const [rows, setRows] = useState<ParameterRow[]>(() => rowsFromSelection(selected, options));
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [draftTouched, setDraftTouched] = useState(false);
  const chosen = new Set(rows.map((row) => row.id));
  const addable = options.filter((item) => !chosen.has(item.id));
  const draftError = customDraftError(name, description, rows, options);
  const tooFew = rows.length < MIN_PARAMETERS;

  function addCustom() {
    setDraftTouched(true);
    if (draftError) return;
    setRows((current) => [...current, { id: customParameterId(name), name: name.trim(), description: description.trim(), custom: true }]);
    setName("");
    setDescription("");
    setDraftTouched(false);
  }

  return (
    <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="edit-parameters-title">
      <div className="confirm-card profile-editor parameter-editor">
        <h2 id="edit-parameters-title">Edit parameters</h2>
        <ol className="parameter-list" aria-label="Radar parameters in order">
          {rows.map((row, index) => (
            <li key={row.id}>
              <div className="parameter-row-text">
                <strong>{row.name}</strong>
                <span>{row.description}</span>
              </div>
              <div className="parameter-row-actions">
                <button type="button" aria-label={`Move ${row.name} up`} disabled={index === 0} onClick={() => setRows((current) => moveRow(current, index, index - 1))}>↑</button>
                <button type="button" aria-label={`Move ${row.name} down`} disabled={index === rows.length - 1} onClick={() => setRows((current) => moveRow(current, index, index + 1))}>↓</button>
                <button type="button" aria-label={`Remove ${row.name}`} onClick={() => setRows((current) => current.filter((item) => item.id !== row.id))}>Remove</button>
              </div>
            </li>
          ))}
        </ol>
        {addable.length ? (
          <div className="parameter-add">
            <span>Add</span>
            {addable.map((item) => (
              <button
                key={item.id}
                type="button"
                title={item.description}
                disabled={rows.length >= MAX_PARAMETERS}
                onClick={() => setRows((current) => [...current, { id: item.id, name: item.name, description: item.description, custom: item.custom }])}
              >
                + {item.name}
              </button>
            ))}
          </div>
        ) : null}
        <form
          className="parameter-custom"
          onSubmit={(event) => {
            event.preventDefault();
            addCustom();
          }}
        >
          <label htmlFor="custom-parameter-name">Custom parameter</label>
          <input id="custom-parameter-name" className="ui-field" placeholder="e.g. Sleep regularity" value={name} maxLength={32} onChange={(event) => setName(event.target.value)} />
          <label htmlFor="custom-parameter-description">What it measures</label>
          <input id="custom-parameter-description" className="ui-field" placeholder="e.g. Nights in bed within 30 minutes of target" value={description} maxLength={160} onChange={(event) => setDescription(event.target.value)} />
          {name.trim() ? (
            <p className="parameter-hint">Scored only from observations recorded as <code>{customParameterId(name).replace("custom:", "trait_")}</code>, on a 0–1 scale. It stays empty until those exist.</p>
          ) : null}
          {draftTouched && draftError ? <p role="alert">{draftError}</p> : null}
          <button type="submit" className="markets-select" disabled={!name.trim()}>Add custom parameter</button>
        </form>
        {tooFew ? <p className="parameter-hint" role="status">Keep at least {MIN_PARAMETERS} parameters.</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        <div className="composer-actions">
          <button type="button" disabled={saving || tooFew} onClick={() => onSave(selectionPayload(rows))}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
