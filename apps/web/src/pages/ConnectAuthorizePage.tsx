import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type McpAuthorizationRequest } from "../api/client";
import "../auth/auth.css";

export function ConnectAuthorizePage() {
  const [params] = useSearchParams();
  const requestId = params.get("request") || "";
  const [request, setRequest] = useState<McpAuthorizationRequest | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [leaving, setLeaving] = useState<string | null>(null);

  useEffect(() => {
    if (!requestId) {
      setError("This link is missing its connection request.");
      return;
    }
    const controller = new AbortController();
    void api.mcpAuthorizationRequest(requestId, controller.signal).then((next) => {
      setRequest(next);
      setSelected(new Set(next.scopes.map((scope) => scope.scope)));
    }).catch((caught: unknown) => {
      if (controller.signal.aborted) return;
      setError(caught instanceof Error ? caught.message : "This connection request could not be loaded.");
    });
    return () => controller.abort();
  }, [requestId]);

  async function decide(approve: boolean) {
    if (!request) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.decideMcpAuthorization(request.request_id, {
        approve,
        scopes: approve ? [...selected] : undefined,
      });
      setLeaving(approve ? `Returning to ${request.client_name}…` : "Request denied. Returning to the agent…");
      window.location.assign(result.redirect_url);
    } catch (caught) {
      setBusy(false);
      setError(caught instanceof Error ? caught.message : "The decision could not be saved.");
    }
  }

  function toggle(scope: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(scope)) next.delete(scope);
      else next.add(scope);
      return next;
    });
  }

  return (
    <main className="auth-screen">
      <section className="auth-panel consent-panel">
        <p className="eyebrow">PLAY IT OUT</p>
        <h1>Connect an agent</h1>
        {request ? (
          <>
            <p className="auth-copy">
              <strong>{request.client_name}</strong> is asking to use your Play It Out account. Choose
              what it may do.
            </p>
            <fieldset className="consent-scopes" disabled={busy || Boolean(leaving)}>
              <legend>Permissions</legend>
              {request.scopes.map((scope) => (
                <label key={scope.scope} className="consent-scope">
                  <input
                    type="checkbox"
                    checked={selected.has(scope.scope)}
                    onChange={() => toggle(scope.scope)}
                  />
                  <span>
                    <strong>{scope.label}</strong>
                    <small>{scope.description}</small>
                    {scope.spends_credits ? <small className="consent-cost">Can spend model credits.</small> : null}
                  </span>
                </label>
              ))}
            </fieldset>
            <ul className="consent-warnings">
              {request.warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
            {leaving ? <p className="auth-status" role="status">{leaving}</p> : (
              <div className="consent-actions">
                <button
                  type="button"
                  className="auth-primary"
                  disabled={busy || selected.size === 0}
                  onClick={() => void decide(true)}
                >
                  {busy ? "Saving…" : "Approve"}
                </button>
                <button
                  type="button"
                  className="auth-text-button"
                  disabled={busy}
                  onClick={() => void decide(false)}
                >
                  Deny
                </button>
              </div>
            )}
            <p className="consent-footnote">
              You can revoke this connection at any time in Settings → Personal agents. Evidence the agent
              submits is labeled agent-reported.
            </p>
          </>
        ) : (
          <p className="auth-copy">{error ? "This request cannot be used." : "Loading the connection request…"}</p>
        )}
        {error ? <p className="auth-error" role="alert">{error}</p> : null}
      </section>
    </main>
  );
}
