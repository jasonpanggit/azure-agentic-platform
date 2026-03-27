/**
 * Auth fixture — provides bearer token and API URLs to E2E tests.
 *
 * Usage in tests:
 *   import { test } from '../fixtures/auth';
 *   test('my test', async ({ apiRequest, bearerToken }) => { ... });
 */
import { test as base, APIRequestContext } from '@playwright/test';

interface AuthFixtures {
  bearerToken: string;
  apiUrl: string;
  baseUrl: string;
  apiRequest: APIRequestContext;
}

export const test = base.extend<AuthFixtures>({
  bearerToken: async ({}, use) => {
    const token = process.env.E2E_BEARER_TOKEN || 'dev-token';
    await use(token);
  },

  apiUrl: async ({}, use) => {
    const url = process.env.E2E_API_URL || 'http://localhost:8000';
    await use(url);
  },

  baseUrl: async ({}, use) => {
    const url = process.env.E2E_BASE_URL || 'http://localhost:3000';
    await use(url);
  },

  apiRequest: async ({ playwright, bearerToken, apiUrl }, use) => {
    const context = await playwright.request.newContext({
      baseURL: apiUrl,
      extraHTTPHeaders: {
        Authorization: `Bearer ${bearerToken}`,
        'Content-Type': 'application/json',
      },
    });
    await use(context);
    await context.dispose();
  },
});

export { expect } from '@playwright/test';
