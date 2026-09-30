import { defineConfig } from "@playwright/test";

/**
 * E2E against the REAL backend (http://localhost:8000). Chromium's fake microphone plays WAVs
 * from e2e/.audio (see e2e/prepare-audio.sh), so recording, upload and recognition are real.
 * Each spec sets its own fake-mic file through launch args.
 */
export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: "http://localhost:3000",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
