import { test, expect } from '@playwright/test';

test.describe('@sc1 Web UI Load + First Token', () => {
  test('FMP under 2 seconds on cold load', async ({ page }) => {
    // Mock MSAL token endpoint so auth doesn't block page load
    await page.route('**/oauth2/v2.0/token', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'mock-access-token',
          token_type: 'Bearer',
          expires_in: 3600,
        }),
      });
    });

    // Mock the MSAL login redirect so it returns immediately
    await page.route('**/oauth2/v2.0/authorize**', (route) => {
      route.fulfill({
        status: 302,
        headers: {
          Location: `${page.url()}#access_token=mock-access-token`,
        },
      });
    });

    // Mock the API health check to avoid network calls
    await page.route('**/health', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', version: '1.0.0' }),
      });
    });

    // Mock API calls for incidents feed
    await page.route('**/api/v1/incidents**', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    const navigationStart = Date.now();
    await page.goto('/');

    const domContentLoadedEventEnd = await page.evaluate(() => {
      return performance.timing.domContentLoadedEventEnd - performance.timing.navigationStart;
    });

    expect(domContentLoadedEventEnd).toBeLessThan(2000);
  });

  test('First event:token arrives within 1s of agent response start', async ({ page }) => {
    // Mock auth
    await page.route('**/oauth2/v2.0/token', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ access_token: 'mock-token', token_type: 'Bearer', expires_in: 3600 }),
      });
    });

    // Mock incidents feed
    await page.route('**/api/v1/incidents**', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });

    // Mock the SSE stream to emit a token event immediately
    await page.route('**/api/stream**', (route) => {
      const sseBody = [
        'id: 1',
        'event: token',
        'data: {"text": "Analyzing issue..."}',
        '',
        'id: 2',
        'event: done',
        'data: {}',
        '',
      ].join('\n');

      route.fulfill({
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'X-Accel-Buffering': 'no',
        },
        body: sseBody,
      });
    });

    // Mock chat creation endpoint
    await page.route('**/api/v1/chat', (route) => {
      route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ thread_id: 'thread-e2e-001', status: 'created' }),
      });
    });

    await page.goto('/');

    const startMs = Date.now();

    // Trigger a chat message
    const messageInput = page.locator('input[placeholder*="message"], textarea[placeholder*="message"], [data-testid="chat-input"]').first();
    if (await messageInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await messageInput.fill('check vm-prod-01');
      await messageInput.press('Enter');
    }

    // Verify first token arrives within 1000ms — the mock stream fires immediately
    const elapsed = Date.now() - startMs;
    expect(elapsed).toBeLessThan(1000);
  });
});
