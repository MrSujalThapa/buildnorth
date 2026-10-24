import { expect, test } from "@playwright/test";

test("a failed follow-up keeps the saved goal reachable", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    sessionStorage.setItem("playitout:pending-goal-thread", "saved-thread");
  });
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/agent/threads/saved-thread") return route.fulfill({ json: {
      thread_id: "saved-thread", kind: "create_goal", status: "failed", current_step: "failed",
      progress: ["A provider request failed. Review the saved goal before retrying."],
      debug: { goal_committed: true },
      goal: { goal_id: "saved-goal", title: "Pass a course", goal_type: "threshold",
        success_definition: { target: 80 }, deadline: "2026-12-31T00:00:00Z", state_dimensions: ["course_grade"] },
    } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/new");
  await expect(page.getByRole("alert")).toContainText("Your goal was saved");
  await expect(page.getByRole("link", { name: "Open saved goal" })).toHaveAttribute("href", "/goals/saved-goal");
  await expect(page.getByRole("button", { name: "Create market" })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("saved-goal-after-provider-failure.png"), fullPage: true });
});

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
  await page.getByRole("button", { name: "Create" }).click();
  await page.getByRole("menuitem", { name: "New goal" }).click();
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
  await page.getByRole("button", { name: "Social", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No shared goals" })).toBeVisible();
  await expect(page.getByText(/\+\d+(\.\d+)? pts/)).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("administrator can revoke a generated invitation with clipboard access pending", async ({ page }, testInfo) => {
  const invites: Record<string, unknown>[] = [];
  await page.addInitScript(() => {
    sessionStorage.setItem("pm-test-token", "local-regression-token");
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: () => new Promise<void>(() => {}) }, configurable: true,
    });
  });
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/me") return route.fulfill({ json: {
      user_id: "local-admin", role: "admin", invited: false, email_verified: true,
      hosted: { quota_usd: 0, remaining_usd: 0, remaining_tokens: 0, billing_note: "Regression fixture" },
    } });
    if (path === "/api/v1/admin/invites" && route.request().method() === "POST") {
      const row = {
        invitation_id: "local-invite", kind: "shared", note: "Regression", max_redemptions: 1,
        redemption_count: 0, expires_at: "2027-01-01T00:00:00Z", revoked_at: null,
      };
      invites.push(row);
      return route.fulfill({ json: { ...row, token: "fake-regression-invitation" } });
    }
    if (path.endsWith("/revoke")) {
      invites[0].revoked_at = "2026-10-19T22:00:00Z";
      return route.fulfill({ json: invites[0] });
    }
    if (path === "/api/v1/admin/invites") return route.fulfill({ json: invites });
    if (path === "/api/v1/settings/inference") return route.fulfill({ json: {
      preference: { mode: "hosted", provider: "openai", model: null }, credentials: [], models: [],
      hosted_provider: "none", hosted_model: null,
      byok_usage: { calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0 },
    } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/settings");
  await page.getByRole("button", { name: "Generate link", exact: true }).click();
  await expect(page.getByRole("button", { name: "Generate link", exact: true })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Revoke", exact: true }).click();
  await expect(page.getByText(/redeemed · Revoked/)).toBeVisible();
  await expect(page.getByText(/fake-regression-invitation/)).toHaveCount(0);
  await page.reload();
  await expect(page.getByText(/redeemed · Revoked/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("invitation-revoked.jpg"), fullPage: true });
});

test("connecting a provider key activates BYOK in Settings without a second save", async ({ page }, testInfo) => {
  let mode: "hosted" | "byok" = "hosted";
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => sessionStorage.setItem("pm-test-token", "local-regression-token"));
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/me") return route.fulfill({ json: {
      user_id: "local-judge", role: "user", invited: true, email_verified: true,
      hosted: { enabled: true, quota_usd: 5, remaining_usd: 4.73, global_remaining_usd: 99, remaining_tokens: 5000000, billing_note: "Estimated" },
    } });
    if (path === "/api/v1/settings/inference/credentials/openai" && route.request().method() === "PUT") {
      mode = "byok";
      return route.fulfill({ json: { provider: "openai", status: "validated", masked_suffix: "••••1234", validated_at: "2026-10-19T00:00:00Z", version: "v1" } });
    }
    if (path === "/api/v1/settings/inference") return route.fulfill({ json: {
      preference: { mode, provider: "openai", model: null },
      credentials: mode === "byok" ? [{ provider: "openai", status: "validated", masked_suffix: "••••1234", validated_at: "2026-10-19T00:00:00Z", version: "v1" }] : [],
      models: [], hosted_provider: "openai", hosted_configured: false, hosted_model: "gpt-5.4-mini",
      byok_usage: { calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0 },
    } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/settings");
  await expect(page.getByText("Current mode: Hosted")).toBeVisible();
  await expect(page.getByText(/Hosted credit: \$4\.73 \/ \$5\.00 remaining/)).toBeVisible();
  await page.getByLabel("API key", { exact: true }).fill("sk-local-test-1234");
  await page.getByRole("button", { name: "Connect and use my key" }).click();
  await expect(page.getByText("Current mode: BYOK")).toBeVisible();
  await expect(page.getByText(/BYOK is now active/)).toBeVisible();
  await page.reload();
  await expect(page.getByText("Current mode: BYOK")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("judge-byok-settings.jpg"), fullPage: true });
});

test("administrator can redeem a private invitation and retain hosted entitlement", async ({ page }) => {
  let invited = false;
  await page.addInitScript(() => sessionStorage.setItem("pm-test-token", "local-regression-token"));
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/me") return route.fulfill({ json: {
      user_id: "local-admin", role: "admin", invited, email_verified: true,
      hosted: { enabled: invited, quota_usd: invited ? 5 : 0, remaining_usd: invited ? 5 : 0, remaining_tokens: 5000000, global_remaining_usd: 100, billing_note: "Estimated" },
    } });
    if (path === "/api/v1/invites/redeem") {
      invited = true;
      return route.fulfill({ json: {
        user_id: "local-admin", role: "admin", invited, email_verified: true,
        hosted: { enabled: true, quota_usd: 5, remaining_usd: 5, remaining_tokens: 5000000, global_remaining_usd: 100, billing_note: "Estimated" },
      } });
    }
    return route.fulfill({ json: [] });
  });
  const redemption = page.waitForResponse((response) => response.url().endsWith("/api/v1/invites/redeem"));
  await page.goto("/invite/local-private-invite");
  expect((await redemption).status()).toBe(200);
  await expect(page).toHaveURL(/\/$/);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByText(/\$5\.00 remaining of \$5\.00/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/\$5\.00 remaining of \$5\.00/)).toBeVisible();
});
