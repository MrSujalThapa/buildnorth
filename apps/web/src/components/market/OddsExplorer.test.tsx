import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ODDS_EXPLORER_RANGES } from "./marketRanges";
import OddsExplorer from "./OddsExplorer";

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
