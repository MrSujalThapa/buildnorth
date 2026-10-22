import { describe, expect, it } from "vitest";

import type { WhatIfBaselineState, WhatIfResult } from "../api/client";
import { causalCaption, toImpactViewModel } from "./impactViewModel";
import type { WhatIfPreview } from "./templateTypes";

describe("toImpactViewModel", () => {
  it("reports simulated results in the goal's unit, never as odds", () => {
    const result = {
      outcome_quantiles: { p10: 1835.9, p50: 2026.1, p90: 2307.0 },
      distribution_bins: [
        { lower: 1800, upper: 2000, mass: 0.4 },
        { lower: 2000, upper: 2400, mass: 0.6 },
        { lower: 2400, upper: 2600, mass: 0 },
      ],
      diagnostics: { n_draws: 2000, seed: 7, converged: true, achieved_mc_error: 0.01, duration_ms: 4 },
      sensitivity: [],
      opportunity_costs: [],
      receipt: {},
    } as unknown as WhatIfResult;
    const baseline = { target_value: 2700, target_unit: "seconds", direction: "at_most", config: { seed: 7 } } as unknown as WhatIfBaselineState;
    const impact = toImpactViewModel({} as WhatIfPreview, result, baseline);
    expect(impact.likelyRangeLabel).toBe("30:36–38:27");
    expect(impact.outcomeBins).toHaveLength(2);
    expect(impact.outcomeScale).toEqual({ unit: "seconds", target: 2700, direction: "at_most" });
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
