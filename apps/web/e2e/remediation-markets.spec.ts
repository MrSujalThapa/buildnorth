import { expect, test } from "@playwright/test";

const goal = {
  goal_id: "20000000-0000-0000-0000-000000000001",
  title: "Read 20 books by end of 2026",
  goal_type: "continuous_target",
  deadline: "2026-12-31T23:59:59Z",
  forecast_status: "ANCHORED",
  state_dimensions: ["books_read"],
};
const collection = {
  collection: { collection_id: "30000000-0000-0000-0000-000000000001", owner_id: "10000000-0000-0000-0000-000000000001", name: "Personal", description: "", icon: null, color: null, position: 0, goal_ids: [goal.goal_id] },
  progress: { value: null, available: 0, total: 1, incomplete: true, methodology: "", notes: [] },
  portfolio_odds: 62,
  change_pp: null,
  priced_goals: 1,
  total_goals: 1,
  portfolio_methodology: "Equal-weight average of published member-goal probabilities.",
  series: [{ goal_id: goal.goal_id, title: goal.title, color: "#187f75", withheld: false, points: [{ timestamp: "2026-10-19T12:00:00Z", value: 58 }, { timestamp: "2026-10-20T12:00:00Z", value: 62 }] }],
};

test("markets and collection stay clear at desktop and mobile widths", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok" } }));
  await page.route("**/api/v1/goals/dashboard", (route) => route.fulfill({ json: { goals: [goal], histories: { [goal.goal_id]: [] }, collections: [collection] } }));
  await page.route("**/api/v1/collections/**", (route) => route.fulfill({ json: collection }));
  await page.goto("/markets");
  await expect(page.getByRole("heading", { name: "Your outcomes" })).toBeVisible();
  await expect(page.getByText("Track how new evidence changes")).toHaveCount(0);
  await expect(page.getByText("PERSONAL", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: goal.title })).toBeVisible();
  await expect(page.locator(".collection-card .market-card-odds")).toHaveText("62%");
  await expect(page.locator(".collection-card .market-card-return")).toHaveText("—");
  await expect(page.locator(".collection-card .recharts-line")).toHaveCount(1);
  await expect(page.locator(".collection-card .collection-legend")).toHaveCount(0);
  await page.screenshot({ path: `test-results/remediation-markets-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("button", { name: "Select Personal collection" }).click();
  await expect(page.getByRole("toolbar", { name: "Selection actions" })).toContainText("1 selected");
  await expect(page.getByRole("button", { name: "Share" })).toBeDisabled();
  await page.getByRole("button", { name: "Select Personal collection" }).click();
  await expect(page.getByRole("toolbar", { name: "Selection actions" })).toContainText("0 selected");
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Open Personal collection" }).click();
  await expect(page.getByRole("heading", { name: "Personal" })).toBeVisible();
  await expect(page.getByText("62%", { exact: true })).toBeVisible();
  await page.getByText("Goals and calculation").click();
  await expect(page.getByText("1 of 1 goals have published odds.")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
