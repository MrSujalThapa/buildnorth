import { describe, expect, it } from "vitest";

import { formatOutcome, formatOutcomeRange, targetLabel } from "./outcomeFormat";

describe("formatOutcome", () => {
  it("renders durations in seconds as clock time", () => {
    expect(formatOutcome(2700, "seconds")).toBe("45:00");
    expect(formatOutcome(5025, "seconds")).toBe("1:23:45");
    expect(formatOutcome(42, "seconds")).toBe("42 s");
  });

  it("renders dollars and plain counts with their unit", () => {
    expect(formatOutcome(100000, "USD")).toBe("$100,000");
    expect(formatOutcome(23.46, "books")).toBe("23.5 books");
    expect(formatOutcome(3, null)).toBe("3");
  });
});

describe("formatOutcomeRange", () => {
  it("omits missing or zero-width intervals instead of showing 0-0", () => {
    expect(formatOutcomeRange(null, 4, "books")).toBe("—");
    expect(formatOutcomeRange(12, 12, "books")).toBe("—");
  });

  it("orders the bounds", () => {
    expect(formatOutcomeRange(30, 18, "books")).toBe("18–30 books");
    expect(formatOutcomeRange(84000, 97250, "USD")).toBe("$84,000–$97,250");
  });
});

describe("targetLabel", () => {
  it("states the direction of success", () => {
    expect(targetLabel({ unit: "seconds", target: 2700, direction: "at_most" })).toBe("Target ≤ 45:00");
    expect(targetLabel({ unit: "USD", target: 100000, direction: "at_least" })).toBe("Target ≥ $100,000");
    expect(targetLabel({ unit: null, target: null, direction: "at_least" })).toBeNull();
  });
});
