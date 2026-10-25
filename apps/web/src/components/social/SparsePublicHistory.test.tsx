import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import MarketSparkline from "../market/MarketSparkline";
import SparsePublicHistory from "./SparsePublicHistory";
import { sparseGeometry } from "./sparseGeometry";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const day = 24 * 60 * 60 * 1000;
const start = Date.parse("2026-10-01T00:00:00Z");

test("one observation is a single dot at the latest edge with a level guide", () => {
  const points = sparseGeometry([{ timestamp: start, value: 42 }]);
  expect(points).toHaveLength(1);
  expect(points[0]!.x).toBeGreaterThan(90);
  const { container } = render(<SparsePublicHistory history={[{ timestamp: start, value: 42 }]} compact />);
  expect(container.querySelectorAll(".sparse-chart-dot")).toHaveLength(1);
  expect(container.querySelector(".sparse-chart-guide")).not.toBeNull();
  expect(container.querySelector(".sparse-chart-line")).toBeNull();
  expect(screen.getByRole("img")).toHaveAccessibleName(/42% published Oct 1, 2026/);
});

test("two observations draw a step segment with dots and higher odds plot higher", () => {
  const history = [
    { timestamp: start, value: 30 },
    { timestamp: start + 3 * day, value: 45 },
  ];
  const [first, last] = sparseGeometry(history);
  expect(first!.x).toBeLessThan(last!.x);
  expect(last!.y).toBeLessThan(first!.y);
  const { container } = render(<SparsePublicHistory history={history} compact />);
  expect(container.querySelectorAll(".sparse-chart-dot")).toHaveLength(2);
  expect(container.querySelector(".sparse-chart-line")?.getAttribute("d")).toMatch(/^M .* H .* V /);
  expect(screen.getByTestId("sparse-chart-plot")).toHaveClass("trend-positive");
});

test("sparkline never falls back to a percent tile for sparse history", () => {
  const { container } = render(<MarketSparkline history={[{ timestamp: start, value: 61 }]} />);
  expect(container.querySelector(".market-sparkline.is-sparse svg")).not.toBeNull();
  expect(container.textContent).not.toContain("61%");
});

test("sparkline shows no chart rather than inventing history", () => {
  render(<MarketSparkline history={[]} />);
  expect(screen.getByRole("img", { name: "No published history" })).toBeInTheDocument();
});
