import { expect, test, vi } from "vitest";
import { shareLink } from "./share";

test("falls back to copying the public URL", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText }, share: undefined });
  await expect(shareLink({ url: "https://playitout.example/m/1", title: "Goal" })).resolves.toBe("copied");
  expect(writeText).toHaveBeenCalledWith("https://playitout.example/m/1");
});