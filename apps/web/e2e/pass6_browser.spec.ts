import { expect, test } from "@playwright/test";

const API = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";
const CAREER = "20000000-0000-0000-0000-000000000002";

test.describe("Pass 6 browser journeys", () => {
  test("What If Change runs simulation for LinkedIn intervention", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto(`/goals/${CAREER}/what-if`);
    await expect(page.getByText(/What if|Change|intervention/i).first()).toBeVisible({ timeout: 60_000 });
    const input = page.getByPlaceholder(/What if|Describe|action/i).or(page.locator("textarea")).first();
    await input.fill("What if I post on LinkedIn 4 times a week?");
    const run = page.getByRole("button", { name: /Run|Simulate|Explore/i }).first();
    if (await run.isVisible()) {
      await run.click();
    }
    await expect(page.locator("body")).toContainText(/odds|probability|%|NOT_PRICED|Not priced|Result/i, {
      timeout: 120_000,
    });
  });

  test("Markets dark mode shares shell tokens with What If", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto("/");
    const theme = page.getByRole("button", { name: /Switch to dark mode|Switch to light mode/i });
    const label = (await theme.getAttribute("aria-label")) || "";
    if (label.includes("dark")) {
      await theme.click();
    }
    await page.goto("/");
    const marketsColor = await page.locator("main").evaluate((el) => getComputedStyle(el).backgroundColor);
    await page.goto(`/goals/${CAREER}/what-if`);
    const whatIfColor = await page.locator("main").evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(marketsColor).not.toBe("rgba(0, 0, 0, 0)");
    expect(whatIfColor).toBe(marketsColor);
  });

  test("Evidence workspace opens for career goal", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto(`/goals/${CAREER}/evidence`);
    await expect(page.getByText(/Evidence|Sources|Recommended|Connected/i).first()).toBeVisible({
      timeout: 90_000,
    });
  });
});

test("API health for browser suite", async ({ request }) => {
  const response = await request.get(`${API}/health`);
  expect(response.ok()).toBeTruthy();
});
