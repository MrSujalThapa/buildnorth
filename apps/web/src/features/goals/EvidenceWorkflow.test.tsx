import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { api, type WorkflowSnapshot } from "../../api/client";
import { EvidenceWorkflow } from "./EvidenceWorkflow";

afterEach(() => vi.restoreAllMocks());

const pending = {
  thread_id: "thread-1", status: "interrupted", progress: [],
  interrupt: { type: "confirm_evidence", questions: [], proposal: { events: [] } },
} as unknown as WorkflowSnapshot;

function mount(client: QueryClient) {
  render(<QueryClientProvider client={client}><MemoryRouter>
    <EvidenceWorkflow goalId="goal-1" initialSnapshot={pending} />
  </MemoryRouter></QueryClientProvider>);
}

it("refreshes dashboard only after a completed evidence workflow", async () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  vi.spyOn(api, "resumeThread").mockResolvedValue({ ...pending, status: "completed", interrupt: null });
  mount(client);
  expect(invalidate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Commit evidence" }));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["goals", "dashboard"] }));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["market-history", "goal-1"] });
});

it("does not invalidate dashboard for incomplete or failed confirmation", async () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  vi.spyOn(api, "resumeThread").mockResolvedValueOnce({ ...pending, status: "interrupted" });
  mount(client);
  fireEvent.click(screen.getByRole("button", { name: "Commit evidence" }));
  await waitFor(() => expect(api.resumeThread).toHaveBeenCalled());
  expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["goals", "dashboard"] });
});

it("shows a failed confirmation instead of implying publication", async () => {
  const client = new QueryClient();
  vi.spyOn(api, "resumeThread").mockRejectedValue(new Error("Provider unavailable"));
  mount(client);
  fireEvent.click(screen.getByRole("button", { name: "Commit evidence" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Provider unavailable");
});
