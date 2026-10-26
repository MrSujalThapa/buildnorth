import { expect, test, vi } from "vitest";
import type { PublicMarketDetail, PublicMarketUpdate } from "../../api/client";
import { buildAssistantSummary, shareLink } from "./share";

test("falls back to copying the public URL", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText }, share: undefined });
  await expect(shareLink({ url: "https://playitout.example/m/1", title: "Goal" })).resolves.toBe("copied");
  expect(writeText).toHaveBeenCalledWith("https://playitout.example/m/1");
});

function update(overrides: Partial<PublicMarketUpdate>): PublicMarketUpdate {
  return {
    published_at: "2026-10-01T00:00:00Z",
    probability: 0.457,
    previous_probability: null,
    change_points: null,
    kind: "first_publication",
    receipt_recorded: true,
    evidence_total: 2,
    new_evidence_count: 2,
    retired_evidence_count: null,
    new_evidence_metrics: ["applications submitted"],
    other_new_evidence_count: 1,
    model: "count_process@v1",
    model_change: null,
    status_change: null,
    definition_revised: false,
    deadline_changed: false,
    ...overrides,
  };
}

function summaryMarket(visibility: "public" | "private"): PublicMarketDetail {
  const history = [
    { created_at: "2026-10-01T00:00:00Z", probability: 0.457 },
    { created_at: "2026-10-06T00:00:00Z", probability: 0.578 },
  ];
  return {
    goal_id: "g1",
    title: "Land an FDE offer",
    description: "Reach 40 applications submitted by Dec 31, 2026",
    category: "career",
    visibility,
    creator: { user_id: "owner-1", handle: "maya", username: "maya", display_name: "Maya", bio: null, has_photo: false },
    star_count: 3,
    fork_count: 1,
    starred: false,
    published_at: "2026-10-01T00:00:00Z",
    updated_at: null,
    latest_probability: 0.578,
    forecast: { status: "published" },
    history,
    fork: null,
    blueprint: {
      title: "Land an FDE offer",
      description: "Reach 40 applications submitted by Dec 31, 2026",
      category: "career",
      deadline: "2026-12-31T23:59:59Z",
      success_criteria: { metric: "applications_submitted", operator: ">=", target: 40 },
      milestones: ["Ship portfolio", { title: "First onsite" }],
      strategies: ["Two tailored applications per weekday"],
      evidence_types: ["Recruiter email thread"],
      suggested_integrations: ["gmail-sync-secret-connector"],
      model_configuration: { token: "sk-live-secret", family: "count_process" },
      forecast: { status: "published" },
      tracked_metrics: ["applications_submitted", "interviews"],
    },
    share_path: "/m/g1",
    updates: [
      update({}),
      update({
        published_at: "2026-10-06T00:00:00Z",
        probability: 0.578,
        previous_probability: 0.457,
        change_points: 12.1,
        kind: "update",
        new_evidence_count: 3,
        new_evidence_metrics: ["applications submitted", "interviews"],
        other_new_evidence_count: 1,
        model_change: { previous: "count_process@v1", current: "count_process@v2" },
      }),
    ],
    modeled_sensitivity: { published_at: "2026-10-06T00:00:00Z", model: "count_process@v2", drivers: ["application rate"] },
  };
}

test("assistant summary carries the public market essentials with an instruction line", () => {
  const text = buildAssistantSummary(summaryMarket("public"), "https://playitout.example/m/g1");
  const [instruction] = text.split("\n");
  expect(instruction).toMatch(/^I'm sharing a goal market from Play It Out\. Please help me reason about it\./);
  expect(instruction).toMatch(/not their causes/);
  for (const expected of [
    "# Land an FDE offer",
    "- Creator: @maya",
    "- Public market: https://playitout.example/m/g1",
    "- Published odds: 57.8% as of Oct 6, 2026",
    "- Deadline: December 31, 2026",
    "- Measure: Applications submitted",
    "- Comparison: At least",
    "- Target: 40",
    "## Approach\n- Two tailored applications per weekday",
    "1. Ship portfolio\n2. First onsite",
    "- applications submitted\n- interviews",
    "- Oct 6, 2026: 45.7% → 57.8% (+12.1 pts). 3 new evidence records: applications submitted, interviews + 1 other; Model count_process@v1 → count_process@v2",
    "- Oct 1, 2026: 45.7%. First publication, 2 evidence records: applications submitted + 1 other",
    "## Modeled sensitivity (assumptions the model uses, not causes)\n- application rate",
  ]) {
    expect(text).toContain(expected);
  }
});

test("assistant summary never includes model configuration, integrations or credentials", () => {
  const text = buildAssistantSummary(summaryMarket("public"), "https://playitout.example/m/g1");
  for (const forbidden of ["sk-live-secret", "token", "gmail-sync-secret-connector", "Recruiter email thread", "owner-1", "user_id"]) {
    expect(text).not.toContain(forbidden);
  }
});

test("private markets never get a public link in the summary", () => {
  const text = buildAssistantSummary(summaryMarket("private"), "https://playitout.example/m/g1");
  expect(text).toContain("- Visibility: private, not published");
  expect(text).not.toContain("https://playitout.example/m/g1");
});
