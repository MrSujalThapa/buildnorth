import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const goal = { goal_id: "20000000-0000-0000-0000-000000000001", title: "Read 20 books", goal_type: "continuous_target", deadline: "2026-12-31T23:59:59Z", forecast_status: "ANCHORED", state_dimensions: ["books_read"] };
const avatar = readFileSync("e2e/fixtures/avatar.png");
const parameterKeys = ["Weekly applications", "Focused hours", "Monthly savings", "Weekly running"];
const parameterValues = [0.7, 0.42, 0.28, 0.61];
const parameterRadar = {
  estimator_version: "parameter_profile@1.0.0",
  execution: { probability: 0, n_eff: 12, confidence: "medium", source: "FITTED", usable: true, notes: [] },
  dimensions: parameterKeys.map((label, index) => ({
    key: ["weekly_applications", "weekly_focus_hours", "monthly_savings", "weekly_running_km"][index],
    label,
    value: parameterValues[index],
    display_percent: Math.round((parameterValues[index] ?? 0) * 100),
    limited_evidence: false,
    confidence: "medium",
    provenance: {
      comparable_commitments: 6,
      completed: 6,
      sources: ["manual"],
      n_eff: 6,
      formula: "Average over the selected window",
      details: [`Current average ${parameterValues[index]} in range`],
    },
  })),
  disclaimer: "Axes are measurable parameters you selected, not personality traits or goal names.",
  evidence_sufficiency: "medium",
  n_raw: 24,
  n_eff: 24,
};

test("profile editing and custom dimensions work at desktop and mobile widths", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let dimensions: { label: string; goal_ids: string[] }[] = [];
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
      const body = route.request().postDataJSON() as { dimensions?: typeof dimensions };
      if (body.dimensions) dimensions = body.dimensions;
    }
    return route.fulfill({ json: {
      account: { user_id: "10000000-0000-0000-0000-000000000001", email: "reader@example.com", profile: { display_name: "Reader", username: "reader", bio: "", avatar_value: null, dimensions } },
      goal_count: 1, collection_count: 0, privacy: "private",
      radar: parameterRadar, radar_kind: "parameters",
    } });
  });
  await page.goto("/profile");
  await expect(page.getByRole("heading", { name: "Reader", exact: true })).toBeVisible();
  await expect(page.getByText("@reader")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add photo" })).toHaveCount(0);
  await expect(page.getByText("Weekly applications")).toBeVisible();
  await expect(page.getByText("Current average 0.7 in range")).toBeVisible();
  await expect(page.getByText("hierarchical shrinkage")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "View demonstration" })).toBeVisible();
  await page.screenshot({ path: `test-results/remediation-profile-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "Edit areas" }).click();
  await page.getByRole("button", { name: "Add Reading" }).click();
  await page.getByRole("dialog", { name: "Your areas" }).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => dimensions).toEqual([{ label: "Reading", goal_ids: [goal.goal_id] }]);
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
