import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { api, type WorkflowSnapshot } from "../../api/client";
import { NewGoalPage } from "./NewGoalPage";

afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

test("failed goal creation explains the provider error and links to Settings", async () => {
  vi.spyOn(api, "startThreadAsync").mockRejectedValue(new Error("API request failed (Hosted inference is not configured)"));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><NewGoalPage /></MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("What should happen?"), { target: { value: "Pass 06: run 10 km by December 2027" } });
  fireEvent.click(screen.getByRole("button", { name: "Create market" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Hosted inference is not configured");
  expect(screen.getByRole("link", { name: "Check inference settings" })).toHaveAttribute("href", "/settings#inference-heading");
  expect(screen.getByRole("button", { name: "Create market" })).toBeEnabled();
});

test("long-running goal creation shows honest persisted progress", async () => {
  const running = { thread_id: "test-thread", status: "running", progress: [] } as unknown as WorkflowSnapshot;
  vi.spyOn(api, "startThreadAsync").mockResolvedValue(running);
  vi.spyOn(api, "getThread").mockResolvedValue(running);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><NewGoalPage /></MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("What should happen?"), { target: { value: "Read 20 books by December 2026" } });
  fireEvent.click(screen.getByRole("button", { name: "Create market" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Working on your goal");
});

test("reload recovers a running goal thread", async () => {
  const running = { thread_id: "persisted-thread", status: "running", progress: [] } as unknown as WorkflowSnapshot;
  sessionStorage.setItem("playitout:pending-goal-thread", running.thread_id);
  vi.spyOn(api, "getThread").mockResolvedValue(running);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><NewGoalPage /></MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("status")).toHaveTextContent("Working on your goal");
  expect(api.getThread).toHaveBeenCalledWith("persisted-thread");
});

test("expired goal thread reports a timeout after reload", async () => {
  sessionStorage.setItem("playitout:pending-goal-thread", "expired-thread");
  const failed = { thread_id: "expired-thread", status: "failed", progress: [],
    debug: { failure_code: "workflow_timeout" } } as unknown as WorkflowSnapshot;
  vi.spyOn(api, "getThread").mockResolvedValue(failed);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><NewGoalPage /></MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("This attempt timed out");
  expect(sessionStorage.getItem("playitout:pending-goal-thread")).toBeNull();
});

test("async resume after clarification keeps polling until confirm", async () => {
  const threadId = "resume-thread";
  const running = { thread_id: threadId, status: "running", progress: ["Understanding goal"] } as unknown as WorkflowSnapshot;
  const clarification = {
    thread_id: threadId,
    status: "needs_input",
    progress: ["Understanding goal"],
    interrupt: {
      type: "clarification",
      message: "A few details are needed.",
      questions: [{ id: "q1", question: "Target company?", why_needed: "scope" }],
    },
  } as unknown as WorkflowSnapshot;
  const resuming = {
    thread_id: threadId,
    status: "running",
    progress: ["Understanding goal", "Continuing the agent workflow"],
  } as unknown as WorkflowSnapshot;
  const confirm = {
    thread_id: threadId,
    status: "needs_input",
    progress: ["Understanding goal", "Continuing the agent workflow"],
    interrupt: {
      type: "confirm_contract",
      proposal: {
        title: "Receive an FDE offer",
        goal_type: "career",
        success_metric: "offer",
        success_operator: ">=",
        success_target: "1",
        deadline: "2027-08-01",
      },
    },
  } as unknown as WorkflowSnapshot;
  vi.spyOn(api, "startThreadAsync").mockResolvedValue(running);
  vi.spyOn(api, "getThread").mockResolvedValueOnce(clarification).mockResolvedValue(confirm);
  vi.spyOn(api, "resumeThreadAsync").mockResolvedValue(resuming);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><NewGoalPage /></MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("What should happen?"), { target: { value: "Receive an FDE offer by August 2027" } });
  fireEvent.click(screen.getByRole("button", { name: "Create market" }));
  expect(await screen.findByRole("button", { name: "Continue" })).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Target company set" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(await screen.findByRole("button", { name: "Confirm" }, { timeout: 5000 })).toBeInTheDocument();
});

test("provider timeout after commit links to the saved goal", async () => {
  sessionStorage.setItem("playitout:pending-goal-thread", "saved-thread");
  const failed = {
    thread_id: "saved-thread", status: "failed", progress: [],
    goal: { goal_id: "saved-goal", title: "Pass a course" },
    debug: { goal_committed: true },
  } as unknown as WorkflowSnapshot;
  vi.spyOn(api, "getThread").mockResolvedValue(failed);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><NewGoalPage /></MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Your goal was saved");
  expect(screen.getByRole("link", { name: "Open saved goal" })).toHaveAttribute("href", "/goals/saved-goal");
  expect(screen.queryByRole("button", { name: "Create market" })).not.toBeInTheDocument();
});
