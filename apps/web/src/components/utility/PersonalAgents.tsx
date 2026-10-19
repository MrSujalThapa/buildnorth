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
                  <ol className="agent-steps">
                    <li>In your agent’s connector settings, add a custom remote MCP server with the URL above.</li>
                    <li>Choose OAuth. The agent opens Play It Out and asks for the permissions it needs.</li>
                    <li>Review those permissions, untick any you do not want, and approve.</li>
                  </ol>
                  <span>
                    You never paste a token. Grok supports custom connectors with OAuth but has not been tested
                    against Play It Out; other clients are untested unless listed in the project report.
                  </span>
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
