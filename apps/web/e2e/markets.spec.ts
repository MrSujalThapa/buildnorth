import { expect, test, type Page } from "@playwright/test";

const seededGoals = [
  {
    goal_id: "20000000-0000-0000-0000-000000000001",
    title: "Receive Waterloo Engineering admission",
    goal_type: "deadline_event",
    deadline: "2028-05-31T23:59:59Z",
    forecast_status: "EXPLORATORY",
    state_dimensions: ["academic_performance"],
  },
  {
    goal_id: "20000000-0000-0000-0000-000000000002",
    title: "Receive a Big Tech or FDE offer",
    goal_type: "deadline_event",
    deadline: "2028-08-31T23:59:59Z",
    forecast_status: "EXPLORATORY",
    state_dimensions: ["technical_interview"],
  },
  {
    goal_id: "20000000-0000-0000-0000-000000000003",
    title: "Reach one million dollars in net worth",
    goal_type: "continuous_target",
    deadline: "2035-12-31T23:59:59Z",
    forecast_status: "EXPLORATORY",
    state_dimensions: ["liquid_assets"],
  },
  {
    goal_id: "20000000-0000-0000-0000-000000000004",
    title: "Run a 10K in under 50 minutes",
    goal_type: "threshold",
    deadline: "2028-06-30T23:59:59Z",
    forecast_status: "EXPLORATORY",
    state_dimensions: ["recent_race_time"],
  },
];

async function mockApi(page: Page, goals: unknown[] = seededGoals) {
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok", service: "api", version: "test" } }));
  await page.route("**/api/v1/goals/dashboard", (route) => {
    const items = Array.isArray(goals) ? goals : [];
    const histories = Object.fromEntries(
      items.map((goal) => [(goal as { goal_id: string }).goal_id, []]),
    );
    return route.fulfill({ json: { goals: items, histories } });
  });
  await page.route("**/api/v1/goals", (route) => route.fulfill({ json: goals }));
  await page.route("**/api/v1/what-if/history/**", (route) => route.fulfill({ json: [] }));
}

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test("seeded goals render as an unpriced market grid", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByText("MARKETS", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your outcomes" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Receive Waterloo Engineering admission" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Run a 10K in under 50 minutes" })).toBeVisible();
  await expect(page.locator(".market-card-odds").first()).toHaveText("—");
  await expect(page.locator(".market-card-return").first()).toHaveText("Needs more information");
  await expect(page.locator('[data-testid="probability-line"]')).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(/\d+%/);
  await assertNoHorizontalOverflow(page);
  expect(errors.filter((error) => !error.includes("favicon"))).toEqual([]);
});

test("light and dark themes persist across reload", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", /light|dark/);
  const toggle = page.getByRole("button", { name: /Switch to (dark|light) mode/ });
  if ((page.viewportSize()?.width ?? 1000) <= 640) {
    await expect(toggle).toBeHidden();
    return;
  }
  const current = await html.getAttribute("data-theme");
  await toggle.click();
  const next = current === "dark" ? "light" : "dark";
  await expect(html).toHaveAttribute("data-theme", next);
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", next);
});

test("theme toggle is keyboard operable", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  const toggle = page.getByRole("button", { name: /Switch to (dark|light) mode/ });
  if ((page.viewportSize()?.width ?? 1000) <= 640) {
    await expect(toggle).toBeHidden();
    return;
  }
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("html")).toHaveAttribute("data-theme", /light|dark/);
});

test("narrow viewports keep a single column without overflow", async ({ page }) => {
  await mockApi(page);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Run a 10K in under 50 minutes" })).toBeVisible();
    await assertNoHorizontalOverflow(page);
  }
});

test("crystal canvas mounts on fine pointers and hides under reduced motion", async ({ page }, testInfo) => {
  await mockApi(page);
  await page.goto("/");
  if (testInfo.project.name === "mobile-chromium") {
    await expect(page.locator("canvas.crystal-field")).toHaveCount(0);
    return;
  }
  await expect(page.locator("canvas.crystal-field")).toHaveCount(1);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await expect(page.locator("canvas.crystal-field")).toHaveCount(0);
});
