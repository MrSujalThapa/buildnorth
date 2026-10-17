import { render, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { CrystalField } from "./CrystalField";

afterEach(() => {
  vi.restoreAllMocks();
});

function stubMatchMedia(options: { reducedMotion?: boolean; coarse?: boolean }) {
  vi.stubGlobal("matchMedia", (query: string) => {
    const matches = query.includes("prefers-reduced-motion")
      ? Boolean(options.reducedMotion)
      : query.includes("pointer: coarse")
        ? Boolean(options.coarse)
        : false;
    return {
      matches,
      media: query,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent() { return false; },
    };
  });
}

test("mounts a decorative canvas for fine pointers without reduced motion", async () => {
  stubMatchMedia({});
  const { container } = render(<CrystalField />);
  await waitFor(() => {
    expect(container.querySelector("canvas.crystal-field")).not.toBeNull();
  });
  expect(container.querySelector("canvas.crystal-field")).toHaveAttribute("aria-hidden", "true");
});

test("does not mount the canvas when reduced motion is requested", () => {
  stubMatchMedia({ reducedMotion: true });
  const { container } = render(<CrystalField />);
  expect(container.querySelector("canvas.crystal-field")).toBeNull();
});

test("does not mount the canvas for coarse pointers", () => {
  stubMatchMedia({ coarse: true });
  const { container } = render(<CrystalField />);
  expect(container.querySelector("canvas.crystal-field")).toBeNull();
});
