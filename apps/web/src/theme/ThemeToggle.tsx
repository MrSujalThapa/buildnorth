import { useTheme } from "./useTheme";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";

  return (
    <button type="button" className="theme-toggle" onClick={toggle} aria-label={`Switch to ${next} theme`} aria-pressed={theme === "dark"}>
      <span className="theme-toggle-glyph" aria-hidden="true">
        {theme === "dark" ? (
          <svg viewBox="0 0 24 24" width="16" height="16">
            <circle cx="12" cy="12" r="4" fill="currentColor" />
            <path
              d="M12 3v1.6M12 19.4V21M4.9 4.9l1.1 1.1M18 18l1.1 1.1M3 12h1.6M19.4 12H21M4.9 19.1 6 18M18 6l1.1-1.1"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="square"
            />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" width="16" height="16">
            <path d="M15.2 13.2A6.2 6.2 0 0 1 10.8 4a6.4 6.4 0 1 0 8.4 8.4 6.2 6.2 0 0 1-4 0.8Z" fill="currentColor" />
          </svg>
        )}
      </span>
    </button>
  );
}
