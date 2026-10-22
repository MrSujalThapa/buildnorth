import { expect, it } from "vitest";
import { scenarioErrorMessage } from "./WhatIfPage";

it("surfaces the API failure detail instead of failing silently", () => {
  const error = new Error("API request failed (Agent output failed validation after bounded retries)");
  expect(scenarioErrorMessage(error)).toBe(
    "Couldn't run this scenario: Agent output failed validation after bounded retries",
  );
  expect(scenarioErrorMessage(null)).toBeNull();
});
