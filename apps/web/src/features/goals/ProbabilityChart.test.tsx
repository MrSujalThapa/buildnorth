import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { ProbabilityChart } from "./ProbabilityChart";

test("unpriced markets show an empty grid without a probability line", () => {
  render(<ProbabilityChart chartId="goal-1" title="Run a 10K" status="EXPLORATORY" />);
  expect(screen.getByRole("img", { name: /not priced/i })).toBeInTheDocument();
  expect(screen.queryByTestId("probability-line")).not.toBeInTheDocument();
  expect(screen.getByText("Not priced")).toBeInTheDocument();
  expect(screen.getByText("Exploratory")).toBeInTheDocument();
});

test("priced markets render a real series when history is supplied", () => {
  render(
    <ProbabilityChart
      chartId="goal-2"
      title="Run a 10K"
      status="CALIBRATED"
      currentProbability={0.42}
      changePp={-3}
      series={[
        { t: 1, p: 0.4 },
        { t: 2, p: 0.42 },
      ]}
    />,
  );
  expect(screen.getByTestId("probability-line")).toBeInTheDocument();
  expect(screen.getByText("42%")).toBeInTheDocument();
  expect(screen.getByText("-3 pp")).toBeInTheDocument();
});
