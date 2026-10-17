import { expect, test, type Page } from "@playwright/test";

/**
 * Cold browser E2E across goal families — uses live API (no fixture mocks).
 * NOT_PRICED / EXPLORATORY is acceptable; silent failures are not.
 */

async function createGoalViaUi(page: Page, prompt: string): Promise<string | null> {
  await page.goto("/new");
  const input = page.getByLabel("What should happen?");
  await expect(input).toBeVisible({ timeout: 60_000 });
  await input.fill(prompt);
  await page.getByRole("button", { name: "Create market" }).click();

  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    if (/\/goals\/[0-9a-f-]{36}/i.test(page.url())) break;

    const confirm = page.getByRole("button", { name: "Confirm", exact: true });
    if (await confirm.isVisible().catch(() => false) && (await confirm.isEnabled().catch(() => false))) {
      await confirm.click();
      await page.waitForTimeout(2000);
      continue;
    }

    const continueBtn = page.getByRole("button", { name: "Continue", exact: true });
    if (await continueBtn.isVisible().catch(() => false) && (await continueBtn.isEnabled().catch(() => false))) {
      const fields = page.locator(".composer-form input");
      const count = await fields.count();
      for (let f = 0; f < count; f++) {
        const field = fields.nth(f);
        const value = await field.inputValue();
        if (!value.trim()) {
          const label = ((await fields.nth(f).getAttribute("id")) || "").toLowerCase();
          await field.fill(label.includes("date") || label.includes("deadline") ? "2027-08-30" : "Use a reasonable default from the stated goal.");
        }
      }
      await continueBtn.click();
      await page.waitForTimeout(2000);
      continue;
    }

    await page.waitForTimeout(1000);
  }

  await expect
    .poll(() => page.url(), { timeout: 180_000 })
    .toMatch(/\/goals\/[0-9a-f-]{36}/i);

  const match = page.url().match(/\/goals\/([0-9a-f-]{36})/i);
  return match?.[1] ?? null;
}

async function walkGoalSurfaces(page: Page, goalId: string) {
  await page.goto(`/goals/${goalId}`);
  await expect(page.locator("body")).toContainText(
    /Evidence|What if|odds|forecast|EXPLORATORY|ANCHORED|NOT_PRICED|Needs more|%/i,
    { timeout: 60_000 },
  );

  await page.goto(`/goals/${goalId}/evidence`);
  await expect(page.getByText(/Evidence|Sources|Recommended|Connected|Sync|provider/i).first()).toBeVisible({
    timeout: 90_000,
  });

  await page.goto(`/goals/${goalId}/what-if`);
  await expect(page.getByRole("tab", { name: "Change" })).toBeVisible({ timeout: 90_000 });

  const input = page.getByPlaceholder("What if I change the plan…");
  await expect(input).toBeVisible({ timeout: 30_000 });
  await input.fill("What if I spend 5 focused hours per week on the highest-leverage activity?");
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.locator("body")).toContainText(
    /odds|probability|%|NOT_PRICED|Not priced|Result|distribution|needs more|assumption/i,
    { timeout: 120_000 },
  );

  for (const tab of ["Futures", "Compare", "Paths"] as const) {
    await page.getByRole("tab", { name: tab }).click();
    await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
  }
}

test.describe("Cold goal journeys (live API)", () => {
  test("Career / promotion goal cold path", async ({ page }) => {
    test.setTimeout(360_000);
    const goalId = await createGoalViaUi(
      page,
      "Get promoted to Senior Software Engineer within 12 months",
    );
    expect(goalId, "expected a created goal id").toBeTruthy();
    await walkGoalSurfaces(page, goalId!);
  });

  test("Running goal cold path", async ({ page }) => {
    test.setTimeout(360_000);
    const goalId = await createGoalViaUi(page, "Run a half marathon under 1 hour 45 minutes by June 2027");
    expect(goalId, "expected a created goal id").toBeTruthy();
    await walkGoalSurfaces(page, goalId!);
  });

  test("Finance goal cold path", async ({ page }) => {
    test.setTimeout(360_000);
    const goalId = await createGoalViaUi(page, "Build a $20,000 emergency fund by December 2027");
    expect(goalId, "expected a created goal id").toBeTruthy();
    await walkGoalSurfaces(page, goalId!);
  });

  test("Arbitrary newsletter growth goal cold path", async ({ page }) => {
    test.setTimeout(360_000);
    const goalId = await createGoalViaUi(page, "Grow my technical newsletter to 5,000 subscribers by end of 2027");
    expect(goalId, "expected a created goal id").toBeTruthy();
    await walkGoalSurfaces(page, goalId!);
  });
});
