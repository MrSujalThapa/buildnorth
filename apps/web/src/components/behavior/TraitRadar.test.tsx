import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TraitEstimate, TraitSeries } from "../../api/client";
import { TraitRadar, pointsChange } from "./TraitRadar";
import { radarSeries } from "./traitRadarModel";

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
const series: TraitSeries[] = [
  { id: "overall", label: "Overall", values: { discipline: 0.72, realism: 0.6, focus: null, consistency: 0.55 } },
  { id: "career", label: "Career", values: { discipline: 0.8, realism: 0.6, focus: 0.5, consistency: 0.7 } },
  { id: "personal", label: "Personal", values: { discipline: 0.6, realism: 0.7, focus: null, consistency: 0.5 } },
];

describe("TraitRadar", () => {
  it("overlays every life area on one radar with no area toggles", () => {
    const { container } = render(<TraitRadar traits={traits} series={series} />);
    expect(container.querySelectorAll(".trait-series")).toHaveLength(3);
    expect(container.querySelectorAll(".trait-shape")).toHaveLength(3);
    expect(screen.queryByRole("group", { name: "Execution area" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Career" })).toBeNull();
    expect(screen.getByRole("img", { name: /3 series: Career, Personal, Overall/ })).toBeInTheDocument();
    expect(container.querySelectorAll(".trait-axis")).toHaveLength(4);
  });

  it("skips an unmeasured axis instead of drawing it as zero", () => {
    const shapes = radarSeries(traits, series);
    const personal = shapes.find((shape) => shape.id === "personal")!;
    expect(personal.points.map((point) => point.traitId)).toEqual(["discipline", "realism", "consistency"]);
    expect(personal.missing).toEqual(["focus"]);
    const { container } = render(<TraitRadar traits={traits} series={series} />);
    expect(container.querySelectorAll("[data-testid='trait-series-personal'] .trait-node")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: /Focus, overall not enough evidence/ }));
    expect(screen.getByText(/Not enough evidence yet/)).toBeInTheDocument();
  });

  it("reads out real per-area values for the focused trait", () => {
    render(<TraitRadar traits={traits} series={series} sourceNote="From demo workspace" />);
    const legend = screen.getByRole("list", { name: "Series" });
    expect(legend).toHaveTextContent("Overall72%");
    expect(legend).toHaveTextContent("Career80%");
    expect(legend).toHaveTextContent("Personal60%");
    expect(screen.getByText(/\+8 pts over 28 days/)).toBeInTheDocument();
    expect(screen.getByText(/Used in forecasts/)).toBeInTheDocument();
    expect(screen.getByText("From demo workspace")).toBeInTheDocument();
    expect(pointsChange(traits[1]!)).toBeNull();
  });
});
