import { describe, expect, it } from "vitest";
import { acceptsVisual, type ActiveVisual } from "./whatIfMessageGuard";

const active: ActiveVisual = {
  goalId: "goal-a", requestId: "latest",
  expected: { mode: "impact", view: "deep", question: "Apply to 10 jobs per week" },
};
const result = {
  kind: "playitout_what_if", goal: { goal_id: "goal-a" }, request_id: "latest",
  mode: "impact", view: "deep", question: "Apply to 10 jobs per week",
  history: [], baseline: {},
};

describe("MCP What If result scoping", () => {
  it("accepts the active goal and latest requested analysis", () => {
    expect(acceptsVisual(result, active)).toBe(true);
  });
  it("rejects a different goal, stale request, mode, depth, or question", () => {
    expect(acceptsVisual({ ...result, goal: { goal_id: "goal-b" } }, active)).toBe(false);
    expect(acceptsVisual({ ...result, request_id: "older" }, active)).toBe(false);
    expect(acceptsVisual({ ...result, mode: "compare" }, active)).toBe(false);
    expect(acceptsVisual({ ...result, view: "simple" }, active)).toBe(false);
    expect(acceptsVisual({ ...result, question: "other" }, active)).toBe(false);
  });
});
