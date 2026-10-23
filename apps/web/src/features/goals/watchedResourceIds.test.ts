import { expect, it } from "vitest";
import type { SourceRecipeRecord } from "../../api/client";
import { watchedResourceIds } from "./EvidenceSourceWorkspace";

it("watches every approved resource once even when a recipe has multiple read actions", () => {
  const recipe: SourceRecipeRecord = {
    goal_id: "goal",
    plugin_id: "notion",
    label: "Two book reports",
    approved: true,
    steps: [
      { capability_id: "read", resource_uri: "composio://notion/page-a", arguments: {} },
      { capability_id: "metadata", resource_uri: "composio://notion/page-a", arguments: {} },
      { capability_id: "read", resource_uri: "composio://notion/page-b", arguments: {} },
      { capability_id: "read", resource_uri: "composio://github/other", arguments: {} },
    ],
  };
  expect(watchedResourceIds(recipe)).toEqual(["page-a", "page-b"]);
});
