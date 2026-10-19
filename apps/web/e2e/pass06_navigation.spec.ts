import { expect, test } from "@playwright/test";

// Isolated UI regression only. These fixtures are never live-production evidence.
test("empty catalog leads to goal creation and an actionable provider failure", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/agent/threads") return route.fulfill({
      status: 503, json: { error: { type: "ProviderNotConfiguredError", message: "Hosted inference is not configured" } },
    });
    if (path === "/api/v1/settings/inference") return route.fulfill({ json: {
      preference: { mode: "hosted", provider: "openai", model: null }, credentials: [], models: [],
      hosted_provider: "none", hosted_model: null,
      byok_usage: { calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0 },
    } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/markets");
  await expect(page.getByText("No goals yet")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("markets-create.jpg"), fullPage: true });
  await page.getByRole("link", { name: "Create goal", exact: true }).click();
  await expect(page).toHaveURL(/\/new$/);
  await page.reload();
  await expect(page.getByRole("heading", { name: "New market" })).toBeVisible();
  await page.getByLabel("What should happen?").fill("Pass 06: run 10 km under 50 minutes by December 2027");
  const response = page.waitForResponse((r) => r.url().endsWith("/api/v1/agent/threads"));
  await page.getByRole("button", { name: "Create market", exact: true }).click();
  expect((await response).status()).toBe(503);
  await expect(page.getByRole("alert")).toContainText("Hosted inference is not configured");
  await expect(page.getByRole("button", { name: "Create market", exact: true })).toBeEnabled();
  await expect(page.getByRole("link", { name: "Check inference settings" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("goal-provider-failure.jpg"), fullPage: true });
  await page.getByRole("link", { name: "Check inference settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
