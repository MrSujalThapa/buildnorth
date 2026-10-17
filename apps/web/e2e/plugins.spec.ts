import { expect, test } from "@playwright/test";

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";

/** Real OAuth destinations after leaving the same-origin launcher. */
const AUTH_DESTINATION =
  /connect\.composio\.dev|backend\.composio\.dev|accounts\.google\.com|notion\.so|api\.notion\.com|slack\.com|github\.com|login\.microsoftonline\.com/i;

async function clickConnectForSearch(page: import("@playwright/test").Page, query: string) {
  await page.goto("/plugins");
  await expect(page.getByText("Loading plugins…")).toHaveCount(0, { timeout: 120_000 });
  await page.getByPlaceholder("Search plugins…").fill(query);
  await expect(page.getByRole("heading", { name: "Results" })).toBeVisible({ timeout: 120_000 });
  const row = page.getByRole("article").filter({ hasText: new RegExp(query, "i") }).first();
  await expect(row).toBeVisible({ timeout: 120_000 });
  const button = row.locator("button.connection-state");
  await expect(button).toBeVisible({ timeout: 30_000 });
  return button;
}

async function expectPopupReachesAuthDestination(
  context: import("@playwright/test").BrowserContext,
  page: import("@playwright/test").Page,
  connectButton: import("@playwright/test").Locator,
) {
  const popupPromise = context.waitForEvent("page");
  await connectButton.click();
  const popup = await popupPromise;

  // Launcher may briefly be same-origin /auth/composio/launch — must leave it.
  await expect
    .poll(
      async () => {
        try {
          return popup.url();
        } catch {
          return "about:blank";
        }
      },
      { timeout: 45_000 },
    )
    .toMatch(AUTH_DESTINATION);

  const finalUrl = popup.url();
  expect(finalUrl).not.toMatch(/^about:blank$/i);
  expect(finalUrl).not.toMatch(/\/auth\/composio\/launch/i);
  await expect(
    page.getByText(/Authorization opened in a new tab|Popup blocked/i).first(),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("link", { name: /Open authorization link/i })).toBeVisible({
    timeout: 10_000,
  });
  return popup;
}

test.describe("Plugins auth flow", () => {
  test("Notion connect launcher navigates off about:blank to auth destination", async ({
    page,
    context,
  }) => {
    test.setTimeout(120_000);
    const button = await clickConnectForSearch(page, "notion");
    const popup = await expectPopupReachesAuthDestination(context, page, button);
    await popup.close();
  });

  test("Gmail connect auth initiation reaches provider OAuth", async ({ page, context }) => {
    test.setTimeout(120_000);
    const button = await clickConnectForSearch(page, "gmail");
    const popup = await expectPopupReachesAuthDestination(context, page, button);
    await popup.close();
  });

  test("Google Calendar connect auth initiation reaches provider OAuth", async ({ page, context }) => {
    test.setTimeout(120_000);
    await page.goto("/plugins");
    await expect(page.getByText("Loading plugins…")).toHaveCount(0, { timeout: 120_000 });
    await page.getByPlaceholder("Search plugins…").fill("calendar");
    await expect(page.getByRole("heading", { name: "Results" })).toBeVisible({ timeout: 120_000 });
    const row = page
      .getByRole("article")
      .filter({ hasText: /Google Calendar|Calendar/i })
      .first();
    await expect(row).toBeVisible({ timeout: 120_000 });
    const button = row.locator("button.connection-state");
    const popup = await expectPopupReachesAuthDestination(context, page, button);
    await popup.close();
  });

  test("Slack connect auth initiation reaches provider OAuth", async ({ page, context }) => {
    test.setTimeout(120_000);
    const button = await clickConnectForSearch(page, "slack");
    const popup = await expectPopupReachesAuthDestination(context, page, button);
    await popup.close();
  });

  test("connected GitHub connect API is idempotent", async ({ request }) => {
    const response = await request.post(`${API_BASE}/api/v1/plugins/github/connect`, {
      data: { gateway_provider: "composio" },
    });
    expect(response.ok()).toBeTruthy();
    const body = (await response.json()) as { status: string; auth_url?: string };
    expect(body.status).toBe("connected");
    expect(body.auth_url).toBeUndefined();
  });

  test("installed GitHub appears without starting OAuth", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto("/plugins");
    await expect(page.getByText("Loading plugins…")).toHaveCount(0, { timeout: 120_000 });
    await expect(page.getByRole("button", { name: "View GitHub" })).toBeVisible();
    await expect(page.getByText(/Authorization opened/i)).toHaveCount(0);
  });

  test("popup blocked shows the manual authorization link", async ({ page }) => {
    test.setTimeout(120_000);
    await page.addInitScript(() => {
      Object.defineProperty(window, "open", { value: () => null, configurable: true });
    });
    const button = await clickConnectForSearch(page, "airtable");
    await button.click();
    await expect(page.getByText(/Popup blocked/i)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("link", { name: /Open authorization link/i })).toBeVisible();
  });

  test("server error on connect is visible", async ({ page }) => {
    test.setTimeout(120_000);
    await page.route("**/api/v1/plugins/notion/connect**", (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ error: { message: "composio upstream failed" } }),
        });
      }
      return route.continue();
    });
    const button = await clickConnectForSearch(page, "notion");
    await button.click();
    await expect(page.getByText(/failed|error|upstream/i).first()).toBeVisible({ timeout: 30_000 });
  });
});
