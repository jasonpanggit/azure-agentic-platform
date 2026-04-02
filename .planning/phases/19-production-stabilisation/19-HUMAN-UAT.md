---
status: partial
phase: 19-production-stabilisation
source: [19-VERIFICATION.md]
started: 2026-04-02T14:00:00.000Z
updated: 2026-04-02T14:00:00.000Z
---

## Current Test

[awaiting operator execution]

## Tests

### 1. Azure MCP Server — internal-only ingress active in prod
expected: `terraform apply` completes with zero diff; `ca-azure-mcp-prod` no longer reachable from internet; `--dangerously-disable-http-incoming-auth` no longer in running container CMD
result: [pending]

### 2. Entra authentication live on API gateway
expected: Staging validation script (`scripts/auth-validation/validate-staging-auth.sh`) exits 0; prod `terraform apply` completes; unauthenticated request to `/api/v1/incidents` returns HTTP 401
result: [pending]

### 3. MCP tool groups registered in Foundry
expected: `terraform apply` registers `azure-mcp-connection` and `arc-mcp-connection`; `scripts/ops/19-3-register-mcp-connections.sh` exits 0; Network/Security/Arc/SRE agents no longer return "tool group was not found"
result: [pending]

### 4. Runbook search 500 fixed
expected: `bash scripts/ops/19-4-seed-runbooks.sh` exits 0; `GET /api/v1/runbooks/search?q=cpu+high` returns HTTP 200 with ≥1 result; validate.py 12 domain queries all pass ≥ 0.75 similarity
result: [pending]

### 5. Teams proactive alerting delivering Adaptive Cards
expected: Bot installed in Teams channel via `scripts/ops/19-5-package-manifest.sh`; `TEAMS_CHANNEL_ID` set on `ca-teams-bot-prod`; `scripts/ops/19-5-test-teams-alerting.sh` exits 0; Adaptive Card appears in channel within 120 seconds of Sev1 incident creation
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
