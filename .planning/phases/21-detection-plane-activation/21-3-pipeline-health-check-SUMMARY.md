# Summary: Plan 21-3 — Pipeline Health Monitoring

**Status:** COMPLETE
**Date:** 2026-04-03
**Branch:** gsd/phase-21-detection-plane-activation
**Commits:** 3739a64, 6ae9c28

---

## What Was Done

### Task 21-3-01: Detection pipeline health check script

Created `scripts/ops/21-3-detection-health-check.sh` — a standalone operational health monitor for the PROD-004 detection pipeline.

**7 checks implemented:**

| # | Check | Auth Required |
|---|-------|---------------|
| 1 | Fabric capacity `fcaapprod` is Active | No |
| 2 | Fabric workspace `aap-prod` exists | No (Fabric token) |
| 3 | Event Hub namespace `ehns-aap-prod` is Active | No |
| 4 | Event Hub `eh-alerts-prod` is configured (retention > 0) | No |
| 5 | API gateway `/health` returns HTTP 200 | No |
| 6 | Recent `det-` prefixed incidents exist | Yes (E2E_CLIENT_ID) |
| 7 | Container App `ca-api-gateway-prod` is Running | No |

**PROD-004 status output:**
- `HEALTHY` — 0 failures → exit 0
- `DEGRADED` — some failures but API gateway + Fabric capacity up → exit 1
- `UNHEALTHY` — API gateway down or Fabric capacity not Active → exit 1

### Task 21-3-02: Operator documentation update

Appended `## Ongoing Health Monitoring` section to `docs/ops/detection-plane-activation.md` with:
- Usage examples (basic + authenticated)
- Health check coverage table (7 checks, auth requirements)
- Recommended schedule (manual after Terraform apply, CI post-deploy, daily cron at 06:00 UTC)

---

## Acceptance Criteria — All Passing

- [x] `scripts/ops/21-3-detection-health-check.sh` exists and is executable
- [x] `bash -n` syntax check exits 0
- [x] `#!/usr/bin/env bash` shebang on line 1
- [x] `set -euo pipefail` present
- [x] PROD-004 referenced 5 times (header + summary + status output)
- [x] `fcaapprod` referenced (Fabric capacity check)
- [x] `ehns-aap-prod` referenced (Event Hub namespace check)
- [x] `eh-alerts-prod` referenced (Event Hub configuration check)
- [x] `det-` prefix check present
- [x] HEALTHY/DEGRADED/UNHEALTHY status output
- [x] PASS_COUNT / FAIL_COUNT tracking
- [x] `/health` endpoint check
- [x] `docs/ops/detection-plane-activation.md` has "Ongoing Health Monitoring" section
- [x] Documentation references `21-3-detection-health-check`
- [x] Documentation has "Recommended Schedule"

---

## Files Modified

| File | Change |
|------|--------|
| `scripts/ops/21-3-detection-health-check.sh` | Created (243 lines, executable) |
| `docs/ops/detection-plane-activation.md` | Appended 34 lines (Ongoing Health Monitoring section) |
