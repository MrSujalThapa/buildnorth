import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type PluginCatalogResponse, type PluginConnectResponse, type PluginView } from "../api/client";
import PluginsPage from "../components/plugins/PluginsPage";
import { isPluginConnected, pluginViewToDisplay } from "../components/plugins/pluginPresentation";
import {
  composioAuthChannelName,
  composioAuthLauncherPath,
  createComposioAuthRequestId,
  deliverComposioAuthUrl,
  parseComposioAuthUrlRequest,
} from "../features/plugins/composioAuthLaunch";

/**
 * Open a same-origin launcher tab synchronously on click.
 * Do NOT use noopener here if we keep a Window ref for diagnostics; BroadcastChannel
 * delivery still works if the browser nulls the proxy. Avoid noreferrer so referrer
 * policy does not interfere with same-origin launcher bootstrap.
 */
function openAuthLauncher(requestId: string): Window | null {
  return window.open(composioAuthLauncherPath(requestId), "_blank");
}

function deliverAuthUrl(
  requestId: string | null,
  url: string,
  popup: Window | null,
): "delivered" | "blocked" {
  if (requestId) {
    deliverComposioAuthUrl(requestId, url, popup);
    // Same-origin launcher was opened on click; treat as delivered even if the
    // WindowProxy is null — BroadcastChannel / localStorage still reach it.
    return "delivered";
  }
  const fallback = window.open(url, "_blank", "noopener,noreferrer");
  return fallback ? "delivered" : "blocked";
}

export function PluginsRoute() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const [authNotice, setAuthNotice] = useState<string | null>(null);
  const [blockedAuthUrl, setBlockedAuthUrl] = useState<string | null>(null);
  const authPopupRef = useRef<Window | null>(null);
  const authRequestIdRef = useRef<string | null>(null);
  const pendingAuthUrlRef = useRef<string | null>(null);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedQuery(query.trim()), 280);
    return () => window.clearTimeout(handle);
  }, [query]);

  const plugins = useQuery({
    queryKey: ["plugins", debouncedQuery],
    queryFn: ({ signal }) => api.pluginsCatalog(signal, debouncedQuery || undefined),
    placeholderData: keepPreviousData,
    staleTime: 120_000,
    refetchOnWindowFocus: false,
  });

  const clearAuthUi = useCallback(() => {
    setAuthNotice(null);
    setBlockedAuthUrl(null);
    pendingAuthUrlRef.current = null;
    authPopupRef.current?.close();
    authPopupRef.current = null;
    authRequestIdRef.current = null;
  }, []);

  const presentAuthUrl = (url: string) => {
    const popup = authPopupRef.current;
    const requestId = authRequestIdRef.current;
    const popupBlocked = Boolean(requestId) && !popup;
    const popupClosed = Boolean(popup?.closed);

    // Always attempt delivery when a launcher request exists — WindowProxy.closed
    // can be a false positive; localStorage/BroadcastChannel still reach the tab.
    if (requestId) {
      pendingAuthUrlRef.current = url;
      deliverComposioAuthUrl(requestId, url, popup);
    } else {
      const result = deliverAuthUrl(null, url, popup);
      if (result === "blocked") {
        setBlockedAuthUrl(url);
        setAuthNotice("Popup blocked. Open the authorization link below to continue.");
        return;
      }
    }

    setBlockedAuthUrl(url);
    if (popupBlocked) {
      setAuthNotice("Popup blocked. Open the authorization link below to continue.");
    } else if (popupClosed) {
      setAuthNotice("Authorization tab may have closed. Open the authorization link below if sign-in did not appear.");
    } else {
      setAuthNotice("Authorization opened in a new tab. Complete sign-in, then return here.");
    }
  };

  const handleConnectResult = (result: PluginConnectResponse, popup: Window | null) => {
    authPopupRef.current = popup;
    if (result.status === "connected") {
      popup?.close();
      clearAuthUi();
      return;
    }
    if (result.auth_url) {
      presentAuthUrl(result.auth_url);
      return;
    }
    popup?.close();
    setAuthNotice("Connection updated. Waiting for provider authorization status…");
    setBlockedAuthUrl(null);
  };

  const connectPlugin = useMutation({
    mutationFn: (pluginId: string) => api.connectPlugin(pluginId),
    onSettled: () => {
      setConnectingId(null);
      void queryClient.invalidateQueries({ queryKey: ["plugins"] });
    },
  });

  const refreshConnection = useMutation({
    mutationFn: (pluginId: string) => api.refreshPluginConnection(pluginId),
    onSettled: () => {
      setConnectingId(null);
      void queryClient.invalidateQueries({ queryKey: ["plugins"] });
    },
  });

  const disconnectPlugin = useMutation({
    mutationFn: (pluginId: string) => api.disconnectPlugin(pluginId),
    onMutate: (pluginId) => {
      setDisconnectingId(pluginId);
      clearAuthUi();
    },
    onSettled: () => {
      setDisconnectingId(null);
      void queryClient.invalidateQueries({ queryKey: ["plugins"] });
    },
  });

  const pluginViews = plugins.data?.items ?? [];
  const providerMessage = plugins.data?.provider_message ?? (plugins.isError ? "Plugins could not be loaded. Retry in a moment." : null);

  const pendingPlugins = useMemo(
    () => pluginViews.filter((plugin) => plugin.connection.status === "pending_auth" && !isPluginConnected(plugin)),
    [pluginViews],
  );
  const pendingKey = pendingPlugins.map((plugin) => plugin.definition.id).join(",");

  useEffect(() => {
    const redeliver = (requestId: string) => {
      const url = pendingAuthUrlRef.current;
      if (!url || authRequestIdRef.current !== requestId) return;
      deliverComposioAuthUrl(requestId, url, authPopupRef.current);
    };

    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const parsed = parseComposioAuthUrlRequest(event.data);
      if (parsed) redeliver(parsed.requestId);
    };
    window.addEventListener("message", onMessage);

    let channel: BroadcastChannel | null = null;
    const requestId = authRequestIdRef.current;
    if (requestId) {
      try {
        channel = new BroadcastChannel(composioAuthChannelName(requestId));
        channel.onmessage = (event) => {
          const parsed = parseComposioAuthUrlRequest(event.data);
          if (parsed) redeliver(parsed.requestId);
        };
      } catch {
        // ignore
      }
    }

    return () => {
      window.removeEventListener("message", onMessage);
      channel?.close();
    };
  }, [connectingId]);

  useEffect(() => {
    if (!pendingKey) return undefined;
    const ids = pendingKey.split(",");
    let inFlight = false;
    let attempts = 0;
    let stopped = false;
    const refreshPending = async () => {
      if (inFlight || stopped) return;
      if (attempts >= 24) {
        stopped = true;
        setAuthNotice("Still waiting for authorization. Refresh the connection from its plugin card.");
        return;
      }
      inFlight = true;
      attempts += 1;
      try {
        const results = await Promise.all(ids.map((id) => api.refreshPluginConnection(id)));
        for (const result of results) {
          if (result.status !== "connected") continue;
          queryClient.setQueryData<PluginCatalogResponse>(["plugins", debouncedQuery], (current) => current && ({
            ...current,
            items: current.items.map((item) => item.definition.id === result.plugin_id
              ? { ...item, connection: { ...item.connection, status: "connected", account_metadata: {
                ...item.connection.account_metadata,
                ...(result.connected_account_id ? { connected_account_id: result.connected_account_id } : {}),
                ...(result.account_label ? { account_label: result.account_label } : {}),
              } } }
              : item),
          }));
          clearAuthUi();
          setAuthNotice(`${result.plugin_id} connected.`);
          void queryClient.invalidateQueries({ queryKey: ["plugins"] });
        }
      } catch {
        // A transient provider failure is retried within the bounded window.
      } finally {
        inFlight = false;
      }
    };
    const onFocus = () => { void refreshPending(); };
    window.addEventListener("focus", onFocus);
    const timer = window.setInterval(onFocus, 5000);
    void refreshPending();
    return () => {
      stopped = true;
      window.removeEventListener("focus", onFocus);
      window.clearInterval(timer);
    };
  }, [pendingKey, debouncedQuery, queryClient, clearAuthUi]);

  const displays = useMemo(() => pluginViews.map(pluginViewToDisplay), [pluginViews]);
  const viewById = useMemo(
    () => new Map(pluginViews.map((plugin) => [plugin.definition.id, plugin] as const)),
    [pluginViews],
  );

  const connectedIds = useMemo(
    () => new Set(pluginViews.filter(isPluginConnected).map((plugin) => plugin.definition.id)),
    [pluginViews],
  );

  const selected = selectedId ? displays.find((plugin) => plugin.id === selectedId) ?? null : null;

  const runConnect = async (pluginId: string, plugin: PluginView) => {
    setConnectingId(pluginId);
    setBlockedAuthUrl(null);
    setAuthNotice(null);

    const existingAuthUrl = plugin.connection.account_metadata?.auth_url;
    const needsOAuth =
      plugin.connection.status === "not_connected" ||
      plugin.connection.status === "error" ||
      (plugin.connection.status === "pending_auth" && Boolean(existingAuthUrl));

    const requestId = needsOAuth ? createComposioAuthRequestId() : null;
    authRequestIdRef.current = requestId;
    const popup = requestId ? openAuthLauncher(requestId) : null;
    authPopupRef.current = popup;

    if (needsOAuth && !popup) {
      setAuthNotice("Popup blocked. Connect will provide an authorization link if needed.");
    }

    try {
      if (plugin.connection.status === "pending_auth" || plugin.connection.status === "error") {
        if (existingAuthUrl && requestId) {
          pendingAuthUrlRef.current = existingAuthUrl;
          deliverComposioAuthUrl(requestId, existingAuthUrl, popup);
          setBlockedAuthUrl(existingAuthUrl);
          if (!popup) {
            setAuthNotice("Popup blocked. Open the authorization link below to continue.");
          } else {
            setAuthNotice("Authorization opened in a new tab. Complete sign-in, then return here.");
          }
        } else if (existingAuthUrl) {
          setBlockedAuthUrl(existingAuthUrl);
          setAuthNotice("Popup blocked. Open the authorization link below to continue.");
        }
        const result = await refreshConnection.mutateAsync(pluginId);
        handleConnectResult(result, popup);
        return;
      }

      const result = await connectPlugin.mutateAsync(pluginId);
      handleConnectResult(result, popup);
    } catch (error) {
      popup?.close();
      authPopupRef.current = null;
      authRequestIdRef.current = null;
      setAuthNotice(error instanceof Error ? error.message : "Connect failed.");
      setBlockedAuthUrl(null);
    }
  };

  const handleToggleConnection = (pluginId: string) => {
    const plugin = viewById.get(pluginId);
    if (!plugin) return;

    if (isPluginConnected(plugin)) {
      disconnectPlugin.mutate(pluginId);
      return;
    }

    void runConnect(pluginId, plugin);
  };

  return (
    <>
      {authNotice || blockedAuthUrl || providerMessage ? (
        <div className="plugins-auth-notice" role="status">
          {providerMessage ? <p>{providerMessage}</p> : null}
          {plugins.isError ? (
            <p>
              <button type="button" onClick={() => void plugins.refetch()}>Retry catalog</button>
            </p>
          ) : null}
          {authNotice ? <p>{authNotice}</p> : null}
          {blockedAuthUrl ? (
            <p>
              <a href={blockedAuthUrl} target="_blank" rel="noopener noreferrer">
                Open authorization link
              </a>
            </p>
          ) : null}
        </div>
      ) : null}
      <PluginsPage
        plugins={displays}
        query={query}
        onQueryChange={setQuery}
        connectedIds={connectedIds}
        selected={selected}
        onSelect={(plugin) => setSelectedId(plugin?.id ?? null)}
        onToggleConnection={handleToggleConnection}
        isConnectionDisabled={(pluginId) => {
          const plugin = viewById.get(pluginId);
          return (
            connectingId === pluginId ||
            disconnectingId === pluginId ||
            plugin?.connection.status === "unavailable"
          );
        }}
        isLoading={plugins.isLoading && !plugins.data}
        isRefreshing={plugins.isFetching && Boolean(plugins.data)}
      />
    </>
  );
}
