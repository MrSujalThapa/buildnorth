import { describe, expect, it } from "vitest";
import type { PluginView } from "../../api/client";
import { canonicalCatalog } from "./canonicalCatalog";

function view(id: string, name: string, status: PluginView["connection"]["status"], provider = "composio"): PluginView {
  return {
    definition: { id, name, description: name, category: "integration", provider_type: provider, logo_url: provider === "composio" ? `${id}.svg` : null, capabilities: [], used_for: [] },
    connection: { plugin_id: id, status, connected_at: null, last_sync_at: null, permissions: [], account_metadata: {}, error: null },
  };
}

describe("canonical catalog", () => {
  it("uses the real toolkit logo and keeps a linked legacy account", () => {
    const rows = canonicalCatalog([
      view("calendar", "Google Calendar", "connected", "future_gateway"),
      view("googlecalendar", "Google Calendar", "not_connected"),
    ]);
    expect(rows).toHaveLength(1);
    const first = rows[0];
    expect(first).toBeDefined();
    if (!first) throw new Error("canonical provider missing");
    expect(first.definition.logo_url).toBe("googlecalendar.svg");
    expect(first.connection.status).toBe("connected");
    expect(first.definition.id).toBe("calendar");
  });

  it("drops built-in evidence tools and keeps distinct provider identities", () => {
    const rows = canonicalCatalog([
      view("manual", "Manual", "not_connected", "direct"),
      view("csv", "CSV Import", "not_connected", "direct"),
      view("sheets", "Google Sheets", "not_connected", "future_gateway"),
      view("googlesheets", "Google Sheets", "not_connected"),
      view("slack", "Slack", "not_connected"),
      view("slackbot", "Slackbot", "not_connected"),
    ]);
    expect(rows.map((row) => row.definition.id)).toEqual(["googlesheets", "slack", "slackbot"]);
  });
});
