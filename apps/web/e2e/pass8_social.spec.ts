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
    if (path === "/api/v1/public/markets") return route.fulfill({ json: { items: [market] } });
    if (path.endsWith(`/api/v1/public/markets/${market.goal_id}`)) return route.fulfill({ json: market });
    if (path === "/api/v1/public/creators") return route.fulfill({ json: { items: [market.creator] } });
    if (path.includes("/public/profiles/alice/markets")) return route.fulfill({ json: { items: [market] } });
    if (path.includes("/public/profiles/alice")) return route.fulfill({ json: {
      creator: market.creator, follower_count: 2, following_count: 1, following: false, is_self: false,
      market_count: 1, contribution_total: 4, activity: [{ day: "2026-10-01", count: 2 }],
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
  await expect(page.getByRole("button", { name: "What if" })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("public-market.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/u/alice");
  await expect(page.getByRole("heading", { name: "Alice" })).toBeVisible();
  await expect(page.getByText("Your parameters")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("public-profile-mobile.png"), fullPage: true });
});
