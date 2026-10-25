import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ODDS_EXPLORER_RANGES } from "./marketRanges";
import OddsExplorer from "./OddsExplorer";

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

test("empty published history does not invent a series", () => {
  render(<OddsExplorer history={[]} ranges={ODDS_EXPLORER_RANGES} />);
  expect(screen.getByRole("status")).toHaveTextContent(/no published odds/i);
  expect(screen.queryByLabelText("Chart range")).not.toBeInTheDocument();
});

test("range controls stay available for sparse history", () => {
  render(
    <OddsExplorer
      history={[{ timestamp: Date.parse("2026-10-18T00:00:00Z"), value: 33.3 }]}
      ranges={ODDS_EXPLORER_RANGES}
    />,
  );
  expect(screen.getByLabelText("Chart range")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "1D" }));
  expect(screen.getByRole("button", { name: "1D" })).toHaveClass("selected");
});

test("scenario branches still plot when published history is empty", () => {
  render(
    <OddsExplorer
      history={[]}
      ranges={ODDS_EXPLORER_RANGES}
      lineOnly
      percentAxis
      showHistoryInLegend={false}
      branches={[
        { id: "original", label: "Original", color: "#d4a82d", start: 40, end: 40 },
        { id: "what-if", label: "What if", color: "#2fb36d", start: 40, end: 55, note: "+15.0 pts" },
      ]}
    />,
  );
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Chart range")).not.toBeInTheDocument();
  expect(screen.getByTestId("series-original")).toHaveTextContent("40%");
  expect(screen.getByTestId("series-what-if")).toHaveTextContent("+15.0 pts");
});
