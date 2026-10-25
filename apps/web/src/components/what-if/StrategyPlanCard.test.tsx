import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { StrategyPlan } from "../../api/client";
import StrategyPlanCard from "./StrategyPlanCard";

const plan: StrategyPlan = {
  family: "outreach",
  interpretation:
    "You are considering direct outreach to people at companies you want to join. PlayItOut can price that through one modeled lever: weekly applications (currently 2 applications/week).",
  levers: [
    {
      assumption: "weekly_application_rate",
      label: "weekly applications",
      unit: "applications/week",
      unit_label: "targeted outreach emails per week",
      baseline_value: 2,
      minimum: 0,
      maximum: 50,
      operation: "add",
      question: "How many targeted cold emails will you send per week, on top of your current applications?",
      mapping_note: "Modeled as extra entries in your weekly application pipeline.",
      suggested_values: [2, 5, 10],
    },
  ],
  needs: ["How many targeted cold emails will you send per week, on top of your current applications?"],
  analysis: [{ heading: "Tradeoff", body: "Generic bulk email adds volume without interviews." }],
  stated_quantity: null,
  modeled: false,
};

describe("StrategyPlanCard", () => {
  it("asks for the missing quantity and runs the user's amount, not an inferred one", () => {
    const onRun = vi.fn();
    render(<StrategyPlanCard plan={plan} question="what if i cold email fdes" onRun={onRun} />);
    expect(screen.getByText("Make it measurable")).toBeInTheDocument();
    expect(screen.getByText(/No probability change is assumed/)).toBeInTheDocument();
    expect(screen.getByText("Tradeoff")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+10" }));
    expect(onRun).toHaveBeenCalledWith(
      "what if i cold email fdes (+10 targeted outreach emails per week)",
      plan.levers[0],
      10,
    );

    fireEvent.change(screen.getByLabelText(plan.levers[0]!.question), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Run scenario" }));
    expect(onRun).toHaveBeenLastCalledWith(expect.any(String), plan.levers[0], 7);
  });

  it("refuses amounts above the model's lever cap", () => {
    render(<StrategyPlanCard plan={plan} question="q" onRun={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(plan.levers[0]!.question), { target: { value: "60" } });
    expect(screen.getByRole("button", { name: "Run scenario" })).toBeDisabled();
    expect(screen.getByText(/caps this lever at 50/)).toBeInTheDocument();
  });
});
