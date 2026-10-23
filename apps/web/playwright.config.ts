import { defineConfig, devices } from "@playwright/test";

// End-to-end checks against a running web app (M8-05): `make up`, or a Cloud Run candidate in
// deploy.yml. Nothing here starts servers.
export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 30_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    // E2E_VIDEO=on records each test (the README demo GIF is made from one).
    video: process.env.E2E_VIDEO === "on" ? "on" : "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
