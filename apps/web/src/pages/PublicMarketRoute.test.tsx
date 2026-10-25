import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
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
