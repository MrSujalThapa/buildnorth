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

test("groups measured parameters by life area instead of mixing every axis", () => {
  render(<ParameterRadar profile={profile} />);
  expect(screen.getByRole("tab", { name: /Career/ })).toBeVisible();
  expect(screen.getByRole("tab", { name: /Fitness/ })).toBeVisible();
  expect(screen.getAllByText("Applications / week").length).toBeGreaterThan(0);
  expect(screen.queryByText("Running / week")).toBeNull();
  fireEvent.click(screen.getByRole("tab", { name: /Fitness/ }));
  expect(screen.getAllByText("Running / week").length).toBeGreaterThan(0);
  expect(screen.queryByText("Applications / week")).toBeNull();
});
