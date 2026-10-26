import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { api, type PublicMarketDetail } from "../api/client";
import { PublicMarketRoute } from "./PublicMarketRoute";

vi.mock("../auth/AuthGate", () => ({ useAccount: () => ({ user_id: "owner-1" }) }));
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);
afterEach(() => vi.restoreAllMocks());

function detail(history: PublicMarketDetail["history"]): PublicMarketDetail {
  return {
    goal_id: "g1",
    title: "Save $20,000 in emergency fund by December 2027",
    description: "Reach $20,000 in emergency fund by Dec 31, 2027",
    category: "finance",
    visibility: "private",
    creator: { user_id: "owner-1", handle: "sujal", username: "sujal", display_name: "Sujal", bio: null, has_photo: false },
    star_count: 0,
    fork_count: 0,
    starred: false,
    published_at: null,
    updated_at: null,
    latest_probability: history.length ? history[history.length - 1]!.probability : null,
    forecast: { status: history.length ? "published" : "unpublished" },
    history,
    fork: null,
    blueprint: {
      title: "Save $20,000 in emergency fund by December 2027",
      description: "Reach $20,000 in emergency fund by Dec 31, 2027",
      category: "finance",
      deadline: "2027-12-31T23:59:59Z",
      success_criteria: { metric: "emergency_fund", operator: ">=", target: "20000", unit: "USD" },
      milestones: ["Save $5,000 by March"],
      strategies: [],
      evidence_types: [],
      suggested_integrations: [],
      model_configuration: {},
      forecast: { status: "published" },
    },
    share_path: "/m/g1",
  };
}

function LocationProbe() {
  const location = useLocation();
  return <p data-testid="location">{location.pathname}{location.search}</p>;
}

function renderRoute() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/m/g1"]}>
        <Routes>
          <Route path="/m/:goalId" element={<PublicMarketRoute />} />
          <Route path="/goals/:goalId" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("a one-point market uses the same layout with a sparse chart and real blueprint", async () => {
  vi.spyOn(api, "publicMarket").mockResolvedValue(detail([{ created_at: "2026-10-20T00:00:00Z", probability: 0.27 }]));
  const { container } = renderRoute();
  expect(await screen.findByRole("heading", { name: /Save \$20,000/ })).toBeInTheDocument();
  expect(screen.queryByText("Not published")).not.toBeInTheDocument();
  expect(container.querySelector(".pm-sparse-frame .sparse-chart-dot")).not.toBeNull();
  const stats = container.querySelector(".pm-stats") as HTMLElement;
  expect(within(stats).getByText("27.0%")).toBeInTheDocument();
  expect(within(stats).getByText("Dec 31, 2027")).toBeInTheDocument();
  const blueprint = screen.getByRole("region", { name: "Blueprint" });
  expect(within(blueprint).getByText("At least")).toBeInTheDocument();
  expect(within(blueprint).getByText("20,000")).toBeInTheDocument();
  expect(within(blueprint).getByText("USD")).toBeInTheDocument();
  expect(within(blueprint).getByText("Save $5,000 by March")).toBeInTheDocument();
  expect(within(blueprint).queryByText(/No public success criteria/)).not.toBeInTheDocument();
  const about = screen.getByRole("region", { name: "About" });
  expect(within(about).getByText("Reach $20,000 in emergency fund by Dec 31, 2027")).toBeInTheDocument();
  const owner = screen.getByRole("link", { name: "Open as owner" });
  expect(owner).toHaveClass("pm-action");
  expect(owner).not.toHaveClass("ui-button");
  expect(screen.getByText("Private")).toBeInTheDocument();
});

test("a multi-point market shows change since first publication in points", async () => {
  vi.spyOn(api, "publicMarket").mockResolvedValue(detail([
    { created_at: "2026-10-01T00:00:00Z", probability: 0.2 },
    { created_at: "2026-10-05T00:00:00Z", probability: 0.25 },
    { created_at: "2026-10-09T00:00:00Z", probability: 0.31 },
  ]));
  const { container } = renderRoute();
  await screen.findByRole("heading", { name: /Save \$20,000/ });
  expect(within(container.querySelector(".pm-stats") as HTMLElement).getByText("+11.0 pts")).toBeInTheDocument();
  expect(screen.getByLabelText("Chart range")).toBeInTheDocument();
});

function updatesDetail(visibility: "public" | "private"): PublicMarketDetail {
  const market = detail([
    { created_at: "2026-10-01T00:00:00Z", probability: 0.3 },
    { created_at: "2026-10-06T00:00:00Z", probability: 0.421 },
    { created_at: "2026-10-09T00:00:00Z", probability: 0.35 },
  ]);
  const base = {
    receipt_recorded: true, retired_evidence_count: 0, other_new_evidence_count: 0, model: "count_process@v1",
    model_change: null, status_change: null, definition_revised: false, deadline_changed: false,
  };
  return {
    ...market,
    visibility,
    updates: [
      { ...base, published_at: "2026-10-01T00:00:00Z", probability: 0.3, previous_probability: null, change_points: null,
        kind: "first_publication", evidence_total: 2, new_evidence_count: 2, new_evidence_metrics: ["emergency fund"] },
      { ...base, published_at: "2026-10-06T00:00:00Z", probability: 0.421, previous_probability: 0.3, change_points: 12.1,
        kind: "update", evidence_total: 4, new_evidence_count: 2, new_evidence_metrics: ["emergency fund"], other_new_evidence_count: 1 },
      { ...base, published_at: "2026-10-09T00:00:00Z", probability: 0.35, previous_probability: 0.421, change_points: -7.1,
        kind: "update", evidence_total: 4, new_evidence_count: 0, new_evidence_metrics: [], retired_evidence_count: 1,
        model: "count_process@v2", model_change: { previous: "count_process@v1", current: "count_process@v2" }, deadline_changed: true },
    ],
    modeled_sensitivity: { published_at: "2026-10-09T00:00:00Z", model: "count_process@v2", drivers: ["monthly savings rate"] },
  };
}

function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  return writeText;
}

test("update rows show before/after odds, point change and what the receipt recorded", async () => {
  vi.spyOn(api, "publicMarket").mockResolvedValue(updatesDetail("public"));
  renderRoute();
  await screen.findByRole("heading", { name: /Save \$20,000/ });
  const section = screen.getByRole("region", { name: "What moves the odds" });
  expect(within(section).queryByText("Forecast updated")).not.toBeInTheDocument();
  const rows = within(section).getAllByRole("listitem").filter((row) => row.closest("ol"));
  expect(rows).toHaveLength(3);
  expect(rows[0]).toHaveTextContent("Oct 9, 2026");
  expect(rows[0]).toHaveTextContent("No new evidence");
  expect(rows[0]).toHaveTextContent("1 record superseded · Model count_process@v1 → count_process@v2 · Deadline changed");
  expect(rows[0]).toHaveTextContent("42.1% → 35.0%");
  expect(within(rows[0]!).getByText("−7.1 pts")).toHaveClass("is-down");
  expect(rows[1]).toHaveTextContent("2 new evidence records: emergency fund + 1 other");
  expect(within(rows[1]!).getByText("+12.1 pts")).toHaveClass("is-up");
  expect(rows[2]).toHaveTextContent("First publication, 2 evidence records: emergency fund");
  const sensitivity = within(section).getByRole("region", { name: "Modeled sensitivity" });
  expect(sensitivity).toHaveTextContent("not observed causes");
  expect(sensitivity).toHaveTextContent("monthly savings rate");
});

test("a private market requires reviewing the AI summary before it can be copied", async () => {
  vi.spyOn(api, "publicMarket").mockResolvedValue(updatesDetail("private"));
  vi.spyOn(api, "mcpStatus").mockRejectedValue(new Error("offline"));
  const writeText = stubClipboard();
  renderRoute();
  await screen.findByRole("heading", { name: /Save \$20,000/ });
  fireEvent.click(screen.getByRole("button", { name: "Share" }));
  const dialog = await screen.findByRole("dialog", { name: "Share market" });
  expect(within(dialog).queryByRole("button", { name: "Copy public market link" })).not.toBeInTheDocument();
  expect(within(dialog).getByText(/This market is private\. Publish it/)).toBeInTheDocument();
  expect(within(dialog).queryByRole("button", { name: /Copy/ })).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Review summary before copying" }));
  const preview = within(dialog).getByLabelText("Summary preview");
  expect(preview).toHaveTextContent("Visibility: private, not published");
  expect(preview.textContent).not.toContain("/m/g1");
  fireEvent.click(within(dialog).getByRole("button", { name: "Copy this summary" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledOnce());
  expect(writeText).toHaveBeenCalledWith(preview.textContent);
  expect(await within(dialog).findByText("AI-assistant summary copied")).toBeInTheDocument();
});

test("a public market copies its link and summary directly and points to the MCP connector", async () => {
  vi.spyOn(api, "publicMarket").mockResolvedValue(updatesDetail("public"));
  vi.spyOn(api, "mcpStatus").mockResolvedValue({
    enabled: true, endpoint: "https://playitout.example/mcp", transport: "streamable-http", auth: "oauth",
    dynamic_client_registration: true, scopes: [], default_scopes: [], public_https: true, tools: [],
  });
  const writeText = stubClipboard();
  renderRoute();
  await screen.findByRole("heading", { name: /Save \$20,000/ });
  fireEvent.click(screen.getByRole("button", { name: "Share" }));
  const dialog = await screen.findByRole("dialog", { name: "Share market" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Copy public market link" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/m/g1`));
  fireEvent.click(within(dialog).getByRole("button", { name: "Copy AI-assistant summary" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
  const summary = writeText.mock.calls[1]![0] as string;
  expect(summary).toContain(`- Public market: ${window.location.origin}/m/g1`);
  expect(summary).toContain("42.1% → 35.0% (−7.1 pts)");
  const connector = await within(dialog).findByRole("link", { name: "Open connector settings" });
  expect(connector).toHaveAttribute("href", "/settings#personal-agents-heading");
  expect(within(dialog).getByRole("heading", { name: "Use in ChatGPT via MCP connector" })).toBeInTheDocument();
});

test("forking navigates to the new goal with the forked flag", async () => {
  vi.spyOn(api, "publicMarket").mockResolvedValue(detail([]));
  vi.spyOn(api, "forkMarket").mockResolvedValue({
    goal_id: "fork-9", created: true, visibility: "private", forked_from: "g1", carried_fields: ["title"],
  });
  renderRoute();
  await screen.findByRole("heading", { name: /Save \$20,000/ });
  expect(screen.getByRole("status")).toHaveTextContent(/No forecast has been published/);
  fireEvent.click(screen.getByRole("button", { name: /Fork/ }));
  fireEvent.click(screen.getByRole("button", { name: "Create fork" }));
  expect(await screen.findByTestId("location")).toHaveTextContent("/goals/fork-9?forked=1");
});
