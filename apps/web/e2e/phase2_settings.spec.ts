import { expect, test } from "@playwright/test";

test("manage provider credentials and explicit billing without exposing saved keys", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  const settings = {
    preference: { mode: "hosted" as "hosted" | "byok", provider: "openai" as "openai" | "anthropic", model: null as string | null },
    credentials: [] as { provider: string; status: string; masked_suffix: string; version: string; validated_at: string }[],
    models: [
      { provider: "openai", model: "gpt-5.4-mini", structured: true, tools: true, display_name: "GPT-5.4 mini" },
      { provider: "anthropic", model: "claude-sonnet-5-5", structured: true, tools: true, display_name: "Claude Sonnet 5.5" },
    ],
    discovered_models: {} as Record<string, { provider: string; model: string; structured: boolean; tools: boolean }[]>,
    recommended_model: "gpt-5.4-mini",
    hosted_provider: "spur",
    hosted_configured: true,
    hosted_model: "spur-glm-5-3",
    byok_usage: { calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0 },
  };
  const calls: string[] = [];
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok", service: "api", version: "test" } }));
  await page.route("**/api/v1/mcp/**", (route) => {
    const url = route.request().url();
    if (url.includes("/connections")) return route.fulfill({ json: [] });
    return route.fulfill({ json: { enabled: true, resource: "http://127.0.0.1:8030/mcp" } });
  });
  await page.route("**/api/v1/settings/inference**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    calls.push(`${req.method()} ${url.pathname}`);
    if (url.pathname.endsWith("/validate")) return route.fulfill({ json: settings.credentials[0] });
    if (url.pathname.includes("/credentials/")) {
      if (req.method() === "DELETE") {
        settings.credentials = [];
        return route.fulfill({ status: 204, body: "" });
      }
      const provider = url.pathname.split("/").at(-1)! as "openai" | "anthropic";
      const key = (req.postDataJSON() as { api_key: string }).api_key;
      const metadata = {
        provider,
        status: "validated",
        masked_suffix: `••••${key.slice(-4)}`,
        version: "opaque-version",
        validated_at: "2026-10-17T12:00:00Z",
      };
      settings.credentials = [metadata];
      settings.preference = { mode: "byok", provider, model: settings.preference.model };
      settings.discovered_models[provider] = settings.models.filter((item) => item.provider === provider);
      return route.fulfill({ json: metadata });
    }
    if (req.method() === "PUT") settings.preference = req.postDataJSON();
    return route.fulfill({ json: settings });
  });
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "PlayItOut credits" })).toBeVisible();
  const submitColors = await page.getByRole("button", { name: "Connect and use my key" }).evaluate((button) => {
    const style = getComputedStyle(button);
    return { color: style.color, background: style.backgroundColor };
  });
  expect(submitColors.background).not.toBe("rgba(0, 0, 0, 0)");
  expect(submitColors.background).not.toBe(submitColors.color);
  await page.getByLabel("API key", { exact: true }).fill("sk-test-openai-private-1234");
  await page.getByRole("button", { name: "Connect and use my key" }).click();
  await expect(page.getByText(/Validated connection · ••••1234/)).toBeVisible();
  await expect(page.getByLabel("Replacement API key")).toBeEmpty();
  await expect(page.getByText("Current mode: BYOK")).toBeVisible();
  await page.getByLabel("Compatible model").selectOption("gpt-5.4-mini");
  await page.getByRole("button", { name: "Save BYOK preference" }).click();
  await expect(page.getByText("BYOK preference saved.")).toBeVisible();
  await expect(page.getByText(/Your OpenAI or Anthropic account pays/)).toBeVisible();
  await page.getByRole("button", { name: "Validate key" }).click();
  await expect(page.getByText("connection validated", { exact: false })).toBeVisible();
  await page.getByLabel("Replacement API key").fill("sk-test-openai-replacement-5678");
  await page.getByRole("button", { name: "Replace key" }).click();
  await expect(page.getByText(/Validated connection · ••••5678/)).toBeVisible();
  await page.getByRole("button", { name: "Delete key" }).click();
  await expect(page.getByText("No key saved for this provider.")).toBeVisible();
  await expect(page.getByText("Current mode: BYOK")).toBeVisible();
  await page.getByLabel("Provider").selectOption("anthropic");
  await page.getByLabel("API key", { exact: true }).fill("sk-ant-test-private-9012");
  await page.getByRole("button", { name: "Connect and use my key" }).click();
  await expect(page.getByText(/Validated connection · ••••9012/)).toBeVisible();
  await page.getByLabel("Compatible model").selectOption("claude-sonnet-5-5");
  await page.getByRole("button", { name: "Save BYOK preference" }).click();
  await expect(page.getByText("BYOK preference saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Provider")).toHaveValue("anthropic");
  await expect(page.getByLabel("Compatible model")).toHaveValue("claude-sonnet-5-5");
  await expect(page.locator("body")).not.toContainText("sk-ant-test-private");
  const saved = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(saved).not.toContain("sk-ant-test-private");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath("settings-byok.png"), fullPage: true });
  await page.getByRole("button", { name: "Use PlayItOut credits" }).click();
  await expect(page.getByText(/Hosted Spur credits are now active/)).toBeVisible();
  await page.getByRole("button", { name: "Dark Near-black interface", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("settings-dark.png"), fullPage: true });
  await page.getByRole("button", { name: "Light Warm white interface", exact: true }).click();
  expect(calls.some((call) => call.includes("DELETE"))).toBeTruthy();
  expect(errors).toEqual([]);
});

test("provider failures give an actionable error and never change billing mode", async ({ page }) => {
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok", service: "api", version: "test" } }));
  await page.route("**/api/v1/mcp/**", (route) => {
    const url = route.request().url();
    if (url.includes("/connections")) return route.fulfill({ json: [] });
    return route.fulfill({ json: { enabled: true, resource: "http://127.0.0.1:8030/mcp" } });
  });
  await page.route("**/api/v1/settings/inference", (route) => route.fulfill({ json: {
    preference: { mode: "byok", provider: "anthropic", model: "claude-sonnet-5-5" },
    credentials: [], models: [{ provider: "anthropic", model: "claude-sonnet-5-5", structured: true, tools: true }],
    hosted_provider: "spur", hosted_configured: true, hosted_model: "spur-glm-5-3",
    byok_usage: { calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0 },
  } }));
  await page.route("**/api/v1/settings/inference/credentials/anthropic", (route) => route.fulfill({
    status: 502, json: { error: { message: "anthropic authentication failed. Replace or validate your key." } },
  }));
  await page.goto("/settings");
  await page.getByLabel("API key", { exact: true }).fill("sk-ant-test-revoked-key");
  await page.getByRole("button", { name: "Connect and use my key" }).click();
  await expect(page.getByText("Replace or validate your key")).toBeVisible();
  await expect(page.getByText("Current mode: BYOK")).toBeVisible();
  await expect(page.getByLabel("API key", { exact: true })).toBeEmpty();
});
