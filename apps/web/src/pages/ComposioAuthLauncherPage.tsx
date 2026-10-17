import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  clearStoredComposioAuthUrl,
  composioAuthChannelName,
  parseComposioAuthUrlMessage,
  readStoredComposioAuthUrl,
  requestComposioAuthUrl,
} from "../features/plugins/composioAuthLaunch";

/**
 * Lightweight same-origin page opened synchronously on Connect click.
 * Navigates itself to the Composio auth URL once the main app delivers it.
 */
export function ComposioAuthLauncherPage() {
  const [params] = useSearchParams();
  const requestId = (params.get("id") ?? "").trim();
  const [status, setStatus] = useState<"preparing" | "redirecting" | "error">(
    requestId ? "preparing" : "error",
  );
  const [error, setError] = useState<string | null>(
    requestId ? null : "Missing authorization request id.",
  );

  const title = useMemo(() => {
    if (status === "redirecting") return "Redirecting to authorization…";
    if (status === "error") return "Authorization could not start";
    return "Preparing authorization…";
  }, [status]);

  useEffect(() => {
    if (!requestId) return undefined;

    let cancelled = false;
    let channel: BroadcastChannel | null = null;
    let navigated = false;

    const navigate = (authUrl: string) => {
      if (cancelled || navigated) return;
      navigated = true;
      setStatus("redirecting");
      clearStoredComposioAuthUrl(requestId);
      window.location.replace(authUrl);
    };

    const acceptPayload = (data: unknown) => {
      const parsed = parseComposioAuthUrlMessage(data);
      if (!parsed || parsed.requestId !== requestId) return;
      navigate(parsed.authUrl);
    };

    const tryStored = () => {
      const stored = readStoredComposioAuthUrl(requestId);
      if (stored) navigate(stored);
    };

    tryStored();
    requestComposioAuthUrl(requestId);

    const onWindowMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      acceptPayload(event.data);
    };
    window.addEventListener("message", onWindowMessage);

    const onStorage = (event: StorageEvent) => {
      if (event.key !== composioAuthChannelName(requestId)) return;
      tryStored();
    };
    window.addEventListener("storage", onStorage);

    try {
      channel = new BroadcastChannel(composioAuthChannelName(requestId));
      channel.onmessage = (event) => acceptPayload(event.data);
    } catch {
      // Fall through to localStorage polling.
    }

    const poll = window.setInterval(() => {
      tryStored();
      if (!navigated) requestComposioAuthUrl(requestId);
    }, 200);

    const timeout = window.setTimeout(() => {
      if (cancelled || navigated) return;
      setStatus("error");
      setError(
        "Timed out waiting for the authorization link. Return to Plugins and use Open authorization link.",
      );
    }, 60_000);

    return () => {
      cancelled = true;
      window.clearInterval(poll);
      window.clearTimeout(timeout);
      window.removeEventListener("message", onWindowMessage);
      window.removeEventListener("storage", onStorage);
      channel?.close();
    };
  }, [requestId]);

  return (
    <main
      style={{
        minHeight: "100vh",
        margin: 0,
        display: "grid",
        placeItems: "center",
        fontFamily: "system-ui, sans-serif",
        background: "#0b0d10",
        color: "#f4f6f8",
        padding: "24px",
      }}
    >
      <div style={{ maxWidth: 420, textAlign: "center", lineHeight: 1.5 }}>
        <h1 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: 8 }}>{title}</h1>
        {status === "preparing" ? (
          <p style={{ opacity: 0.8, margin: 0 }}>Complete sign-in when the provider page loads.</p>
        ) : null}
        {error ? (
          <p style={{ opacity: 0.9, margin: 0 }} role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </main>
  );
}
