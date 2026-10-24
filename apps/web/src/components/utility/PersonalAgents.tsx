import { Copy } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type McpConnection, type McpStatus } from "../../api/client";

function when(value: string | null): string {
  return value ? new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "never";
}

export function PersonalAgents() {
  const [status, setStatus] = useState<McpStatus | null>(null);
  const [connections, setConnections] = useState<McpConnection[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [copied, setCopied] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const [nextStatus, nextConnections] = await Promise.all([
      api.mcpStatus(signal),
      api.mcpConnections(signal),
    ]);
    setStatus(nextStatus);
    setConnections(nextConnections);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal).catch((caught: unknown) => {
      if (controller.signal.aborted) return;
      setError(caught instanceof Error ? caught.message : "Personal agent settings could not be loaded.");
    });
    return () => controller.abort();
  }, [refresh]);

  async function copyEndpoint(endpoint: string) {
    try {
      await navigator.clipboard.writeText(endpoint);
      setCopied(true);
    } catch {
      setNotice("Copy failed. Select the address and copy it manually.");
    }
  }

  async function revoke(connection: McpConnection) {
    setBusyId(connection.connection_id);
    setError(null);
    setNotice("");
    try {
      await api.revokeMcpConnection(connection.connection_id);
      await refresh();
      setNotice(`${connection.client_name} can no longer access your account.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The connection could not be revoked.");
    } finally {
      setBusyId(null);
    }
  }

  const active = connections.filter((item) => item.status === "active");
  const revoked = connections.filter((item) => item.status === "revoked").slice(0, 5);

  return (
    <section className="settings-group" aria-labelledby="personal-agents-heading">
      <h2 id="personal-agents-heading">Personal agents</h2>
      {!status ? (
        <p className="setting-note">{error ? "Personal agent settings are unavailable." : "Loading personal agent settings…"}</p>
      ) : (
        <>
          <div className="settings-list">
            <div className="setting-row agent-endpoint-row">
              <div>
                <strong>Remote MCP server</strong>
                <span>
                  {status.enabled
                    ? "Agents that support remote MCP with OAuth can create goals, submit evidence, read historical odds and run What If scenarios after you approve them. Probabilities always come from Play It Out’s models."
                    : "Remote MCP is turned off for this deployment."}
                </span>
                {status.enabled ? (
                  <div className="invite-created">
                    <code>{status.endpoint}</code>
                    <button type="button" onClick={() => void copyEndpoint(status.endpoint)}>
                      <Copy size={15} />
                      {copied ? "Copied" : "Copy MCP URL"}
                    </button>
                  </div>
                ) : null}
                {status.enabled && !status.public_https ? (
                  <span>
                    This address only works from this computer. Hosted agents such as Grok need a public
                    HTTPS address, so they cannot connect to this deployment yet.
                  </span>
                ) : null}
              </div>
            </div>
            {status.enabled ? (
              <div className="setting-row agent-steps-row">
                <div>
                  <strong>How to connect</strong>
                  <span>One OAuth connection covers goals, evidence, history, What If, and charts. You never paste a token.</span>
                  <p className="agent-client-label">ChatGPT</p>
                  <ol className="agent-steps">
                    <li>In ChatGPT, add a custom MCP server. Do not publish it.</li>
                    <li>Use the server URL above and sign in with OAuth.</li>
                    <li>Approve only the permissions you want on the Play It Out consent screen.</li>
                    <li>Try a normal chat, then Work separately if you use it. One surface does not prove the other.</li>
                  </ol>
                  <p className="agent-client-label">Grok</p>
                  <ol className="agent-steps">
                    <li>In Grok connectors or Grok Bot plugins, add a custom MCP server with the same URL.</li>
                    <li>Choose OAuth and approve the same consent screen.</li>
                  </ol>
                  <span>
                    If a host cannot show the interactive chart, ask for the static chart image. The same history is on this goal’s page.
                  </span>
                </div>
              </div>
            ) : null}
            {status.enabled ? (
              <div className="setting-row agent-steps-row">
                <div>
                  <strong>Permissions</strong>
                  <ul className="agent-steps">
                    {status.scopes.map((scope) => (
                      <li key={scope.scope}>
                        <span className="agent-scope-name">{scope.label}</span>
                        {" — "}
                        {scope.writes ? "Can change your account. " : "Read only. "}
                        {scope.description}
                      </li>
                    ))}
                  </ul>
                  <span>
                    Creating a goal and free-text evidence use model credits and stay off until you approve them.
                    Structured evidence does not. What If never changes the published forecast.
                    Agents cannot mark evidence as independently verified, and they cannot edit a goal’s title, deadline, or success definition.
                    Progress is new evidence.
                  </span>
                </div>
              </div>
            ) : null}
            {status.enabled ? (
              <div className="setting-row agent-steps-row">
                <div>
                  <strong>What is verified</strong>
                  <ul className="agent-steps">
                    <li>MCP reference client: connect, read, create, evidence, history, What If, chart data, and revocation are covered by this server’s tests.</li>
                    <li>ChatGPT Chat: not verified.</li>
                    <li>ChatGPT Work: not verified.</li>
                    <li>Grok Bot: not verified.</li>
                    <li>Interactive charts inside those hosts: not verified.</li>
                  </ul>
                  <span>Revoke a connection below. Later protected calls from that client fail. Goals already saved stay on your account.</span>
                </div>
              </div>
            ) : null}
            <div className="setting-row">
              <div>
                <strong>Model credits</strong>
                <span>
                  Reading goals, structured evidence and What If make no model calls. Creating a goal
                  and natural-language submissions use Play It Out agents and are paid the way you
                  chose under “Who pays for inference”. An agent can only do this if you approve
                  “Create goals” and “Use model credits”.
                </span>
              </div>
            </div>
          </div>
          <div className="invite-list" aria-label="Connected agents">
            {active.length === 0 ? (
              <p className="setting-note">No agents are connected.</p>
            ) : (
              active.map((connection) => (
                <div key={connection.connection_id} className="invite-row">
                  <div>
                    <strong>{connection.client_name}</strong>
                    <span>
                      Connected {when(connection.created_at)} · last used {when(connection.last_used_at)}
                    </span>
                    <span>{connection.scopes.map((scope) => scope.label).join(" · ")}</span>
                  </div>
                  <div className="invite-row-actions">
                    <button
                      type="button"
                      disabled={busyId === connection.connection_id}
                      onClick={() => void revoke(connection)}
                    >
                      {busyId === connection.connection_id ? "Revoking…" : "Revoke"}
                    </button>
                  </div>
                </div>
              ))
            )}
            {revoked.map((connection) => (
              <div key={connection.connection_id} className="invite-row agent-revoked">
                <div>
                  <strong>{connection.client_name}</strong>
                  <span>Revoked {when(connection.revoked_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      {error ? <p className="setting-note" role="alert">{error}</p> : null}
      <p className="setting-note" role="status" aria-live="polite">{notice}</p>
    </section>
  );
}
