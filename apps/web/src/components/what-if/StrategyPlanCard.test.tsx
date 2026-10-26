import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { StrategyPlan } from "../../api/client";
import StrategyPlanCard from "./StrategyPlanCard";

const plan: StrategyPlan = {
  family: "outreach",
  interpretation:
    "You are considering direct outreach. PlayItOut can price it through weekly applications (currently 2 applications/week) once you choose how replies are modeled.",
  levers: [
    {
      assumption: "weekly_application_rate",
      label: "weekly applications",
      unit: "applications/week",
      unit_label: "outreach emails per week",
      baseline_value: 2,
      minimum: 0,
      maximum: 50,
      operation: "add",
      question: "How many targeted cold emails will you send per week?",
      mapping_note: "A cold email is not an application.",
      suggested_values: [2, 5, 10],
    },
  ],
  needs: ["Choose how to model it: your expected reply rate, or the application proxy."],
  analysis: [{ heading: "Tradeoff", body: "Generic bulk email adds volume without interviews." }],
  stated_quantity: null,
  modeled: false,
  affected_outcomes: ["Replies from people you contact", "Offers"],
  options: [
    {
      id: "reply_rate",
      label: "Use my expected reply rate",
      description: "Emails enter the pipeline at the reply rate you expect.",
      proxy: false,
      inputs: [
        { key: "amount", label: "How many targeted cold emails will you send per week?", unit: "outreach emails per week", minimum: 0, maximum: 48, required: true, value: null, suggested_values: [2, 5, 10] },
        { key: "reply_rate_pct", label: "What share of emails do you expect to get a reply?", unit: "% replies", minimum: 0, maximum: 100, required: true, value: null, suggested_values: [5, 10, 20] },
      ],
    },
    {
      id: "as_applications",
      label: "Count each email as one application",
      description: "A simplifying proxy.",
      proxy: true,
      inputs: [
        { key: "amount", label: "How many targeted cold emails will you send per week?", unit: "outreach emails per week", minimum: 0, maximum: 48, required: true, value: null, suggested_values: [2, 5, 10] },
      ],
    },
  ],
};

describe("StrategyPlanCard", () => {
  it("does not treat cold email as an application until the user chooses an option", () => {
    const onRun = vi.fn();
    render(<StrategyPlanCard plan={plan} question="what if i cold email fdes" onRun={onRun} />);
    expect(screen.getByText("Make it measurable")).toBeInTheDocument();
    expect(screen.getByText(/Can affect/)).toBeInTheDocument();
    expect(screen.getByText("Use my expected reply rate")).toBeInTheDocument();
    expect(screen.getByText("Count each email as one application")).toBeInTheDocument();
    expect(screen.getByText("Proxy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run scenario" })).not.toBeInTheDocument();
    expect(onRun).not.toHaveBeenCalled();
  });

  it("runs only after the user picks an option and supplies its inputs", () => {
    const onRun = vi.fn();
    render(<StrategyPlanCard plan={plan} question="what if i cold email fdes" onRun={onRun} />);
    fireEvent.click(screen.getByLabelText(/Use my expected reply rate/));
    fireEvent.click(screen.getByRole("button", { name: "+10" }));
    fireEvent.click(screen.getByRole("button", { name: "20" }));
    fireEvent.click(screen.getByRole("button", { name: "Run scenario" }));
    expect(onRun).toHaveBeenCalledWith("what if i cold email fdes", plan, "reply_rate", { amount: 10, reply_rate_pct: 20 });
  });

  it("refuses amounts above the model's lever cap", () => {
    render(<StrategyPlanCard plan={plan} question="q" onRun={vi.fn()} />);
    fireEvent.click(screen.getByLabelText(/Count each email as one application/));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "60" } });
    expect(screen.getByRole("button", { name: "Run scenario" })).toBeDisabled();
    expect(screen.getByText(/supports at most 48/)).toBeInTheDocument();
  });
});
