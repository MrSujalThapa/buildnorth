import { useEffect, useMemo, useState } from "react";
import { api, type InferenceModelOption, type InferencePreference, type InferenceSettings as Settings } from "../../api/client";
import type { HostedUsage } from "../../auth/session";

export function InferenceSettings({
  hosted,
  isAdmin = false,
}: {
  hosted?: HostedUsage | null;
  isAdmin?: boolean;
}) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [mode, setMode] = useState<InferencePreference["mode"]>("hosted");
  const [provider, setProvider] = useState<InferencePreference["provider"]>("openai");
  const [model, setModel] = useState("");
  const [modelQuery, setModelQuery] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  function accept(next: Settings) {
    setSettings(next);
    setMode(next.preference.mode);
    setProvider(next.preference.provider);
    setModel(next.preference.mode === "byok" ? next.preference.model || "" : "");
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

  const credential = settings?.credentials.find((item) => item.provider === provider);
  const hostedLabel = settings?.hosted_provider === "spur" ? "Spur" : settings?.hosted_provider || "not configured";
  const byokModels = useMemo(() => {
    const listed = settings?.discovered_models?.[provider] || settings?.models.filter((item) => item.provider === provider) || [];
    const needle = modelQuery.trim().toLowerCase();
    if (!needle) return listed;
    return listed.filter((item) =>
      `${item.display_name || ""} ${item.model}`.toLowerCase().includes(needle),
    );
  }, [settings, provider, modelQuery]);
  const recommendedModel = settings?.preference.mode === "byok"
    && settings.preference.provider === provider
    && settings.recommended_model
    && (settings.discovered_models?.[provider] || settings.models).some(
      (item) => item.model === settings.recommended_model,
    )
    ? settings.recommended_model
    : null;

  function modelLabel(item: InferenceModelOption): string {
    const name = item.display_name || item.model;
    const flags = [
      item.structured ? "forecasting" : "not for forecasting",
      item.pricing_available === false ? "cost estimate unavailable" : null,
    ].filter(Boolean);
    return `${name}${flags.length ? ` · ${flags.join(" · ")}` : ""}`;
  }

  const hostedAvailable = hosted
    ? hosted.hosted_available ?? (!hosted.kill_switch && hosted.remaining_usd > 0 && (hosted.global_remaining_usd == null || hosted.global_remaining_usd > 0) && Boolean(settings?.hosted_configured))
    : false;

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
                <span>
                  Provider: {settings.preference.mode === "byok" ? settings.preference.provider : hostedLabel}
                  {" · "}
                  Model: {settings.preference.mode === "byok" ? settings.preference.model || "provider default" : settings.hosted_model || "not configured"}
                </span>
              </div>
            </div>
          </div>

          <div className="inference-mode-grid">
            <article className={`inference-card${mode === "hosted" ? " selected" : ""}`}>
              <h3>PlayItOut credits</h3>
              <p>Hosted inference runs on Spur. Your personal allowance is used; BYOK keys are not charged here.</p>
              <dl className="inference-meta">
                <div><dt>Provider</dt><dd>Spur</dd></div>
                <div><dt>Model</dt><dd>{settings.hosted_model || "not configured"}</dd></div>
                <div>
                  <dt>Personal credit</dt>
                  <dd>
                    {hosted
                      ? `$${Number(hosted.remaining_usd).toFixed(2)} / $${Number(hosted.quota_usd).toFixed(2)} remaining`
                      : "Sign in to see your remaining credit."}
                  </dd>
                </div>
                <div>
                  <dt>Availability</dt>
                  <dd>
                    {hosted?.kill_switch
                      ? "Hosted inference disabled"
                      : !settings.hosted_configured
                        ? "Hosted provider not configured"
                        : hostedAvailable
                          ? "Hosted inference available"
                          : "Hosted credit is unavailable for this account"}
                  </dd>
                </div>
                {isAdmin && hosted && hosted.global_remaining_usd != null ? (
                  <div>
                    <dt>Platform remaining</dt>
                    <dd>${Number(hosted.global_remaining_usd).toFixed(2)}</dd>
                  </div>
                ) : null}
              </dl>
              <button
                type="button"
                disabled={busy || mode === "hosted"}
                onClick={() => void perform(async () => {
                  accept(await api.saveInferencePreference({ mode: "hosted", provider, model: null }));
                  setNotice("Hosted Spur credits are now active.");
                })}
              >
                Use PlayItOut credits
              </button>
            </article>

            <article className={`inference-card${mode === "byok" ? " selected" : ""}`}>
              <h3>My API key</h3>
              <p>Your OpenAI or Anthropic account pays for agent inference. Hosted Spur credits are not consumed.</p>
              <form className="inference-settings-form inference-byok-form" onSubmit={(event) => {
                event.preventDefault();
                void perform(async () => {
                  accept(await api.saveInferencePreference({ mode: "byok", provider, model: model || null }));
                  setNotice("BYOK preference saved.");
                });
              }}>
                <fieldset className="choice-row">
                  <legend>Provider</legend>
                  {(["openai", "anthropic"] as const).map((item) => (
                    <button
                      key={item}
                      type="button"
                      aria-pressed={provider === item}
                      disabled={busy}
                      onClick={() => {
                        setProvider(item);
                        setModel("");
                        setKey("");
                        setModelQuery("");
                      }}
                    >
                      {item === "openai" ? "OpenAI" : "Anthropic"}
                    </button>
                  ))}
                </fieldset>
                <label>Search models
                  <input
                    type="search"
                    value={modelQuery}
                    disabled={busy}
                    placeholder="Filter compatible models"
                    onChange={(event) => setModelQuery(event.target.value)}
                  />
                </label>
                <div className="model-picker" role="listbox" aria-label="Compatible model">
                  <button
                    type="button"
                    role="option"
                    aria-selected={!model}
                    disabled={busy}
                    onClick={() => setModel("")}
                  >
                    {recommendedModel ? `Recommended (${recommendedModel})` : "Provider default"}
                  </button>
                  {byokModels.map((item) => (
                    <button
                      key={item.model}
                      type="button"
                      role="option"
                      aria-selected={model === item.model}
                      disabled={busy || !item.structured}
                      onClick={() => setModel(item.model)}
                    >
                      {modelLabel(item)}
                    </button>
                  ))}
                </div>
                <button type="submit" disabled={busy || !credential}>Save BYOK preference</button>
              </form>
              <div className="setting-row inference-key-row">
                <div>
                  <strong>{provider === "openai" ? "OpenAI" : "Anthropic"} key</strong>
                  <span>
                    {credential
                      ? `${credential.status === "validated" ? "Validated connection" : "Key needs validation or replacement"} · ${credential.masked_suffix} · ${new Date(credential.validated_at).toLocaleDateString()}`
                      : "No key saved for this provider."}
                  </span>
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
                <label htmlFor="byok-api-key">{credential ? "Replacement API key" : "API key"}
                  <input
                    id="byok-api-key"
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    minLength={12}
                    maxLength={512}
                    required
                    value={key}
                    disabled={busy}
                    onChange={(event) => setKey(event.target.value)}
                  />
                </label>
                <button type="submit" disabled={busy || !key.trim()}>
                  {credential ? "Replace key" : "Connect and use my key"}
                </button>
              </form>
            </article>
          </div>
          <p className="setting-note">
            Hosted credit: {hosted ? `$${Number(hosted.remaining_usd).toFixed(2)} / $${Number(hosted.quota_usd).toFixed(2)} remaining` : "unavailable"}
            {hosted && !settings.hosted_configured ? " · Hosted provider not configured" : ""}
            {hosted && hosted.remaining_usd <= 0 ? " · Hosted credit is unavailable for this account. Connect your own key to use BYOK." : ""}
          </p>
          <p className="setting-note">Keys are encrypted on the server and never returned. Connecting a key activates BYOK. Provider authentication or quota failures stop the request without switching billing modes. Your provider account pays for BYOK usage.</p>
          <p className="setting-note">BYOK usage: {settings.byok_usage.calls} calls · {settings.byok_usage.input_tokens + settings.byok_usage.output_tokens} tokens · estimated ${Number(settings.byok_usage.estimated_cost_usd).toFixed(4)}. External research tools use a separate hosted dollar allowance when available.</p>
        </>
      )}
      {error ? <p className="setting-note" role="alert">{error}</p> : null}
      <p className="setting-note" role="status" aria-live="polite">{notice}</p>
    </section>
  );
}
