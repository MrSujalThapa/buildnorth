import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { futuresFromDistribution } from "../../adapters/compareViewModel";
import PossibleFuturesView from "./PossibleFuturesView";

const scenarios = futuresFromDistribution({
  priced: true,
  message: null,
  outcomes: [
    { label: "Target reached", probability: 0.82, median: 2214.59, p10: 1972.03, p90: 2421.21, downside: false },
    { label: "Downside outcome", probability: 0.18, median: 2850, p10: 2700, p90: 3000, downside: true },
  ],
} as never);

function renderView(view: "simple" | "deep") {
  return render(
    <PossibleFuturesView
      view={view}
      decision="Race in 8 weeks"
      onDecisionChange={() => {}}
      onRun={() => {}}
      selectedClusterId={null}
      onSelectCluster={() => {}}
      scenarios={scenarios}
      outcomeScale={{ unit: "seconds", target: 2700, direction: "at_most" }}
    />,
  );
}

describe("PossibleFuturesView", () => {
  it("shows scenario results in the goal's unit, never as inflated percentages", () => {
    const { container } = renderView("deep");
    expect(screen.getByLabelText("Simulated result range per scenario")).toHaveTextContent("32:52–40:21");
    expect(container.textContent).not.toMatch(/\d{4,}%/);
  });

  it("reports scenario shares as percentages of simulated futures", () => {
    renderView("simple");
    expect(screen.getByLabelText("Possible future scenarios")).toHaveTextContent("82%");
  });

  it("withholds unweighted structural scenarios from the result view", () => {
    render(
      <PossibleFuturesView
        view="simple"
        decision="Read two books weekly"
        onDecisionChange={() => {}}
        onRun={() => {}}
        priced={false}
        message="Possible futures are structurally valid but unpriced."
        selectedClusterId={null}
        onSelectCluster={() => {}}
        scenarios={[{ id: "upside", label: "Strong upside path", probability: null, tone: "positive", outcome: null }]}
        outcomeScale={{ unit: "books", target: 20, direction: "at_least" }}
      />,
    );
    expect(screen.getByText("Futures unavailable")).toBeVisible();
    expect(screen.getByText("Possible futures are structurally valid but unpriced.")).toBeVisible();
    expect(screen.queryByLabelText("Possible future scenarios")).not.toBeInTheDocument();
  });

  it("labels event futures without fractional event counts", () => {
    render(
      <PossibleFuturesView view="deep" decision="Apply for roles"
        onDecisionChange={() => {}} onRun={() => {}}
        selectedClusterId={null} onSelectCluster={() => {}}
        scenarios={scenarios}
        outcomeScale={{ unit: "event", target: 1, direction: "at_least" }} />,
    );
    expect(screen.getByText(/offer\/no offer categories/)).toBeVisible();
    expect(screen.queryByText(/1972\.03 event/)).not.toBeInTheDocument();
  });
});
