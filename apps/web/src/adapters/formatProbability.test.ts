import { describe, expect, it } from "vitest";

import { formatProbabilityPercent } from "./formatProbability";

describe("formatProbabilityPercent", () => {
  it("shows one decimal for sub-10% values", () => {
    expect(formatProbabilityPercent(0.94)).toBe("0.9%");
    expect(formatProbabilityPercent(9.4)).toBe("9.4%");
  });

  it("rounds whole percentages for larger values", () => {
    expect(formatProbabilityPercent(67.2)).toBe("67%");
    expect(formatProbabilityPercent(93.4)).toBe("93%");
  });

  it("returns an em dash for missing values", () => {
    expect(formatProbabilityPercent(null)).toBe("—");
  });
});
