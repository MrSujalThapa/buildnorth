import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { ParameterProfile } from "../../api/client";
import { ParameterRadar } from "./ParameterRadar";

const profile: ParameterProfile = {
  version: "measured_parameters@2.0.0",
  as_of: "2026-10-24T00:00:00Z",
  evidence_count: 4,
  synthetic: false,
  parameters: [
    {
      id: "weekly_applications",
      name: "Applications / week",
      metric: "applications_per_week",
      unit: "applications/week",
      window_days: 56,
      aggregation: "latest_period",
      normalization: "scale_max",
      raw_value: 8,
      value: 0.4,
      observation_count: 2,
      source_types: ["manual"],
      evidence_ids: ["e1"],
      last_observed_at: "2026-10-20T12:00:00Z",
      status: "measured",
    },
    {
      id: "weekly_running_km",
      name: "Running / week",
      metric: "weekly_distance_km",
      unit: "km/week",
      window_days: 56,
      aggregation: "latest_period",
      normalization: "scale_max",
      raw_value: 24,
      value: 0.4,
      observation_count: 2,
      source_types: ["manual"],
      evidence_ids: ["e2"],
      status: "measured",
    },
    {
      id: "reading_minutes",
      name: "Reading time",
      metric: "reading_minutes",
      unit: "minutes/30 days",
      window_days: 30,
      aggregation: "sum_increments",
      normalization: "scale_max",
      raw_value: null,
      value: null,
      observation_count: 0,
      source_types: [],
      evidence_ids: [],
      status: "insufficient",
    },
  ],
};

test("draws every measured life area at once and leaves unmeasured areas empty", () => {
  render(<ParameterRadar profile={profile} />);
  expect(screen.queryByRole("tab")).toBeNull();
  expect(screen.getByTestId("life-series-weekly_applications")).toBeInTheDocument();
  expect(screen.getByTestId("life-series-weekly_running_km")).toBeInTheDocument();
  expect(screen.queryByTestId("life-series-reading_minutes")).toBeNull();
  expect(screen.getByText("Not measured")).toBeVisible();
});

test("tooltip shows measurement, unit, source and observation date", () => {
  render(<ParameterRadar profile={profile} />);
  fireEvent.mouseEnter(screen.getByTestId("life-series-weekly_applications"));
  const tooltip = screen.getByRole("status");
  expect(tooltip).toHaveTextContent("8 applications/week");
  expect(tooltip).toHaveTextContent("Source: manual");
  expect(tooltip).toHaveTextContent("Last observed");
});
