import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../api/client";
import { NewGoalPage } from "./NewGoalPage";

afterEach(() => vi.restoreAllMocks());

test("failed goal creation explains the provider error and links to Settings", async () => {
  vi.spyOn(api, "startThread").mockRejectedValue(new Error("API request failed (Hosted inference is not configured)"));
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
