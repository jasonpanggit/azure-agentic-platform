import { defineConfig, devices } from '@playwright/test';

/**
 * E2E Playwright config for Phase 7 tests against real deployed Container Apps.
 *
 * Required environment variables:
 *   E2E_BASE_URL    — Web UI Container App FQDN (e.g., https://ca-web-ui-staging.azurecontainerapps.io)
 *   E2E_API_URL     — API gateway Container App FQDN
 *   E2E_CLIENT_ID   — Service principal client ID for auth
 *   E2E_CLIENT_SECRET — Service principal client secret
 *   E2E_TENANT_ID   — Entra tenant ID
 */
export default defineConfig({
  testDir: '.',
  fullyParallel: false,  // E2E tests share state; run sequentially
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,  // Sequential for state isolation
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'html',
  timeout: 120_000,  // 2 min per test (agent responses can be slow)
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    extraHTTPHeaders: {
      // Bearer token injected by global setup
      ...(process.env.E2E_BEARER_TOKEN
        ? { Authorization: `Bearer ${process.env.E2E_BEARER_TOKEN}` }
        : {}),
    },
  },
  globalSetup: './global-setup.ts',
  globalTeardown: './global-teardown.ts',
  projects: [
    {
      name: 'e2e-chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
