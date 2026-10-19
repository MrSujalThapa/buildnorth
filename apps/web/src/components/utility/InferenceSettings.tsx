import { useEffect, useState } from "react";
import { api, type InferencePreference, type InferenceSettings as Settings } from "../../api/client";
import type { HostedUsage } from "../../auth/session";

export function InferenceSettings({ hosted }: { hosted?: HostedUsage | null }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [mode, setMode] = useState<InferencePreference["mode"]>("hosted");
  const [provider, setProvider] = useState<InferencePreference["provider"]>("openai");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  function accept(next: Settings) {
    setSettings(next);
    setMode(next.preference.mode);
    setProvider(next.preference.provider);
    setModel(next.preference.model || "");
  }

  useEffect(() => {
    let cancelled = false;
    void api.inferenceSettings().then((next) => {
      if (!cancelled) accept(next);
    }).catch((caught: unknown) => {
      if (!cancelled) setError(caught instanceof Error ? caught.message : "Settings could not be loaded.");
    });
    return () => { cancelled = true; };
  }, []);

  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setNotice("");
    try { await action(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "The provider request failed."); }
    finally { setBusy(false); }
  }

  const activeProvider = mode === "byok" ? provider : settings?.hosted_provider;
  const models = settings?.models.filter((item) => item.provider === activeProvider) || [];
  const credential = settings?.credentials.find((item) => item.provider === provider);

  return (
    <section className="settings-group" aria-labelledby="inference-heading">
      <h2 id="inference-heading">Inference</h2>
      {!settings ? (
        <p className="setting-note">{error ? "Inference settings are unavailable." : "Loading inference settings…"}</p>
      ) : (
        <>
          <div className="settings-list">
            <div className="setting-row">
              <div>
                <strong>Current mode: {settings.preference.mode === "byok" ? "BYOK" : "Hosted"}</strong>
                <span>{settings.preference.mode === "byok"
                  ? "Your selected provider account pays for agent inference. Hosted tokens are not consumed."
                  : `Play It Out pays through ${settings.hosted_provider}. Your hosted allowance and limits apply.`}</span>
                <span>Provider: {settings.preference.mode === "byok" ? settings.preference.provider : settings.hosted_provider} · Model: {settings.preference.mode === "byok" ? settings.preference.model || "provider default" : settings.hosted_model || "not configured"}</span>
                {hosted ? <span>Hosted credit: ${Number(hosted.remaining_usd).toFixed(2)} / ${Number(hosted.quota_usd).toFixed(2)} remaining · Global balance: ${Number(hosted.global_remaining_usd || 0).toFixed(2)} · {hosted.kill_switch ? "Hosted inference disabled" : !settings.hosted_configured ? "Hosted provider not configured" : Number(hosted.global_remaining_usd || 0) <= 0 ? "Global credits exhausted" : "Hosted inference available"}</span> : null}
                {hosted && (hosted.remaining_usd <= 0 || !hosted.enabled) ? <span>Hosted credit is unavailable for this account. Connect your own key to use BYOK.</span> : null}
              </div>
            </div>
          </div>
          <form className="inference-settings-form" onSubmit={(event) => {
            event.preventDefault();
            void perform(async () => {
              accept(await api.saveInferencePreference({ mode, provider, model: model || null }));
              setNotice("Inference preference saved.");
            });
          }}>
            <label>Inference mode
              <select value={mode} disabled={busy} onChange={(event) => {
                setMode(event.target.value as InferencePreference["mode"]); setModel("");
              }}>
                <option value="hosted">Hosted — Play It Out pays</option>
                <option value="byok">BYOK — your provider account pays</option>
              </select>
            </label>
            <label>BYOK provider
              <select value={provider} disabled={busy} onChange={(event) => {
                setProvider(event.target.value as InferencePreference["provider"]); setModel(""); setKey("");
              }}>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
              </select>
            </label>
            <label>Agent model
              <select value={model} disabled={busy} onChange={(event) => setModel(event.target.value)}>
                <option value="">Provider default{mode === "hosted" && settings.hosted_model ? ` (${settings.hosted_model})` : ""}</option>
                {models.map((item) => <option key={item.model} value={item.model}>{item.model}</option>)}
              </select>
            </label>
            <button type="submit" disabled={busy}>{busy ? "Working…" : "Save inference preference"}</button>
          </form>
          <div className="setting-row inference-key-row">
            <div>
              <strong>{provider === "openai" ? "OpenAI" : "Anthropic"} key</strong>
              <span>{credential ? `${credential.status === "validated" ? "Validated connection" : "Key needs validation or replacement"} · ${credential.masked_suffix} · ${new Date(credential.validated_at).toLocaleDateString()}` : "No key saved for this provider."}</span>
            </div>
            {credential ? <div className="invite-row-actions">
              <button type="button" disabled={busy} onClick={() => void perform(async () => {
                await api.validateProviderKey(provider);
                setSettings(await api.inferenceSettings());
                setNotice("Provider connection validated.");
              })}>Validate key</button>
              <button type="button" disabled={busy} onClick={() => void perform(async () => {
                await api.deleteProviderKey(provider);
                setKey("");
                setSettings(await api.inferenceSettings());
                setNotice("Key deleted. BYOK stays selected until you change it.");
              })}>Delete key</button>
            </div> : null}
          </div>
          <form className="inference-settings-form inference-key-form" onSubmit={(event) => {
            event.preventDefault();
            const candidate = key;
            setKey("");
            void perform(async () => {
              await api.saveProviderKey(provider, candidate);
                accept(await api.inferenceSettings());
                setNotice("Key validated, encrypted, and connected. BYOK is now active.");
            });
          }}>
            <label>{credential ? "Replacement API key" : "API key"}
              <input type="password" autoComplete="off" spellCheck={false} minLength={12} maxLength={512}
                required value={key} disabled={busy} onChange={(event) => setKey(event.target.value)} />
            </label>
            <button type="submit" disabled={busy || !key.trim()}>{credential ? "Replace key" : "Add and validate key"}</button>
          </form>
          <p className="setting-note">Keys are encrypted on the server and never returned. Connecting a key activates BYOK. Provider authentication or quota failures stop the request without switching billing modes. API billing is separate from a chat subscription.</p>
          <p className="setting-note">BYOK usage: {settings.byok_usage.calls} calls · {settings.byok_usage.input_tokens + settings.byok_usage.output_tokens} tokens · estimated ${Number(settings.byok_usage.estimated_cost_usd).toFixed(4)}. External research tools use a separate hosted dollar allowance when available.</p>
        </>
      )}
      {error ? <p className="setting-note" role="alert">{error}</p> : null}
      <p className="setting-note" role="status" aria-live="polite">{notice}</p>
    </section>
  );
}
