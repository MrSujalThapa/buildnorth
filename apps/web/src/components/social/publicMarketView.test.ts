import { expect, test } from "vitest";
import type { PublicMarketDetail } from "../../api/client";
import { criteriaRows, publicMarketStats, signedPoints } from "./publicMarketView";

function market(overrides: Partial<PublicMarketDetail> = {}): PublicMarketDetail {
  return {
    goal_id: "g1",
    title: "Read 20 books by end of 2026",
    description: "",
    category: "learning",
    visibility: "private",
    creator: { user_id: "u1", handle: "reader", username: "reader", display_name: "Reader", bio: null, has_photo: false },
    star_count: 2,
    fork_count: 1,
    starred: false,
    published_at: null,
    updated_at: null,
    latest_probability: 0.42,
    forecast: { status: "published" },
    history: [
      { created_at: "2026-10-01T00:00:00Z", probability: 0.31 },
      { created_at: "2026-10-10T00:00:00Z", probability: 0.42 },
    ],
    fork: null,
    blueprint: {
      title: "Read 20 books by end of 2026",
      description: "Reach 20 books read by Dec 31, 2026",
      category: "learning",
      deadline: "2026-12-31T23:59:59Z",
      success_criteria: { metric: "books_read", operator: ">=", target: "20", unit: "books" },
      milestones: [],
      strategies: [],
      evidence_types: [],
      suggested_integrations: [],
      model_configuration: {},
      forecast: { status: "published" },
    },
    share_path: "/m/g1",
    ...overrides,
  };
}

test("criteria rows read Measure, Comparison, Target, Unit in order", () => {
  expect(criteriaRows({ unit: "books", target: "20", operator: ">=", metric: "books_read" })).toEqual([
    { key: "metric", label: "Measure", value: "Books read" },
    { key: "operator", label: "Comparison", value: "At least" },
    { key: "target", label: "Target", value: "20" },
    { key: "unit", label: "Unit", value: "books" },
  ]);
  expect(criteriaRows({ event: "signed_offer", description: "shown elsewhere" })).toEqual([
    { key: "event", label: "Outcome", value: "Signed offer" },
  ]);
});

test("stats report change in percentage points since first publication", () => {
  const stats = publicMarketStats(market());
  expect(stats.latestOdds).toBeCloseTo(42);
  expect(stats.changePoints).toBeCloseTo(11);
  expect(stats.updates).toBe(2);
  expect(stats.targetDate).toBe("Dec 31, 2026");
  expect(signedPoints(stats.changePoints!)).toBe("+11.0 pts");
  expect(signedPoints(-2.04)).toBe("−2.0 pts");
});

test("withheld markets never expose odds or change", () => {
  const stats = publicMarketStats(market({ forecast: { status: "withheld" }, latest_probability: null }));
  expect(stats.latestOdds).toBeNull();
  expect(stats.changePoints).toBeNull();
  expect(stats.updates).toBe(2);
});
