import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const goal = { goal_id: "20000000-0000-0000-0000-000000000001", title: "Read 20 books", goal_type: "continuous_target", deadline: "2026-12-31T23:59:59Z", forecast_status: "ANCHORED", state_dimensions: ["books_read"] };
const avatar = readFileSync("e2e/fixtures/avatar.png");
const axes = ["discipline", "realism", "focus", "consistency"];
const traits = axes.map((id, index) => ({
  id, name: ["Discipline", "Goal realism", "Focus", "Consistency"][index],
  description: "Observed behavior.", measurement: "Based on recorded commitments.",
  evidence: ["manual"], custom: false, forecast_use: id === "discipline" ? "execution_probability" : "exploratory",
  value: [0.81, 0.7, null, 0.62][index], interval: index === 2 ? null : [0.5, 0.9],
  n_eff: 12, observations: 16, confidence: "moderate", previous_value: null, sources: ["manual"], window_days: 28,
}));
const traitProfile = {
  estimator_version: "behavior_traits_v1", as_of: "2026-10-24T00:00:00Z", traits,
  series: [
    { id: "overall", label: "Overall", values: { discipline: 0.81, realism: 0.7, focus: null, consistency: 0.62 } },
    { id: "coding", label: "Coding", values: { discipline: 0.61, realism: 0.65, focus: null, consistency: 0.5 } },
  ],
  trial_count: 16, evidence_count: 0,
};

test("profile editing, photo, and execution areas work at desktop and mobile widths", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let fields = { display_name: "Reader", username: "reader", bio: "" };
  let selectedParameters = axes;
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
      const body = route.request().postDataJSON() as Partial<typeof fields> & { parameter_ids?: string[] };
      fields = { ...fields, ...Object.fromEntries(Object.entries(body).filter(([key]) => key in fields)) } as typeof fields;
      if (body.parameter_ids) selectedParameters = body.parameter_ids;
    }
    return route.fulfill({ json: {
      account: { user_id: "10000000-0000-0000-0000-000000000001", email: "reader@example.com", profile: { ...fields, avatar_value: null, dimensions: [] } },
      goal_count: 1, collection_count: 0, privacy: "private",
      traits: traitProfile, selected_parameters: selectedParameters,
      available_parameters: traits.map((item) => ({ id: item.id, name: item.name, description: item.description, custom: false })),
    } });
  });
  await page.goto("/profile");
  await expect(page.getByRole("heading", { name: "Reader", exact: true })).toBeVisible();
  await expect(page.getByText("@reader")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add photo" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Execution profile" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Overall" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("img", { name: /Overall execution radar/ })).toBeVisible();
  await page.getByRole("button", { name: "Coding" }).click();
  await expect(page.getByRole("img", { name: /Coding execution radar/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Coding" })).toHaveAttribute("aria-pressed", "true");
  await page.screenshot({ path: `test-results/remediation-profile-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "Edit parameters" }).click();
  await expect(page.getByRole("dialog", { name: "Edit parameters" })).toBeVisible();
  await page.getByRole("dialog", { name: "Edit parameters" }).getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Edit profile" })).toBeVisible();
  await page.getByRole("textbox", { name: "Display name" }).fill("Unsaved name");
  await page.getByRole("dialog", { name: "Edit profile" }).getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("heading", { name: "Reader", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("textbox", { name: "Display name" }).fill("Reader Two");
  await page.getByRole("textbox", { name: "Bio" }).fill("Reading and coding.");
  await page.getByRole("dialog", { name: "Edit profile" }).getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: "Reader Two" })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Reading and coding.")).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
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
