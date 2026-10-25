import { App } from "@modelcontextprotocol/ext-apps";
import { createRoot } from "react-dom/client";
import { useState } from "react";
import type { WhatIfMode, WhatIfView } from "../adapters/templateTypes";
import { WhatIfVisualEmbed, type WhatIfVisualPayload, type WhatIfVisualRequest } from "../components/what-if/WhatIfVisualEmbed";
import { acceptsVisual } from "./whatIfMessageGuard";

declare global {
  interface Window { __PLAYITOUT_WHATIF_PAYLOAD__?: WhatIfVisualPayload; }
}

const app = new App({ name: "PlayItOut What If", version: "0.1.0" }, { availableDisplayModes: ["inline"] });
const root = createRoot(document.getElementById("root")!);
let selectedGoal: string | null = window.__PLAYITOUT_WHATIF_PAYLOAD__?.goal.goal_id ?? null;
let selectedRequest: string | null = null;
let expected: Pick<WhatIfVisualRequest, "mode" | "view" | "question"> | null = null;
let payload: WhatIfVisualPayload | null = window.__PLAYITOUT_WHATIF_PAYLOAD__ ?? null;
let error: string | null = null;
let loading = false;

function ingest(value: unknown): void {
  if (!acceptsVisual(value, { goalId: selectedGoal, requestId: selectedRequest, expected })) return;
  selectedGoal = value.goal.goal_id;
  payload = value;
  error = null;
  loading = false;
  draw();
}

async function requestVisual(request: WhatIfVisualRequest): Promise<void> {
  if (selectedGoal && request.goal_id !== selectedGoal) return;
  const requestId = crypto.randomUUID();
  selectedRequest = requestId;
  expected = { mode: request.mode, view: request.view, question: request.question };
  error = null;
  loading = true;
  draw();
  try {
    const response = await app.callServerTool({ name: "show_what_if_visualization", arguments: {
      ...request, request_id: requestId,
    } });
    if (response.isError) throw new Error("The What If operation failed. Please retry.");
    ingest(response.structuredContent);
  } catch (caught) {
    if (selectedRequest === requestId) {
      error = caught instanceof Error ? caught.message : "The What If operation failed.";
      loading = false;
      draw();
    }
  }
}

function View() {
  const [, refresh] = useState(0);
  window.__playitoutRefresh = () => refresh((value) => value + 1);
  if (loading || !payload) return <main className="what-if-page mcp-what-if">
    {error ? <p role="alert">{error}</p> : <p role="status">{loading ? "Running the backend analysis…" : "Waiting for a What If result…"}</p>}
  </main>;
  const change = (mode: WhatIfMode, view: WhatIfView) => void requestVisual({
    goal_id: payload!.goal.goal_id, mode, view, question: payload!.question,
    target_probability: payload!.targetProbability ?? undefined,
    alternatives: payload!.alternatives ?? undefined,
  });
  return <div className="mcp-what-if-host">
    <nav className="mcp-what-if-controls" aria-label="What If analysis">
      {(["impact", "futures", "compare", "paths"] as WhatIfMode[]).map((mode) =>
        <button key={mode} aria-pressed={payload!.mode === mode} onClick={() => change(mode, payload!.view)}>{mode === "impact" ? "Change" : mode === "paths" ? "Reverse" : mode}</button>)}
      <button aria-pressed={payload.view === "simple"} onClick={() => change(payload!.mode, "simple")}>Simple</button>
      <button aria-pressed={payload.view === "deep"} onClick={() => change(payload!.mode, "deep")}>Deeper analysis</button>
    </nav>
    {error ? <p role="alert">{error}</p> : null}
    <WhatIfVisualEmbed key={`${payload.goal.goal_id}:${payload.mode}:${payload.view}:${payload.request_id ?? payload.question}`}
      payload={payload} onRequest={(request) => { void requestVisual(request); }} />
  </div>;
}

declare global {
  interface Window { __playitoutRefresh?: () => void; }
}
function draw() { window.__playitoutRefresh?.(); }
root.render(<View />);

app.ontoolinput = (input) => {
  const id = input.arguments?.goal_id;
  if (typeof id === "string") {
    const mode = input.arguments?.mode;
    const view = input.arguments?.view;
    const question = input.arguments?.question;
    expected = (mode === "impact" || mode === "futures" || mode === "compare" || mode === "paths")
      && (view === "simple" || view === "deep") && typeof question === "string"
      ? { mode, view, question } : null;
    selectedRequest = typeof input.arguments?.request_id === "string"
      ? input.arguments.request_id : null;
    selectedGoal = id;
    payload = null;
    error = null;
    loading = true;
    draw();
  }
};
app.ontoolresult = (result) => {
  if (!result.isError) ingest(result.structuredContent);
  else {
    loading = false;
    error = "The What If operation failed. Please retry.";
    draw();
  }
};
app.onhostcontextchanged = (context) => {
  document.documentElement.classList.toggle("theme-dark", context.theme === "dark");
};
if (window.parent !== window) void app.connect().catch(() => {
  error = "The host could not connect to this visualization.";
  draw();
});
