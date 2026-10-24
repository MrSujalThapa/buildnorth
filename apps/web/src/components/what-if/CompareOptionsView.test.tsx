import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import type { CompareOption, Market } from "../../adapters/templateTypes";
import CompareOptionsView from "./CompareOptionsView";

function option(id: string, label: string, odds: number, outcome: CompareOption["outcome"]): CompareOption {
  return { id, label, odds, downside: "Low", time: "Low", followThrough: 80, sensitivity: "Low", note: "", outcome };
}

it("shows each option's simulated result in the goal's unit, not as odds", () => {
  render(
    <CompareOptionsView
      market={{ id: "g", title: "Run a 10K in under 45 minutes" } as Market}
      view="simple"
      options={[
        option("path-a", "Easy runs", 99.9, { p10: 1943, p50: 2181, p90: 2389 }),
        option("path-b", "Intervals", 100, { p10: 1700, p50: 1905, p90: 2120 }),
      ]}
      outcomeScale={{ unit: "seconds", target: 2700, direction: "at_most" }}
      selectedIds={["path-a", "path-b"]}
      onSelectedIdsChange={() => {}}
      isolatedId={null}
      onIsolate={() => {}}
    />,
  );
  const figure = screen.getByRole("figure", { name: "Simulated results for each option" });
  expect(figure.textContent).toContain("32:23–39:49");
  expect(figure.textContent).toContain("Target ≤ 45:00");
  expect(figure.textContent).not.toMatch(/\d{4,}%/);
});

it("shows a failed comparison without stale odds", () => {
  render(
    <CompareOptionsView
      market={{ id: "g", title: "Read 20 books" } as Market}
      view="deep"
      options={[option("old", "Old run", 92, null)]}
      outcomeScale={{ unit: "books", target: 20, direction: "at_least" }}
      priced={false}
      message="Could not compare these paths. Try again."
      selectedIds={["old"]}
      onSelectedIdsChange={() => {}}
      isolatedId={null}
      onIsolate={() => {}}
    />,
  );
  expect(screen.getByText("Could not compare these paths. Try again.")).toBeInTheDocument();
  expect(screen.queryByText("92%")).not.toBeInTheDocument();
});
