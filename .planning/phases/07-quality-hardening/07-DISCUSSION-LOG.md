# Phase 7: Quality & Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 07-quality-hardening
**Areas discussed:** E2E test strategy, Observability scope, Runbook library seeding, Prod deployment & APIM

---

## E2E Test Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Real deployed environment | All tests run against real Container Apps in a dedicated E2E environment spun up in CI | ✓ |
| Use existing staging environment | Persistent staging endpoints, no spin-up cost | |
| Hybrid (real for core, stubs for Teams/RBAC) | Only core flows use real infra | |

**User's choice:** Real deployed environment
**Notes:** Aligns with SC-1 mandate: "no test targets localhost or stubs Azure APIs"

---

### E2E Authentication

| Option | Description | Selected |
|--------|-------------|----------|
| Service principal (client credentials) | Dedicated Entra app registration, client_id + secret in GitHub Secrets | ✓ |
| Test user + MSAL storageState | Real user login persisted in playwright/.auth/ | |
| Auth bypass header in E2E env | Skip token validation with a bypass header | |

**User's choice:** Service principal (client credentials)
**Notes:** Avoids MSAL browser redirects in headless Playwright

---

### Test Data Isolation

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated E2E containers in Cosmos DB | incidents-e2e, approvals-e2e with cleanup fixture | ✓ |
| Tagged test data in shared containers | Test run ID prefix, cleanup job after run | |
| Use staging Cosmos DB (ephemeral) | Staging data resets on each deploy | |

**User's choice:** Dedicated E2E containers
**Notes:** Keeps prod and staging containers clean

---

### HITL Teams Approval E2E

| Option | Description | Selected |
|--------|-------------|----------|
| Verify via Graph API + direct webhook | Check Teams channel message via Graph, simulate approval via direct HTTP | ✓ |
| Full bot round-trip in E2E | Send message via Bot Connector API, simulate card action | |
| Skip Teams E2E — manual verification only | it.skip in Phase 7 | |

**User's choice:** Graph API + direct webhook
**Notes:** Most reliable for CI; avoids Teams conversation complexity

---

## Observability Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-instrumentation only | opentelemetry-instrument for Python/Node; App Insights exporter | ✓ |
| Auto + manual agent spans | Manual spans around Foundry API calls | |
| Full custom instrumentation | Spans for every agent handoff, tool call, SSE event | |

**User's choice:** Auto-instrumentation only
**Notes:** Phase 7 is "complete", not "perfect" — manual spans are Phase 8

---

### Observability Dashboard

| Option | Description | Selected |
|--------|-------------|----------|
| Azure Monitor defaults (no custom dashboard) | Built-in Application Map and Live Metrics | |
| Fabric Real-Time dashboard | KQL-based Fabric dashboard | |
| Web UI observability tab | New tab in the Web UI querying Azure Monitor Query API | ✓ |

**User's choice:** Web UI observability tab
**Notes:** Operators see traces inline without leaving the platform

---

## Runbook Library Seeding

| Option | Description | Selected |
|--------|-------------|----------|
| Claude generates from Azure domain knowledge | ~10 runbooks/domain from CLAUDE.md knowledge | ✓ |
| You provide templates, Claude expands | User-provided templates expanded to ~60 runbooks | |
| Minimal seed (3-5 runbooks only) | Minimum to pass E2E tests | |

**User's choice:** Claude generates from Azure domain knowledge
**Notes:** Fastest path; realistic enough for E2E and demo readiness

---

### Seed Script Execution

| Option | Description | Selected |
|--------|-------------|----------|
| CI/CD seed on staging; manual for prod | Runs in CI on staging deploy; prod is a manual one-time step | ✓ |
| Terraform null_resource | Infra and seed together | |
| Manual GitHub Actions workflow | workflow_dispatch against any environment | |

**User's choice:** CI/CD seed on staging; manual for prod
**Notes:** Idempotent; never auto-seeds prod

---

## Prod Deployment & APIM

| Option | Description | Selected |
|--------|-------------|----------|
| Skip APIM — defer to future milestone | api-gateway continues as direct ingress; no production traffic to justify cost | ✓ |
| Add APIM Standard v2 | Rate limiting, JWT validation, developer portal (~$700/month) | |
| APIM Consumption tier (low-cost) | Pay-per-call, no SLA | |

**User's choice:** Skip APIM
**Notes:** No production traffic yet; Phase 6 D-03 said "evaluate with production traffic data"

---

### Prod Apply Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Terraform apply with auto-generated FQDNs | Full module stack; auto-generated Container Apps URLs | ✓ |
| Terraform apply + custom domain + TLS | Branded URL via Front Door | |
| Validate-only (prod already exists) | terraform plan + confirm zero diff | |

**User's choice:** Terraform apply with auto-generated FQDNs
**Notes:** Matches SC-7 exactly; custom domain deferred

---

## Claude's Discretion

- Application Insights connection string injection pattern
- Web UI Observability tab component design and chart library
- Playwright fixture structure for E2E test data setup/teardown
- OWASP checklist items beyond the core items
- Runbook markdown schema/frontmatter format

## Deferred Ideas

- APIM Standard v2 — no production traffic data, defer to future milestone
- Custom domain + TLS — use auto-generated FQDNs for now
- Full bot round-trip E2E — Graph API verification is sufficient for Phase 7
- Manual OpenTelemetry spans — Phase 8 observability improvement
