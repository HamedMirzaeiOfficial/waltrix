import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.E2E_PORT ?? 4823);
const db = process.env.WALTRIX_E2E_DATABASE_URL ?? "postgresql://waltrix@127.0.0.1:4822/waltrix_e2e";
const python = process.env.PYTHON ?? "../../.venv/bin/python";

/**
 * Critical user journeys against the real stack: the API process serves the
 * built dashboard (single origin) and talks to a disposable PostgreSQL database.
 * Run `npm run build -w @waltrix/web` first.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: { baseURL: `http://127.0.0.1:${port}`, trace: "retain-on-failure" },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1360, height: 860 } },
      testIgnore: /mobile\.spec\.ts/,
    },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: {
    command:
      `${python} -c "from waltrix_core.migrate import downgrade, upgrade; downgrade('${db}', 'base'); upgrade('${db}')" && ` +
      `${python} -m uvicorn waltrix_api.asgi:app --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/readyz`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      WALTRIX_DATABASE_URL: db,
      WALTRIX_WEB_DIST: "dist",
      WALTRIX_LOG_JSON: "false",
      WALTRIX_LOG_LEVEL: "WARNING",
      WALTRIX_LOGIN_RATE_LIMIT_PER_MINUTE: "100",
    },
  },
});
