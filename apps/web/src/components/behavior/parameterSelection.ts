import type { TraitOption } from "../../api/client";

export const MIN_PARAMETERS = 3;
export const MAX_PARAMETERS = 10;
export const MAX_CUSTOM_PARAMETERS = 6;

export type ParameterRow = {
  id: string;
  name: string;
  description: string;
  custom: boolean;
};

/** Mirrors the server's slug so a new custom parameter can be ordered before it is saved. */
export function customParameterId(name: string): string {
  const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 36);
  return `custom:${slug || "trait"}`;
}

export function rowsFromSelection(selected: string[], options: TraitOption[]): ParameterRow[] {
  const byId = new Map(options.map((item) => [item.id, item]));
  return selected.flatMap((id) => {
    const option = byId.get(id);
    return option ? [{ id, name: option.name, description: option.description, custom: option.custom }] : [];
  });
}

export function moveRow(rows: ParameterRow[], from: number, to: number): ParameterRow[] {
  if (to < 0 || to >= rows.length) return rows;
  const next = [...rows];
  const [item] = next.splice(from, 1);
  if (item) next.splice(to, 0, item);
  return next;
}

export function customDraftError(name: string, description: string, rows: ParameterRow[], options: TraitOption[]): string | null {
  const trimmed = name.trim();
  if (trimmed.length < 2) return "Name needs at least 2 characters.";
  if (description.trim().length < 4) return "Describe what this parameter measures.";
  const id = customParameterId(trimmed);
  const builtIn = options.some((item) => !item.custom && (item.id === id.slice(7) || item.name.toLowerCase() === trimmed.toLowerCase()));
  if (builtIn || rows.some((row) => row.id === id || row.name.toLowerCase() === trimmed.toLowerCase())) {
    return "That parameter is already on the list.";
  }
  if (rows.filter((row) => row.custom).length >= MAX_CUSTOM_PARAMETERS) return `Up to ${MAX_CUSTOM_PARAMETERS} custom parameters.`;
  if (rows.length >= MAX_PARAMETERS) return `Up to ${MAX_PARAMETERS} parameters.`;
  return null;
}

export function selectionPayload(rows: ParameterRow[]) {
  return {
    parameter_ids: rows.map((row) => row.id),
  };
}
