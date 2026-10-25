import { expect, test } from "@playwright/test";

const market = {
  goal_id: "11111111-1111-1111-1111-111111111111",
  title: "Land an FDE offer",
  description: "Public blueprint",
  category: "deadline_event",
  visibility: "public",
  creator: { user_id: "aaaa", handle: "alice", username: "alice", display_name: "Alice", bio: "Builder", has_photo: false },
  star_count: 1,
  fork_count: 0,
  starred: false,
  published_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  latest_probability: 0.42,
  forecast: { status: "published" },
  history: [{ created_at: "2026-09-01T00:00:00Z", probability: 0.3 }, { created_at: "2026-10-01T00:00:00Z", probability: 0.42 }],
  fork: null,
  blueprint: {
    title: "Land an FDE offer",
    description: "Public blueprint",
    category: "deadline_event",
    deadline: "2026-12-31T23:59:59Z",
    success_criteria: { event: "signed_offer" },
    milestones: ["Prep"],
    strategies: ["Practice interviews"],
    evidence_types: ["applications"],
    suggested_integrations: [],
    model_configuration: {},
    forecast: { status: "published" },
  },
  share_path: "/m/11111111-1111-1111-1111-111111111111",
};

test("marketplace and public market stay honest with real chart data", async ({ page }, testInfo) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/me") return route.fulfill({ json: {
      user_id: "user-1", clerk_user_id: "clerk-1", email: "alice@example.test", invited: true, role: "user",
    } });
    if (path === "/api/v1/public/markets") return route.fulfill({ json: { items: [market], total: 1, limit: 24, offset: 0 } });
    if (path.endsWith(`/api/v1/public/markets/${market.goal_id}`)) return route.fulfill({ json: market });
    if (path === "/api/v1/public/creators") return route.fulfill({ json: { items: [market.creator] } });
    if (path.includes("/public/profiles/alice/markets")) return route.fulfill({ json: { items: [market], total: 1, limit: 24, offset: 0 } });
    if (path.includes("/public/profiles/alice")) return route.fulfill({ json: {
      creator: market.creator, follower_count: 2, following_count: 1, following: false, is_self: false,
      market_count: 1, contribution_total: 2, activity: [{ day: "2026-10-01", count: 2 }],
    } });
    if (path.includes("/goals/dashboard")) return route.fulfill({ json: { goals: [], histories: {}, collections: [] } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/social");
  await expect(page.getByRole("heading", { name: "Discover" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Land an FDE offer" })).toBeVisible();
  await page.getByRole("button", { name: /Land an FDE offer/ }).click();
  await expect(page).toHaveURL(/\/m\//);
  await expect(page.getByText("42.0%")).toBeVisible();
  await expect(page.locator(".sparse-public-point")).toHaveCount(2);
  await expect(page.locator(".market-chart-wrapper svg")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "What if" })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("public-market.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/u/alice");
  await expect(page.getByRole("heading", { name: "Alice" })).toBeVisible();
  await expect(page.getByText("Only events on public markets appear here.")).toBeVisible();
  await expect(page.getByText("Your parameters")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("public-profile-mobile.png"), fullPage: true });
});


test("social errors are not presented as empty content and can recover", async ({ page }, testInfo) => {
  let failed = true;
  await page.route("**/api/v1/public/markets*", async (route) => {
    if (failed) return route.fulfill({ status: 503, json: { detail: "Unavailable" } });
    return route.fulfill({ json: { items: [market] } });
  });
  await page.route("**/api/v1/public/creators", (route) => route.fulfill({ json: { items: [] } }));
  await page.goto("/social");
  await expect(page.getByRole("alert")).toContainText("Could not load markets");
  await expect(page.getByText("No public markets")).toHaveCount(0);
  failed = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: market.title })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("discover-recovered.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath("discover-recovered-mobile.png"), fullPage: true });
});


test("Discover loads API pages, deduplicates and resets for search and sort", async ({ page }, testInfo) => {
  const items = Array.from({ length: 25 }, (_, index) => ({
    ...market, goal_id: `11111111-1111-1111-1111-${String(index + 1).padStart(12, "0")}`, title: `Journey ${index + 1}`,
  }));
  let pageTwoFailed = false;
  const requests: string[] = [];
  await page.route("**/api/v1/public/creators", (route) => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/public/markets*", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url.search);
    const q = url.searchParams.get("q");
    const sort = url.searchParams.get("sort");
    const offset = Number(url.searchParams.get("offset") ?? 0);
    if (q === "missing") return route.fulfill({ json: { items: [], total: 0, limit: 24, offset: 0 } });
    if (q) return route.fulfill({ json: { items: [items[24]], total: 1, limit: 24, offset: 0 } });
    if (sort === "stars") return route.fulfill({ json: { items: [items[23]], total: 1, limit: 24, offset: 0 } });
    if (offset === 24 && !pageTwoFailed) { pageTwoFailed = true; return route.fulfill({ status: 503, json: { detail: "Unavailable" } }); }
    return route.fulfill({ json: {
      items: offset === 0 ? items.slice(0, 24) : [items[23], items[24]],
      total: 25, limit: 24, offset,
    } });
  });
  await page.goto("/social");
  await expect(page.getByText("Showing 24 of 25 public markets")).toBeVisible();
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByText("Could not load more markets.")).toBeVisible();
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Showing 25 of 25 public markets")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Journey 24" })).toHaveCount(1);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("discover-paginated.png") });
  await page.getByRole("textbox", { name: "Search public markets" }).fill("specific");
  await expect(page.getByText("Showing 1 of 1 public markets")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Journey 1" })).toHaveCount(0);
  await page.getByRole("textbox", { name: "Search public markets" }).fill("missing");
  await expect(page.getByRole("heading", { name: "No matching markets" })).toBeVisible();
  await page.getByRole("button", { name: "Clear search" }).click();
  await page.getByRole("combobox", { name: "Sort markets" }).selectOption("stars");
  await expect(page.getByText("Showing 1 of 1 public markets")).toBeVisible();
  expect(requests.some((value) => value.includes("offset=24"))).toBe(true);
  expect(requests.some((value) => value.includes("q=specific"))).toBe(true);
  expect(requests.some((value) => value.includes("sort=stars"))).toBe(true);
});

test("one or two published observations render without a synthetic trend", async ({ page }, testInfo) => {
  const observed = [
    { created_at: "2026-09-01T00:00:00Z", probability: 0.3 },
    { created_at: "2026-10-01T00:00:00Z", probability: 0.42 },
  ];
  await page.route("**/api/v1/public/markets/**", (route) => route.fulfill({ json: { ...market, history: observed } }));
  await page.goto(`/m/${market.goal_id}`);
  await expect(page.locator(".sparse-public-point")).toHaveCount(2);
  await expect(page.locator(".market-chart-wrapper svg")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "What counts as success" })).toBeVisible();
  await expect(page.getByText("signed offer")).toBeVisible();
  await expect(page.getByText(/Target date: December 31, 2026/)).toBeVisible();
  await expect(page.locator(".sparse-public-history")).toHaveScreenshot("sparse-two-observations.png", { animations: "disabled" });
  await page.screenshot({ path: testInfo.outputPath("two-observations-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath("two-observations-mobile.png"), fullPage: true });
  observed.pop();
  await page.reload();
  await expect(page.locator(".sparse-public-point")).toHaveCount(1);
  await expect(page.locator(".market-chart-wrapper svg")).toHaveCount(0);
  await expect(page.locator(".sparse-public-history")).toHaveScreenshot("sparse-one-observation.png", { animations: "disabled" });
});


test("three published forecasts retain the existing interactive chart", async ({ page }) => {
  await page.route("**/api/v1/public/markets/**", (route) => route.fulfill({ json: {
    ...market, history: [
      ...market.history, { created_at: "2026-10-20T00:00:00Z", probability: 0.47 },
    ],
  } }));
  await page.goto(`/m/${market.goal_id}`);
  await expect(page.locator(".sparse-public-history")).toHaveCount(0);
  await expect(page.locator(".market-chart-wrapper svg")).toBeVisible();
  await expect(page.getByRole("button", { name: "ALL" })).toBeVisible();
});
