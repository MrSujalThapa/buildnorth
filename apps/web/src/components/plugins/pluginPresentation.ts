import {
  CalendarDays,
  Code2,
  FileText,
  FolderOpen,
  Mail,
  MessageSquare,
  Palette,
  Sheet,
  Timer,
  type LucideIcon,
} from "lucide-react";
import type { PluginView } from "../../api/client";
import type { PluginDisplay } from "./PluginsPage";

const iconById: Record<string, LucideIcon> = {
  github: Code2,
  gmail: Mail,
  calendar: CalendarDays,
  drive: FolderOpen,
  strava: Timer,
  notion: FileText,
  slack: MessageSquare,
  sheets: Sheet,
  figma: Palette,
};

const readsById: Record<string, string[]> = {
  github: ["Pull requests", "Commits", "Issues", "Review activity"],
  gmail: ["Selected recruiter mail", "Application updates", "Interview messages"],
  calendar: ["Selected calendar events", "Event duration", "Attendance patterns"],
  drive: ["Selected documents", "File activity"],
  strava: ["Workouts", "Distance", "Training time"],
  notion: ["Selected pages", "Project updates", "Goal notes"],
  slack: ["Selected channel activity", "Project updates"],
  sheets: ["Selected spreadsheets", "Tracker updates"],
  figma: ["Selected files", "Design activity", "Prototype updates"],
};

function formatLastSync(lastSyncAt: string | null | undefined): string | undefined {
  if (!lastSyncAt) return undefined;
  const parsed = new Date(lastSyncAt);
  if (Number.isNaN(parsed.getTime())) return undefined;
  const minutes = Math.max(0, Math.round((Date.now() - parsed.getTime()) / 60_000));
  if (minutes < 1) return "Last synced just now";
  if (minutes < 60) return `Last synced ${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return `Last synced ${hours} hr ago`;
}

export function isPluginConnected(plugin: PluginView): boolean {
  return plugin.connection.status === "connected" || plugin.connection.status === "syncing";
}

export function pluginViewToDisplay(plugin: PluginView): PluginDisplay {
  const id = plugin.definition.id;
  const reads =
    plugin.definition.capabilities.length > 0
      ? plugin.definition.capabilities.map((capability) => capability.label)
      : readsById[id] ?? ["Selected read activity"];
  const usedFor =
    plugin.definition.used_for.length > 0
      ? plugin.definition.used_for
      : ["Goal evidence"];
  return {
    id,
    name: plugin.definition.name,
    description: plugin.definition.description,
    reads,
    usedFor,
    account:
      plugin.connection.account_metadata.account_label ||
      plugin.connection.account_metadata.connected_account_id ||
      undefined,
    lastSyncLabel: formatLastSync(plugin.connection.last_sync_at),
    logoUrl: plugin.definition.logo_url ?? undefined,
    Icon: iconById[id] ?? Code2,
    connectionStatus: plugin.connection.status,
  };
}
