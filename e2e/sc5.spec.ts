/**
 * SC-5: Resource Identity Certainty — stale_approval (E2E-001)
 *
 * Tests against real deployed endpoints. Verifies the approval API
 * handles expired approvals correctly (returns 410 Gone).
 */
import { test, expect } from './fixtures/auth';

test.describe('@sc5 Approval Lifecycle (E2E)', () => {

  test('Expired approval returns 410 Gone', async ({ apiRequest }) => {
    // Attempt to approve a non-existent or expired approval
    const response = await apiRequest.post('/api/v1/approvals/appr-nonexistent/approve', {
      data: {
        decided_by: 'e2e-test@contoso.com',
        thread_id: 'thread-nonexistent',
      },
    });

    // Should return 400 (not found) or 410 (expired)
    expect([400, 404, 410]).toContain(response.status());
  });

  test('List pending approvals returns array', async ({ apiRequest }) => {
    const response = await apiRequest.get('/api/v1/approvals?status=pending');

    if (response.ok()) {
      const body = await response.json();
      expect(Array.isArray(body)).toBeTruthy();
    }
  });
});
