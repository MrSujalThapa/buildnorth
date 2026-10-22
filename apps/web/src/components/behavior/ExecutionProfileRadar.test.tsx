import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { ExecutionProfileRadar, type BehaviorProfile } from "./ExecutionProfileRadar";

test("does not render the rejected six-trait skeleton", () => {
  const profile: BehaviorProfile = {
    estimator_version: "legacy",
    execution: { probability: 0.2, n_eff: 1, confidence: "insufficient", source: "TEST", usable: false, notes: [] },
    dimensions: [
      { key: "follow_through", label: "Follow-through", value: null, display_percent: null,
        limited_evidence: true, confidence: "insufficient",
        provenance: { comparable_commitments: 0, completed: 0, sources: [], n_eff: 0, formula: "", details: [] } },
      { key: "consistency", label: "Consistency", value: null, display_percent: null,
        limited_evidence: true, confidence: "insufficient",
        provenance: { comparable_commitments: 0, completed: 0, sources: [], n_eff: 0, formula: "", details: [] } },
      { key: "momentum", label: "Momentum", value: null, display_percent: null,
        limited_evidence: true, confidence: "insufficient",
        provenance: { comparable_commitments: 0, completed: 0, sources: [], n_eff: 0, formula: "", details: [] } },
    ],
    disclaimer: "", evidence_sufficiency: "insufficient", n_raw: 0, n_eff: 0,
  };
  const { container } = render(<ExecutionProfileRadar profile={profile} />);
  expect(screen.getByText(/No measured parameters yet/)).toBeVisible();
  expect(container.querySelector("svg")).toBeNull();
});

test("partial parameter evidence plots measured axes without inventing a full polygon", () => {
  const profile: BehaviorProfile = {
    estimator_version: "parameter_profile@1.0.0",
    execution: { probability: 0, n_eff: 4, confidence: "low", source: "FITTED", usable: true, notes: [] },
    dimensions: [
      { key: "weekly_applications", label: "Weekly applications", value: 0.7, display_percent: 70,
        limited_evidence: false, confidence: "medium",
        provenance: { comparable_commitments: 4, completed: 4, sources: ["manual"], n_eff: 4, formula: "Average applications per week", details: ["Current average 14.00 per week"] } },
      { key: "monthly_savings", label: "Monthly savings", value: null, display_percent: null,
        limited_evidence: true, confidence: "insufficient",
        provenance: { comparable_commitments: 0, completed: 0, sources: [], n_eff: 0, formula: "", details: [] } },
      { key: "weekly_running_km", label: "Weekly running", value: null, display_percent: null,
        limited_evidence: true, confidence: "insufficient",
        provenance: { comparable_commitments: 1, completed: 1, sources: [], n_eff: 1, formula: "", details: [] } },
    ],
    disclaimer: "", evidence_sufficiency: "low", n_raw: 5, n_eff: 5,
  };
  const { container } = render(<ExecutionProfileRadar profile={profile} />);
  expect(screen.getByText("Some parameters need more observations.")).toBeVisible();
  expect(container.querySelectorAll(".radar-node")).toHaveLength(1);
  expect(container.querySelector(".radar-fill")).toBeNull();
  expect(screen.getByText("Current average 14.00 per week")).toBeVisible();
});
