import { expect, test } from "vitest";
import { linkedGoals, resolveAreas, suggestAreas } from "./profileAreas";

const goals = [
  { goal_id: "book", title: "Read 20 books" },
  { goal_id: "run", title: "Run a half marathon" },
];

test("suggested areas come from tracked goals before generic extras", () => {
  const labels = suggestAreas(goals, []);
  expect(labels[0]).toBe("Reading");
  expect(labels).toContain("Fitness");
});

test("a single title match is linked without asking", () => {
  expect(resolveAreas([{ label: "Reading", goal_ids: [] }], goals)).toEqual([
    { label: "Reading", goal_ids: ["book"] },
  ]);
  expect(linkedGoals("Music", goals).ids).toEqual([]);
});
