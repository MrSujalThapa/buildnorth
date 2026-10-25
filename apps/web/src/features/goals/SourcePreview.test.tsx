import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { SourcePreview } from "../../api/client";
import { SourcePreviewView, sourceNoun } from "./SourcePreview";

const fixture: SourcePreview = {
  resource_title: "Field notes",
  resource_type: "application/custom-record",
  tool_name: "PROVIDER_GET_RECORD",
  arguments: { range: "A1:B2" },
  fields: [],
  validation_status: "unverified",
  promotes_to_verified_outcome: false,
  measurements: [
    { id: "pace", label: "Pace", detail: "1 recorded value · min/km", unit: "min/km", ambiguous: false },
  ],
  records: [
    {
      kind: "activity",
      title: "Morning session",
      timestamp: "2026-10-20",
      metric: "Pace",
      numeric_value: 5.2,
      unit: "min/km",
      metrics: [{ label: "Pace", value: 5.2, unit: "min/km" }],
    },
    {
      kind: "message",
      title: "Session update",
      actor: "Ada Lovelace",
      timestamp: "2026-10-21",
      text: "Finished the session.",
    },
    {
      kind: "document",
      title: "Field note",
      text: "A note captured from the connected account.",
    },
    {
      kind: "measurement",
      title: "2026-10-22",
      timestamp: "2026-10-22",
      metric: "Pace",
      numeric_value: 5.1,
      unit: "min/km",
    },
  ],
};

test("an unknown provider renders every record shape without its tool name", () => {
  render(
    <SourcePreviewView
      preview={fixture}
      selectedMeasurementId="pace"
      trackingLabel="Pace"
      onSelectMeasurement={() => undefined}
      onTrackingLabel={() => undefined}
    />,
  );
  expect(screen.getByText("Morning session")).toBeTruthy();
  expect(screen.getByText("Ada Lovelace")).toBeTruthy();
  expect(screen.getByText("Field note")).toBeTruthy();
  expect(screen.getByText("5.1 min/km")).toBeTruthy();
  expect(screen.getByText("Preview of detected data")).toBeTruthy();
  expect(screen.queryByText("Example")).toBeNull();
  expect(screen.queryByText("PROVIDER_GET_RECORD")).toBeNull();
  expect(screen.queryByText(/google sheets|strava|gmail/i)).toBeNull();
});

test("resource headings follow the records that were returned", () => {
  expect(sourceNoun(["application/vnd.google-apps.spreadsheet"])).toBe("spreadsheet");
  expect(sourceNoun(["page", "page"])).toBe("document");
  expect(sourceNoun(["private", "page"])).toBe("document");
  expect(sourceNoun(["private", "public"])).toBe("source");
});
