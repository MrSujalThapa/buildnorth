import { expect, test } from "vitest";
import { applyTheme, persistTheme, readStoredTheme, THEME_STORAGE_KEY, toggleTheme } from "./theme";

test("toggleTheme flips light and dark", () => {
  expect(toggleTheme("light")).toBe("dark");
  expect(toggleTheme("dark")).toBe("light");
});

test("persistTheme stores the explicit preference", () => {
  persistTheme("dark");
  expect(readStoredTheme()).toBe("dark");
  expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
});

test("applyTheme sets data-theme and color-scheme", () => {
  applyTheme("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(document.documentElement.style.colorScheme).toBe("dark");
});
