import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const goal = { goal_id: "20000000-0000-0000-0000-000000000001", title: "Read 20 books", goal_type: "continuous_target", deadline: "2026-12-31T23:59:59Z", forecast_status: "ANCHORED", state_dimensions: ["books_read"] };
const avatar = readFileSync("e2e/fixtures/avatar.png");
const axes = ["weekly_applications", "monthly_savings", "weekly_running_km", "reading_minutes"];
const parameterNames = ["Applications / week", "Monthly savings", "Running / week", "Reading time"];
const parameterValues = [12, 900, null, 45];
const parameterUnits = ["applications/week", "CAD/month", "km/week", "minutes/30 days"];
// Captured from the production trait estimator for a seeded owner workspace.
const traitProfile = JSON.parse(readFileSync("e2e/fixtures/profile-traits.json", "utf8")) as unknown;
const traitSources = { cohort: "workspace_seed", authentic_trials: 0, workspace_seed_trials: 106 };

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
  await page.route("**/api/v1/public/profiles/reader", (route) => route.fulfill({ json: {
    creator: { user_id: "10000000-0000-0000-0000-000000000001", handle: "reader", username: "reader", display_name: fields.display_name, bio: fields.bio, has_photo: false },
    follower_count: 0, following_count: 0, following: false, is_self: true, market_count: 0,
    contribution_total: 0, activity: [],
  } }));
  await page.route("**/api/v1/public/profiles/reader/markets*", (route) => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/public/profiles/reader/stars", (route) => route.fulfill({ json: { items: [] } }));
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
      traits: traitProfile, trait_sources: traitSources, selected_parameters: selectedParameters,
      radar: { version: "measured_parameters@2.0.0", as_of: "2026-10-24T00:00:00Z", evidence_count: 3, synthetic: false,
        parameters: selectedParameters.map((id) => {
          const index = axes.indexOf(id);
          const raw = parameterValues[index];
          return { id, name: parameterNames[index], metric: id, unit: parameterUnits[index], window_days: 56,
            aggregation: id === "reading_minutes" ? "sum_increments" : "latest_period",
            normalization: "fixture display scale", raw_value: raw, value: raw == null ? null : raw / 1000,
            observation_count: raw == null ? 0 : 1, source_types: raw == null ? [] : ["manual"],
            evidence_ids: raw == null ? [] : [`fixture-${id}`], status: raw == null ? "insufficient" : "measured" };
        }) },
      available_parameters: axes.map((id, index) => ({ id, name: parameterNames[index], description: `${parameterUnits[index]} · last 56 days`, custom: false })),
    } });
  });
  await page.goto("/profile");
  await expect(page.getByRole("heading", { name: "Reader", exact: true })).toBeVisible();
  await expect(page.getByText("@reader")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add photo" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Behavior profile" })).toBeVisible();
  await expect(page.getByRole("img", { name: /Behavior radar with 6 series/ })).toBeVisible();
  await expect(page.locator(".trait-series")).toHaveCount(6);
  await expect(page.locator(".trait-area-filter")).toHaveCount(0);
  await page.getByRole("button", { name: /Consistency, overall 65%/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".trait-readout-value")).toHaveText("65%");
  await expect(page.getByRole("list", { name: "Series" })).toContainText("Personal33%");
  await page.getByRole("list", { name: "Series" }).getByText("Career").hover();
  await expect(page.locator("[data-testid='trait-series-career']")).toHaveClass(/is-highlighted/);
  await expect(page.getByText(/demo workspace/).first()).toBeVisible();
  await expect(page.getByTestId("parameter-reading_minutes")).toContainText("45 minutes/30 days");
  await expect(page.getByRole("heading", { name: "Activity", exact: true })).toBeVisible();
  await page.screenshot({ path: `test-results/remediation-profile-light-${testInfo.project.name}.png`, fullPage: true });
  await page.evaluate(() => window.localStorage.setItem("pm-theme", "dark"));
  await page.reload();
  await expect(page.locator(".trait-series")).toHaveCount(6);
  await page.locator(".trait-radar").screenshot({ path: `test-results/profile-radar-dark-${testInfo.project.name}.png` });  await page.screenshot({ path: `test-results/remediation-profile-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "Edit parameters" }).click();
  await expect(page.getByRole("dialog", { name: "Edit parameters" })).toBeVisible();
  await page.getByRole("button", { name: "Remove Monthly savings" }).click();
  await page.getByRole("dialog", { name: "Edit parameters" }).getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("list", { name: "Measured activity" })).not.toContainText("Monthly savings");
  await page.reload();
  await expect(page.getByRole("button", { name: "Edit parameters" })).toBeVisible();
  await page.getByRole("button", { name: "Edit parameters" }).click();
  await expect(page.getByRole("button", { name: "Remove Monthly savings" })).toHaveCount(0);
  await page.getByRole("dialog", { name: "Edit parameters" }).getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Edit profile", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Edit profile" })).toBeVisible();
  await page.getByRole("textbox", { name: "Display name" }).fill("Unsaved name");
  await page.getByRole("dialog", { name: "Edit profile" }).getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("heading", { name: "Reader", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit profile", exact: true }).click();
  await page.getByRole("textbox", { name: "Display name" }).fill("Reader Two");
  await page.getByRole("textbox", { name: "Bio" }).fill("Reading and coding.");
  await page.getByRole("dialog", { name: "Edit profile" }).getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: "Reader Two" })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Reading and coding.")).toBeVisible();
  await page.getByRole("button", { name: "Edit profile", exact: true }).click();
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
  await page.getByRole("button", { name: "Edit profile", exact: true }).click();
  await page.getByRole("button", { name: "Remove photo" }).click();
  await expect(page.getByLabel("Initials avatar")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
