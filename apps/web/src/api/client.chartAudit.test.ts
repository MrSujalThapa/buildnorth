import { afterEach, expect, it, vi } from "vitest";
import { api } from "./client";

afterEach(() => vi.unstubAllGlobals());

it("treats a missing optional evidence continuation as absent, preserving receipt status", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 404 }));
  vi.stubGlobal("fetch", fetcher);
  await expect(api.goalEvidenceContinuation("legacy-goal")).resolves.toBeNull();
  expect(fetcher).toHaveBeenCalledOnce();
});

it("keeps a real continuation service failure visible", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
  await expect(api.goalEvidenceContinuation("goal-1")).rejects.toThrow("503");
});
