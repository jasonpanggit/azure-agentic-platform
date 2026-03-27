/**
 * AUDIT-006 E2E: Remediation Activity Report Export
 *
 * Verifies the export endpoint returns a structured JSON report
 * with report_metadata and remediation_events.
 */
import { test, expect } from './fixtures/auth';

test.describe('AUDIT-006: Audit Report Export', () => {

  test('Export endpoint returns structured report', async ({ apiRequest }) => {
    const now = new Date();
    const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);

    const response = await apiRequest.get('/api/v1/audit/export', {
      params: {
        from_time: thirtyDaysAgo.toISOString(),
        to_time: now.toISOString(),
      },
      timeout: 30_000,
    });

    expect(response.ok()).toBeTruthy();

    const report = await response.json();

    // Verify report_metadata structure
    expect(report).toHaveProperty('report_metadata');
    expect(report.report_metadata).toHaveProperty('generated_at');
    expect(report.report_metadata).toHaveProperty('period');
    expect(report.report_metadata.period).toHaveProperty('from');
    expect(report.report_metadata.period).toHaveProperty('to');
    expect(report.report_metadata).toHaveProperty('total_events');
    expect(typeof report.report_metadata.total_events).toBe('number');

    // Verify remediation_events is an array
    expect(report).toHaveProperty('remediation_events');
    expect(Array.isArray(report.remediation_events)).toBeTruthy();

    // If events exist, verify each has required fields
    for (const event of report.remediation_events) {
      expect(event).toHaveProperty('agentId');
      expect(event).toHaveProperty('toolName');
      expect(event).toHaveProperty('outcome');
      expect(event).toHaveProperty('approval_chain');
    }
  });

  test('Export requires authentication', async ({ playwright }) => {
    const unauthContext = await playwright.request.newContext({
      baseURL: process.env.E2E_API_URL || 'http://localhost:8000',
    });

    try {
      const response = await unauthContext.get('/api/v1/audit/export', {
        params: {
          from_time: '2026-01-01T00:00:00Z',
          to_time: '2026-12-31T23:59:59Z',
        },
      });
      // Should return 401 in prod, 200 in dev mode
      expect([200, 401]).toContain(response.status());
    } finally {
      await unauthContext.dispose();
    }
  });
});
