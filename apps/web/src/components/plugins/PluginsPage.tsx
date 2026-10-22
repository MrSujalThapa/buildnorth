import { useMemo } from "react";
import { Check, Plus, Search, type LucideIcon } from "lucide-react";
import PluginDetailPanel from "./PluginDetailPanel";
import { PluginBrandIcon } from "./PluginBrandIcon";
import "./plugins.css";

export type PluginDisplay = {
  id: string;
  name: string;
  description: string;
  reads: string[];
  usedFor: string[];
  account?: string;
  lastSyncLabel?: string;
  logoUrl?: string;
  Icon: LucideIcon;
  connectionStatus: "connected" | "not_connected" | "pending_auth" | "syncing" | "error" | "unavailable";
};

export type PluginsPageProps = {
  plugins: PluginDisplay[];
  query: string;
  onQueryChange: (value: string) => void;
  connectedIds: ReadonlySet<string>;
  selected: PluginDisplay | null;
  onSelect: (plugin: PluginDisplay | null) => void;
  onToggleConnection: (pluginId: string) => void;
  isConnectionDisabled?: (pluginId: string) => boolean;
  isLoading?: boolean;
  isRefreshing?: boolean;
  canBrowse?: boolean;
  browsing?: boolean;
  onBrowse?: () => void;
};

export default function PluginsPage({
  plugins,
  query,
  onQueryChange,
  connectedIds,
  selected,
  onSelect,
  onToggleConnection,
  isConnectionDisabled,
  isLoading = false,
  isRefreshing = false,
  canBrowse = false,
  browsing = false,
  onBrowse,
}: PluginsPageProps) {
  const filtered = useMemo(() => {
    const trimmed = query.trim();
    if (trimmed) {
      return plugins;
    }
    return plugins.filter((plugin) =>
      `${plugin.name} ${plugin.description}`.toLowerCase().includes(query.toLowerCase()),
    );
  }, [plugins, query]);

  if (isLoading) {
    return (
      <main className="plugins-page">
        <div className="plugins-shell">
          <p role="status">Loading plugins…</p>
        </div>
      </main>
    );
  }

  return (
    <main className="plugins-page">
      <div className="plugins-shell">
        <header className="plugins-header">
          <div>
            <h1>Plugins</h1>
            {isRefreshing ? <span role="status" className="field-hint">Updating…</span> : null}
          </div>
          <label className="plugin-search">
            <Search size={18} />
            <span className="visually-hidden">Search plugins</span>
            <input
              name="plugin-search"
              autoComplete="off"
              type="search"
              placeholder="Search plugins…"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
            />
          </label>
        </header>

        <section className="installed-section" aria-labelledby="installed-title">
          <div className="section-heading">
            <h2 id="installed-title">Installed</h2>
            <span>{connectedIds.size}</span>
          </div>
          <div className="installed-strip">
            {plugins
              .filter((plugin) => connectedIds.has(plugin.id))
              .map((plugin) => (
                <button
                  key={plugin.id}
                  type="button"
                  onClick={() => onSelect(plugin)}
                  aria-label={`View ${plugin.name}`}
                >
                  <PluginBrandIcon id={plugin.id} logoUrl={plugin.logoUrl} Icon={plugin.Icon} size={21} />
                  <span>{plugin.name}</span>
                </button>
              ))}
            <button
              type="button"
              onClick={() => document.getElementById("popular-title")?.scrollIntoView()}
              aria-label="Add a plugin"
            >
              <Plus size={21} />
              <span>Add</span>
            </button>
          </div>
        </section>

        <section className="plugin-directory" aria-labelledby="popular-title">
          <div className="section-heading">
            <h2 id="popular-title">{query.trim() ? "Results" : "Popular"}</h2>
            <span>{filtered.length} plugins</span>
          </div>
          {filtered.length ? (
            <div className="plugin-list">
              {filtered.map((plugin) => {
                const connected = connectedIds.has(plugin.id);
                const pending = plugin.connectionStatus === "pending_auth";
                const disabled = isConnectionDisabled?.(plugin.id) ?? false;
                return (
                  <article className="plugin-row" key={plugin.id}>
                    <button className="plugin-main" type="button" onClick={() => onSelect(plugin)}>
                      <span className="plugin-icon">
                        <PluginBrandIcon id={plugin.id} logoUrl={plugin.logoUrl} Icon={plugin.Icon} size={22} />
                      </span>
                      <span>
                        <strong>{plugin.name}</strong>
                        <small>{plugin.description}</small>
                      </span>
                    </button>
                    <button
                      className={
                        connected
                          ? "connection-state connected"
                          : pending
                            ? "connection-state pending"
                            : "connection-state"
                      }
                      type="button"
                      disabled={disabled}
                      onClick={(event) => {
                        event.stopPropagation();
                        onToggleConnection(plugin.id);
                      }}
                      aria-label={`${connected ? "Disconnect" : pending ? "Continue authorization for" : "Connect"} ${plugin.name}`}
                    >
                      {connected ? (
                        <>
                          <Check size={14} />
                          Connected
                        </>
                      ) : pending ? (
                        "Pending"
                      ) : (
                        <Plus size={18} />
                      )}
                    </button>
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="plugins-empty">No plugins match “{query}”.</p>
          )}
          {canBrowse && !query.trim() ? (
            <button type="button" className="plugin-browse" onClick={onBrowse} disabled={browsing}>
              {browsing ? "Loading integrations…" : "Browse all integrations"}
            </button>
          ) : null}
        </section>
      </div>
      {selected ? (
        <PluginDetailPanel
          plugin={selected}
          connected={connectedIds.has(selected.id)}
          onToggle={() => onToggleConnection(selected.id)}
          onClose={() => onSelect(null)}
        />
      ) : null}
    </main>
  );
}
