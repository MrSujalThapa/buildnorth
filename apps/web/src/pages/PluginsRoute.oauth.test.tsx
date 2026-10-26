import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { api, type PluginConnectResponse, type PluginView } from "../api/client";
import type { PluginDisplay } from "../components/plugins/PluginsPage";
import { composioAuthChannelName } from "../features/plugins/composioAuthLaunch";
import { PluginsRoute } from "./PluginsRoute";

vi.mock("../components/plugins/PluginsPage", () => ({
  default: ({ plugins, onToggleConnection }: {
    plugins: PluginDisplay[];
    onToggleConnection: (id: string) => void;
  }) => <div>{plugins.map((plugin) => <button key={plugin.id} type="button" onClick={() => onToggleConnection(plugin.id)}>Connect {plugin.id}</button>)}</div>,
}));

function plugin(id: string): PluginView {
  return {
    definition: { id, name: id, description: id, category: "integration", provider_type: "composio", capabilities: [], used_for: [] },
    connection: { plugin_id: id, status: "not_connected", connected_at: null, last_sync_at: null, permissions: [], account_metadata: {}, error: null },
  };
}

function deferred() {
  let resolve!: (value: PluginConnectResponse) => void;
  const promise = new Promise<PluginConnectResponse>((done) => { resolve = done; });
  return { promise, resolve };
}

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

test("overlapping Connect clicks deliver each toolkit URL only to its own launcher", async () => {
  const drive = deferred();
  const slack = deferred();
  const calls: string[] = [];
  vi.spyOn(api, "pluginsCatalog").mockResolvedValue({
    items: [plugin("googledrive"), plugin("slack")], next_cursor: null, total_items: 2,
  });
  vi.spyOn(api, "connectPlugin").mockImplementation((id) => {
    calls.push(id);
    return id === "googledrive" ? drive.promise : slack.promise;
  });
  const popups: { close: ReturnType<typeof vi.fn>; postMessage: ReturnType<typeof vi.fn>; closed: boolean }[] = [];
  const opened: string[] = [];
  vi.spyOn(window, "open").mockImplementation((url) => {
    opened.push(String(url));
    const popup = { close: vi.fn(), postMessage: vi.fn(), closed: false };
    popups.push(popup);
    return popup as unknown as Window;
  });

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><PluginsRoute /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Connect googledrive" }));
  fireEvent.click(screen.getByRole("button", { name: "Connect slack" }));
  await waitFor(() => expect(calls).toEqual(["googledrive", "slack"]));
  const driveRequest = new URL(opened[0]!, window.location.origin).searchParams.get("id")!;
  const slackRequest = new URL(opened[1]!, window.location.origin).searchParams.get("id")!;
  expect(driveRequest).not.toBe(slackRequest);

  slack.resolve({ plugin_id: "slack", connection_id: "slack-connection", status: "pending_auth", auth_url: "https://auth.test/slack" });
  await waitFor(() => expect(localStorage.getItem(composioAuthChannelName(slackRequest))).toBe("https://auth.test/slack"));
  drive.resolve({ plugin_id: "googledrive", connection_id: "drive-connection", status: "pending_auth", auth_url: "https://auth.test/googledrive" });
  await waitFor(() => expect(localStorage.getItem(composioAuthChannelName(driveRequest))).toBe("https://auth.test/googledrive"));
  expect(localStorage.getItem(composioAuthChannelName(slackRequest))).toBe("https://auth.test/slack");
  expect(popups[1]?.close).not.toHaveBeenCalled();
});

test("a mismatched response cannot redirect the selected plugin launcher", async () => {
  vi.spyOn(api, "pluginsCatalog").mockResolvedValue({
    items: [plugin("supabase")], next_cursor: null, total_items: 1,
  });
  vi.spyOn(api, "connectPlugin").mockResolvedValue({
    plugin_id: "outlook", connection_id: "wrong", status: "pending_auth",
    auth_url: "https://auth.test/outlook",
  });
  vi.spyOn(window, "open").mockReturnValue({ close: vi.fn(), closed: false } as unknown as Window);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><PluginsRoute /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Connect supabase" }));
  expect(await screen.findByText(/did not match the selected plugin/)).toBeInTheDocument();
  expect(Object.keys(localStorage).some((key) => key.startsWith("pm-composio-auth:"))).toBe(false);
});
