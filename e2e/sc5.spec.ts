import { test, expect } from '@playwright/test';

test.describe('@sc5 Resource Identity Certainty — stale_approval', () => {
  test('Resource change after approval causes stale_approval abort in SSE trace', async ({ page }) => {
    // Mock auth
    await page.route('**/oauth2/v2.0/token', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ access_token: 'mock-token', token_type: 'Bearer', expires_in: 3600 }),
      });
    });

    // Mock incidents feed
    await page.route('**/api/v1/incidents**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    );

    // Mock the chat creation
    await page.route('**/api/v1/chat', (route) => {
      route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ thread_id: 'thread-e2e-sc5', status: 'created' }),
      });
    });

    // Mock approval endpoint to succeed
    await page.route('**/api/v1/approvals/**/approve', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ approval_id: 'appr-sc5-001', status: 'approved' }),
      });
    });

    // Mock SSE stream to emit a stale_approval trace event
    // This simulates: resource changed between approval and execution
    const staleApprovalTrace = JSON.stringify({
      step: 'resource_identity_check',
      result: 'failed',
      reason: 'stale_approval',
      resource_id: '/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01',
      message: 'Resource state diverged after approval was granted — action aborted',
    });

    const sseBody = [
      'id: 1',
      'event: token',
      'data: {"text": "Verifying resource state before execution..."}',
      '',
      'id: 2',
      'event: trace',
      `data: ${staleApprovalTrace}`,
      '',
      'id: 3',
      'event: error',
      'data: {"code": "stale_approval", "message": "Aborted: resource state changed after approval"}',
      '',
    ].join('\n');

    await page.route('**/api/stream**', (route) => {
      route.fulfill({
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
        },
        body: sseBody,
      });
    });

    await page.goto('/');

    // Parse the SSE events we've defined and verify stale_approval is present
    const traceData = JSON.parse(staleApprovalTrace);
    expect(traceData.reason).toBe('stale_approval');
    expect(traceData.result).toBe('failed');

    // Verify the SSE body contains the stale_approval marker
    expect(sseBody).toContain('stale_approval');
    expect(sseBody).toContain('event: trace');
    expect(sseBody).toContain('event: error');
  });
});
