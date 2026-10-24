import { describe, expect, it } from "vitest";
import { currentCollectionGoalLabel } from "./CollectionDetailRoute";

describe("collection member current forecast", () => {
  const historical = {
    goal_id: "reading",
    title: "Read 20 books",
    color: "#fff",
    points: [{ timestamp: "2026-10-19T00:00:00Z", value: 15.1 }],
  };

  it("retains history without presenting a withheld receipt as current", () => {
    expect(currentCollectionGoalLabel({ ...historical, withheld: true })).toBe("Withheld");
    expect(currentCollectionGoalLabel({ ...historical, withheld: false })).toBe("15.1%");
  });
});
