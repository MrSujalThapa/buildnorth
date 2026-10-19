import { describe, expect, it } from "vitest";

import { causalCaption, formatLikelyRange } from "./impactViewModel";

describe("formatLikelyRange", () => {
  it("omits a zero-width interval instead of showing 0-0", () => {
    expect(formatLikelyRange({ p10: 0, p90: 0 }, 12)).toBe("—");
    expect(formatLikelyRange({ p10: 41.2, p90: 41.2 }, 12)).toBe("—");
  });

  it("formats a real sampling range", () => {
    expect(formatLikelyRange({ p10: 12.4, p90: 18.1 }, 20)).toBe("12–18%");
  });
});

describe("causalCaption", () => {
  it("prefers the model message over a generic label", () => {
    expect(
      causalCaption({
        message: "Hypothetical model-parameter change.",
        receipt: { causal_status: "parameter_intervention" },
      } as never),
    ).toBe("Hypothetical model-parameter change.");
  });

  it("labels unmapped interventions as not invented", () => {
    expect(
      causalCaption({
        message: null,
        receipt: { causal_status: "unmapped_intervention" },
      } as never),
    ).toMatch(/not mapped/i);
  });
});
