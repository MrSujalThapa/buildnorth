import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: unknown }) => <div>{children as never}</div>,
  };
});

import WealthsimpleAreaChart, { scenarioRegionPad } from "./WealthsimpleAreaChart";

test("scenario region occupies a substantial share of the x-domain", () => {
  const span = 20 * 24 * 60 * 60 * 1000;
  const pad = scenarioRegionPad(span);
  expect(pad / (span + pad)).toBeCloseTo(0.45, 5);
});

test("terminal branches render without inventing a historical series", () => {
  render(
    <WealthsimpleAreaChart
      data={[]}
      lineOnly
      percentAxis
      showHistoryInLegend={false}
      branches={[
        { id: "original", label: "Original", color: "#d4a82d", start: 71.9, end: 71.9, dashed: true },
        { id: "what-if", label: "What if: skip exam", color: "#e5534b", start: 71.9, end: 65, note: "−6.9 pts" },
      ]}
    />,
  );
  expect(screen.getByTestId("series-original")).toHaveTextContent("71.9%");
  expect(screen.getByTestId("series-what-if")).toHaveTextContent("65%");
  expect(screen.getByTestId("series-what-if")).toHaveTextContent("−6.9 pts");
  expect(screen.queryByTestId("series-__history")).not.toBeInTheDocument();
});

test("legend click highlights a future series", () => {
  const onBranchSelect = vi.fn();
  render(
    <WealthsimpleAreaChart
      data={[]}
      lineOnly
      percentAxis
      highlightedBranchId="offer"
      onBranchSelect={onBranchSelect}
      branches={[
        { id: "offer", label: "Offer", color: "#5b8def", points: [{ timestamp: 0, value: 76 }, { timestamp: 1, value: 76 }] },
        { id: "no-offer", label: "No offer", color: "#e5534b", points: [{ timestamp: 0, value: 24 }, { timestamp: 1, value: 24 }] },
      ]}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /No offer/i }));
  expect(onBranchSelect).toHaveBeenCalledWith("no-offer");
  expect(screen.getByTestId("series-offer")).toHaveClass("is-active");
});
