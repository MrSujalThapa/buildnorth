import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

test("a failed route offers a visible recovery action", () => {
  const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
  function FailedRoute(): never {
    throw new Error("Failed to fetch dynamically imported module");
  }
  try {
    render(<ErrorBoundary><FailedRoute /></ErrorBoundary>);
    expect(screen.getByRole("heading", { name: "Something went wrong" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload page" })).toBeInTheDocument();
  } finally {
    logged.mockRestore();
  }
});
