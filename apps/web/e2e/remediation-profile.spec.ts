import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const goal = { goal_id: "20000000-0000-0000-0000-000000000001", title: "Read 20 books", goal_type: "continuous_target", deadline: "2026-12-31T23:59:59Z", forecast_status: "ANCHORED", state_dimensions: ["books_read"] };
const avatar = readFileSync("e2e/fixtures/avatar.png");
const traitKeys = ["Follow-through", "Consistency", "Commitment realism", "Momentum", "Reliability", "Recovery"];
const emptyTraits = traitKeys.map((label, index) => ({
  key: `trait-${index}`, label, value: null, display_percent: null, limited_evidence: true,
  confidence: "insufficient", provenance: { comparable_commitments: 0, completed: 0, sources: [], n_eff: 0, formula: "", details: [] },
}));

test("profile editing and custom dimensions work at desktop and mobile widths", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let dimensions: { label: string; goal_ids: string[] }[] = [];
  let uploadedPhoto: Buffer | null = null;
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok" } }));
  await page.route("**/api/v1/profile/photo", async (route) => {
    const method = route.request().method();
    if (method === "PUT") {
      uploadedPhoto = route.request().postDataBuffer();
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
      const body = route.request().postDataJSON() as { dimensions?: typeof dimensions };
      if (body.dimensions) dimensions = body.dimensions;
    }
    return route.fulfill({ json: {
      account: { user_id: "10000000-0000-0000-0000-000000000001", email: "reader@example.com", profile: { display_name: "Reader", username: "reader", bio: "", avatar_value: null, dimensions } },
      goal_count: 1, collection_count: 0, privacy: "private",
      radar: { estimator_version: "behavior_hierarchical_beta_v1", execution: { probability: 0.5, n_eff: 0, confidence: "insufficient", source: "PRIOR", usable: false, notes: [] }, dimensions: emptyTraits, disclaimer: "", evidence_sufficiency: "insufficient", n_raw: 0, n_eff: 0 },
    } });
  });
  await page.goto("/profile");
  await expect(page.getByRole("heading", { name: "Profile", exact: true })).toBeVisible();
  await expect(page.getByText("@reader")).toBeVisible();
  await expect(page.getByText("Your execution profile appears as planned actions are verified.")).toBeVisible();
  await page.screenshot({ path: `test-results/remediation-profile-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "Edit areas" }).click();
  await page.getByRole("button", { name: "Add area" }).click();
  await page.getByRole("textbox", { name: "Area 1 name" }).fill("Reading");
  await page.getByRole("checkbox", { name: "Read 20 books" }).check();
  await page.getByRole("dialog", { name: "Your areas" }).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => dimensions).toEqual([{ label: "Reading", goal_ids: [goal.goal_id] }]);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Edit profile" })).toBeVisible();
  await page.getByRole("dialog", { name: "Edit profile" }).getByRole("button", { name: "Cancel" }).click();
  await page.locator("#profile-photo-input").setInputFiles({
    name: "avatar.png", mimeType: "image/png",
    buffer: avatar,
  });
  await expect(page.getByLabel("Profile photo preview").locator("img")).toBeVisible();
  await page.getByRole("slider", { name: "Horizontal position" }).fill("20");
  await expect(page.getByLabel("Profile photo preview").locator("img")).toHaveCSS("object-position", "20% 50%");
  await page.getByRole("button", { name: "Save photo" }).click();
  await expect(page.getByText("Replace photo")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Profile photo preview").locator("img")).toBeVisible();
  await page.getByRole("button", { name: "Remove photo" }).click();
  await expect(page.getByLabel("Initials avatar")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
