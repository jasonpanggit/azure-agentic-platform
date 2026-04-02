# Quick Task Summary: Validate Azure Monitor Is Receiving Logs

**ID:** 260402-gcx
**Status:** COMPLETE
**Branch:** `quick/260402-gcx-validate-appinsights`
**Commits:** 3

---

## What Was Done

### Task 1: KQL Validation Queries
**File:** `scripts/validate-appinsights/kql-queries.md`

Created 5 KQL queries for the Application Insights Logs blade:

1. **Heartbeat** — Which `cloud_RoleName` values have sent ANY telemetry in the last 24h
2. **Per-container signal breakdown** — traces/requests/dependencies/exceptions per role
3. **Silent containers** — Left-anti join against the 12 expected names to find missing ones
4. **Recent errors** — Exceptions grouped by container in the last 6h
5. **OTel SDK init confirmation** — Startup log messages from each container

### Task 2: CLI Validation Script
**File:** `scripts/validate-appinsights/validate.sh` (executable)

Bash script that:
- Accepts `--app` (resource ID) or auto-detects from `rg-aap-prod`
- Runs heartbeat KQL via `az monitor app-insights query`
- Parses JSON, extracts `cloud_RoleName` values
- Compares against the 12 expected containers
- Prints a formatted pass/fail table with last seen time and count
- Shows unexpected `cloud_RoleName` values if any appear
- Exits 0 if all 12 present, exits 1 if any missing
- Prints per-container remediation hints (check env var, check replicas, check logs, rebuild image)

### Task 3: Validation Report Template
**File:** `scripts/validate-appinsights/VALIDATION-REPORT.md`

Operator-fillable template with:
- Results table listing all 12 containers (Container App name + cloud_RoleName)
- Summary section (sending/silent/errors counts)
- Remediation actions table with common fix steps
- Paste areas for KQL Query 5 output and validate.sh output
- Sign-off checklist

---

## Verification Checklist

- [x] `scripts/validate-appinsights/kql-queries.md` contains 5 KQL queries
- [x] `scripts/validate-appinsights/validate.sh` is executable, uses `az monitor app-insights query`
- [x] `scripts/validate-appinsights/VALIDATION-REPORT.md` template lists all 12 containers
- [x] No code changes to existing source files (validation-only task)
- [x] 3 atomic commits (one per task)

---

## Notes

- The `cloud_RoleName` values are assumptions based on `service_name` in code. Query 1 reveals the actual values in App Insights.
- Containers scaled to 0 replicas won't send telemetry until they receive traffic. This is expected, not a bug.
- The Arc MCP Server OTel wiring was just added in quick task 260402-fvo — it won't have telemetry until the image is rebuilt and pushed to ACR.
- The validate.sh script requires bash 4+ (uses associative arrays with `declare -A`). macOS users may need to use `/usr/local/bin/bash` from Homebrew.
