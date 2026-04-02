# KQL Validation Queries for App Insights Telemetry

> **Purpose:** Paste these queries into the Application Insights > Logs blade to validate that all 12 AAP containers are sending telemetry.
>
> **App Insights Resource:** `appi-aap-prod` (resource group `rg-aap-prod`)
>
> **Expected `cloud_RoleName` values:** These are derived from the `service_name` argument passed to `setup_telemetry()` or `configure_azure_monitor()` in each container. The actual values appearing in App Insights may differ — Query 1 reveals the truth.

---

## Query 1: Heartbeat — Which containers have sent ANY telemetry in the last 24h?

Unions across all telemetry tables and groups by `cloud_RoleName`. This is the single most important query — it shows which containers are alive.

```kql
union traces, requests, dependencies, exceptions, customMetrics
| where timestamp > ago(24h)
| summarize LastSeen=max(timestamp), TelemetryCount=count() by cloud_RoleName
| order by cloud_RoleName asc
```

**Expected output:** A table with up to 12 rows (one per container), showing the last telemetry timestamp and total count. Any container NOT appearing here is silent.

| cloud_RoleName | LastSeen | TelemetryCount |
|---|---|---|
| aiops-orchestrator-agent | 2026-04-02T... | ... |
| aiops-compute-agent | 2026-04-02T... | ... |
| ... | ... | ... |

---

## Query 2: Per-Container Signal Breakdown — What telemetry types are present?

For each role, shows which of the four primary telemetry types (traces, requests, dependencies, exceptions) are being emitted. Helps identify containers that are only partially instrumented.

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

**Expected output:** Multiple rows per container — ideally at least `traces` and `requests` for HTTP-serving containers (api-gateway, teams-bot, arc-mcp-server) and `traces` + `dependencies` for agent containers that make outbound Azure SDK calls.

| cloud_RoleName | TelemetryType | Count | LastSeen |
|---|---|---|---|
| aiops-compute-agent | dependencies | 142 | ... |
| aiops-compute-agent | traces | 891 | ... |
| api-gateway | requests | 2,341 | ... |
| api-gateway | traces | 4,102 | ... |
| ... | ... | ... | ... |

---

## Query 3: Silent Containers — Which of the 12 expected containers have NOT sent telemetry?

Compares the expected list of `cloud_RoleName` values against actual telemetry. Any result row is a container that needs investigation.

```kql
let expected = dynamic([
  "aiops-orchestrator-agent",
  "aiops-compute-agent",
  "aiops-network-agent",
  "aiops-storage-agent",
  "aiops-security-agent",
  "aiops-arc-agent",
  "aiops-sre-agent",
  "aiops-patch-agent",
  "aiops-eol-agent",
  "api-gateway",
  "teams-bot",
  "arc-mcp-server"
]);
let active = union traces, requests, dependencies, exceptions
| where timestamp > ago(24h)
| distinct cloud_RoleName;
print Expected=expected
| mv-expand Expected to typeof(string)
| join kind=leftanti active on $left.Expected == $right.cloud_RoleName
| project SilentContainer=Expected
```

**Expected output:** Ideally **zero rows** (all 12 containers are sending). Any row listed is a container that has NOT sent telemetry in the last 24h.

**Common reasons for silence:**
- Container scaled to 0 replicas (min_replicas=0 in Terraform) and hasn't received traffic
- `APPLICATIONINSIGHTS_CONNECTION_STRING` env var not set on the Container App
- Container image hasn't been rebuilt since OTel wiring was added
- Container is crash-looping (check `az containerapp logs show`)

---

## Query 4: Recent Errors — Any exceptions in the last 6h?

Surfaces exceptions grouped by container. High error counts may indicate misconfiguration, missing env vars, or Azure SDK auth failures.

```kql
exceptions
| where timestamp > ago(6h)
| summarize
    ErrorCount=count(),
    LastError=max(timestamp),
    Sample=take_any(outerMessage)
  by cloud_RoleName
| order by ErrorCount desc
```

**Expected output:** Ideally zero rows or low counts. Pay attention to:
- `DefaultAzureCredential` errors — RBAC not assigned to managed identity
- `ConnectionRefused` — dependent service not reachable
- `asyncpg` errors — PostgreSQL connection issues

| cloud_RoleName | ErrorCount | LastError | Sample |
|---|---|---|---|
| api-gateway | 3 | 2026-04-02T... | "Connection refused..." |
| ... | ... | ... | ... |

---

## Query 5: OTel SDK Init Confirmation — Did each container log its startup message?

Each Python container logs either "Azure Monitor OpenTelemetry configured" (success) or "OTel disabled" (missing connection string) at startup. This query finds those messages.

```kql
traces
| where timestamp > ago(24h)
| where message has "Azure Monitor OpenTelemetry configured"
    or message has "OTel disabled"
    or message has "APPLICATIONINSIGHTS_CONNECTION_STRING"
| project timestamp, cloud_RoleName, message
| order by timestamp desc
```

**Expected output:** One or more rows per container showing the startup log line. Containers with "OTel disabled" have `APPLICATIONINSIGHTS_CONNECTION_STRING` not set.

| timestamp | cloud_RoleName | message |
|---|---|---|
| 2026-04-02T10:00:00Z | api-gateway | "Azure Monitor OpenTelemetry configured" |
| 2026-04-02T09:58:00Z | aiops-compute-agent | "Azure Monitor OpenTelemetry configured" |
| ... | ... | ... |

**Note:** The Teams Bot (TypeScript) uses `useAzureMonitor()` and may not emit the exact same log message. Check for any startup-related trace from `teams-bot`.
