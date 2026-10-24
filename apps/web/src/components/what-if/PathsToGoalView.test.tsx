import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import type { Market } from "../../adapters/templateTypes";
import PathsToGoalView from "./PathsToGoalView";

it("stops loading when a completed search has no feasible paths", () => {
  render(
    <PathsToGoalView
      market={{ id: "reading", title: "Read 20 books" } as Market}
      view="simple"
      paths={undefined}
      loading={false}
      priced
      message="No feasible path was found within the current limits."
      selectedPathId={null}
      selectedVariantId={null}
      targetOdds={70}
      onSelectPath={() => {}}
      onSelectVariant={() => {}}
      onTargetOddsChange={() => {}}
      onSeeFutures={() => {}}
      selectedSimulation={null}
      onSelectSimulation={() => {}}
    />,
  );
  expect(screen.getByText("No feasible path was found within the current limits.")).toBeInTheDocument();
  expect(screen.queryByText(/Searching backend paths/)).not.toBeInTheDocument();
});
