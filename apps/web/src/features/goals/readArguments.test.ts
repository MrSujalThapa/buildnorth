import { describe, expect, it } from "vitest";
import { additionalRequiredArguments } from "./readArguments";

describe("additionalRequiredArguments", () => {
  it("asks for schema-required scope fields and leaves the resource id to the selection", () => {
    expect(additionalRequiredArguments({
      properties: {
        spreadsheet_id: { type: "string" },
        range: { type: "string", description: "A1 notation" },
        max_results: { type: "integer" },
      },
      required: ["spreadsheet_id", "range", "max_results"],
    })).toEqual(["range"]);
  });

  it("reads a parameters wrapper", () => {
    expect(additionalRequiredArguments({
      parameters: { required: ["ranges"], properties: { ranges: { type: "array" } } },
    })).toEqual(["ranges"]);
  });
});
