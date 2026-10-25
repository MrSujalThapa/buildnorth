import type { WhatIfVisualPayload, WhatIfVisualRequest } from "../components/what-if/WhatIfVisualEmbed";

export type ActiveVisual = {
  goalId: string | null;
  requestId: string | null;
  expected: Pick<WhatIfVisualRequest, "mode" | "view" | "question"> | null;
};

export function acceptsVisual(value: unknown, active: ActiveVisual): value is WhatIfVisualPayload {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  const goal = item.goal as Record<string, unknown> | undefined;
  if (item.kind !== "playitout_what_if" || typeof goal?.goal_id !== "string"
    || !["impact", "futures", "compare", "paths"].includes(String(item.mode))
    || !["simple", "deep"].includes(String(item.view))
    || !Array.isArray(item.history) || !item.baseline) return false;
  if (active.goalId && goal.goal_id !== active.goalId) return false;
  if (active.expected && (item.mode !== active.expected.mode || item.view !== active.expected.view
    || item.question !== active.expected.question)) return false;
  if (active.requestId && item.request_id !== active.requestId) return false;
  return true;
}
