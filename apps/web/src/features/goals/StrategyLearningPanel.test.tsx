import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api, type StrategyLearningContext, type StrategyRecommendation } from "../../api/client";
import { StrategyLearningPanel } from "./StrategyLearningPanel";

afterEach(() => vi.restoreAllMocks());

const empty: StrategyLearningContext = {
  goal_id: "goal-1",
  as_of: "2026-10-25T00:00:00Z",
  past_trials: [],
  note: "Observed association is not evidence that a recommendation caused an outcome.",
};

test("loads empty strategy history and records accept after generate", async () => {
  const generated: StrategyRecommendation = {
    recommendation_id: "rec-1",
    strategy_key: "targeted_outreach",
    action: "Contact one hiring team this week",
    recommended_at: "2026-10-25T00:00:00Z",
    decision: "pending",
    why_now: "The deadline is approaching",
    next_step: "Send one message",
  };
  let listed = empty;
  vi.spyOn(api, "strategyLearning").mockImplementation(() => Promise.resolve(listed));
  vi.spyOn(api, "generateStrategyRecommendation").mockImplementation(() => {
    listed = { ...empty, past_trials: [generated] };
    return Promise.resolve(generated);
  });
  vi.spyOn(api, "strategyRecommendationFeedback").mockImplementation(() => {
    listed = { ...empty, past_trials: [{ ...generated, decision: "accepted" }] };
    return Promise.resolve({ ...generated, decision: "accepted" });
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StrategyLearningPanel goalId="goal-1" />
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "Strategy feedback" })).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Suggest a next step" }));
  expect(await screen.findByRole("button", { name: "I’ll try this" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "I’ll try this" }));
  await waitFor(() =>
    expect(api.strategyRecommendationFeedback).toHaveBeenCalledWith("goal-1", "rec-1", "accepted"),
  );
});
