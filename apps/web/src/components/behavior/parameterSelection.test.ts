import { describe, expect, it } from "vitest";
import type { TraitOption } from "../../api/client";
import { customDraftError, customParameterId, moveRow, rowsFromSelection, selectionPayload } from "./parameterSelection";

const option = (id: string, name: string, custom = false): TraitOption => ({
  id,
  name,
  description: `${name} description`,
  measurement: "",
  evidence: [],
  custom,
  forecast_use: "exploratory",
});

const options = [option("discipline", "Discipline"), option("focus", "Focus"), option("recovery", "Recovery"), option("custom:sleep", "Sleep", true)];

describe("parameter selection", () => {
  it("matches the server slug for custom ids", () => {
    expect(customParameterId("  Sleep Regularity! ")).toBe("custom:sleep_regularity");
    expect(customParameterId("!!")).toBe("custom:trait");
  });

  it("keeps saved order and drops unknown ids", () => {
    const rows = rowsFromSelection(["focus", "missing", "discipline"], options);
    expect(rows.map((row) => row.id)).toEqual(["focus", "discipline"]);
    expect(moveRow(rows, 1, 0).map((row) => row.id)).toEqual(["discipline", "focus"]);
    expect(moveRow(rows, 0, -1)).toBe(rows);
  });

  it("requires a definition and rejects duplicates for custom parameters", () => {
    const rows = rowsFromSelection(["discipline", "custom:sleep"], options);
    expect(customDraftError("Mood", "", rows, options)).toMatch(/Describe/);
    expect(customDraftError("Sleep", "Hours slept", rows, options)).toMatch(/already/);
    expect(customDraftError("Focus", "Deep work share", rows, options)).toMatch(/already/);
    expect(customDraftError("Mood", "Daily self-rated mood", rows, options)).toBeNull();
  });

  it("sends order plus custom definitions", () => {
    const rows = rowsFromSelection(["custom:sleep", "discipline", "focus"], options);
    expect(selectionPayload(rows)).toEqual({
      parameter_ids: ["custom:sleep", "discipline", "focus"],
      custom_parameters: [{ name: "Sleep", description: "Sleep description" }],
    });
  });
});
