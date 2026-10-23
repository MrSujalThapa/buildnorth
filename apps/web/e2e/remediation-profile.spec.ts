import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const goal = { goal_id: "20000000-0000-0000-0000-000000000001", title: "Read 20 books", goal_type: "continuous_target", deadline: "2026-12-31T23:59:59Z", forecast_status: "ANCHORED", state_dimensions: ["books_read"] };
const avatar = readFileSync("e2e/fixtures/avatar.png");
const traitIds = ["follow_through", "consistency", "momentum", "recovery"];
const traitNames = ["Follow-through", "Consistency", "Momentum", "Recovery"];
const traits = traitIds.map((id, index) => ({
  id, name: traitNames[index], description: `${traitNames[index]} across planned actions.`,
  measurement: "Based on observed commitments.", evidence: ["manual"], custom: false,
  forecast_use: index === 0 ? "execution_probability" : "exploratory",
  value: index === 3 ? null : [0.7, 0.42, 0.61][index],
  interval: index === 3 ? null : [0.3, 0.8], n_eff: 6, observations: index === 3 ? 0 : 6,
  confidence: index === 3 ? "insufficient" : "moderate", previous_value: null,
  sources: ["manual"], window_days: 28,
}));
const availableParameters = traits.map(({ id, name, description, measurement, evidence, custom, forecast_use }) =>
  ({ id, name, description, measurement, evidence, custom, forecast_use }));
const traitProfile = {
  estimator_version: "behavior_traits@1.0.0", as_of: "2026-10-23T00:00:00Z", traits,
  series: [{ id: "overall", label: "Overall", values: Object.fromEntries(traits.map((item) => [item.id, item.value])) }],
  trial_count: 18, evidence_count: 18,
};

test("profile photo, radar, and parameter editing work at desktop and mobile widths", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let selectedParameters = traitIds;
  let savedParameters: { parameter_ids: string[]; custom_parameters: { name: string; description: string }[] } | null = null;
  let uploadedPhoto: Buffer | null = null;
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok" } }));
  await page.route("**/api/v1/profile/photo", async (route) => {
    const method = route.request().method();
    if (method === "PUT") {
      uploadedPhoto = route.request().postDataBuffer() ?? avatar;
      return route.fulfill({ json: { status: "saved" } });
    }
    if (method === "DELETE") {
      uploadedPhoto = null;
      return route.fulfill({ json: { status: "removed" } });
    }
    return uploadedPhoto
      ? route.fulfill({ status: 200, contentType: "image/png", body: avatar })
      : route.fulfill({ status: 404, body: "" });
  });
  await page.route("**/api/v1/goals", (route) => route.fulfill({ json: [goal] }));
  await page.route("**/api/v1/profile", async (route) => {
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON() as { parameter_ids?: string[]; custom_parameters?: { name: string; description: string }[] };
      if (body.parameter_ids) {
        selectedParameters = body.parameter_ids;
        savedParameters = { parameter_ids: body.parameter_ids, custom_parameters: body.custom_parameters ?? [] };
      }
    }
    return route.fulfill({ json: {
      account: { user_id: "10000000-0000-0000-0000-000000000001", email: "reader@example.com", profile: { display_name: "Reader", username: "reader", bio: "", avatar_value: null, dimensions: [] } },
      goal_count: 1, collection_count: 0, privacy: "private",
      traits: traitProfile, selected_parameters: selectedParameters, available_parameters: availableParameters,
    } });
  });
  await page.goto("/profile");
  await expect(page.getByRole("heading", { name: "Reader", exact: true })).toBeVisible();
  await expect(page.getByText("@reader")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add photo" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Follow-through, 70%" })).toBeVisible();
  await expect(page.getByText("Recovery, not enough evidence")).toHaveCount(0);
  await page.getByRole("button", { name: "Consistency, 42%" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Consistency", { exact: true }).last()).toBeVisible();
  await page.screenshot({ path: `test-results/remediation-profile-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "Edit parameters" }).click();
  await page.getByRole("dialog", { name: "Edit parameters" }).getByLabel("Custom parameter").fill("Sleep regularity");
  await page.getByRole("dialog", { name: "Edit parameters" }).getByLabel("What it measures").fill("Nights in bed near target");
  await page.getByRole("button", { name: "Add custom parameter" }).click();
  await page.getByRole("dialog", { name: "Edit parameters" }).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => savedParameters?.custom_parameters).toEqual([{ name: "Sleep regularity", description: "Nights in bed near target" }]);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Edit profile" })).toBeVisible();
  await page.locator("#profile-photo-input").setInputFiles({
    name: "avatar.png", mimeType: "image/png",
    buffer: avatar,
  });
  await expect(page.getByLabel("Profile photo preview").locator("img")).toBeVisible();
  await page.getByRole("slider", { name: "Horizontal position" }).fill("20");
  await expect(page.getByLabel("Profile photo preview").locator("img")).toHaveCSS("object-position", "20% 50%");
  const uploaded = page.waitForResponse((response) => response.url().includes("/api/v1/profile/photo") && response.request().method() === "PUT");
  await page.getByRole("dialog", { name: "Edit profile" }).getByRole("button", { name: "Save" }).click();
  await uploaded;
  await expect(page.getByLabel("Profile photo").locator("img")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Profile photo").locator("img")).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Remove photo" }).click();
  await expect(page.getByLabel("Initials avatar")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
