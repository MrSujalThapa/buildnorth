import { useEffect, useMemo, useState, type ReactNode } from "react";
import { applyTheme, persistTheme, readStoredTheme, readSystemTheme, resolveInitialTheme, toggleTheme, type Theme } from "./theme";
import { ThemeContext, type ThemeContextValue } from "./useTheme";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => (typeof document === "undefined" ? "light" : resolveInitialTheme()));

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (readStoredTheme()) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setThemeState(readSystemTheme());
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      setTheme: (next) => {
        persistTheme(next);
        setThemeState(next);
      },
      toggle: () => {
        setThemeState((current) => {
          const next = toggleTheme(current);
          persistTheme(next);
          return next;
        });
      },
    }),
    [theme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
