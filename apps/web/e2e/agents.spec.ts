import { expect, test, type Page } from "@playwright/test";

const confirmation: Record<string, unknown> = {
  thread_id: "30000000-0000-0000-0000-000000000001",
  kind: "create_goal",
  status: "needs_input",
  current_step: "confirm_goal",
  progress: ["Understanding goal"],
  interrupt: {
    type: "confirm_contract",
    questions: [],
    proposal: {
      title: "Receive an SWE/FDE offer from a target company",
      goal_type: "deadline_event",
      success_metric: "offer_received",
      success_operator: "==",
      success_target: "swe_or_fde_offer",
      deadline: "2027-08-31",
    },
    message: "Confirm this goal contract to create the market.",
  },
  goal: null,
  evidence: [],
  research: null,
  pricing: null,
  critic: null,
  agent_run_ids: { goal_architect: "run-architect" },
  debug: {},
};

const completed: Record<string, unknown> = {
  ...confirmation,
  status: "limited",
  current_step: "publish",
  progress: ["Understanding goal", "Researching reference class", "Pricing market", "Checking forecast"],
  interrupt: null,
  goal: {
    goal_id: "20000000-0000-0000-0000-000000000099",
    title: "Receive an SWE/FDE offer from a target company",
    goal_type: "deadline_event",
    deadline: "2027-08-31T23:59:59Z",
    forecast_status: "EXPLORATORY",
    state_dimensions: ["interview_outcomes"],
  },
  pricing: {
    priced: false,
    forecast_status: "EXPLORATORY",
    raw_probability: null,
    calibrated_probability: null,
    limitations: ["No calibrated model applies; probability withheld."],
    receipt: { priced: false },
  },
  critic: {
    decision: "publish_with_limitations",
    issues: [],
    limitations: ["No calibrated model applies; probability withheld."],
    required_actions: [],
  },
  agent_run_ids: { goal_architect: "run-architect", research: "run-research", critic: "run-critic" },
};

const withheld: Record<string, unknown> = {
  ...completed,
  status: "withheld",
  critic: { decision: "withhold", issues: ["Future leakage"], limitations: [], required_actions: [] },
};

const evidencePreview: Record<string, unknown> = {
  thread_id: "30000000-0000-0000-0000-000000000002",
  kind: "add_evidence",
  status: "needs_input",
  current_step: "interrupt_evidence",
  progress: ["Reading evidence"],
  interrupt: {
    type: "confirm_evidence",
    questions: [],
    proposal: {
      events: [
        { summary: "14 LeetCode mediums" },
        { summary: "Meta phone screen unsuccessful" },
      ],
    },
    message: "Review the recognized evidence before it is committed.",
  },
  goal: completed.goal,
  evidence: [
    {
      event_type: "practice",
      domain: "software",
      metric: "leetcode_medium_count",
      numeric_value: 14,
      categorical_value: null,
      unit: "count",
      observed_at: "unknown",
      source_type: "manual",
      summary: "14 LeetCode mediums",
    },
    {
      event_type: "interview",
      domain: "career",
      metric: "phone_screen_result",
      numeric_value: null,
      categorical_value: "unsuccessful",
      unit: null,
      observed_at: "unknown",
      source_type: "manual",
      summary: "Meta phone screen unsuccessful",
    },
  ],
  research: null,
  pricing: null,
  critic: null,
  agent_run_ids: { evidence: "run-evidence" },
  debug: {},
};

async function mockFoundation(page: Page) {
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok", service: "api", version: "test" } }));
  await page.route("**/api/v1/goals", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ json: [] });
    }
    return route.fallback();
  });
}

test("new market confirmation path does not invent odds", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  await mockFoundation(page);
  await page.route("**/api/v1/agent/threads", (route) => {
    if (route.request().method() === "POST" && !route.request().url().includes("resume")) {
      return route.fulfill({ json: confirmation });
    }
    return route.fallback();
  });
  await page.route("**/api/v1/agent/threads/*/resume", (route) => route.fulfill({ json: completed }));
  await page.route("**/api/v1/goals/20000000-0000-0000-0000-000000000099", (route) =>
    route.fulfill({ json: completed.goal }),
  );
  await page.route("**/api/v1/goals/20000000-0000-0000-0000-000000000099/evidence", (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: [] });
    return route.fallback();
  });
  await page.goto("/new");
  await page.getByLabel("What should happen?").fill("I want to receive an SWE/FDE offer from one of my target companies by August 2027.");
  await page.getByRole("button", { name: "Create market" }).click();
  await expect(page.getByRole("heading", { name: "Proposed contract" })).toBeVisible();
  await expect(page.getByText("Understanding goal…")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Researching");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("heading", { name: /SWE\/FDE/ })).toBeVisible();
  await expect(page.getByTestId("goal-price")).toHaveText("Not priced");
  expect(errors.filter((error) => !error.includes("favicon"))).toEqual([]);
});

test("manual evidence preview and withheld state", async ({ page }) => {
  await mockFoundation(page);
  await page.route("**/api/v1/goals/20000000-0000-0000-0000-000000000099", (route) =>
    route.fulfill({ json: completed.goal }),
  );
  await page.route("**/api/v1/goals/20000000-0000-0000-0000-000000000099/evidence", (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: [] });
    if (route.request().method() === "POST") return route.fulfill({ json: evidencePreview });
    return route.fallback();
  });
  await page.route("**/api/v1/agent/threads/*/resume", (route) => route.fulfill({ json: withheld }));
  await page.goto("/goals/20000000-0000-0000-0000-000000000099");
  await page.getByLabel("Add evidence").fill("I solved 14 LeetCode mediums this week and failed a Meta phone screen.");
  await page.getByRole("button", { name: "Submit evidence" }).click();
  await expect(page.getByText("14 LeetCode mediums")).toBeVisible();
  await expect(page.getByText("Meta phone screen unsuccessful")).toBeVisible();
  await page.getByRole("button", { name: "Commit evidence" }).click();
  await expect(page.getByTestId("goal-price")).toHaveText("Withheld");
});

test("debug agents panel is opt-in", async ({ page }) => {
  await mockFoundation(page);
  await page.route("**/api/v1/agent/threads", (route) => route.fulfill({ json: confirmation }));
  await page.goto("/new?debug=agents");
  await page.getByLabel("What should happen?").fill("I want to receive an SWE/FDE offer from one of my target companies by August 2027.");
  await page.getByRole("button", { name: "Create market" }).click();
  await expect(page.getByText("Agent trace")).toBeVisible();
});
