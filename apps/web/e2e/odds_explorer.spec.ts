import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const reportsDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../docs/final/reports");

const goalId = "11111111-1111-4111-8111-111111111111";
const goal = {
  goal_id: goalId,
  title: "Software internship by May",
  goal_type: "deadline_event",
  deadline: "2027-05-31T00:00:00Z",
  forecast_status: "ANCHORED",
  state_dimensions: ["applications"],
  model_requirements: { forecast_spec: { family: "deadline_event_hazard" } },
};
const history = [
  {
    id: "r1",
    probability: 0.22,
    forecast_status: "ANCHORED",
    evidence_watermark: "a",
    model_family: "deadline_event_hazard",
    model_version: "1",
    assumption_hash: "h1",
    simulation_run_id: null,
    source_kind: "published_forecast",
    created_at: "2026-10-01T12:00:00Z",
  },
  {
    id: "r2",
    probability: 0.31,
    forecast_status: "ANCHORED",
    evidence_watermark: "b",
    model_family: "deadline_event_hazard",
    model_version: "1",
    assumption_hash: "h2",
    simulation_run_id: null,
    source_kind: "published_forecast",
    created_at: "2026-10-18T12:00:00Z",
  },
];
const evidence = [
  {
    event_type: "agent_observation",
    domain: "personal_agent",
    metric: "applications",
    numeric_value: 5,
    unit: "count",
    observed_at: "2026-10-10T12:00:00Z",
    source_type: "personal_agent",
    summary: "Applied to five more companies",
    provenance: { observation_kind: "increment", verification_status: "agent_reported" },
  },
];

test("goal detail Odds Explorer scrubs published receipts on desktop and mobile", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok", service: "api", version: "test" } }));
  await page.route(`**/api/v1/goals/${goalId}/evidence`, (route) => route.fulfill({ json: evidence }));
  await page.route(`**/api/v1/what-if/history/${goalId}`, (route) => route.fulfill({ json: history }));
  await page.route(`**/api/v1/goals/${goalId}`, (route) => route.fulfill({ json: goal }));
  await page.route("**/api/v1/goals", (route) => route.fulfill({ json: [goal] }));
  await page.goto(`/goals/${goalId}`);
  await expect(page.getByRole("heading", { name: goal.title })).toBeVisible();
  await expect(page.getByTestId("goal-price")).toContainText("31");
  await expect(page.getByLabel("Chart range")).toBeVisible();
  await page.getByRole("button", { name: "1D" }).click();
  await page.getByRole("button", { name: "ALL" }).click();
  const chart = page.locator(".ws-chart-interaction-layer");
  const box = await chart.boundingBox();
  expect(box).toBeTruthy();
  if (box) {
    await page.mouse.move(box.x + 20, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width - 20, box.y + box.height / 2);
    await page.mouse.up();
  }
  await expect(page.locator(".market-quote")).toContainText("%");
  await page.screenshot({
    path: path.join(reportsDir, `odds-explorer-${testInfo.project.name}.png`),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
