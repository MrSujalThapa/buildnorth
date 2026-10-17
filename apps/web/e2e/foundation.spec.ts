import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok", service: "api", version: "test" } }));
  await page.route("**/api/v1/goals", (route) => route.fulfill({ json: [] }));
});

test("foundation shell is usable without forecast data", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("MARKETS", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your outcomes" })).toBeVisible();
  await expect(page.getByText("No goals yet")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/\d+%/);
});
