import { expect, test } from "@playwright/test";

const plugins = ["googledrive", "slack"].map((id) => ({
  definition: {
    id, name: id === "googledrive" ? "Google Drive" : "Slack", description: id,
    category: "integration", provider_type: "composio", capabilities: [], used_for: [],
  },
  connection: {
    plugin_id: id, status: "not_connected", connected_at: null, last_sync_at: null,
    permissions: [], account_metadata: {}, error: null,
  },
}));

test("overlapping plugin clicks keep their authorization tabs separate (mocked API)", async ({ page, context }, testInfo) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/me") return route.fulfill({ json: {
      user_id: "test-user", clerk_user_id: "test-clerk", email: "test@example.test",
      invited: true, role: "user",
    } });
    if (url.pathname === "/api/v1/plugins") return route.fulfill({ json: {
      items: plugins, next_cursor: null, total_items: 2,
    } });
    if (url.pathname.endsWith("/connect") && route.request().method() === "POST") {
      const id = url.pathname.split("/").at(-2)!;
      if (id === "googledrive") await new Promise((resolve) => setTimeout(resolve, 400));
      return route.fulfill({ json: {
        plugin_id: id, connection_id: `connection-${id}`, status: "pending_auth",
        auth_url: `http://127.0.0.1:5174/auth-test/${id}`,
      } });
    }
    if (url.pathname.endsWith("/refresh")) return route.fulfill({ json: {
      plugin_id: url.pathname.split("/").at(-3), status: "pending_auth",
    } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/plugins");
  await expect(page.getByRole("heading", { name: "Plugins" })).toBeVisible();
  const drive = page.getByRole("article").filter({ hasText: "Google Drive" }).locator("button.connection-state");
  const slack = page.getByRole("article").filter({ hasText: "Slack" }).locator("button.connection-state");
  const firstPopup = context.waitForEvent("page");
  await drive.click();
  const driveTab = await firstPopup;
  const secondPopup = context.waitForEvent("page");
  await slack.click();
  const slackTab = await secondPopup;
  await expect.poll(() => slackTab.url()).toContain("/auth-test/slack");
  await expect.poll(() => driveTab.url()).toContain("/auth-test/googledrive");
  expect(slackTab.isClosed()).toBe(false);
  expect(driveTab.isClosed()).toBe(false);
  await page.screenshot({ path: testInfo.outputPath("plugins-oauth-routing.png"), fullPage: true });
  expect(pageErrors).toEqual([]);
});
