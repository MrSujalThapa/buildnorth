import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import VisibilityControl, { VisibilityBadge } from "../market/VisibilityControl";
import ForkedBlueprintPanel from "./ForkedBlueprintPanel";

test("fork panel lists the carried blueprint and next steps", () => {
  const onEvidence = vi.fn();
  const onWhatIf = vi.fn();
  render(
    <MemoryRouter>
      <ForkedBlueprintPanel
        fork={{
          source_goal_id: "src-1", source_user_id: "u1", source_handle: "reader", source_title: "Read 20 books",
          source_public: true, forked_at: "2026-10-25T00:00:00Z",
          carried_fields: ["title", "deadline", "success_criteria", "forecast_spec"],
        }}
        goal={{
          goal_id: "fork-1", title: "Read 20 books", goal_type: "threshold", deadline: "2026-12-31T23:59:59Z",
          forecast_status: "EXPLORATORY", state_dimensions: ["books_read"],
          success_definition: { metric: "books_read", operator: ">=", target: "20", unit: "books" },
        }}
        onEvidence={onEvidence}
        onWhatIf={onWhatIf}
        onDismiss={vi.fn()}
      />
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: "@reader/Read 20 books" })).toHaveAttribute("href", "/m/src-1");
  expect(screen.getByText(/success criteria, model setup/)).toBeInTheDocument();
  expect(screen.getByText("December 31, 2026")).toBeInTheDocument();
  expect(screen.getByText("Books read")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add evidence" }));
  fireEvent.click(screen.getByRole("button", { name: "Explore What If" }));
  expect(onEvidence).toHaveBeenCalledOnce();
  expect(onWhatIf).toHaveBeenCalledOnce();
});

test("visibility pill shows lock for private, globe for public, and toggles", () => {
  const onToggle = vi.fn();
  const { rerender, container } = render(<VisibilityControl visibility="private" onToggle={onToggle} />);
  const button = screen.getByRole("button", { name: /Private market/ });
  expect(button).toHaveClass("visibility-control", "is-private");
  expect(container.querySelector("svg.lucide-lock")).not.toBeNull();
  fireEvent.click(button);
  expect(onToggle).toHaveBeenCalledOnce();
  rerender(<VisibilityControl visibility="public" onToggle={onToggle} />);
  expect(screen.getByRole("button", { name: /Public market/ })).toHaveClass("is-public");
  expect(container.querySelector("svg.lucide-globe")).not.toBeNull();
  render(<VisibilityBadge visibility="private" />);
  expect(screen.getAllByText("Private").at(-1)?.closest(".visibility-badge")).toHaveClass("is-private");
});
