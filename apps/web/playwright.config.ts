import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: process.env.PHASE2_WEB_URL || "http://127.0.0.1:5174", trace: "on-first-retry" },
  // Mocked E2E cases need token-mode UI and must not reuse a Clerk-enabled dev session.
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5174 --strictPort",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: false,
    env: {
      VITE_AUTH_BYPASS: "true",
      VITE_BACKGROUND_MONITORING: "true",
      VITE_API_BASE_URL:
        process.env.PLAYWRIGHT_API_BASE_URL ||
        process.env.VITE_API_BASE_URL ||
        "http://127.0.0.1:8000",
      VITE_TEST_AUTH_TOKEN: process.env.LIVE_E2E_TOKEN || process.env.VITE_TEST_AUTH_TOKEN || "",
    },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile-chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
