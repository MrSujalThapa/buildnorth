import { Check, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { PluginBrandIcon } from "./PluginBrandIcon";
import type { PluginDisplay } from "./PluginsPage";
export default function PluginDetailPanel({
  plugin,
  connected,
  onToggle,
  onClose,
}: {
  plugin: PluginDisplay;
  connected: boolean;
  onToggle: () => void;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);

  return (
    <div className="plugin-backdrop" onMouseDown={onClose}>
      <aside
        className="plugin-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="plugin-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <span className="plugin-icon large">
            <PluginBrandIcon id={plugin.id} logoUrl={plugin.logoUrl} Icon={plugin.Icon} size={26} />
          </span>          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close plugin details">
            <X size={20} />
          </button>
        </header>
        <h2 id="plugin-title">{plugin.name}</h2>
        <p className="plugin-description">{plugin.description}</p>
        <p className="evidence-note">
          {plugin.name} can contribute verified activity as evidence. Evidence may update a relevant goal
          forecast.
        </p>
        {connected ? (
          <div className="account-block">
            <small>Connected account</small>
            <strong>{plugin.account ?? "Connected"}</strong>
            {plugin.lastSyncLabel ? <span>{plugin.lastSyncLabel}</span> : null}
          </div>
        ) : null}
        <section>
          <h3>What Play It Out can read</h3>
          <ul>
            {plugin.reads.map((item) => (
              <li key={item}>
                <Check size={16} />
                {item}
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h3>Used for</h3>
          <ul className="used-for">
            {plugin.usedFor.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
        <button
          className={connected ? "disconnect-button" : "connect-button"}
          type="button"
          onClick={onToggle}
          disabled={plugin.connectionStatus === "unavailable"}
        >
          {connected ? "Disconnect" : `Connect ${plugin.name}`}
        </button>
      </aside>
    </div>
  );
}
