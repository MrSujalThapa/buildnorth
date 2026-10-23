import type { CourseGradeResult, Goal } from "../api/client";

const COURSE_TOKENS = /\b(grade|exam|course|syllabus|gpa|midterm|academic|assignment)\b/i;

export function isCourseStandingGoal(goal: Pick<Goal, "title" | "state_dimensions" | "success_definition">): boolean {
  const rawMetric = goal.success_definition?.metric;
  const metric = typeof rawMetric === "string" ? rawMetric.replace(/_/g, " ") : "";
  const blob = [goal.title, metric, ...(goal.state_dimensions ?? [])].join(" ");
  return COURSE_TOKENS.test(blob);
}

export function formatCourseScore(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 0 });
}

export function courseStandingSummary(result: CourseGradeResult): string {
  if (result.unattainable) return "Target unattainable even with 100 on remaining work.";
  if (result.already_met) return "Known components already meet the target.";
  if (result.required_remaining != null) {
    const qualifier = result.required_is_uniform ? " on remaining work (shared score)" : " on the remaining component";
    return `Need ${formatCourseScore(result.required_remaining)}${qualifier}.`;
  }
  if (result.status === "needs_scores" || result.status === "underdetermined") {
    return result.missing.length ? `Still need scores for ${result.missing.filter((item) => !item.startsWith("a single")).join(", ")}.` : result.message;
  }
  if (result.average != null) return `Standing ${formatCourseScore(result.average)} / 100.`;
  return result.message;
}
