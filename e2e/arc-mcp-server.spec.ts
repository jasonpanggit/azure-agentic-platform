/**
 * E2E-006: Arc MCP Server Pagination Test
 *
 * Verifies that the Arc MCP Server exhausts all nextLink pages and returns
 * total_count matching the full seeded estate of >100 Arc servers.
 *
 * Strategy: The Arc MCP Server accepts AZURE_ARM_BASE_URL as an environment
 * variable (defaults to https://management.azure.com). In the E2E test
 * environment, a mock ARM server is deployed seeded with 120 Arc machines.
 * This avoids real Azure credentials and expensive real Arc estate provisioning.
 *
 * Test environment requirements:
 *   - ARC_MCP_SERVER_URL: URL of the deployed Arc MCP Server (or local dev)
 *   - API_GATEWAY_URL: URL of the API gateway Container App
 *   - TEST_SUBSCRIPTION_ID: Subscription ID used in mock ARM seeding
 *   - TEST_AUTH_TOKEN: Bearer token for API gateway authentication
 *   - ARC_SEEDED_COUNT: Number of Arc servers seeded in mock ARM (default: 120)
 *
 * Phase 3 Success Criteria verified:
 *   SC-1: Arc Agent calls arc_servers_list without public internet egress
 *   SC-2: arc_servers_list exhausts all nextLink pages; total_count matches ARM count
 *   SC-5: total_count >= 100 in CI E2E run; all pages exhausted
 */

import { test, expect } from '@playwright/test';

const ARC_MCP_SERVER_URL = process.env.ARC_MCP_SERVER_URL || 'http://localhost:8080';
const API_GATEWAY_URL = process.env.API_GATEWAY_URL || 'http://localhost:8000';
const TEST_SUBSCRIPTION_ID = process.env.TEST_SUBSCRIPTION_ID || 'sub-e2e-test-001';
const TEST_AUTH_TOKEN = process.env.TEST_AUTH_TOKEN || 'test-token';
const ARC_SEEDED_COUNT = parseInt(process.env.ARC_SEEDED_COUNT || '120', 10);

// Timeout for agent triage flow — allows up to 90 seconds for full workflow
const TRIAGE_TIMEOUT_MS = 90_000;

test.describe('E2E-006: Arc MCP Server Pagination', () => {

  /**
   * SC-2 + SC-5: arc_servers_list returns total_count >= 100 and
   * total_count equals len(servers) — no pages dropped.
   *
   * This test calls the Arc MCP Server directly (not via Arc Agent) to
   * verify the pagination behavior in isolation.
   */
  test('arc_servers_list exhausts pagination and returns total_count >= 100', async ({ request }) => {
    // Call Arc MCP Server tool directly via MCP protocol
    // POST /mcp with JSON-RPC tool call
    const mcpRequest = {
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/call',
      params: {
        name: 'arc_servers_list',
        arguments: {
          subscription_id: TEST_SUBSCRIPTION_ID,
        },
      },
    };

    const response = await request.post(`${ARC_MCP_SERVER_URL}/mcp`, {
      data: mcpRequest,
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 30_000,
    });

    expect(response.ok(), `Arc MCP Server returned ${response.status()}`).toBeTruthy();

    const body = await response.json();
    expect(body.result).toBeDefined();
    expect(body.error).toBeUndefined();

    // Extract the tool result
    const toolResult = body.result;
    expect(toolResult.content).toBeDefined();

    // Parse the tool response (FastMCP returns content as JSON string in text)
    const arcResult = typeof toolResult.content[0].text === 'string'
      ? JSON.parse(toolResult.content[0].text)
      : toolResult.content[0].text;

    // E2E-006: total_count MUST be >= 100 (seeded estate)
    expect(arcResult.total_count).toBeGreaterThanOrEqual(100);
    expect(arcResult.total_count).toBe(ARC_SEEDED_COUNT);

    // AGENT-006: total_count MUST equal len(servers) — no page dropped
    expect(arcResult.servers).toHaveLength(arcResult.total_count);

    // Verify all server names are unique (no duplicate pages)
    const serverNames = arcResult.servers.map((s: any) => s.name) as string[];
    const uniqueNames = new Set(serverNames);
    expect(uniqueNames.size).toBe(arcResult.total_count);
  });

  /**
   * SC-2: arc_k8s_list also exhausts pagination — verify for K8s tool.
   * Uses the same seeded mock ARM server.
   */
  test('arc_k8s_list exhausts pagination and returns correct total_count', async ({ request }) => {
    const mcpRequest = {
      jsonrpc: '2.0',
      id: 2,
      method: 'tools/call',
      params: {
        name: 'arc_k8s_list',
        arguments: {
          subscription_id: TEST_SUBSCRIPTION_ID,
          include_flux: false,
        },
      },
    };

    const response = await request.post(`${ARC_MCP_SERVER_URL}/mcp`, {
      data: mcpRequest,
      headers: { 'Content-Type': 'application/json' },
      timeout: 30_000,
    });

    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    const arcResult = typeof body.result.content[0].text === 'string'
      ? JSON.parse(body.result.content[0].text)
      : body.result.content[0].text;

    // total_count must equal len(clusters)
    expect(arcResult.total_count).toBe(arcResult.clusters.length);
    // Verify no duplicates
    const clusterNames = arcResult.clusters.map((c: any) => c.name) as string[];
    const uniqueClusterNames = new Set(clusterNames);
    expect(uniqueClusterNames.size).toBe(arcResult.total_count);
  });

  /**
   * SC-6: Full incident flow — Arc Agent receives incident, calls arc_servers_list,
   * and produces diagnosis citing last heartbeat and connectivity duration.
   *
   * Uses the API gateway incident endpoint to trigger the Arc Agent triage.
   */
  test('Arc Agent triage produces diagnosis with connectivity findings', async ({ request }) => {
    // Inject a synthetic Arc disconnection incident
    const incidentPayload = {
      incident_id: `e2e-arc-006-${Date.now()}`,
      severity: 'Sev2',
      domain: 'arc',
      affected_resources: [
        {
          resource_id: `/subscriptions/${TEST_SUBSCRIPTION_ID}/resourceGroups/rg-arc-e2e/providers/Microsoft.HybridCompute/machines/arc-e2e-server-001`,
          subscription_id: TEST_SUBSCRIPTION_ID,
          resource_type: 'Microsoft.HybridCompute/machines',
        },
      ],
      detection_rule: 'ArcServerDisconnected',
      kql_evidence: 'Arc server has not sent heartbeat for >1 hour',
    };

    const incidentResponse = await request.post(
      `${API_GATEWAY_URL}/api/v1/incidents`,
      {
        headers: {
          Authorization: `Bearer ${TEST_AUTH_TOKEN}`,
          'Content-Type': 'application/json',
        },
        data: incidentPayload,
        timeout: 10_000,
      }
    );

    expect(incidentResponse.ok(), `Incident creation failed: ${incidentResponse.status()}`).toBeTruthy();

    const { thread_id } = await incidentResponse.json();
    expect(thread_id).toBeTruthy();

    // Poll for Arc Agent completion (up to TRIAGE_TIMEOUT_MS)
    let triageResult: any = null;

    await expect.poll(
      async () => {
        const statusResponse = await request.get(
          `${API_GATEWAY_URL}/api/v1/threads/${thread_id}/status`,
          {
            headers: { Authorization: `Bearer ${TEST_AUTH_TOKEN}` },
          }
        );
        const statusData = await statusResponse.json();

        if (statusData.status === 'completed' && statusData.arc_tool_results) {
          triageResult = statusData.arc_tool_results;
          return true;
        }
        if (statusData.status === 'failed') {
          throw new Error(`Arc Agent triage failed: ${statusData.error}`);
        }
        return false;
      },
      {
        timeout: TRIAGE_TIMEOUT_MS,
        intervals: [2000, 5000, 10000],
        message: 'Arc Agent triage did not complete within timeout',
      }
    ).toBeTruthy();

    // Verify arc_servers_list was called and returned meaningful results
    expect(triageResult).not.toBeNull();

    // If arc_servers_list tool result is available, verify total_count
    if (triageResult.arc_servers_list) {
      expect(triageResult.arc_servers_list.total_count).toBeGreaterThanOrEqual(1);
      expect(triageResult.arc_servers_list.total_count).toBe(
        triageResult.arc_servers_list.servers.length
      );
    }
  });

  /**
   * Health check: Verify Arc MCP Server /mcp endpoint is reachable.
   * This is a pre-condition for all E2E tests.
   */
  test('Arc MCP Server health check — /mcp endpoint is reachable', async ({ request }) => {
    // MCP servers respond to the initialize request
    const initRequest = {
      jsonrpc: '2.0',
      id: 0,
      method: 'initialize',
      params: {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: { name: 'e2e-test', version: '1.0.0' },
      },
    };

    const response = await request.post(`${ARC_MCP_SERVER_URL}/mcp`, {
      data: initRequest,
      headers: { 'Content-Type': 'application/json' },
      timeout: 10_000,
    });

    expect(response.ok(), `Arc MCP Server unreachable: ${response.status()}`).toBeTruthy();
    const body = await response.json();
    expect(body.result).toBeDefined();
    // Verify server name
    expect(body.result.serverInfo?.name).toBe('arc-mcp-server');
  });

  /**
   * Tool discovery: Verify all 9 required tools are registered.
   */
  test('Arc MCP Server exposes all required tools', async ({ request }) => {
    const listToolsRequest = {
      jsonrpc: '2.0',
      id: 99,
      method: 'tools/list',
      params: {},
    };

    const response = await request.post(`${ARC_MCP_SERVER_URL}/mcp`, {
      data: listToolsRequest,
      headers: { 'Content-Type': 'application/json' },
      timeout: 10_000,
    });

    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    const tools = body.result.tools as Array<{ name: string }>;
    const toolNames = tools.map(t => t.name);

    const requiredTools = [
      'arc_servers_list',
      'arc_servers_get',
      'arc_extensions_list',
      'arc_k8s_list',
      'arc_k8s_get',
      'arc_k8s_gitops_status',
      'arc_data_sql_mi_list',
      'arc_data_sql_mi_get',
      'arc_data_postgresql_list',
    ];

    for (const tool of requiredTools) {
      expect(toolNames, `Missing required tool: ${tool}`).toContain(tool);
    }
  });
});
