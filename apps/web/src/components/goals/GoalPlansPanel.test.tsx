import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { PlannedCommitment } from "../../api/client";
import GoalPlansPanel from "./GoalPlansPanel";

const plan: PlannedCommitment = {
  id: "plan-1",
  goal_id: "goal-1",
  domain: "career",
  action: "Cold email 10 founders a week",
  planned_quantity: 80,
  unit: "applications",
  window_start: "2026-10-01T00:00:00Z",
  window_end: "2026-12-01T00:00:00Z",
  created_at: "2026-10-01T00:00:00Z",
  plan_context: {
    title: "What if I cold email 10 founders a week",
    option_id: "reply_rate",
    proxy: false,
    changes: [{ metric: "weekly_application_rate", operation: "add", value: 10, unit: "applications/week" }],
    quantity_per_period: 10,
    period: "week",
    duration_periods: 8,
    baseline_probability: 0.31,
    scenario_probability: 0.44,
    execution_probability: 0.7,
    assumptions_used: ["Your assumption: 20% of cold emails get a reply."],
    priced_at: "2026-10-01T00:00:00Z",
  },
};

vi.mock("../../api/client", () => ({
  api: {
    listPlans: vi.fn(() => Promise.resolve({ commitments: [plan], observations: [] })),
    evaluatePlan: vi.fn(() => Promise.resolve({ priced: true, baseline_probability: 0.3, scenario_probability: 0.4 })),
    observePlan: vi.fn(() => Promise.resolve({ id: "obs", commitment_id: "plan-1", version: 1, status: "partial", actual_quantity: 20, observed_at: new Date().toISOString() })),
  },
}));

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <GoalPlansPanel goalId="goal-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("GoalPlansPanel", () => {
  it("shows a planned action separately from evidence and can log a check-in", async () => {
    const { api } = await import("../../api/client");
    renderPanel();
    expect(await screen.findByText("What you said you would do")).toBeInTheDocument();
    expect(screen.getByText("Cold email 10 founders a week")).toBeInTheDocument();
    expect(screen.getByText("When you applied it").nextElementSibling).toHaveTextContent("44.0%");
    expect(screen.getByText(/planned actions, not evidence/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/How much did you actually do/), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Log what happened" }));
    await waitFor(() =>
      expect(api.observePlan).toHaveBeenCalledWith(
        "goal-1",
        "plan-1",
        expect.objectContaining({ status: "partial", actual_quantity: 20 }),
      ),
    );
  });
});
