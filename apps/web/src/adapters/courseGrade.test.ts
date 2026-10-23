import { describe, expect, it } from "vitest";

import { courseStandingSummary, formatCourseScore, isCourseStandingGoal } from "./courseGrade";

describe("course standing helpers", () => {
  it("recognizes academic goals and ignores running goals", () => {
    expect(
      isCourseStandingGoal({
        title: "Finish CS 241 with at least 80%",
        state_dimensions: ["midterm", "final exam"],
        success_definition: { metric: "course_grade" },
      }),
    ).toBe(true);
    expect(
      isCourseStandingGoal({
        title: "Finish calculus with at least 70%",
        state_dimensions: ["course_grade"],
        success_definition: { metric: "course_grade" },
      }),
    ).toBe(true);
    expect(
      isCourseStandingGoal({
        title: "Run a 10K in under 45 minutes",
        state_dimensions: ["recent_race_time"],
        success_definition: { metric: "10k_time_seconds" },
      }),
    ).toBe(false);
  });

  it("states the required remaining mark without calling it a forecast", () => {
    const summary = courseStandingSummary({
      status: "needs_scores",
      average: null,
      known_contribution: 27,
      known_weight: 0.3,
      remaining_weight: 0.7,
      required_remaining: 61.428571,
      required_is_uniform: false,
      unattainable: false,
      already_met: false,
      scenarios: [],
      questions: [],
      missing: ["final"],
      message: "arithmetic",
      arithmetic_only: true,
      writes_evidence: false,
    });
    expect(summary).toContain("61.43");
    expect(summary.toLowerCase()).not.toContain("forecast");
    expect(formatCourseScore(null)).toBe("—");
  });
});
