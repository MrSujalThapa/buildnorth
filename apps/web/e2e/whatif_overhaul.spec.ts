import { expect, test } from "@playwright/test";

const GOAL = "20000000-0000-0000-0000-000000000002";

test.beforeEach(async ({ page }) => {
  await page.route(`**/api/v1/goals/${GOAL}`, (route) => route.fulfill({ json: {
    goal_id: GOAL, title: "Land a forward-deployed engineer offer",
    goal_type: "deadline_event", deadline: "2027-08-31T00:00:00Z",
    forecast_status: "published", state_dimensions: ["applications_submitted"],
    success_definition: { metric: "offer_received" },
  } }));
  await page.route(`**/api/v1/goals/${GOAL}/evidence`, (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/v1/what-if/history/${GOAL}`, (route) => route.fulfill({ json: [
    { id: "earlier", probability: 0.6, forecast_status: "published", source_kind: "published_forecast", created_at: "2026-10-01T00:00:00Z" },
    { id: "latest", probability: 0.7646, forecast_status: "published", source_kind: "published_forecast", created_at: "2026-10-24T00:00:00Z" },
  ] }));
  await page.route(`**/api/v1/what-if/baseline-state/${GOAL}`, (route) => route.fulfill({ json: {
    goal_id: GOAL, priced: true, status: "published", current_probability: 0.719,
    published_probability: 0.7646, current_value: 0, target_value: 1, target_unit: "event",
    periods: 44, direction: "at_least", model_family: "deadline_event_hazard",
    model_version: "1.0.0", assumptions: [], config: { seed: 1 },
    compare_candidates: [], resource_constraints: { hours_per_week: 12, money: 0, energy: 1 },
    resource_budget: { hours_per_week: 12, money_per_month: 0 },
  } }));
  await page.route("**/api/v1/what-if/explorations/**", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/what-if/fast-reprice", (route) => route.fulfill({ json: {
    priced: true, status: "EXPLORATORY", baseline_probability: 0.719,
    scenario_probability: 0.719, expected_uplift_pp: 0, assumptions: [],
    outcome_quantiles: {}, distribution_bins: [], fan: [], receipt: {},
  } }));
  await page.route("**/api/v1/what-if/parse-intervention", (route) => {
    const text = (route.request().postDataJSON() as { text: string }).text;
    return route.fulfill({ json: /study|cold email|gym/i.test(text)
      ? { raw_text: text, changes: [], unsupported: ["No measured conversion from this activity to offer odds."], pricing_status: "NOT_PRICED" }
      : { raw_text: text, changes: [{ metric: "applications_per_week", operation: "set", value: 10, unit: "count/week", provenance: "USER_ASSUMPTION" }], unsupported: [], pricing_status: "PRICED" },
    });
  });
  await page.route("**/api/v1/what-if/simulate", (route) => route.fulfill({ json: {
    priced: true, status: "EXPLORATORY", baseline_probability: 0.719,
    scenario_probability: 0.78, expected_uplift_pp: 6.1,
    conditional_on_execution_probability: 0.81, execution_probability: 0.72,
    assumptions: [], outcome_quantiles: {}, distribution_bins: [], fan: [], receipt: {},
  } }));
  await page.route("**/api/v1/what-if/target-search", (route) => {
    const target = (route.request().postDataJSON() as { target_probability: number }).target_probability;
    return route.fulfill({ json: { target_probability: target, current_probability: 0.719,
      gap_pp: (target - 0.719) * 100, feasible: false,
      message: "No measured action reaches this target yet.", paths: [], search_method: "no_supported_levers" } });
  });
  await page.route("**/api/v1/what-if/parse-decision", (route) => route.fulfill({ json: {
    scenario_labels: ["Offer", "No offer"], unsupported: [],
  } }));
  await page.route("**/api/v1/what-if/possible-futures", (route) => route.fulfill({ json: {
    priced: true, outcomes: [
      { label: "Offer", probability: 0.76, median: 0.76, p10: 0.5, p90: 0.9, downside: false },
      { label: "No offer", probability: 0.24, median: 0.24, p10: 0.1, p90: 0.5, downside: true },
    ], other_probability: 0, evidence_basis: [], model_version: "test", seed: 1,
  } }));
});

test("Change reconciles published odds with a priced hypothetical", async ({ page }) => {
  await page.goto(`/goals/${GOAL}/what-if`);
  await expect(page.getByText(/Published forecast history: 76.46%/)).toBeVisible();
  await page.getByPlaceholder(/What if/i).fill("What if I apply to 10 jobs each week?");
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.getByText("hypothetical change", { exact: true })).toBeVisible();
  await expect(page.getByText(/comparison recalculates a 71.9% baseline/i)).toBeVisible();
  await expect(page.getByText(/Hypothetical scenario: 78%/)).toBeVisible();
  await expect(page.locator(".what-if-market-chart .recharts-line")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
});

test("unsupported study input stays unpriced and Reverse target is editable", async ({ page }) => {
  await page.goto(`/goals/${GOAL}/what-if`);
  await page.getByPlaceholder(/What if/i).fill("What if I study 10 hours tomorrow?");
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.getByRole("alert")).toContainText("No measured conversion");
  await expect(page.getByText(/Hypothetical scenario: —/)).toBeVisible();
  await page.getByRole("tab", { name: "Reverse" }).click();
  await expect(page.getByLabel("Exact target odds")).toHaveValue("85");
  await page.getByLabel("Exact target odds").fill("90");
  await expect(page.getByRole("slider", { name: "Target odds" })).toHaveValue("90");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
});

test("Futures does not show fractional event counts", async ({ page }) => {
  await page.goto(`/goals/${GOAL}/what-if`);
  await page.getByRole("tab", { name: "Futures" }).click();
  await page.getByRole("button", { name: "Map futures" }).click();
  await expect(page.getByLabel("Possible future scenarios")).toContainText("76%");
  await expect(page.locator("body")).not.toContainText("0.76 event");
});
