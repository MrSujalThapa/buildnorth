import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { PersonalAgents } from "../../components/utility/PersonalAgents";
import { ConnectAuthorizePage } from "../../pages/ConnectAuthorizePage";

const read = { scope: "goals:read", label: "Read goals", description: "See goals.", writes: false, spends_credits: false };
const inference = { scope: "inference:use", label: "Use model credits", description: "Run the Evidence Agent.", writes: true, spends_credits: true };

const status = {
  enabled: true,
  endpoint: "http://127.0.0.1:8000/mcp",
  transport: "streamable-http",
  auth: "oauth2.1",
  dynamic_client_registration: true,
  scopes: [read, inference],
  default_scopes: ["goals:read"],
  public_https: false,
  tools: ["get_goal"],
};

const connection = {
  connection_id: "11111111-1111-4111-8111-111111111111",
  client_id: "client",
  client_name: "Desk Agent",
  scopes: [read],
  status: "active",
  created_at: "2026-10-18T10:00:00Z",
  last_used_at: null,
  revoked_at: null,
};

type Call = { url: string; method: string; body: unknown };

function mockFetch(routes: (call: Call) => unknown) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const body: unknown = typeof init?.body === "string" ? JSON.parse(init.body) : null;
    const call = { url, method: init?.method ?? "GET", body };
    calls.push(call);
    return Promise.resolve(new Response(JSON.stringify(routes(call)), { status: 200, headers: { "Content-Type": "application/json" } }));
  });
  return calls;
}

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

test("personal agents shows the endpoint, local-only warning and revokes without exposing tokens", async () => {
  let revoked = false;
  const calls = mockFetch(({ url, method }) => {
    if (url.endsWith("/mcp/status")) return status;
    if (method === "DELETE") {
      revoked = true;
      return { ...connection, status: "revoked", revoked_at: "2026-10-18T11:00:00Z" };
    }
    return revoked ? [{ ...connection, status: "revoked", revoked_at: "2026-10-18T11:00:00Z" }] : [connection];
  });

  render(<PersonalAgents />);
  expect(await screen.findByText("http://127.0.0.1:8000/mcp")).toBeInTheDocument();
  expect(screen.getByText(/only works from this computer/)).toBeInTheDocument();
  expect(screen.getByText("Read goals")).toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(/pio_(at|rt)_/);

  fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
  expect(await screen.findByText("Desk Agent can no longer access your account.")).toBeInTheDocument();
  expect(calls.some((call) => call.method === "DELETE" && call.url.includes(connection.connection_id))).toBe(true);
  expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
  expect(window.localStorage.length).toBe(0);
});

test("consent page approves only the scopes the user keeps", async () => {
  const assign = vi.fn();
  vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, assign });
  const calls = mockFetch(({ method }) => {
    if (method === "POST") return { redirect_url: "http://127.0.0.1:9999/callback?code=x&state=y" };
    return {
      request_id: "req-1",
      client_id: "client",
      client_name: "Desk Agent",
      client_uri: null,
      redirect_host: "127.0.0.1:9999",
      redirect_scheme: "http",
      scopes: [read, inference],
      resource: "http://127.0.0.1:8000/mcp",
      expires_at: "2026-10-18T10:10:00Z",
      verified_client: false,
      warnings: ["Play It Out has not verified this agent."],
    };
  });

  render(
    <MemoryRouter initialEntries={["/connect/authorize?request=req-1"]}>
      <ConnectAuthorizePage />
    </MemoryRouter>,
  );
  expect(await screen.findByText("Desk Agent")).toBeInTheDocument();
  expect(screen.getByText("Can spend model credits.")).toBeInTheDocument();
  expect(screen.getByText("Play It Out has not verified this agent.")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("checkbox", { name: /Use model credits/ }));
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(assign).toHaveBeenCalledWith("http://127.0.0.1:9999/callback?code=x&state=y"));
  const decision = calls.find((call) => call.method === "POST");
  expect(decision?.body).toEqual({ approve: true, scopes: ["goals:read"] });
});
