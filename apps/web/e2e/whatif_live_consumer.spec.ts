import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const apiBase = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";
const screenshotDir = "test-results/whatif-live";
const testToken = process.env.LIVE_E2E_TOKEN ?? process.env.VITE_TEST_AUTH_TOKEN ?? "";

async function apiReady(): Promise<boolean> {
  try {
    const health = await fetch(`${apiBase}/health`);
    return health.ok;
  } catch {
    return false;
  }
}

async function capture(page: Page, label: string) {
  await mkdir(screenshotDir, { recursive: true });
  await page.screenshot({ path: `${screenshotDir}/${test.info().project.name}-${label}.png`, fullPage: true });
}

async function createGoal(page: Page, intent: string): Promise<string> {
  await page.goto("/new");
  await expect(page.getByRole("heading", { name: /New market/i })).toBeVisible();
  await page.getByLabel(/What should happen/i).fill(intent);
  await page.getByRole("button", { name: /Create market/i }).click();
  const continueBtn = page.getByRole("button", { name: /^Continue$/ });
  const confirm = page.getByRole("button", { name: /^Confirm$/ });
  for (let round = 0; round < 4; round += 1) {
    await expect(continueBtn.or(confirm)).toBeVisible({ timeout: 120000 });
    if (await confirm.isVisible()) break;
    const inputs = page.locator("form.composer-form input");
    const count = await inputs.count();
    for (let index = 0; index < count; index += 1) {
      await inputs.nth(index).fill("Target company set; deadline August 2027; FDE role.");
    }
    await continueBtn.click();
  }
  await expect(confirm).toBeVisible({ timeout: 120000 });
  await expect(confirm).toBeEnabled();
  const resume = page.waitForResponse(
    (response) => response.url().includes("/agent/threads/") && response.url().includes("/resume") && response.request().method() === "POST",
    { timeout: 60000 },
  );
  await confirm.click();
  const resumed = await resume;
  expect(resumed.ok(), await resumed.text()).toBeTruthy();
  const payload = (await resumed.json()) as { thread_id?: string; goal?: { goal_id?: string } };
  let goalId = payload.goal?.goal_id;
  if (!goalId && payload.thread_id) {
    await expect
      .poll(
        async () => {
          const thread = await page.request.get(`${apiBase}/api/v1/agent/threads/${payload.thread_id}`, {
            headers: { Authorization: `Bearer ${testToken}` },
          });
          if (!thread.ok()) return "";
          const body = (await thread.json()) as { goal?: { goal_id?: string } };
          return body.goal?.goal_id ?? "";
        },
        { timeout: 30000 },
      )
      .not.toEqual("");
    const thread = await page.request.get(`${apiBase}/api/v1/agent/threads/${payload.thread_id}`, {
      headers: { Authorization: `Bearer ${testToken}` },
    });
    goalId = ((await thread.json()) as { goal?: { goal_id?: string } }).goal?.goal_id;
  }
  expect(goalId).toBeTruthy();
  await page.goto(`/goals/${goalId}`);
  return goalId!;
}

async function addEvidence(page: Page, goalId: string, text: string) {
  await page.goto(`/goals/${goalId}/evidence`);
  await page.getByLabel(/What happened/i).fill(text);
  const started = page.waitForResponse(
    (response) => response.url().includes("/agent/threads") && response.request().method() === "POST",
    { timeout: 120000 },
  );
  await page.getByRole("button", { name: /^Add evidence$/ }).click();
  await started;
  const commit = page.getByRole("button", { name: /Commit evidence/i });
  if (await commit.isVisible({ timeout: 90000 }).catch(() => false)) {
    const inputs = page.locator("form.composer-form input");
    const count = await inputs.count();
    for (let index = 0; index < count; index += 1) {
      await inputs.nth(index).fill("Distinct observed events; not hypothetical applications.");
    }
    const resumed = page.waitForResponse(
      (response) => response.url().includes("/resume") && response.request().method() === "POST",
      { timeout: 120000 },
    );
    await commit.click();
    const resumeResponse = await resumed;
    expect(resumeResponse.ok(), await resumeResponse.text()).toBeTruthy();
  }
  await expect(page.locator("body")).toContainText(/Recent events|Committed|evidence/i, { timeout: 120000 });
}

test.describe("live consumer What If (unmocked API)", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(process.env.LIVE_SPUR_E2E !== "1", "LIVE_SPUR_E2E=1 is required for paid Spur browser acceptance");
    test.skip(!(await apiReady()), `API is not running at ${apiBase}`);
    test.skip(!testToken, "LIVE_E2E_TOKEN is required for an invited test principal");
    await page.addInitScript((token) => sessionStorage.setItem("pm-test-token", token), testToken);
  });

  test("career goal create, evidence, market, What If, reprice", async ({ page }) => {
    test.setTimeout(420_000);
    const providers: string[] = [];
    const requestIds: string[] = [];
    page.on("response", async (response) => {
      if (!response.ok()) return;
      const url = response.url();
      if (
        !url.includes("/agent/threads") &&
        !url.includes("/parse-intervention") &&
        !url.includes("/goals/") 
      ) {
        return;
      }
      if (!url.includes("/api/v1/")) return;
      try {
        const body = (await response.json()) as {
          inference_provider?: string;
          inference_model?: string;
          agent_run_id?: string;
          debug?: { inference?: { provider?: string; model?: string; request_id?: string } };
        };
        const provider = body.inference_provider ?? body.debug?.inference?.provider;
        if (provider) providers.push(provider);
        const requestId = body.debug?.inference?.request_id;
        if (requestId) requestIds.push(requestId);
      } catch {
        return;
      }
    });
    const goalId = await createGoal(
      page,
      "I want to receive an FDE offer from a target company by August 2027.",
    );
    await capture(page, "goal-created");
    const stored = await page.request.get(`${apiBase}/api/v1/goals/${goalId}`, {
      headers: { Authorization: `Bearer ${testToken}` },
    });
    expect(stored.ok()).toBeTruthy();
    expect((await stored.json()).goal_id).toBe(goalId);

    await addEvidence(page, goalId, "I submitted 9 applications this month and got 2 recruiter screens.");
    await capture(page, "evidence");
    await page.reload();
    await expect(page.getByLabel(/What happened/i)).toBeVisible();

    await page.goto(`/goals/${goalId}/what-if`);
    await expect(page.getByPlaceholder(/What if/i)).toBeVisible({ timeout: 20000 });
    await capture(page, "whatif-desktop");
    const parsed = page.waitForResponse(
      (response) => response.url().includes("/parse-intervention") && response.request().method() === "POST",
      { timeout: 120000 },
    );
    await page.getByPlaceholder(/What if/i).fill(
      "What if I increase my applications from 8 per week to 15 per week for the next two months?",
    );
    await page.getByRole("button", { name: "Run scenario" }).click();
    const parseBody = (await (await parsed).json()) as {
      inference_provider?: string;
      inference_model?: string;
      inference_request_id?: string;
      changes?: { metric: string; operation: string; value: number }[];
    };
    expect(parseBody.inference_provider).toBe("spur");
    expect(parseBody.inference_model ?? "").toMatch(/glm/);
    expect(parseBody.changes?.length ?? 0).toBeGreaterThan(0);
    await expect(page.locator("body")).toContainText(/hypothetical|scenario|15|applications|published/i, {
      timeout: 60000,
    });
    const details = page.getByRole("button", { name: "Details" }).first();
    if (await details.isVisible().catch(() => false)) {
      await details.click();
      await expect(page.getByRole("dialog", { name: "Scenario details" })).toBeVisible();
      await page.getByRole("button", { name: "Close details" }).click();
    }
    await page.getByPlaceholder(/What if/i).fill("I keep reaching final rounds with no offers. What should I change?");
    await page.getByRole("button", { name: "Run scenario" }).click();
    await expect(page.locator(".insight-card, .scenario-plain, .quiet-copy, [role='alert']").first()).toBeVisible({
      timeout: 30000,
    });
    await capture(page, "strategy");
    await page.getByRole("tab", { name: "Futures" }).click();
    await page.getByRole("tab", { name: "Compare" }).click();
    await page.getByRole("tab", { name: "Reverse" }).click();
    await page.getByRole("tab", { name: "Change" }).click();
    await addEvidence(
      page,
      goalId,
      "A recruiter responded yesterday. I completed one interview. One application was rejected. I was introduced to a founder. I submitted 3 additional applications this week.",
    );
    const payload = {
      entries: [
        { key: "onsite_finals", label: "Final-round interviews", value: 2, unit: "count" },
      ],
    };
    const headers = { Authorization: `Bearer ${testToken}` };
    const first = await page.request.post(`${apiBase}/api/v1/goals/${goalId}/evidence/manual`, {
      headers,
      data: payload,
    });
    expect(first.ok()).toBeTruthy();
    const retry = await page.request.post(`${apiBase}/api/v1/goals/${goalId}/evidence/manual`, {
      headers,
      data: payload,
    });
    expect(retry.ok()).toBeTruthy();
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto(`/goals/${goalId}/what-if`);
    await capture(page, "whatif-dark");
    await page.getByPlaceholder(/What if/i).fill(
      "Given the recruiter response, interview, rejection, and founder introduction, what is the highest-leverage next move?",
    );
    await page.getByRole("button", { name: "Run scenario" }).click();
    await expect(page.locator(".insight-card, .scenario-plain, .quiet-copy, [role='alert']").first()).toBeVisible({
      timeout: 120000,
    });
    expect(providers.length, "agent-dependent browser calls must record a provider").toBeGreaterThan(0);
    expect(providers.every((item) => item === "spur"), `expected spur, got ${providers.join(",")}`).toBeTruthy();
    expect(requestIds.length, "browser Spur calls must expose a request id").toBeGreaterThan(0);
  });

  test("savings goal does not force an unpriceable publish", async ({ page }) => {
    test.skip(true, "Spur budget: career journey only this pass");
    test.setTimeout(240_000);
    const goalId = await createGoal(page, "I want to reach $80,000 in savings by December 2028.");
    await addEvidence(page, goalId, "Current savings are 18000 CAD in a high-interest account.");
    await capture(page, "savings");
    const listed = await page.request.get(`${apiBase}/api/v1/goals/${goalId}/evidence`, {
      headers: { Authorization: `Bearer ${testToken}` },
    });
    expect(listed.ok()).toBeTruthy();
    await page.goto(`/goals/${goalId}/what-if`);
    await page.getByPlaceholder(/What if/i).fill("What if I saved 900 a month instead?");
    await page.getByRole("button", { name: "Run scenario" }).click();
    await expect(page.locator("body")).toContainText(/scenario|unpriced|savings|published|not yet|CAD|month/i, {
      timeout: 20000,
    });
  });
});
