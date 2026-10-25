import { fireEvent, render, screen } from "@testing-library/react";
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
  expect(screen.getByText("Confirm what this represents")).toBeTruthy();
  expect(screen.getByText("Preview of detected data")).toBeTruthy();
  expect(screen.getByText("Unverified")).toBeTruthy();
  expect(screen.queryByText("Example")).toBeNull();
  expect(screen.queryByText("PROVIDER_GET_RECORD")).toBeNull();
  expect(screen.queryByText(/google sheets|strava|gmail/i)).toBeNull();
});

test("a longer preview stays compact until the reader asks for the rest", () => {
  const records = [0, 1, 2, 3, 4, 5].map((index) => ({
    kind: "measurement" as const,
    title: `2026-10-${20 + index}`,
    timestamp: `2026-10-${20 + index}`,
    metric: "Pace",
    numeric_value: index + 1,
    unit: "min/km",
  }));
  render(
    <SourcePreviewView
      preview={{ ...fixture, records, measurements: [{ id: "pace", label: "Pace", detail: "6 recorded values · min/km", unit: "min/km", ambiguous: false }] }}
      selectedMeasurementId="pace"
      trackingLabel="Pace"
      onSelectMeasurement={() => undefined}
      onTrackingLabel={() => undefined}
    />,
  );
  expect(screen.queryByText("2026-10-25")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Show 2 more" }));
  expect(screen.getByText("2026-10-25")).toBeTruthy();
});

test("an unstructured source does not offer a fake progress measurement", () => {
  render(
    <SourcePreviewView
      preview={{
        ...fixture,
        tool_name: "ACME_GET_VALUES",
        measurements: [],
        notice: "No measurable progress detected. You can monitor this source for changes or choose which fields matter.",
        columns: ["Task", "Note"],
        records: [
          { kind: "record", title: "Read", cells: ["Read", "Chapter 1"] },
          { kind: "record", title: "Rest", cells: ["Rest", ""] },
        ],
      }}
      selectedMeasurementId={null}
      trackingLabel=""
      onSelectMeasurement={() => undefined}
      onTrackingLabel={() => undefined}
    />,
  );
  expect(screen.getByText("No measurable progress detected. You can monitor this source for changes or choose which fields matter.")).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "Task" })).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "Note" })).toBeTruthy();
  expect(screen.getByText("Chapter 1")).toBeTruthy();
  expect(screen.queryByText("Records")).toBeNull();
  expect(screen.queryByText("ACME_GET_VALUES")).toBeNull();
});

test("a long document preview stays truncated until it is expanded", () => {
  const text = "A".repeat(180);
  render(
    <SourcePreviewView
      preview={{
        ...fixture,
        measurements: [],
        notice: "No measurable progress detected. You can monitor this source for changes or choose which fields matter.",
        records: [{ kind: "document", title: `${"A".repeat(90)}…`, text }],
      }}
      selectedMeasurementId={null}
      trackingLabel=""
      onSelectMeasurement={() => undefined}
      onTrackingLabel={() => undefined}
    />,
  );
  expect(screen.queryByText(text)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Expand" }));
  expect(screen.getByText(text)).toBeTruthy();
});

test("resource headings follow the records that were returned", () => {
  expect(sourceNoun(["application/vnd.google-apps.spreadsheet"])).toBe("spreadsheet");
  expect(sourceNoun(["page", "page"])).toBe("document");
  expect(sourceNoun(["private", "page"])).toBe("document");
  expect(sourceNoun(["private", "public"])).toBe("source");
});
