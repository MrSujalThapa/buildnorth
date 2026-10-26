import { describe, expect, it } from "vitest";

import type { PlannedCommitment, StrategyChangesResponse, WhatIfResult } from "../api/client";
import { draftPlan, outcomeFor, planState } from "./planAdoption";

const priced: StrategyChangesResponse = {
  option_id: "reply_rate",
  title: "What if I cold email 10 founders a week",
  changes: [
    { metric: "weekly_application_rate", operation: "add", value: 10, unit: "applications/week", frequency: "week", scope: "goal_state", provenance: "USER_ASSUMPTION" },
    { metric: "application_to_response", operation: "set", value: 0.15, unit: "probability", frequency: null, scope: "goal_state", provenance: "USER_ASSUMPTION" },
  ],
  assumptions_used: ["Your assumption: 20% of cold emails get a reply."],
  conflicts: [],
  proxy: false,
};
const result = { priced: true, baseline_probability: 0.3, scenario_probability: 0.42, execution_probability: 0.6 } as WhatIfResult;

describe("draftPlan", () => {
  it("stores the priced scenario as a hypothesis with totals for the window", () => {
    const draft = draftPlan({ priced, result, domain: "career", durationWeeks: 8, start: new Date("2026-10-26T00:00:00Z") });
    expect(draft?.summary).toBe("+10 applications per week for 8 weeks");
    expect(draft?.body.planned_quantity).toBe(80);
    expect(draft?.body.action).toBe("Cold email 10 founders a week");
    expect(draft?.body.window_end).toBe("2026-12-21T00:00:00.000Z");
    expect(draft?.body.plan_context.changes).toHaveLength(2);
    expect(draft?.body.plan_context.scenario_probability).toBe(0.42);
  });

  it("refuses to draft when nothing was priced", () => {
    expect(draftPlan({ priced: null, result, domain: "x", durationWeeks: 4, start: new Date() })).toBeNull();
    expect(draftPlan({ priced, result: { ...result, priced: false }, domain: "x", durationWeeks: 4, start: new Date() })).toBeNull();
  });

  it("converts monthly plans and keeps decreases explicit", () => {
    const monthly = { ...priced, changes: [{ ...priced.changes[0]!, metric: "flow", operation: "subtract", value: 500, unit: "currency/month", frequency: "month" }] };
    const draft = draftPlan({ priced: monthly, result, domain: "finance", durationWeeks: 13, start: new Date() });
    expect(draft?.decrease).toBe(true);
    expect(draft?.summary).toBe("−500 dollars per month for 3 months");
    expect(draft?.body.planned_quantity).toBe(1500);
  });
});

describe("planState", () => {
  const plan = { id: "p1", planned_quantity: 40, window_start: "2026-10-01T00:00:00Z", window_end: "2026-11-01T00:00:00Z" } as PlannedCommitment;

  it("separates planned, active, due and observed states", () => {
    expect(planState(plan, [], new Date("2026-09-01"))).toBe("planned");
    expect(planState(plan, [], new Date("2026-10-15"))).toBe("active");
    expect(planState(plan, [], new Date("2026-11-05"))).toBe("due");
    const obs = (version: number, status: "cancelled" | "partial") => ({ id: String(version), commitment_id: "p1", version, status, actual_quantity: null, observed_at: "" });
    expect(planState(plan, [obs(1, "partial"), obs(2, "cancelled")], new Date())).toBe("abandoned");
  });

  it("scores a check-in against the planned total", () => {
    expect(outcomeFor(plan, 0).status).toBe("missed");
    expect(outcomeFor(plan, 20).status).toBe("partial");
    expect(outcomeFor(plan, 45).status).toBe("completed");
  });
});
