import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TraitEstimate, TraitSeries } from "../../api/client";
import { TraitRadar, pointsChange } from "./TraitRadar";

function trait(id: string, value: number | null, previous: number | null = null): TraitEstimate {
  return {
    id,
    name: id[0]!.toUpperCase() + id.slice(1),
    description: `${id} description.`,
    measurement: `${id} measurement.`,
    evidence: [],
    custom: false,
    forecast_use: id === "discipline" ? "execution_probability" : "exploratory",
    value,
    interval: value == null ? null : [Math.max(0, value - 0.1), Math.min(1, value + 0.1)],
    n_eff: value == null ? 0 : 10,
    observations: value == null ? 1 : 12,
    confidence: value == null ? "insufficient" : "moderate",
    previous_value: previous,
    sources: [],
    window_days: 28,
  };
}

const traits = [trait("discipline", 0.72, 0.64), trait("realism", 0.6), trait("focus", null), trait("consistency", 0.55)];

describe("TraitRadar", () => {
  it("defaults to overall and selects one measured area without averaging contexts", () => {
    const series: TraitSeries[] = [
      { id: "career", label: "Career", values: { discipline: 0.8, realism: 0.6, focus: 0.5, consistency: 0.7 } },
      { id: "personal", label: "Personal", values: { discipline: 0.6, realism: 0.7, focus: 0.4, consistency: 0.5 } },
    ];
    const { container } = render(<TraitRadar traits={traits} series={series} />);
    expect(container.querySelectorAll(".trait-shape")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Overall" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Career" }));
    expect(container.querySelectorAll(".trait-shape")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Career" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("img", { name: /Career execution radar/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Personal" }));
    expect(container.querySelectorAll(".trait-shape")).toHaveLength(1);
    expect(screen.getByRole("img", { name: /Personal execution radar/ })).toBeInTheDocument();
    expect(container.querySelectorAll(".trait-axis")).toHaveLength(4);
  });

  it("does not close a shape through an unmeasured axis or invent a value", () => {
    const series: TraitSeries[] = [
      { id: "overall", label: "Overall", values: { discipline: 0.72, realism: 0.6, focus: null, consistency: 0.55 } },
    ];
    const { container } = render(<TraitRadar traits={traits} series={series} />);
    expect(container.querySelector(".trait-shape")).toBeNull();
    expect(container.querySelectorAll(".trait-node")).toHaveLength(3);
    expect(screen.queryByRole("group", { name: "Execution area" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Focus, not enough evidence/ }));
    expect(screen.getByText(/Not enough evidence yet/)).toBeInTheDocument();
  });

  it("explains the forecast link and the change in points", () => {
    render(<TraitRadar traits={traits} series={[{ id: "overall", label: "Overall", values: { discipline: 0.72, realism: 0.6, focus: null, consistency: 0.55 } }]} />);
    expect(screen.getByText(/\+8 pts over 28 days/)).toBeInTheDocument();
    expect(screen.getByText(/Used in forecasts/)).toBeInTheDocument();
    expect(pointsChange(traits[1]!)).toBeNull();
  });
});
