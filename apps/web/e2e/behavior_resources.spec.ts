import { expect, test } from "@playwright/test";

const CAREER = "20000000-0000-0000-0000-000000000002";
const RUNNING = "20000000-0000-0000-0000-000000000004";

const careerPlan = {
  goal_title: "Get promoted / get FDE offer",
  goal_type: "deadline_event",
  state_dimensions: ["interview_practice", "applications"],
  recommended: [
    {
      plugin_id: "notion",
      relevance: "recommended",
      rationale: "Practice and application records.",
      resources: [
        {
          resource_id: "leetcode-journal",
          label: "LeetCode journal",
          rationale: "Contains historical practice frequency and completion records relevant to interview-preparation consistency.",
          resource_type: "page",
          why: "Contains historical practice frequency and completion records relevant to interview-preparation consistency.",
          goal_relevance: "high",
          state_variables: ["DSA practice consistency", "execution history"],
          recommended: true,
        },
        {
          resource_id: "application-tracker",
          label: "application tracker",
          rationale: "Application pipeline.",
          resource_type: "database",
          why: "Tracks applications and interviews.",
          goal_relevance: "high",
          state_variables: ["applications"],
          recommended: true,
        },
        {
          resource_id: "running-journal",
          label: "running journal",
          rationale: "Training notes.",
          resource_type: "page",
          why: "Training notes, not interview evidence.",
          goal_relevance: "low",
          state_variables: [],
          recommended: false,
        },
        {
          resource_id: "random-notes",
          label: "random notes",
          rationale: "Unrelated.",
          resource_type: "page",
          why: "No overlap with the career contract.",
          goal_relevance: "irrelevant",
          state_variables: [],
          recommended: false,
        },
      ],
    },
  ],
  irrelevant: [],
  manual_fallback_note: "",
};

const runningPlan = {
  ...careerPlan,
  goal_title: "Run a faster 10K",
  recommended: [
    {
      plugin_id: "notion",
      relevance: "recommended",
      rationale: "Training journal.",
      resources: [
        {
          resource_id: "running-journal",
          label: "running journal",
          rationale: "Training sessions.",
          resource_type: "page",
          why: "Running and training completion history.",
          goal_relevance: "high",
          state_variables: ["training_consistency"],
          recommended: true,
        },
        {
          resource_id: "leetcode-journal",
          label: "LeetCode journal",
          rationale: "Interview practice.",
          resource_type: "page",
          why: "Interview practice, not running evidence.",
          goal_relevance: "low",
          state_variables: [],
          recommended: false,
        },
        {
          resource_id: "application-tracker",
          label: "application tracker",
          rationale: "Job pipeline.",
          resource_type: "database",
          why: "Applications are not running evidence.",
          goal_relevance: "low",
          state_variables: [],
          recommended: false,
        },
      ],
    },
  ],
};

function pluginView(id: string, name: string) {
  return {
    definition: {
      id,
      name,
      description: `${name} workspace`,
      category: "integration",
      provider_type: "composio",
      logo_url: null,
      capabilities: [],
      used_for: [],
    },
    connection: {
      plugin_id: id,
      status: "connected",
      connected_at: "2026-08-30T00:00:00Z",
      last_sync_at: "2026-08-30T12:00:00Z",
      permissions: ["read"],
      account_metadata: {},
      error: null,
    },
  };
}

function goalPayload(goalId: string, title: string) {
  return {
    goal_id: goalId,
    title,
    goal_type: "deadline_event",
    deadline: "2027-08-31T00:00:00Z",
    forecast_status: "EXPLORATORY",
    state_dimensions: ["interview_practice"],
  };
}

test.describe("Resource-specific evidence", () => {
  test.beforeEach(async ({ page }) => {
    await page.route(/\/api\/v1\/goals\/[^/?]+$/, async (route) => {
      const goalId = route.request().url().split("/").pop() ?? CAREER;
      const title = goalId === RUNNING ? "Run a faster 10K" : "Get promoted / get FDE offer";
      await route.fulfill({ json: goalPayload(goalId, title) });
    });
    await page.route("**/api/v1/what-if/history/**", (route) => route.fulfill({ json: [] }));
    await page.route("**/api/v1/goals/*/evidence/sources/recipes", (route) => route.fulfill({ json: [] }));
    await page.route("**/api/v1/goals/*/evidence", (route) => {
      if (route.request().url().includes("/sources/")) return route.fallback();
      return route.fulfill({ json: [] });
    });
    await page.route("**/api/v1/goals/*/behavior-profile", (route) =>
      route.fulfill({
        json: {
          estimator_version: "behavior_hierarchical_beta_v1",
          execution: {
            probability: 0.63,
            n_eff: 12,
            confidence: "medium",
            source: "FITTED",
            usable: true,
            notes: [],
          },
          dimensions: [
            {
              key: "follow_through",
              label: "Follow-through",
              value: 0.63,
              display_percent: 63,
              limited_evidence: false,
              confidence: "medium",
              provenance: {
                comparable_commitments: 18,
                completed: 14,
                recency_weighted_completion: 0.63,
                evidence_window_days: 42,
                sources: ["Calendar", "Notion"],
                n_eff: 12,
                formula: "recency-weighted Beta-Bernoulli",
                details: ["18 comparable commitments", "14 completed"],
              },
            },
          ],
          disclaimer: "Summarizes observed behavior, not personality.",
          evidence_sufficiency: "medium",
          n_raw: 18,
          n_eff: 12,
        },
      }),
    );
    await page.route("**/api/v1/plugins?*", (route) =>
      route.fulfill({
        json: {
          items: [pluginView("notion", "Notion"), pluginView("github", "GitHub")],
          next_cursor: null,
          total_items: 2,
        },
      }),
    );
    await page.route("**/api/v1/plugins/connected", (route) =>
      route.fulfill({ json: [pluginView("notion", "Notion"), pluginView("github", "GitHub")] }),
    );
    await page.route("**/api/v1/plugins", (route) => {
      if (route.request().url().includes("/resources")) return route.fallback();
      return route.fulfill({
        json: {
          items: [pluginView("notion", "Notion"), pluginView("github", "GitHub")],
          next_cursor: null,
          total_items: 2,
        },
      });
    });
    await page.route("**/api/v1/what-if/baseline-state/**", (route) =>
      route.fulfill({
        json: {
          priced: true,
          current_value: 80,
          target_value: 150,
          periods: 12,
          direction: "increase",
          assumptions: [
            {
              name: "execution_probability",
              value: 0.72,
              minimum: 0,
              maximum: 1,
              step: 0.01,
              source: "EXPLORATION_ASSUMPTION",
              unit: "probability",
              editable: true,
            },
          ],
          config: { n_draws: 2000, seed: 1 },
          default_intervention: { id: "primary-plan", title: "Scenario plan", action_type: "flow_change" },
        },
      }),
    );
    await page.route("**/api/v1/what-if/parse-intervention", (route) =>
      route.fulfill({
        json: {
          raw_text: "What if I do LeetCode 2 hours per day?",
          changes: [],
          unsupported: [],
          effect_assigned: false,
        },
      }),
    );
    await page.route("**/api/v1/what-if/fast-reprice", (route) =>
      route.fulfill({
        json: {
          priced: true,
          status: "EXPLORATORY",
          message: null,
          baseline_probability: 0.41,
          scenario_probability: 0.5,
          conditional_on_execution_probability: 0.58,
          execution_probability: 0.63,
          expected_uplift_pp: 9,
          uplift_interval_pp: [2, 12],
          p_uplift_positive: 0.7,
          outcome_quantiles: { p10: 0.4, p50: 0.5, p90: 0.62 },
          fan: [],
          distribution_bins: [{ lower: 0.4, upper: 0.6, mass: 1 }],
          assumptions: [],
          opportunity_costs: [],
          diagnostics: { n_draws: 2000, seed: 1, converged: true, achieved_mc_error: 0.01, duration_ms: 12 },
          sensitivity: [],
          fragility_pp: 1,
          run_id: "behavior-e2e",
          persisted: false,
          history_snapshot_created: false,
          receipt: {},
          llm_calls: 0,
          total_latency_ms: 12,
        },
      }),
    );
  });

  test("Career ranks LeetCode/application above running/random", async ({ page }) => {
    await page.route("**/api/v1/goals/*/evidence/sources/plan", (route) =>
      route.fulfill({ json: careerPlan }),
    );
    await page.route("**/api/v1/plugins/notion/resources", (route) =>
      route.fulfill({
        json: careerPlan.recommended[0].resources.map((item) => ({
          uri: `composio://notion/${item.resource_id}`,
          name: item.label,
          description: item.why,
          resource_type: item.resource_type,
        })),
      }),
    );
    await page.goto(`/goals/${CAREER}/evidence`);
    await expect(page.getByText(/Evidence/i).first()).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: /Find relevant sources/i }).click();
    await page.getByRole("button", { name: /Notion/i }).first().click();
    await expect(page.getByText("LeetCode journal")).toBeVisible({ timeout: 30_000 });
    const labels = await page.locator(".evidence-resource-list strong").allTextContents();
    expect(labels[0]?.toLowerCase()).toContain("leetcode");
    expect(labels.join(" ").toLowerCase()).toContain("running journal");
    expect(labels.indexOf("LeetCode journal")).toBeLessThan(labels.findIndex((item) => item.toLowerCase().includes("running")));
  });

  test("Running ranks the running journal above LeetCode", async ({ page }) => {
    await page.route("**/api/v1/goals/*/evidence/sources/plan", (route) =>
      route.fulfill({ json: runningPlan }),
    );
    await page.route("**/api/v1/plugins/notion/resources", (route) =>
      route.fulfill({
        json: runningPlan.recommended[0].resources.map((item) => ({
          uri: `composio://notion/${item.resource_id}`,
          name: item.label,
          description: item.why,
          resource_type: item.resource_type,
        })),
      }),
    );
    await page.goto(`/goals/${RUNNING}/evidence`);
    await expect(page.getByText(/Evidence/i).first()).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: /Notion/i }).first().click();
    const labels = await page.locator(".evidence-resource-list strong").allTextContents();
    expect(labels[0]?.toLowerCase()).toContain("running");
  });

  test("GitHub repo selection stays goal-specific", async ({ page }) => {
    await page.route("**/api/v1/goals/*/evidence/sources/plan", (route) =>
      route.fulfill({
        json: {
          goal_title: "engineering career",
          goal_type: "deadline_event",
          state_dimensions: ["project_activity"],
          recommended: [
            {
              plugin_id: "github",
              relevance: "recommended",
              rationale: "Selected repositories.",
              resources: [
                {
                  resource_id: "MrSujalThapa/playitout",
                  label: "MrSujalThapa/playitout",
                  rationale: "Active engineering repo.",
                  resource_type: "repository",
                  why: "Project activity for the career goal.",
                  goal_relevance: "high",
                  state_variables: ["project_activity"],
                  recommended: true,
                },
                {
                  resource_id: "someone/unrelated",
                  label: "someone/unrelated",
                  rationale: "Unrelated.",
                  resource_type: "repository",
                  why: "No overlap with the career contract.",
                  goal_relevance: "low",
                  state_variables: [],
                  recommended: false,
                },
              ],
            },
          ],
          irrelevant: [],
        },
      }),
    );
    await page.route("**/api/v1/plugins/github/resources", (route) => route.fulfill({ json: [
      { uri: "composio://github/MrSujalThapa/playitout", name: "MrSujalThapa/playitout", resource_type: "repository" },
      { uri: "composio://github/someone/unrelated", name: "someone/unrelated", resource_type: "repository" },
    ] }));
    await page.goto(`/goals/${CAREER}/evidence`);
    await page.getByRole("button", { name: /Find relevant sources/i }).click();
    await page.getByRole("button", { name: /GitHub/i }).first().click();
    await expect(page.getByText("MrSujalThapa/playitout")).toBeVisible();
    await page.getByText("MrSujalThapa/playitout").click();
    await expect(page.getByRole("button", { name: /Save source/i })).toBeVisible();
  });

  test("source sync status survives reload and reports completion", async ({ page }, testInfo) => {
    let status: "queued" | "completed" | null = null;
    const job = () => ({
      id: "30000000-0000-0000-0000-000000000001", owner_id: "10000000-0000-0000-0000-000000000001",
      goal_id: CAREER, status, created_at: "2026-10-20T12:00:00Z", updated_at: "2026-10-20T12:00:00Z",
      started_at: null, finished_at: null,
      receipt: status === "completed" ? { records_scanned: 1, records_added: 0, duplicates: 1 } : {},
      error: null,
    });
    await page.route("**/api/v1/goals/*/evidence/sources/recipes", (route) => route.fulfill({ json: [
      { goal_id: CAREER, plugin_id: "notion", label: "Book report", approved: true, steps: [] },
    ] }));
    await page.route(`**/api/v1/goals/${CAREER}/evidence/sources/sync`, (route) => {
      if (route.request().method() === "POST") {
        status = "queued";
        return route.fulfill({ status: 202, json: job() });
      }
      return route.fulfill({ json: status ? job() : null });
    });
    await page.goto(`/goals/${CAREER}/evidence`);
    await page.getByRole("button", { name: "Sync sources" }).click();
    await expect(page.getByText("Sync queued")).toBeVisible();
    await page.reload();
    await expect(page.getByText("Sync queued")).toBeVisible();
    status = "completed";
    await expect(page.getByText("No new updates")).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: `test-results/remediation-evidence-sync-${testInfo.project.name}.png`, fullPage: true });
  });

  test("approved source watch can be paused, stopped, and restarted", async ({ page }, testInfo) => {
    const resourceIds = ["12345678-1234-1234-1234-123456789abc", "12345678-1234-1234-1234-123456789abd"];
    const statuses = new Map<string, "active" | "paused" | "revoked">();
    const watch = (resourceId: string) => ({
      id: resourceId, goal_id: CAREER,
      plugin_id: "notion", resource_id: resourceId,
      scope: "parent", status: statuses.get(resourceId), last_success_at: null, last_error: null,
    });
    await page.route("**/api/v1/goals/*/evidence/sources/recipes", (route) => route.fulfill({ json: [
      { goal_id: CAREER, plugin_id: "notion", label: "Book Reports", approved: true, steps: [
        { capability_id: "notion.page.read", resource_uri: "composio://notion/12345678-1234-1234-1234-123456789abc", arguments: {} },
        { capability_id: "notion.page.read", resource_uri: "composio://notion/12345678-1234-1234-1234-123456789abd", arguments: {} },
      ] },
    ] }));
    await page.route("**/api/v1/goals/*/evidence/sources/watches", (route) => {
      if (route.request().method() === "POST") {
        expect(route.request().postDataJSON()).toMatchObject({ plugin_id: "notion", scope: "parent" });
        const resourceId = route.request().postDataJSON().resource_id as string;
        expect(resourceIds).toContain(resourceId);
        statuses.set(resourceId, "active");
        return route.fulfill({ json: watch(resourceId) });
      }
      return route.fulfill({ json: [...statuses.keys()].map(watch) });
    });
    await page.route("**/api/v1/goals/*/evidence/sources/watches/*", (route) => {
      const resourceId = route.request().url().split("/").at(-1)!;
      statuses.set(resourceId, route.request().postDataJSON().status);
      return route.fulfill({ json: watch(resourceId) });
    });
    await page.goto(`/goals/${CAREER}/evidence`);
    await page.getByRole("button", { name: "Watch 2 areas" }).click();
    await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
    expect([...statuses.values()]).toEqual(["active", "active"]);
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
    await page.getByRole("button", { name: "Stop" }).click();
    await expect(page.getByRole("button", { name: "Restart" })).toBeVisible();
    await page.getByRole("button", { name: "Restart" }).click();
    await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
    await page.screenshot({ path: `test-results/source-watch-${testInfo.project.name}.png`, fullPage: true });
  });

  test("What If keeps execution-adjusted odds separate", async ({ page }) => {
    await page.route("**/api/v1/what-if/simulate", (route) =>
      route.fulfill({
        json: {
          priced: true,
          status: "EXPLORATORY",
          message: null,
          baseline_probability: 0.41,
          scenario_probability: 0.5,
          conditional_on_execution_probability: 0.58,
          execution_probability: 0.63,
          expected_uplift_pp: 9,
          uplift_interval_pp: [2, 12],
          p_uplift_positive: 0.7,
          outcome_quantiles: { p10: 0.4, p50: 0.5, p90: 0.62 },
          fan: [],
          distribution_bins: [{ lower: 0.4, upper: 0.6, mass: 1 }],
          assumptions: [],
          opportunity_costs: [],
          diagnostics: { n_draws: 2000, seed: 1, converged: true, achieved_mc_error: 0.01, duration_ms: 12 },
          sensitivity: [],
          fragility_pp: 1,
          run_id: "behavior-e2e",
          persisted: false,
          history_snapshot_created: false,
          receipt: {},
          llm_calls: 0,
          total_latency_ms: 12,
          execution_breakdown: {
            current_probability: 0.41,
            conditional_on_full_execution: 0.58,
            follow_through_probability: 0.63,
            execution_adjusted_probability: 0.5,
          },
        },
      }),
    );
    await page.goto(`/goals/${CAREER}/what-if`);
    await page.getByPlaceholder(/What if/i).fill("What if I do LeetCode 2 hours per day?");
    await page.getByRole("button", { name: /Run scenario/i }).click();
    await expect(page.getByText("If fully executed")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Estimated follow-through")).toBeVisible();
    await expect(page.getByText("Scenario odds")).toBeVisible();
    await expect(page.getByText("Scenario baseline")).toBeVisible();
  });
});
