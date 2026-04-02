# Quick Task: Validate Azure Monitor Is Receiving Logs

**ID:** 260402-gcx
**Created:** 2026-04-02
**Type:** Validation / Diagnostic
**Scope:** All 12 agent containers → Application Insights telemetry

---

## Context

Quick task 260402-fvo confirmed all 12 containers have OTel wiring in code. This task validates that telemetry is *actually arriving* in Application Insights. The Arc MCP Server was the last gap (just fixed) and may not have telemetry yet depending on when the container was rebuilt.

### Container Names (prod)

| # | Container App | OTel Service Name / Role |
|---|---|---|
| 1 | ca-orchestrator-prod | aiops-orchestrator-agent |
| 2 | ca-compute-prod | aiops-compute-agent |
| 3 | ca-network-prod | aiops-network-agent |
| 4 | ca-storage-prod | aiops-storage-agent |
| 5 | ca-security-prod | aiops-security-agent |
| 6 | ca-arc-prod | aiops-arc-agent |
| 7 | ca-sre-prod | aiops-sre-agent |
| 8 | ca-patch-prod | aiops-patch-agent |
| 9 | ca-eol-prod | aiops-eol-agent |
| 10 | ca-api-gateway-prod | api-gateway |
| 11 | ca-teams-bot-prod | teams-bot |
| 12 | ca-arc-mcp-server-prod | arc-mcp-server |

### Key Insight: `cloud_RoleName` vs `AppRoleName`

- Python agents using `configure_azure_monitor()` emit telemetry with `cloud_RoleName` set to the `service.name` OTEL resource attribute (the string passed to `setup_telemetry()`)
- The existing observability route queries `AppRoleName` (an Application Insights auto-mapped field from `cloud_RoleName`)
- We need to determine the **actual** `cloud_RoleName` values appearing in App Insights, not assumed ones

---

## Tasks

### Task 1: Create KQL Validation Queries

**File:** `scripts/validate-appinsights/kql-queries.md`

Write a set of KQL queries an operator can paste into the Application Insights Logs blade:

1. **Heartbeat query** — Which `cloud_RoleName` values have sent ANY telemetry in the last 24h?
   ```kql
   union traces, requests, dependencies, exceptions, customMetrics
   | where timestamp > ago(24h)
   | summarize LastSeen=max(timestamp), TelemetryCount=count() by cloud_RoleName
   | order by cloud_RoleName asc
   ```

2. **Per-container signal breakdown** — For each role, what telemetry types are present?
   ```kql
   union
     (traces | project cloud_RoleName, TelemetryType="traces", timestamp),
     (requests | project cloud_RoleName, TelemetryType="requests", timestamp),
     (dependencies | project cloud_RoleName, TelemetryType="dependencies", timestamp),
     (exceptions | project cloud_RoleName, TelemetryType="exceptions", timestamp)
   | where timestamp > ago(24h)
   | summarize Count=count(), LastSeen=max(timestamp) by cloud_RoleName, TelemetryType
   | order by cloud_RoleName asc, TelemetryType asc
   ```

3. **Silent containers** — Which of the 12 expected containers have NOT sent telemetry?
   ```kql
   let expected = dynamic(["aiops-orchestrator-agent","aiops-compute-agent","aiops-network-agent","aiops-storage-agent","aiops-security-agent","aiops-arc-agent","aiops-sre-agent","aiops-patch-agent","aiops-eol-agent","api-gateway","teams-bot","arc-mcp-server"]);
   let active = union traces, requests, dependencies, exceptions
   | where timestamp > ago(24h)
   | distinct cloud_RoleName;
   print Expected=expected
   | mv-expand Expected to typeof(string)
   | join kind=leftanti active on $left.Expected == $right.cloud_RoleName
   | project SilentContainer=Expected
   ```

4. **Recent errors per container** — Any exceptions in the last 6h?
   ```kql
   exceptions
   | where timestamp > ago(6h)
   | summarize ErrorCount=count(), LastError=max(timestamp), Sample=take_any(outerMessage) by cloud_RoleName
   | order by ErrorCount desc
   ```

5. **OTel SDK init confirmation** — Look for the startup log line from each container:
   ```kql
   traces
   | where timestamp > ago(24h)
   | where message has "Azure Monitor OpenTelemetry configured" or message has "OTel disabled"
   | project timestamp, cloud_RoleName, message
   | order by timestamp desc
   ```

**Acceptance:** File exists with 5 numbered KQL queries, each with title and expected output description.

---

### Task 2: Create CLI Validation Script

**File:** `scripts/validate-appinsights/validate.sh`

A bash script that uses `az monitor app-insights query` to programmatically run the heartbeat query and produce a pass/fail report. Requires:
- `az` CLI authenticated
- App Insights resource name or `--app` ID

Script logic:
1. Accept `--app` (App Insights resource ID) or auto-detect from `az monitor app-insights component show -g rg-aap-prod`
2. Run the heartbeat KQL query (query 1 from Task 1)
3. Parse JSON output, extract `cloud_RoleName` values
4. Compare against the 12 expected container names
5. Print a table:
   ```
   Container                    Status    Last Seen           Count
   ─────────────────────────────────────────────────────────────────
   aiops-orchestrator-agent     PASS      2026-04-02T10:15Z   1,247
   aiops-compute-agent          PASS      2026-04-02T10:14Z     892
   arc-mcp-server               FAIL      (no telemetry)          0
   ```
6. Exit 0 if all 12 present, exit 1 if any missing
7. Print remediation hints for missing containers:
   - "Container not sending telemetry. Check: (1) APPLICATIONINSIGHTS_CONNECTION_STRING env var set on Container App, (2) container image includes OTel SDK, (3) container is running (not crashed/scaled to 0)"

**Acceptance:** Script is executable, uses `az monitor app-insights query`, produces human-readable table, exits 0/1.

---

### Task 3: Create Validation Report Template

**File:** `scripts/validate-appinsights/VALIDATION-REPORT.md`

A template the operator fills in after running the queries/script:

```markdown
# App Insights Telemetry Validation Report

**Date:** ____
**App Insights Resource:** ____
**Operator:** ____

## Results

| # | Container | cloud_RoleName | Receiving Telemetry | Last Seen | Signal Types | Notes |
|---|-----------|----------------|-------|-----------|-------------|-------|
| 1 | ca-orchestrator-prod | aiops-orchestrator-agent | | | | |
| ... | ... | ... | ... | ... | ... | ... |
| 12 | ca-arc-mcp-server-prod | arc-mcp-server | | | | |

## Summary

- **Sending:** __/12
- **Silent:** __/12
- **Errors detected:** __

## Remediation Actions

(Fill in for any silent containers)

| Container | Root Cause | Action | Owner | Done |
|-----------|------------|--------|-------|------|
| | | | | |

## OTel Init Log Check

(Paste output of KQL query 5 here)
```

**Acceptance:** Template file exists with all 12 containers listed, clear instructions for operator.

---

## Verification

- [ ] `scripts/validate-appinsights/kql-queries.md` contains 5 KQL queries
- [ ] `scripts/validate-appinsights/validate.sh` is executable, runs against App Insights
- [ ] `scripts/validate-appinsights/VALIDATION-REPORT.md` template lists all 12 containers
- [ ] No code changes to existing source files (this is a validation-only task)

## Notes

- The `cloud_RoleName` values are assumptions based on the `service_name` passed to `setup_telemetry()` / `configure_azure_monitor()`. The actual values may differ — query 1 will reveal them.
- If a container is scaled to 0 replicas (min_replicas=0 in Terraform), it won't send telemetry until it receives traffic. This is expected, not a bug.
- The Arc MCP Server OTel wiring was just added — it won't have telemetry until the image is rebuilt and pushed to ACR.
