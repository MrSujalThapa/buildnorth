import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const GOAL = "20000000-0000-0000-0000-000000000002";
const screenshotDir = "test-results/whatif-quality";

async function capture(page: import("@playwright/test").Page, label: string) {
  await mkdir(screenshotDir, { recursive: true });
  await page.screenshot({ path: `${screenshotDir}/${test.info().project.name}-${label}.png`, fullPage: true });
}

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
    const applicationCount = /2 applications/i.test(text) ? 2 : 10;
    return route.fulfill({ json: /study|cold email|gym/i.test(text)
      ? { raw_text: text, changes: [], unsupported: ["No measured conversion from this activity to offer odds."], pricing_status: "NOT_PRICED" }
      : { raw_text: text, changes: [{ metric: "applications_per_week", operation: "set", value: applicationCount, unit: "count/week", provenance: "USER_ASSUMPTION" }], unsupported: [], pricing_status: "PRICED" },
    });
  });
  await page.route("**/api/v1/what-if/simulate", (route) => {
    const body = route.request().postDataJSON() as { parsed_changes?: { value: number }[] };
    const lower = body.parsed_changes?.[0]?.value === 2;
    return route.fulfill({ json: {
    priced: true, status: "EXPLORATORY", baseline_probability: 0.719,
    scenario_probability: lower ? 0.65 : 0.78, expected_uplift_pp: lower ? -6.9 : 6.1,
    conditional_on_execution_probability: 0.81, execution_probability: 0.72,
    assumptions: [], outcome_quantiles: {}, distribution_bins: [], fan: [], receipt: {},
  } });
  });
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
  await page.route("**/api/v1/what-if/compare-paths", (route) => route.fulfill({ json: {
    paths: [
      { id: "path-a", label: "Apply to 10 jobs a week", primary_goal_probability: 0.79,
        resource_cost: { hours_per_week: 5, money_per_month: 0, energy: 0 },
        assumptions: [], model_status: "EXPLORATORY", secondary_outcomes: {} },
      { id: "path-b", label: "Cold email founders", primary_goal_probability: null,
        resource_cost: { hours_per_week: 2, money_per_month: 0, energy: 0 },
        assumptions: [], model_status: "NOT_MODELED", secondary_outcomes: {} },
    ], model_family: "deadline_event_hazard", model_version: "test", seed: 1,
  } }));
});

test("Change reconciles published odds with a priced hypothetical", async ({ page }) => {
  await page.goto(`/goals/${GOAL}/what-if`);
  await expect(page.getByText(/Published forecast: 76.46%/)).toBeVisible();
  await page.getByRole("button", { name: "Details" }).first().click();
  await expect(page.getByRole("dialog", { name: "Scenario details" })).toBeVisible();
  await expect(page.getByText(/No measured parameters yet|Parameter profile radar/)).toBeVisible();
  await page.getByRole("button", { name: "Close details" }).click();
  const skip = page.getByRole("link", { name: "Skip to main content" });
  await expect(skip).toHaveCSS("clip", /rect\(0(px)?, 0(px)?, 0(px)?, 0(px)?\)/);
  await page.getByPlaceholder(/What if/i).fill("What if I apply to 10 jobs each week?");
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.getByText("hypothetical change", { exact: true })).toBeVisible();
  await expect(page.getByText(/changes the comparison from 71.9% to 78%/i)).toBeVisible();
  await expect(page.getByText(/This is a modeled scenario, not a new published forecast/i)).toBeVisible();
  await expect(page.getByText(/Hypothetical scenario: 78%/)).toBeVisible();
  await expect(page.getByText("Outcome range unavailable")).toHaveCount(0);
  await expect(page.locator(".what-if-market-chart .recharts-line")).toBeVisible();
  await expect(page.locator(".what-if-market-chart .recharts-area-curve")).toBeVisible();
  expect(await page.locator(".what-if-market-chart .recharts-area-curve").getAttribute("d"))
    .toMatch(/^M\d/);
  const linePath = await page.locator(".what-if-market-chart .recharts-line-curve").getAttribute("d");
  const areaPath = await page.locator(".what-if-market-chart .recharts-area-curve").getAttribute("d");
  expect((linePath ?? "").length).toBeLessThan((areaPath ?? "").length);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await capture(page, "change-light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.theme)).toBe("dark");
  await capture(page, "change-dark");
});

test("unsupported study input stays unpriced and Reverse target is editable", async ({ page }) => {
  await page.goto(`/goals/${GOAL}/what-if`);
  await page.getByPlaceholder(/What if/i).fill("What if I study 10 hours tomorrow?");
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.getByRole("alert")).toContainText("No measured conversion");
  await expect(page.locator(".what-if-chart-legend .hypothetical-positive, .what-if-chart-legend .hypothetical-negative")).toHaveCount(0);
  await page.getByRole("tab", { name: "Reverse" }).click();
  await expect(page.getByLabel("Exact target odds")).toHaveValue("85");
  await page.getByLabel("Exact target odds").fill("90");
  await expect(page.getByRole("slider", { name: "Target odds" })).toHaveValue("90");
  await capture(page, "reverse");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
});

test("a lower modeled application rate makes a red negative scenario", async ({ page }) => {
  await page.goto(`/goals/${GOAL}/what-if`);
  await page.getByPlaceholder(/What if/i).fill("What if I submit 2 applications a week?");
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.getByText("65%", { exact: true })).toBeVisible();
  await expect(page.getByText("-6.9 pts")).toBeVisible();
  await expect(page.locator(".what-if-market-chart .hypothetical-negative")).toContainText("65%");
  await expect(page.locator(".what-if-market-chart .recharts-line-curve"))
    .toHaveAttribute("stroke", "#c44745");
  await capture(page, "change-negative");
});

test("Futures does not show fractional event counts", async ({ page }) => {
  await page.goto(`/goals/${GOAL}/what-if`);
  await page.getByRole("tab", { name: "Futures" }).click();
  await page.getByRole("button", { name: "Map futures" }).click();
  await expect(page.getByLabel("Possible future scenarios")).toContainText("76%");
  await expect(page.locator("body")).not.toContainText("0.76 event");
  await capture(page, "futures");
});

test("Compare ranks only modeled options and Deeper analysis remains navigable", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`/goals/${GOAL}/what-if`);
  await page.getByRole("tab", { name: "Compare" }).click();
  await page.locator('textarea[name="compare-path-a"]').fill("Apply to 10 jobs a week");
  await page.locator('textarea[name="compare-path-b"]').fill("Cold email founders");
  await page.getByRole("button", { name: "Compare these paths" }).click();
  await expect(page.getByText("Highest modeled goal odds")).toBeVisible();
  await expect(page.getByText("Apply to 10 jobs a week").first()).toBeVisible();
  await expect(page.getByText("No modeled effect or ranking is available for this option.")).toBeVisible();
  await capture(page, "compare");
  await page.getByRole("tab", { name: "Deeper analysis" }).click();
  await expect(page.getByLabel("Option visibility")).toBeVisible();
  expect(errors).toEqual([]);
});

test("strategic questions stay unpriced and still show useful ideas", async ({ page }) => {
  await page.unroute("**/api/v1/what-if/parse-intervention");
  await page.route("**/api/v1/what-if/parse-intervention", (route) => {
    const text = (route.request().postDataJSON() as { text: string }).text;
    return route.fulfill({
      json: {
        raw_text: text,
        changes: [],
        unsupported: [],
        pricing_status: "NOT_PRICED",
        request_kind: "opportunity_discovery",
        insights: [{
          title: "Ask that investor for a few targeted introductions",
          description: "Use the existing VC relationship.",
          why_it_might_help: "Warm paths reach founders without a calibrated coefficient.",
          why_this_fits: "Authorized context mentions a VC.",
          next_step: "Write a three-sentence ask.",
          evidence_to_collect: "Introductions and interviews.",
          model_status: "UNPRICED",
        }],
      },
    });
  });
  await page.goto(`/goals/${GOAL}/what-if`);
  await page.getByPlaceholder(/What if/i).fill("what's the smartest move I haven't tried yet?");
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.getByText("Ask that investor for a few targeted introductions")).toBeVisible();
  await expect(page.getByText("Probability impact not yet estimated")).toBeVisible();
  await expect(page.getByText(/hypothetical change/)).toHaveCount(0);
});

test("current odds does not invent strategy cards", async ({ page }) => {
  await page.unroute("**/api/v1/what-if/parse-intervention");
  await page.route("**/api/v1/what-if/parse-intervention", (route) => {
    const text = (route.request().postDataJSON() as { text: string }).text;
    return route.fulfill({
      json: {
        raw_text: text,
        changes: [],
        unsupported: ["Showing published odds only; no scenario was run."],
        pricing_status: "NOT_PRICED",
        request_kind: "current_odds",
        insights: [],
        consumer_summary: "Your latest published odds are 76.46%. That is the market number, not a What If scenario.",
      },
    });
  });
  await page.goto(`/goals/${GOAL}/what-if`);
  await page.getByPlaceholder(/What if/i).fill("What are my odds right now?");
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.getByText(/Your latest published odds are 76.46%/)).toBeVisible();
  await expect(page.locator(".insight-card")).toHaveCount(0);
});
