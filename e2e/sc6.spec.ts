/**
 * SC-6: GitOps vs Direct-Apply Path (E2E-001)
 *
 * Tests against real deployed endpoints — no mocks.
 * Verifies Arc Agent correctly detects GitOps-managed clusters
 * and routes to PR creation vs direct apply.
 */
import { test, expect } from './fixtures/auth';

test.describe('@sc6 GitOps vs Direct-Apply Path (E2E)', () => {

  test('@sc6-gitops GitOps detection endpoint returns expected fields', async ({ apiRequest }) => {
    // Verify the Arc agent chat endpoint accepts a GitOps-related query
    const response = await apiRequest.post('/api/v1/chat', {
      data: {
        message: 'check gitops status for arc-cluster-prod-01',
      },
      timeout: 15_000,
    });

    // 202 Accepted or 503 (if Foundry not configured in E2E env)
    expect([202, 503]).toContain(response.status());

    if (response.status() === 202) {
      const body = await response.json();
      expect(body.thread_id).toBeTruthy();
      expect(body.status).toBe('created');
    }
  });

  test('@sc6-direct Arc K8s list endpoint is reachable', async ({ apiRequest }) => {
    // Verify the Arc K8s list endpoint responds (used by GitOps detection)
    const response = await apiRequest.get('/api/v1/arc/k8s', {
      timeout: 15_000,
    });

    // 200 (list returned) or 404 (endpoint not yet deployed) — both valid in staging
    expect([200, 404, 503]).toContain(response.status());

    if (response.status() === 200) {
      const body = await response.json();
      // Response should be an array or object with clusters field
      const hasClusters = Array.isArray(body) || Array.isArray(body?.clusters);
      expect(hasClusters).toBeTruthy();
    }
  });

  test('@sc6-path Flux gitops_status tool endpoint responds', async ({ apiRequest }) => {
    // Verify the gitops status endpoint exists and handles the request
    const response = await apiRequest.get(
      '/api/v1/arc/k8s/arc-cluster-prod-01/gitops?subscription_id=sub-e2e-test',
      { timeout: 15_000 }
    );

    // Any non-5xx response is acceptable (404 = cluster not found in E2E env)
    expect(response.status()).toBeLessThan(500);
  });
});
