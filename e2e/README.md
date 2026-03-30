# E2E Tests

End-to-end tests for the Azure Agentic Platform services, built with [Playwright](https://playwright.dev/).

## Running Tests

```bash
# Install dependencies
npm install

# Run all tests (headless)
npx playwright test

# Run a specific spec file
npx playwright test arc-mcp-server.spec.ts

# Run with headed browser (useful for debugging)
npx playwright test --headed

# Show HTML report after a run
npx playwright show-report
```

## Test Files

| File | Suite | Description |
|------|-------|-------------|
| `arc-mcp-server.spec.ts` | E2E-006 | Arc MCP Server pagination — verifies `arc_servers_list` exhausts all `nextLink` pages against a mock ARM server seeded with 120 Arc machines |
| `e2e-audit-export.spec.ts` | — | Audit log export flow |
| `e2e-hitl-approval.spec.ts` | — | Human-in-the-loop approval flow via Teams Adaptive Cards |
| `e2e-incident-flow.spec.ts` | — | Full incident triage flow through the API gateway |
| `e2e-rbac.spec.ts` | — | RBAC enforcement on API gateway endpoints |
| `e2e-sse-reconnect.spec.ts` | — | SSE streaming reconnect behaviour |
| `e2e-teams-roundtrip.spec.ts` | — | Teams bot round-trip message flow |
| `sc1.spec.ts` | SC-1 | Arc Agent calls `arc_servers_list` without public internet egress |
| `sc2.spec.ts` | SC-2 | `arc_servers_list` exhausts all `nextLink` pages; `total_count` matches ARM count |
| `sc5.spec.ts` | SC-5 | `total_count >= 100` in CI E2E run; all pages exhausted |
| `sc6.spec.ts` | SC-6 | Additional success-criteria coverage |

## Environment Variables

Variables are read at runtime. Tests fall back to local-dev defaults where shown; variables with no default **must** be set for that suite to pass.

### Global (all tests)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `E2E_BASE_URL` | No | `http://localhost:3000` | Base URL of the Next.js web UI Container App |
| `E2E_API_URL` | No | `http://localhost:8000` | Base URL of the API gateway Container App (used by audit-export, RBAC specs) |
| `E2E_BEARER_TOKEN` | No* | `dev-token` | Bearer token injected as an `Authorization` header on all requests; auto-populated by `global-setup.ts` via MSAL when `E2E_CLIENT_ID` / `E2E_CLIENT_SECRET` are provided |
| `CI` | No | — | Standard CI flag; disables `forbidOnly`, enables retries (×2), switches to GitHub Actions reporter |

### Authentication / Entra ID (global-setup.ts)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `E2E_CLIENT_ID` | No* | — | Service principal client ID for acquiring a bearer token via MSAL client-credentials flow; if absent, `E2E_BEARER_TOKEN` falls back to `dev-token` |
| `E2E_CLIENT_SECRET` | No* | — | Client secret paired with `E2E_CLIENT_ID`; treat as a secret — never commit |
| `E2E_TENANT_ID` | No* | — | Entra tenant ID; required when `E2E_CLIENT_ID` is set and for Teams round-trip tests |
| `E2E_API_AUDIENCE` | No | `''` | OAuth2 audience (`scope`) used when acquiring the bearer token |

### Cosmos DB cleanup (global-setup / global-teardown)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `E2E_COSMOS_ENDPOINT` | No | — | Cosmos DB account endpoint for seeding / teardown; if absent, DB setup is skipped |
| `E2E_COSMOS_DB` | No | `aap` | Cosmos DB database name used during seed and teardown |

### Arc MCP Server (arc-mcp-server.spec.ts, sc1/sc2/sc5/sc6)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARC_MCP_SERVER_URL` | Yes (non-local) | `http://localhost:8080` | URL of the Arc MCP Server Container App |
| `API_GATEWAY_URL` | Yes (non-local) | `http://localhost:8000` | URL of the API gateway Container App |
| `TEST_SUBSCRIPTION_ID` | No | `sub-e2e-test-001` | Subscription ID used when seeding the mock ARM server |
| `TEST_AUTH_TOKEN` | No | `test-token` | Bearer token for API gateway authentication in the Arc MCP suite |
| `ARC_SEEDED_COUNT` | No | `120` | Number of Arc servers seeded in the mock ARM server; tests assert `total_count >= ARC_SEEDED_COUNT` |

### Teams integration (e2e-teams-roundtrip.spec.ts, e2e-hitl-approval.spec.ts)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `E2E_TEAMS_BOT_URL` | Yes | — | URL of the deployed Teams bot Container App |
| `E2E_BOT_APP_ID` | Yes | `''` | Azure AD app registration ID for the Teams bot |
| `E2E_BOT_APP_PASSWORD` | Yes | `''` | Client secret for `E2E_BOT_APP_ID`; treat as a secret — never commit |
| `E2E_TEAMS_TEAM_ID` | Yes | `''` | Teams team ID used in HITL approval tests |
| `E2E_TEAMS_CHANNEL_ID` | Yes | `''` | Teams channel ID used in HITL approval tests |
| `E2E_GRAPH_CLIENT_ID` | Yes | `''` | Client ID for Microsoft Graph API calls in HITL tests |
| `E2E_GRAPH_CLIENT_SECRET` | Yes | `''` | Client secret for `E2E_GRAPH_CLIENT_ID`; treat as a secret — never commit |

## Local Development

Copy and populate the example env file before running locally:

```bash
cp .env.example .env.local
# Edit .env.local with your values, then:
export $(cat .env.local | xargs) && npx playwright test
```

For Arc MCP pagination tests specifically, start the Arc MCP Server locally (defaults to `:8080`) and a mock ARM server seeded with ≥120 Arc machines before running `arc-mcp-server.spec.ts`.

## CI Configuration

All secret variables (`E2E_CLIENT_SECRET`, `E2E_BOT_APP_PASSWORD`, `E2E_GRAPH_CLIENT_SECRET`) must be stored as **GitHub Actions secrets** and injected via the `env:` block in the workflow — never hardcoded or logged.
