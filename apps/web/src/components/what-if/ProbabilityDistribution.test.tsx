import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import ProbabilityDistribution from "./ProbabilityDistribution";

it("does not report 0% for a series with no simulated outcomes", () => {
  render(<ProbabilityDistribution ariaLabel="Option odds" series={[{ id: "a", label: "Focused", points: [] }]} />);
  expect(screen.getByRole("note").textContent).toBe("No simulated outcomes yet.");
  expect(screen.queryByText(/most likely 0%/)).toBeNull();
});
