import type { PluginView } from "../../api/client";

// Legacy local identifiers are mapped only when their Composio toolkit identity is known.
const legacyToolkitIds: Record<string, string> = {
  calendar: "googlecalendar",
  sheets: "googlesheets",
  drive: "googledrive",
};

export function canonicalToolkitId(id: string): string {
  return legacyToolkitIds[id] ?? id;
}

export function canonicalCatalog(items: PluginView[]): PluginView[] {
  const byToolkit = new Map<string, PluginView>();
  for (const item of items) {
    if (item.definition.id === "manual" || item.definition.id === "csv") continue;
    const key = canonicalToolkitId(item.definition.id);
    const previous = byToolkit.get(key);
    if (!previous) {
      byToolkit.set(key, item);
      continue;
    }
    const currentConnected = ["connected", "syncing", "pending_auth"].includes(item.connection.status);
    const previousConnected = ["connected", "syncing", "pending_auth"].includes(previous.connection.status);
    const providerDefinition = item.definition.provider_type === "composio"
      ? item.definition
      : previous.definition;
    const account = currentConnected && !previousConnected
      ? item
      : previousConnected
        ? previous
        : item.definition.provider_type === "composio"
          ? item
          : previous;
    byToolkit.set(key, {
      definition: { ...providerDefinition, id: account.definition.id },
      connection: account.connection,
    });
  }
  return [...byToolkit.values()];
}
