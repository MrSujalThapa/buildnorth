import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { ExecutionProfileRadar, type BehaviorProfile } from "./ExecutionProfileRadar";

test("partial evidence plots only observed traits without completing a polygon", () => {
  const profile: BehaviorProfile = {
    estimator_version: "synthetic_test_fixture",
    execution: { probability: 0.65, n_eff: 3, confidence: "limited", source: "TEST", usable: false, notes: [] },
    dimensions: [
      { key: "follow_through", label: "Follow-through", value: 0.7, display_percent: 70,
        limited_evidence: false, confidence: "limited",
        provenance: { comparable_commitments: 3, completed: 2, sources: [], n_eff: 3, formula: "Observed", details: [] } },
      { key: "consistency", label: "Consistency", value: null, display_percent: null,
        limited_evidence: true, confidence: "insufficient",
        provenance: { comparable_commitments: 0, completed: 0, sources: [], n_eff: 0, formula: "", details: [] } },
      { key: "momentum", label: "Momentum", value: null, display_percent: null,
        limited_evidence: true, confidence: "insufficient",
        provenance: { comparable_commitments: 0, completed: 0, sources: [], n_eff: 0, formula: "", details: [] } },
    ],
    disclaimer: "", evidence_sufficiency: "partial", n_raw: 3, n_eff: 3,
  };
  const { container } = render(<ExecutionProfileRadar profile={profile} />);
  expect(screen.getByText("Some traits need more observations.")).toBeVisible();
  expect(container.querySelectorAll(".radar-node")).toHaveLength(1);
  expect(container.querySelector(".radar-wedge")).toBeNull();
  expect(screen.queryByText("Observed")).toBeNull();
  expect(screen.getByText("You completed 2 of 3 comparable commitments.")).toBeVisible();
});
