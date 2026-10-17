import { useSearchParams } from "react-router-dom";
import type { WorkflowSnapshot } from "../../api/client";

export function AgentProgress({ snapshot }: { snapshot: WorkflowSnapshot | null }) {
  const executed = snapshot?.progress ?? [];
  if (!snapshot || executed.length === 0) return null;
  return (
    <ol className="agent-progress" aria-label="Workflow progress">
      {executed.map((label) => (
        <li key={label} data-state="done">
          {label}…
        </li>
      ))}
    </ol>
  );
}

export function AgentDebug({ snapshot }: { snapshot: WorkflowSnapshot | null }) {
  const [params] = useSearchParams();
  if (params.get("debug") !== "agents" || !snapshot) return null;
  const rows = [
    ["Goal Architect", snapshot.agent_run_ids.goal_architect ? "✓" : "skipped"],
    ["Evidence Agent", snapshot.agent_run_ids.evidence ? "✓" : "skipped"],
    ["Research", snapshot.agent_run_ids.research ? "✓" : "skipped"],
    ["Forecast Engine", snapshot.pricing ? "✓" : "pending"],
    ["Critic", snapshot.agent_run_ids.critic ? "✓" : "pending"],
  ];
  return (
    <details className="agent-debug">
      <summary>Agent trace</summary>
      <ul>
        {rows.map(([name, state]) => (
          <li key={name}>
            <strong>{name}</strong> {state}
          </li>
        ))}
      </ul>
      {snapshot.pricing?.receipt ? <pre>{JSON.stringify(snapshot.pricing.receipt, null, 2)}</pre> : null}
    </details>
  );
}
