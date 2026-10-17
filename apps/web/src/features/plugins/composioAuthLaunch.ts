/** Same-origin Composio OAuth launcher messaging (no secrets logged). */

export const COMPOSIO_AUTH_CHANNEL_PREFIX = "pm-composio-auth:";
export const COMPOSIO_AUTH_MESSAGE_TYPE = "pm.composio.auth_url" as const;
export const COMPOSIO_AUTH_REQUEST_TYPE = "pm.composio.auth_url_request" as const;

export type ComposioAuthUrlMessage = {
  type: typeof COMPOSIO_AUTH_MESSAGE_TYPE;
  requestId: string;
  authUrl: string;
};

export type ComposioAuthUrlRequest = {
  type: typeof COMPOSIO_AUTH_REQUEST_TYPE;
  requestId: string;
};

export function composioAuthChannelName(requestId: string): string {
  return `${COMPOSIO_AUTH_CHANNEL_PREFIX}${requestId}`;
}

export function isSafeHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

export function parseComposioAuthUrlMessage(data: unknown): ComposioAuthUrlMessage | null {
  if (!data || typeof data !== "object") return null;
  const record = data as Record<string, unknown>;
  if (record.type !== COMPOSIO_AUTH_MESSAGE_TYPE) return null;
  if (typeof record.requestId !== "string" || !record.requestId.trim()) return null;
  if (typeof record.authUrl !== "string" || !isSafeHttpUrl(record.authUrl)) return null;
  return {
    type: COMPOSIO_AUTH_MESSAGE_TYPE,
    requestId: record.requestId.trim(),
    authUrl: record.authUrl,
  };
}

export function parseComposioAuthUrlRequest(data: unknown): ComposioAuthUrlRequest | null {
  if (!data || typeof data !== "object") return null;
  const record = data as Record<string, unknown>;
  if (record.type !== COMPOSIO_AUTH_REQUEST_TYPE) return null;
  if (typeof record.requestId !== "string" || !record.requestId.trim()) return null;
  return { type: COMPOSIO_AUTH_REQUEST_TYPE, requestId: record.requestId.trim() };
}

/**
 * Deliver auth URL to a same-origin launcher tab.
 * Always write localStorage so a late-mounting launcher can poll it.
 * Also postMessage the popup (if usable) and BroadcastChannel.
 */
export function deliverComposioAuthUrl(
  requestId: string,
  authUrl: string,
  popup?: Window | null,
): void {
  if (!requestId || !isSafeHttpUrl(authUrl)) return;
  const payload: ComposioAuthUrlMessage = {
    type: COMPOSIO_AUTH_MESSAGE_TYPE,
    requestId,
    authUrl,
  };

  try {
    localStorage.setItem(composioAuthChannelName(requestId), authUrl);
  } catch {
    // Ignore quota / private-mode failures.
  }

  try {
    if (popup && !popup.closed) {
      popup.postMessage(payload, window.location.origin);
    }
  } catch {
    // Cross-origin / closed proxy — fall through.
  }

  try {
    const channel = new BroadcastChannel(composioAuthChannelName(requestId));
    channel.postMessage(payload);
    channel.close();
  } catch {
    // BroadcastChannel unavailable.
  }
}

export function requestComposioAuthUrl(requestId: string): void {
  if (!requestId) return;
  const payload: ComposioAuthUrlRequest = {
    type: COMPOSIO_AUTH_REQUEST_TYPE,
    requestId,
  };
  try {
    const opener = window.opener as Window | null;
    if (opener && !opener.closed) {
      opener.postMessage(payload, window.location.origin);
    }
  } catch {
    // opener gone or cross-origin
  }
  try {
    const channel = new BroadcastChannel(composioAuthChannelName(requestId));
    channel.postMessage(payload);
    channel.close();
  } catch {
    // ignore
  }
}

export function readStoredComposioAuthUrl(requestId: string): string | null {
  try {
    const value = localStorage.getItem(composioAuthChannelName(requestId));
    return value && isSafeHttpUrl(value) ? value : null;
  } catch {
    return null;
  }
}

export function clearStoredComposioAuthUrl(requestId: string): void {
  try {
    localStorage.removeItem(composioAuthChannelName(requestId));
  } catch {
    // ignore
  }
}

export function createComposioAuthRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `auth-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function composioAuthLauncherPath(requestId: string): string {
  return `/auth/composio/launch?id=${encodeURIComponent(requestId)}`;
}
