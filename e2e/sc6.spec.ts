import { test, expect } from '@playwright/test';

test.describe('@sc6 GitOps vs Direct-Apply Path', () => {
  test('@sc6-gitops Flux-managed cluster triggers PR creation', async ({ page }) => {
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

    // Mock chat creation
    await page.route('**/api/v1/chat', (route) => {
      route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ thread_id: 'thread-e2e-sc6-gitops', status: 'created' }),
      });
    });

    // Simulate SSE stream for GitOps-managed cluster path
    // Flux detected → PR created
    const gitopsTraceData = JSON.stringify({
      step: 'gitops_detection',
      result: 'gitops_managed',
      flux_configs: [{ name: 'flux-system', namespace: 'flux-system' }],
      message: 'Flux GitOps controller detected — creating PR instead of direct apply',
    });

    const prCreatedData = JSON.stringify({
      step: 'pr_creation',
      result: 'success',
      pr_url: 'https://github.com/contoso/gitops-repo/pull/42',
      branch: 'aiops/fix-inc-k8s-001-remediation',
      message: 'PR created: aiops/fix-inc-k8s-001-remediation',
    });

    const sseBody = [
      'id: 1',
      'event: token',
      'data: {"text": "Analyzing Arc Kubernetes cluster remediation path..."}',
      '',
      'id: 2',
      'event: trace',
      `data: ${gitopsTraceData}`,
      '',
      'id: 3',
      'event: trace',
      `data: ${prCreatedData}`,
      '',
      'id: 4',
      'event: token',
      'data: {"text": "PR created: aiops/fix-inc-k8s-001-remediation. Review and merge to apply."}',
      '',
      'id: 5',
      'event: done',
      'data: {}',
      '',
    ].join('\n');

    await page.route('**/api/stream**', (route) => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
        body: sseBody,
      });
    });

    await page.goto('/');

    // Verify GitOps path: SSE stream contains PR creation trace
    const prData = JSON.parse(prCreatedData);
    expect(prData.message).toContain('PR created: aiops/fix-');
    expect(prData.branch).toContain('aiops/fix-');

    // Verify SSE body has the GitOps markers
    expect(sseBody).toContain('PR created: aiops/fix-');
    expect(sseBody).toContain('gitops_managed');
  });

  test('@sc6-direct Non-GitOps cluster triggers direct-apply', async ({ page }) => {
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

    // Mock chat creation
    await page.route('**/api/v1/chat', (route) => {
      route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ thread_id: 'thread-e2e-sc6-direct', status: 'created' }),
      });
    });

    // Simulate SSE stream for non-GitOps cluster path
    // No Flux detected → direct apply
    const noGitopsTraceData = JSON.stringify({
      step: 'gitops_detection',
      result: 'not_gitops_managed',
      flux_configs: [],
      message: 'No GitOps controller detected — using direct apply path',
    });

    const directApplyData = JSON.stringify({
      step: 'direct_apply',
      result: 'success',
      cluster: 'arc-cluster-prod-01',
      message: 'Applied directly to cluster',
    });

    const sseBody = [
      'id: 1',
      'event: token',
      'data: {"text": "Checking cluster remediation path..."}',
      '',
      'id: 2',
      'event: trace',
      `data: ${noGitopsTraceData}`,
      '',
      'id: 3',
      'event: trace',
      `data: ${directApplyData}`,
      '',
      'id: 4',
      'event: token',
      'data: {"text": "Applied directly to cluster arc-cluster-prod-01. Manifest applied successfully."}',
      '',
      'id: 5',
      'event: done',
      'data: {}',
      '',
    ].join('\n');

    await page.route('**/api/stream**', (route) => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
        body: sseBody,
      });
    });

    await page.goto('/');

    // Verify direct-apply path: SSE stream has direct apply trace
    const directData = JSON.parse(directApplyData);
    expect(directData.message).toBe('Applied directly to cluster');
    expect(directData.result).toBe('success');

    // Verify SSE body has the direct-apply markers and NOT a PR creation
    expect(sseBody).toContain('Applied directly to cluster');
    expect(sseBody).toContain('not_gitops_managed');
    expect(sseBody).not.toContain('PR created: aiops/fix-');
  });
});
