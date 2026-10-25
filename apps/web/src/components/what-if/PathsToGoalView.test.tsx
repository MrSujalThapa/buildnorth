import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { ReverseBlueprint } from "../../api/client";
import type { PathStrategy } from "../../adapters/simulations";
import type { Market } from "../../adapters/templateTypes";
import PathsToGoalView from "./PathsToGoalView";

const market = { id: "fde", title: "Land a forward-deployed engineer offer" } as Market;

const change = {
  lever_id: "weekly_application_rate",
  label: "Weekly applications",
  unit: "applications/week",
  baseline_value: 2,
  recommended_value: 40,
  change: 38,
  relative_change: 19,
  range_used: 0.79,
  effort: "heavy" as const,
  description: "Raise weekly applications from 2 to 40 applications/week (+38 applications/week, 20.0× today)",
};

const blueprint: ReverseBlueprint = {
  target_probability: 0.9,
  baseline_probability: 0.74,
  modeled_probability: 0.891,
  delta_pp: 15.1,
  reachable: true,
  already_satisfied: false,
  headline: "To reach ~90%: raise weekly applications to 40 applications/week. Modeled odds 89%.",
  rationale: "The smallest change among 6 priced options that reaches 90% (within 1 pp).",
  lever_changes: [change],
  actions: [],
  steps: [`${change.description}.`, "Stick with it: these odds assume the change holds in about 72% of futures, so slipping more lowers them."],
  tradeoffs: ["Weekly applications at 40 applications/week is a heavy lift; check it fits your week."],
  follow_through_probability: 0.72,
  max_modeled_probability: 0.9036,
  plateau: {
    lever_id: "weekly_application_rate",
    plateau_probability: 0.9036,
    starts_at_value: 40,
    cause: "follow_through",
    explanation: "Odds level off near 90% from about 40 applications/week.",
  },
  alternatives: [
    {
      id: "lever:weekly_application_rate:14",
      label: "Weekly applications at 14 applications/week",
      lever_changes: [{ ...change, recommended_value: 14, change: 12 }],
      actions: [],
      modeled_probability: 0.8155,
      reaches_target: false,
      effort_score: 6,
      note: "Smaller change, 8 pp short of target.",
    },
  ],
  tolerance_pp: 1,
  method: "reverse_blueprint@1.0.0",
};

const sweepPath: PathStrategy = {
  id: "lever-weekly_application_rate-34",
  label: "34 applications/week",
  odds: 87,
  requirement: "",
  subpaths: [],
  cost: 34,
  fragility: "Low",
  onFrontier: true,
  variants: [],
};

function renderView(props: Partial<Parameters<typeof PathsToGoalView>[0]> = {}) {
  const onSeeFutures = vi.fn();
  render(
    <PathsToGoalView
      market={market}
      view="simple"
      paths={[{ ...sweepPath, blueprint }]}
      loading={false}
      priced
      selectedPathId={null}
      selectedVariantId={null}
      targetOdds={90}
      onSelectPath={() => {}}
      onSelectVariant={() => {}}
      onTargetOddsChange={() => {}}
      onSeeFutures={onSeeFutures}
      selectedSimulation={null}
      onSelectSimulation={() => {}}
      {...props}
    />,
  );
  return { onSeeFutures };
}

it("stops loading when a completed search has no feasible paths", () => {
  renderView({ paths: undefined, message: "No feasible path was found within the current limits.", targetOdds: 70 });
  expect(screen.getByText("No feasible path was found within the current limits.")).toBeInTheDocument();
  expect(screen.queryByText(/Searching for paths/)).not.toBeInTheDocument();
});

it("leads with the recommended path blueprint instead of raw lever rows", () => {
  renderView();
  const card = screen.getByRole("region", { name: blueprint.headline });
  expect(within(card).getByText("Recommended path")).toBeInTheDocument();
  expect(within(card).getByText("Reaches ~90%")).toBeInTheDocument();
  const odds = within(card).getByLabelText("Modeled odds");
  expect(within(odds).getByText("74%")).toBeInTheDocument();
  expect(within(odds).getByText("89%")).toBeInTheDocument();
  expect(within(odds).getByText("+15 pp")).toBeInTheDocument();
  const steps = within(card).getByRole("list", { name: "Steps" });
  expect(within(steps).getByText("2/week")).toBeInTheDocument();
  expect(within(steps).getByText("40/week")).toBeInTheDocument();
  expect(within(steps).getByText("Heavy lift")).toBeInTheDocument();
  expect(within(card).getByText(/heavy lift; check it fits your week/)).toBeInTheDocument();
  expect(within(card).getByRole("note")).toHaveTextContent("Odds plateau near 90%.");
  // The raw sweep row is not the headline answer in the simple view.
  expect(screen.queryByText("34 applications/week")).not.toBeInTheDocument();
});

it("lists deduplicated alternatives in a compact table", () => {
  renderView();
  const table = screen.getByRole("region", { name: "Alternatives" });
  const rows = within(table).getAllByRole("row");
  expect(rows).toHaveLength(2);
  const row = rows[1] as HTMLElement;
  expect(within(row).getByRole("rowheader")).toHaveTextContent("Weekly applications at 14 applications/week");
  expect(within(row).getByText("82%")).toBeInTheDocument();
  expect(within(row).getByText("Smaller change, 8 pp short of target.")).toBeInTheDocument();
});

it("hands the recommended setting to Futures", () => {
  const { onSeeFutures } = renderView();
  fireEvent.click(screen.getByRole("button", { name: "See how this could play out" }));
  expect(onSeeFutures).toHaveBeenCalledWith(expect.objectContaining({ id: "blueprint", cost: 40 }));
});

it("falls back to the ranked list when the API sends no blueprint", () => {
  renderView({ paths: [sweepPath] });
  expect(screen.queryByText("Recommended path")).not.toBeInTheDocument();
  expect(screen.getAllByText("34 applications/week").length).toBeGreaterThan(0);
});
