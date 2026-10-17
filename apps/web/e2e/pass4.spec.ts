import { expect, test, type Page } from "@playwright/test";

const goal = {
  goal_id: "20000000-0000-0000-0000-000000000003",
  title: "Reach one million dollars in net worth",
  goal_type: "continuous_target",
  success_definition: { metric: "net_worth", amount: 1_000_000 },
  deadline: "2035-12-31T23:59:59Z",
  forecast_status: "EXPLORATORY",
  state_dimensions: ["liquid_assets", "income", "expenses"],
  resource_constraints: { hours_per_week: 12, budget_amount: 2500, budget_currency: "CAD" },
};

function impact(probability: number) {
  return {
    priced: true, status: "EXPLORATORY", baseline_probability: 0.3,
    scenario_probability: probability, conditional_on_execution_probability: probability + 0.05,
    execution_probability: 0.72, expected_uplift_pp: (probability - 0.3) * 100,
    uplift_interval_pp: [12, 18], p_uplift_positive: 0.72,
    outcome_quantiles: { p10: 700000, p25: 850000, p50: 1000000, p75: 1150000, p90: 1300000 },
    expected_outcome: 1010000, downside_probability: 0.18,
    fan: [{ period: 0, p10: 120000, p50: 120000, p90: 120000 }, { period: 112, p10: 700000, p50: 1000000, p90: 1300000 }],
    assumptions: [], opportunity_costs: ["1 hours/week displaced"],
    diagnostics: { n_draws: 6000, seed: 20260829, converged: true, achieved_mc_error: 0.0064, duration_ms: 25 },
    sensitivity: [{ assumption: "flow", probability_swing_pp: 20, lower_probability: 0.35, upper_probability: 0.55 }],
    fragility_pp: 10, run_id: "run-impact", persisted: true, history_snapshot_created: true,
    receipt: { llm_used: false, model: { family: "continuous_target_transition", version: "1.0.0" } },
    llm_calls: 0, total_latency_ms: 28,
  };
}

async function mockPass4(page: Page) {
  let agentCalls = 0;
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok", service: "api", version: "test" } }));
  await page.route(`**/api/v1/goals/${goal.goal_id}`, (route) => route.fulfill({ json: goal }));
  await page.route(`**/api/v1/goals/${goal.goal_id}/evidence`, (route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/agent/**", (route) => { agentCalls += 1; return route.abort(); });
  await page.route("**/api/v1/what-if/fast-reprice", async (route) => {
    const body = route.request().postDataJSON() as { assumptions: { name: string; value: number }[] };
    const flow = body.assumptions.find((item) => item.name === "flow")?.value ?? 6000;
    await route.fulfill({ json: impact(flow >= 10000 ? 0.62 : 0.45) });
  });
  await page.route("**/api/v1/what-if/history/**", (route) => route.fulfill({ json: [{ id: "history", probability: 0.3, forecast_status: "EXPLORATORY", evidence_watermark: "fixture", model_family: "continuous_target_transition", model_version: "1.0.0", assumption_hash: "hash", simulation_run_id: "run", created_at: "2026-08-29T00:00:00Z" }] }));
  await page.route("**/api/v1/what-if/target-search", (route) => route.fulfill({ json: { target_probability: 0.7, current_probability: 0.3, gap_pp: 40, feasible: true, message: "Minimum viable paths verified against the target.", search_method: "bounded_enumeration", run_id: "target", receipt: {}, paths: [{ label: "Balanced allocation", action_ids: ["balanced"], resulting_probability: 0.71, resource_cost: { hours_per_week: 4, money: 0, energy: 2 }, fragility_pp: 4, valid_because: "Re-simulated and verified." }] } }));
  await page.route("**/api/v1/what-if/action-frontier", (route) => route.fulfill({ json: { selected_id: "a", frontier_ids: ["a", "c"], points: [{ id: "a", label: "Focused allocation", resource_cost: 2, expected_uplift_pp: 6, dominated: false, action_ids: ["focused"], opportunity_costs: ["2 hours/week displaced"], provenance: ["focused:USER_ASSUMPTION"] }, { id: "b", label: "Dominated allocation", resource_cost: 3, expected_uplift_pp: 4, dominated: true, action_ids: ["b"], opportunity_costs: [], provenance: [] }, { id: "c", label: "Intensive allocation", resource_cost: 7, expected_uplift_pp: 14, dominated: false, action_ids: ["intensive"], opportunity_costs: ["7 hours/week displaced"], provenance: ["intensive:USER_ASSUMPTION"] }] } }));
  await page.route("**/api/v1/what-if/possible-futures", (route) => route.fulfill({ json: { priced: false, message: "Possible futures are structurally valid but unpriced.", outcomes: [{ label: "Target reached", probability: null, downside: false, median: null, p10: null, p90: null }, { label: "Downside outcome", probability: null, downside: true, median: null, p10: null, p90: null }], other_probability: 0, evidence_basis: [], model_version: "multi_outcome_transition@1.0.0", run_id: null } }));
  await page.route("**/api/v1/what-if/compare-paths", (route) => route.fulfill({ json: { model_family: "continuous_target_transition", model_version: "1.0.0", seed: 20260829, run_id: "paths", paths: ["Focused", "Balanced", "Intensive"].map((label, index) => ({ id: label.toLowerCase(), label, primary_goal_probability: 0.45 + index * 0.1, expected_outcome: 900000 + index * 100000, median: 900000 + index * 100000, p10: 600000, p90: 1300000, downside_probability: 0.25 - index * 0.05, fragility_pp: 5 + index, resource_cost: { hours_per_week: 2 + index * 2, money: 0, energy: 1 + index }, execution_probability: 0.8, model_status: "EXPLORATORY" })) } }));
  return () => agentCalls;
}

test("PASS 4 decision surfaces are interactive, exact, and agent-free", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  const agentCalls = await mockPass4(page);
  await page.goto(`/goals/${goal.goal_id}/what-if`);
  await expect(page.getByText("45%").first()).toBeVisible();
  await page.getByLabel("Exact recurring flow").fill("10000");
  await expect(page.getByText("62%").first()).toBeVisible();
  await page.getByRole("tab", { name: "Deeper analysis" }).click();
  await expect(page.getByRole("heading", { name: "Market History" })).toBeVisible();
  await page.getByRole("button", { name: "Paths" }).click();
  await page.getByRole("button", { name: "Find Minimum Paths" }).click();
  await expect(page.getByText("→ 71%")).toBeVisible();
  await page.getByRole("button", { name: "Price Feasible Bundles" }).click();
  await expect(page.getByText(/Dominated allocation.*dominated/)).toBeVisible();
  await page.getByRole("button", { name: "Futures" }).dispatchEvent("click");
  await page.getByRole("button", { name: "Structure Futures" }).click();
  await expect(page.getByText("Possible futures are structurally valid but unpriced.")).toBeVisible();
  await page.getByRole("button", { name: "Compare" }).dispatchEvent("click");
  await page.getByRole("button", { name: "Compare Assumption-Conditioned Paths" }).click();
  await expect(page.getByRole("heading", { name: "Intensive" })).toBeVisible();
  await page.getByRole("tab", { name: "Deeper analysis" }).click({ force: true });
  await expect(page.getByText("Forecast Receipt")).toBeVisible();
  expect(agentCalls()).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  expect(errors.filter((error) => !error.includes("favicon"))).toEqual([]);
});
