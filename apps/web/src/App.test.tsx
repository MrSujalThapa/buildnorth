import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";
import { seededGoals } from "./test/fixtures";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function mockApi(goals: unknown = []) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    let payload: unknown = goals;
    if (url.endsWith("/health")) payload = { status: "ok", service: "api", version: "test" };
    else if (url.includes("/history/")) payload = [];
    else if (url.includes("/plugins")) payload = { items: [], provider_status: "unavailable" };
    else if (url.includes("/goals/dashboard")) payload = { goals, histories: {}, collections: [] };
    else if (url.includes("/profile")) payload = { account: { email: "judge@example.test", profile: {} }, goal_count: 0, collection_count: 0, radar: { dimensions: [] }, privacy: "private" };
    else if (url.includes("/goals/") && !url.endsWith("/goals")) payload = (goals as typeof seededGoals)[0] ?? {};
    else if (url.endsWith("/goals")) payload = goals;
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
  });
}

test("renders the approved markets shell without inventing forecasts", async () => {
  mockApi([]);
  renderApp();
  expect(await screen.findByRole("heading", { name: "Your outcomes" })).toBeInTheDocument();
  expect(screen.getByText("MARKETS")).toBeInTheDocument();
});

test("renders seeded goals using the template market cards", async () => {
  mockApi(seededGoals);
  renderApp();
  expect(await screen.findByRole("heading", { name: "Receive Waterloo Engineering admission" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Your outcomes" })).toBeInTheDocument();
});

test.each([{ label: "empty", goals: [] }, { label: "populated", goals: seededGoals }])("goal creation is reachable from the $label markets catalog", async ({ goals }) => {
  mockApi(goals);
  renderApp();
  const create = await screen.findByRole("link", { name: "New goal" });
  expect(create).toHaveAttribute("href", "/new");
  fireEvent.click(screen.getByRole("button", { name: "Create" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "New goal" }));
  expect(await screen.findByRole("heading", { name: "New market" })).toBeInTheDocument();
});

test("theme toggle persists the explicit preference", async () => {
  mockApi([]);
  renderApp();
  const toggle = await screen.findByRole("button", { name: "Switch to dark mode" });
  fireEvent.click(toggle);
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(window.localStorage.getItem("pm-theme")).toBe("dark");
});

test("Social is honest about unavailable sharing and does not invent probability movements", async () => {
  mockApi([]);
  renderApp();
  await screen.findByRole("heading", { name: "Your outcomes" });
  fireEvent.click(within(screen.getByRole("complementary")).getByRole("button", { name: "Social" }));
  expect(await screen.findByRole("heading", { name: "No shared goals" })).toBeInTheDocument();
  expect(screen.queryByText(/\+\d+(\.\d+)? pts/)).not.toBeInTheDocument();
});
