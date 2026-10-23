import { expect, test } from "@playwright/test";

const goalId = "20000000-0000-0000-0000-000000000080";
const goal = {
  goal_id: goalId,
  title: "Finish calculus with at least 70%",
  goal_type: "threshold",
  success_definition: { metric: "course_grade", target: 70 },
  deadline: "2026-12-31T23:59:59Z",
  forecast_status: "UNPRICED",
  state_dimensions: ["course_grade"],
};

test("course standing accepts real inputs without treating hypotheticals as evidence", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let submitted: Record<string, unknown> | null = null;
  await page.route(`**/api/v1/goals/${goalId}`, (route) => route.fulfill({ json: goal }));
  await page.route(`**/api/v1/goals/${goalId}/evidence`, (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/v1/what-if/history/${goalId}`, (route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/what-if/course-grade", (route) => {
    submitted = route.request().postDataJSON() as Record<string, unknown>;
    return route.fulfill({ json: {
      status: "underdetermined", average: null, known_contribution: 27,
      known_weight: 0.3, remaining_weight: 0.7, required_remaining: 61.428571,
      required_is_uniform: false, unattainable: false, already_met: false,
      scenarios: [
        { label: "remaining=50", remaining_score: 50, average: 62, meets_target: false },
        { label: "remaining=80", remaining_score: 80, average: 83, meets_target: true },
      ],
      questions: ["What score should we use for Final?"], missing: ["Final"],
      message: "Hypothetical scores are not evidence.", arithmetic_only: true, writes_evidence: false,
    } });
  });
  await page.goto(`/goals/${goalId}`);
  await expect(page.getByRole("heading", { name: "Course standing" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Compute standing" })).toBeDisabled();
  await page.getByRole("textbox", { name: "Component 1 name" }).fill("Midterm");
  await page.getByRole("spinbutton", { name: "Midterm weight" }).fill("30");
  await page.getByRole("spinbutton", { name: "Midterm score" }).fill("90");
  await page.getByRole("textbox", { name: "Component 2 name" }).fill("Final");
  await page.getByRole("spinbutton", { name: "Final weight" }).fill("70");
  await page.getByRole("spinbutton", { name: "Target course average" }).fill("70");
  await page.getByRole("spinbutton", { name: "Scenario A remaining score" }).fill("50");
  await page.getByRole("spinbutton", { name: "Scenario B remaining score" }).fill("80");
  await page.getByRole("button", { name: "Compute standing" }).click();
  await expect(page.getByText("Need 61.43 on the remaining component.")).toBeVisible();
  await expect(page.getByText("Remaining 50 → 62 (below target)")).toBeVisible();
  await expect(page.getByText("Remaining 80 → 83 (meets target)")).toBeVisible();
  expect(submitted).toMatchObject({ target: 70, scenarios: [50, 80] });
  await page.screenshot({ path: `test-results/course-standing-${testInfo.project.name}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
