# Azure Agentic Platform — Platform Roadmap

**Version:** 2.0
**Date:** 2026-04-01
**Status:** Approved — Pending Implementation
**Author:** Principal Architect

---

## Executive Summary

The current platform has solid structural foundations: the detection plane (Fabric → Cosmos), the HITL approval flow, the Teams bot, the Patch tab, and the overall multi-agent routing architecture are all well-built. What is missing is the middle layer — the **diagnostic data pipeline** that turns raw alerts into evidence operators can act on in under 30 seconds.

The architectural direction adopted in this roadmap is:

> **The platform pre-computes everything an operator needs. Agents surface pre-fetched structured data. Live agentic loops are used only where pre-computation is impossible.**

This eliminates the latency, reliability, and trust problems of live multi-hop agentic investigations while preserving the AI-assisted triage and natural language interface.

---

## Architecture Decision Record

### ADR-001: Pipeline-First, Agents-Second

**Problem:** The current architecture routes incidents to agents that call diagnostic tools in real-time. All 4 compute agent diagnostic tools (`query_activity_log`, `query_log_analytics`, `query_resource_health`, `query_monitor_metrics`) return empty stubs. Even when wired, live multi-hop agentic investigation takes 15–45 seconds per turn, degrades under load, has compounding failure modes, and produces black-box reasoning that operators can't verify.

**Decision:** Introduce a **Diagnostic Pipeline** that runs automatically when an alert fires. The pipeline executes a deterministic playbook (activity log → resource health → metrics → log query), stores structured results in Cosmos DB, and marks the incident as `evidence_ready`. When the operator opens the incident, all evidence is pre-fetched — no live tool calls needed. The agent's role shifts to: translate stored evidence into a readable summary and propose next steps.

**Consequences:**
- Sub-2-second incident open time (evidence is already there)
- Deterministic data collection with a clear audit trail
- Agent reasoning is grounded in pre-fetched facts, not live tool calls that might return different results 5 minutes later
- Live agent interaction is reserved for follow-up questions that can't be pre-computed

### ADR-002: Contextual Chat, Not Global Chat

**Problem:** A single "ask anything" chat interface will hit the 128-tool limit, suffer high latency for cross-domain queries, and require complex orchestration to merge responses from multiple domain agents. At scale, a generalist assistant becomes mediocre at everything.

**Decision:** Two chat surfaces:
1. **Global chat (existing FAB)** — fleet-wide, read-only, ~30 tools. Answers: "how many critical alerts today?", "which VMs haven't been patched?", summary queries.
2. **Resource chat (new inline panel)** — per-resource, domain-scoped, ~20 tools. Used for: triage, investigation, remediation proposals on a specific resource.

Cross-domain correlation is handled at the **UI layer** (navigation between detail panels), not by the LLM.

### ADR-003: Structured Logging First

**Problem:** Diagnosing production issues requires visibility into what each component is doing. Current logging is inconsistent — some modules use `logger.info`, others print, many don't log tool call outcomes.

**Decision:** Every service emits structured log lines visible in Container Apps log stream. Standard format: `%(asctime)s %(levelname)s %(name)s %(message)s`. Key lifecycle events that MUST always be logged:
- Service startup (config values, env var presence, NOT secrets)
- Every inbound API request (method, path, correlation_id)
- Every outbound Azure SDK call (service, operation, resource_id, duration_ms, outcome)
- Every agent tool call (tool_name, parameters summary, outcome, duration_ms)
- Every Cosmos DB read/write (container, operation, document_id, outcome)
- Every error with full traceback and correlation_id

### ADR-004: VM-First, Then Expand

**Problem:** Azure has 12+ resource domains. Trying to monitor everything at once produces shallow coverage everywhere.

**Decision:** Build VM monitoring to production quality before expanding. Each resource type follows the same pattern: diagnostic pipeline → API endpoint → UI tab/detail panel → resource chat. Expansion sequence: VM → AKS → Azure SQL → App Service → Container Apps → Storage → Key Vault → Service Bus → Networking.

---

## Current State Assessment

### What Works
| Component | Status |
|-----------|--------|
| Detection plane (Fabric → Event Hubs → Cosmos) | ✅ Working |
| Alert ingestion API (`POST /api/v1/incidents`) | ✅ Working |
| Alert feed UI (`GET /api/v1/incidents`) | ✅ Working |
| HITL approval flow (ProposalCard → Cosmos → approve/reject) | ✅ Working |
| Teams bot (alert notifications, approval cards) | ✅ Working (needs CHANNEL_ID) |
| Patch tab (ARG-backed, real data) | ✅ Working |
| Chat SSE streaming | ✅ Working |
| Orchestrator routing to domain agents | ✅ Working (needs ORCHESTRATOR_AGENT_ID) |
| Authentication (MSAL, Entra) | ✅ Working |
| Audit log viewer | ✅ Working |
| Runbook RAG (60 runbooks, pgvector) | ✅ Working |

### What Is Broken or Missing
| Component | Status | Impact |
|-----------|--------|--------|
| Compute agent diagnostic tools (4 stubs) | ❌ Return empty data | Triage produces no evidence |
| `IncidentSummary` missing `resource_name`, `resource_group` | ❌ | Can't navigate from alert to resource |
| No pre-investigation pipeline | ❌ Missing entirely | Operator waits 30-60s for live agent |
| No VMDetailPanel | ❌ Missing | No way to investigate a specific VM |
| No VMTab | ❌ Missing | No VM fleet inventory view |
| No `Investigate` CTA on alert rows | ❌ Missing | Alert → triage path doesn't exist |
| No VM metrics charts | ❌ Missing | No visual signal confirmation |
| Observability tab is placeholder | ❌ All mock data | No real monitoring of the platform itself |
| ResourcesTab has no power state / health | ⚠️ Incomplete | Resource health not visible |
| Global chat is same as resource chat | ⚠️ No differentiation | No scoped triage experience |

---

## Phase Plan

### Phase 1: Foundation (Diagnostic Pipeline + Logging)
**Goal:** Every incident arrives with evidence pre-fetched. Every component emits meaningful logs.
**Duration:** 2–3 weeks
**Blocks:** All subsequent phases

#### 1.1 — Wire the compute agent diagnostic tools

**Files:** `agents/compute/tools.py`

Replace the 4 stub returns with real Azure SDK calls:

**`query_activity_log`** → `azure.mgmt.monitor.MonitorManagementClient.activity_logs.list()`
```
filter = f"eventTimestamp ge '{start_time}' and resourceId eq '{resource_id}'"
```
Return: `entries` list of `{eventTimestamp, operationName, caller, status, resourceId, level}`.

**`query_log_analytics`** → `azure.monitor.query.LogsQueryClient.query_workspace()`
```python
from azure.monitor.query import LogsQueryClient, LogsQueryStatus
client = LogsQueryClient(credential)
response = client.query_workspace(workspace_id, kql_query, timespan=timespan)
```
Return: `rows` list of row dicts with column names as keys.

**`query_resource_health`** → `azure.mgmt.resourcehealth.MicrosoftResourceHealth.availability_statuses.get_by_resource()`
```python
from azure.mgmt.resourcehealth import MicrosoftResourceHealth
client = MicrosoftResourceHealth(credential)
status = client.availability_statuses.get_by_resource(resource_uri=resource_id)
```
Return: `availability_state` ("Available"/"Degraded"/"Unavailable"), `summary`, `reason_type`.

**`query_monitor_metrics`** → `azure.mgmt.monitor.MonitorManagementClient.metrics.list()`
```python
from azure.mgmt.monitor import MonitorManagementClient
client = MonitorManagementClient(credential, subscription_id)
metrics = client.metrics.list(resource_uri=resource_id, metricnames=",".join(metric_names), ...)
```
Return: `metrics` list of `{name, unit, timeseries: [{timestamp, average, maximum, minimum}]}`.

**Error handling:** Every tool MUST catch all exceptions, log `tool_name resource_id error duration_ms`, and return `query_status: "error"` with `error` message. Never raise to the LLM.

#### 1.2 — Diagnostic Pipeline service

**New file:** `services/api-gateway/diagnostic_pipeline.py`

This is the core of ADR-001. A background task that runs when an incident is ingested.

```
trigger: POST /api/v1/incidents (after Cosmos write, before 202 return)
flow:
  1. Extract resource_id from first affected_resource
  2. Determine subscription_id from resource_id
  3. Run in parallel (asyncio.gather):
     a. Query Activity Log (last 2h)
     b. Query Resource Health
     c. Query Monitor Metrics (CPU, memory, disk, network — last 2h)
  4. Run sequentially (depends on step 3):
     d. Build KQL query based on incident domain + alert type
     e. Query Log Analytics (if WORKSPACE_ID configured)
  5. Compute evidence_summary:
     - health_state: "Available" | "Degraded" | "Unavailable" | "Unknown"
     - recent_changes: list of activity log entries in last 2h
     - metric_anomalies: list of metrics exceeding thresholds
     - log_errors: count + sample of error/warning lines
  6. Write evidence document to Cosmos DB:
     container: evidence
     document: {
       id: incident_id,
       incident_id,
       resource_id,
       collected_at: ISO timestamp,
       collection_duration_ms,
       pipeline_status: "complete" | "partial" | "failed",
       activity_log: [...],
       resource_health: {...},
       metrics: {...},
       log_analytics: {...},
       evidence_summary: {...}
     }
  7. Update incident document in Cosmos:
     set investigation_status = "evidence_ready"
     set evidence_collected_at = timestamp
```

**Logging requirements:**
```
pipeline: starting | incident_id={} resource_id={}
pipeline: activity_log complete | duration_ms={} entries={}
pipeline: resource_health complete | state={} duration_ms={}
pipeline: metrics complete | metrics_count={} duration_ms={}
pipeline: log_analytics complete | rows={} duration_ms={}
pipeline: evidence written to Cosmos | incident_id={} total_duration_ms={}
pipeline: FAILED | incident_id={} step={} error={}
```

**Failure handling:** Pipeline runs in background — never block the 202 response. If a step fails, log it, mark that step as `status: "error"` in the evidence document, and continue with remaining steps. A partial evidence document is better than no evidence.

#### 1.3 — Enrich IncidentSummary model

**File:** `services/api-gateway/models.py`

Add to `IncidentSummary`:
```python
resource_name: Optional[str] = None        # "vm-prod-001"
resource_group: Optional[str] = None       # "rg-production"
subscription_id: Optional[str] = None      # (already exists but optional)
resource_type: Optional[str] = None        # "microsoft.compute/virtualmachines"
investigation_status: Optional[str] = None # "pending" | "evidence_ready" | "investigating" | "resolved"
evidence_collected_at: Optional[str] = None
```

**File:** `services/api-gateway/incidents_list.py`

Update `list_incidents()` to populate new fields from Cosmos. Extract `resource_name` from the first `affected_resources[0].resource_id` (last segment after `/`), and `resource_group` from the resource ID path.

#### 1.4 — Evidence API endpoint

**File:** `services/api-gateway/main.py` (add route)

```
GET /api/v1/incidents/{incident_id}/evidence
Auth: Bearer token required
Response: {
  incident_id: str,
  pipeline_status: "complete" | "partial" | "failed" | "pending",
  collected_at: str | null,
  evidence_summary: {
    health_state: str,
    recent_changes: [{timestamp, operation, caller, status}],
    metric_anomalies: [{metric_name, current_value, threshold, unit}],
    log_errors: {count: int, sample: [str]}
  },
  raw: {
    activity_log: [...],
    resource_health: {...},
    metrics: {...},
    log_analytics: {...}
  }
}
```

If `pipeline_status == "pending"` (evidence not yet collected), return 202 with `retry_after: 5` header.

#### 1.5 — Comprehensive structured logging audit

**Scope:** All Python services and agents.

Every module must:
1. Use `logging.getLogger(__name__)` — not the root logger, not `print()`
2. Log all Azure SDK calls with outcome and duration
3. Log all Cosmos DB operations with document ID and outcome
4. Log all HTTP requests received with correlation_id, method, path, status_code, duration_ms
5. Never log secrets, tokens, or full resource IDs with sensitive path components
6. Use `LOG_LEVEL` env var (already wired) — default INFO, DEBUG available for diagnostics

**Pattern for Azure SDK calls:**
```python
import time
start = time.monotonic()
try:
    result = client.some_operation(...)
    duration_ms = (time.monotonic() - start) * 1000
    logger.info("azure_sdk: operation=list_vms subscription=%s count=%d duration_ms=%.0f", sub_id, len(result), duration_ms)
    return result
except Exception as e:
    duration_ms = (time.monotonic() - start) * 1000
    logger.error("azure_sdk: operation=list_vms subscription=%s error=%s duration_ms=%.0f", sub_id, e, duration_ms, exc_info=True)
    raise
```

---

### Phase 2: VM Inventory & Detail (The Triage Path)
**Goal:** Operator can click any alert, open a VM detail panel, and see pre-fetched evidence in under 2 seconds.
**Duration:** 2–3 weeks
**Requires:** Phase 1 complete

#### 2.1 — VM Inventory API endpoint

**New file:** `services/api-gateway/vm_inventory.py`

```
GET /api/v1/vms
Auth: Bearer token required
Query params:
  subscriptions: comma-separated subscription IDs (required)
  status: "running" | "stopped" | "deallocated" | "all" (default: "all")
  search: optional text filter on VM name
  limit: int (default 100, max 500)
  offset: int (default 0)

Response: {
  vms: [{
    id: str,                    # full ARM resource ID
    name: str,
    resource_group: str,
    subscription_id: str,
    location: str,
    size: str,                  # Standard_D4s_v5
    os_type: str,               # Windows | Linux
    os_name: str,               # "Windows Server 2022" | "Ubuntu 22.04"
    power_state: str,           # running | stopped | deallocated | unknown
    health_state: str,          # Available | Degraded | Unavailable | Unknown
    ama_status: str,            # installed | not_installed | unknown
    last_heartbeat: str | null, # ISO timestamp
    tags: dict,
    active_alert_count: int,    # count from Cosmos incidents collection
    last_incident_at: str | null
  }],
  total: int,
  has_more: bool
}
```

**Implementation:** Use Azure Resource Graph (`microsoft.compute/virtualmachines`) for the base query. Join with Resource Health for `health_state`. Join with Cosmos incident collection for `active_alert_count`.

**Logging:**
```
vm_inventory: request | subscriptions={} status={} search={}
vm_inventory: arg_query complete | subscriptions={} total={} duration_ms={}
vm_inventory: resource_health_join | vms_checked={} duration_ms={}
vm_inventory: cosmos_alert_join | vms_enriched={} duration_ms={}
vm_inventory: response | total={} returned={} duration_ms={}
```

#### 2.2 — VM Detail API endpoint

**New file:** `services/api-gateway/vm_detail.py`

```
GET /api/v1/vms/{resource_id_base64}
Auth: Bearer token required
Response: {
  id: str,
  name: str,
  resource_group: str,
  subscription_id: str,
  location: str,
  size: str,
  os_type: str,
  os_name: str,
  power_state: str,
  health_state: str,
  health_summary: str,
  ama_status: str,
  availability_zones: [str],
  tags: dict,
  network_interfaces: [{name, private_ip, public_ip, subnet}],
  disks: [{name, size_gb, disk_type, iops_limit}],
  active_incidents: [{incident_id, severity, title, created_at, status}],
  last_patch_assessment: str | null,
  ama_workspace_id: str | null
}
```

Note: `resource_id_base64` is the ARM resource ID base64url-encoded to avoid `/` in URL path.

#### 2.3 — VM metrics history endpoint

```
GET /api/v1/vms/{resource_id_base64}/metrics
Query params:
  metrics: comma-separated metric names (default: "Percentage CPU,Available Memory Bytes,Disk Read Bytes/sec,Network In Total")
  timespan: ISO 8601 duration (default: PT24H)
  interval: ISO 8601 duration (default: PT5M)

Response: {
  resource_id: str,
  timespan: str,
  interval: str,
  metrics: [{
    name: str,
    unit: str,
    timeseries: [{timestamp: str, average: float, maximum: float, minimum: float}]
  }]
}
```

This calls the now-wired `query_monitor_metrics` Azure SDK directly (not through the agent).

#### 2.4 — Next.js proxy routes

**New files:**
- `services/web-ui/app/api/proxy/vms/route.ts` — proxies `GET /api/v1/vms`
- `services/web-ui/app/api/proxy/vms/[vmId]/route.ts` — proxies `GET /api/v1/vms/{id}`
- `services/web-ui/app/api/proxy/vms/[vmId]/metrics/route.ts` — proxies metrics
- `services/web-ui/app/api/proxy/incidents/[incidentId]/evidence/route.ts` — proxies evidence

All follow existing proxy pattern from `app/api/proxy/incidents/route.ts`.

#### 2.5 — VMTab component

**New file:** `services/web-ui/components/VMTab.tsx`

A new dashboard tab ("VMs") added to `DashboardPanel.tsx` between Resources and Observability.

Features:
- Table with columns: Name | Resource Group | Size | OS | Power State | Health | Active Alerts | Last Incident
- Power state badge: running (green), stopped (yellow), deallocated (grey)
- Health badge: Available (green), Degraded (orange), Unavailable (red), Unknown (grey)
- Active alerts count — clicking opens alert feed filtered to that VM
- Search bar (filters by VM name)
- Subscription filter (uses existing `selectedSubscriptions` context)
- Click any row → opens VMDetailPanel (Phase 2.6)
- Auto-refresh every 60 seconds (not aggressive — these are not real-time metrics)
- Loading skeleton (not spinner) while data fetches
- Empty state when no VMs found

#### 2.6 — VMDetailPanel component

**New file:** `services/web-ui/components/VMDetailPanel.tsx`

A right-side drawer panel (same pattern as ChatDrawer but scoped to a VM).

**Sections:**

**Header:**
- VM name, resource group, subscription
- Power state badge + health badge (color-coded)
- Last updated timestamp
- Close button

**Evidence section (appears when investigation_status == "evidence_ready"):**
- Health state card: "Available" / "Degraded" / "Unavailable" with color coding
- Recent changes (last 2h): timeline of activity log entries if any
- Metric anomalies: cards showing metrics that exceeded threshold
- Log errors: count badge, expandable sample

**"Pending investigation" state:**
- Shown when `investigation_status == "pending"`
- Spinner with text "Collecting evidence... (this takes about 15s)"
- Auto-polls `GET /evidence` every 5s until `evidence_ready`

**Metrics charts section:**
- 4 sparkline charts: CPU %, Available Memory (MB), Disk Read (MB/s), Network In (MB/s)
- Time range selector: 1h / 6h / 24h / 7d
- Loading skeleton while fetching

**Active incidents section:**
- List of active incidents for this VM
- Each incident row: severity badge | title | age | status

**Resource chat section (Phase 3):**
- Placeholder in Phase 2, wired in Phase 3
- "Investigate with AI" button → opens scoped chat thread for this VM

**Trigger:** Any alert row click, VMTab row click, or topology node click opens this panel.

#### 2.7 — Alert row "Investigate" CTA

**File:** `services/web-ui/components/AlertFeed.tsx`

Add an "Investigate" button to each alert row:
- Only shown for alerts with `resource_id` populated (requires Phase 1.3)
- Click: open VMDetailPanel pre-populated with that incident's context
- On click: also call `POST /api/v1/incidents/{id}/investigate` (no-op endpoint that ensures the pipeline has run — idempotent)

---

### Phase 3: Resource Chat (Scoped Investigation)
**Goal:** Operator can start a scoped AI conversation from inside VMDetailPanel, grounded in pre-fetched evidence.
**Duration:** 2 weeks
**Requires:** Phase 2 complete

#### 3.1 — Scoped chat endpoint

**New endpoint:** `POST /api/v1/vms/{resource_id_base64}/chat`

Accepts: `{ message: str, thread_id: str | null }`

Behaviour:
1. Load evidence document from Cosmos for the most recent active incident on this VM
2. Build a system context document: `"Resource: {name}. Health: {state}. Recent changes: {list}. Metric anomalies: {list}."`
3. Create or continue a Foundry thread with the compute agent specifically
4. Inject the context document as the first system message on thread creation
5. Return `{ thread_id, run_id, status }`

This thread goes directly to the compute agent — it bypasses the orchestrator. The compute agent has its full tool set available for follow-up queries, but the initial context is grounded in pre-fetched evidence so the first response is fast.

#### 3.2 — Resource chat UI in VMDetailPanel

Wire the "Investigate with AI" section in VMDetailPanel:
- ChatInput (same component as global chat)
- Message thread (same ChatBubble pattern)
- Streaming via existing SSE infrastructure
- ProposalCard appears inline when agent proposes a remediation
- Thread is scoped to this VM — not mixed with global chat history

#### 3.3 — Remediation execution tools

**File:** `agents/compute/tools.py`

Add tools (all go through HITL approval — REMEDI-001 is sacred):

```python
@ai_function
def propose_vm_restart(resource_id: str, justification: str) -> dict:
    """Propose a VM restart. Does NOT execute — creates approval record in Cosmos."""
    # Write to Cosmos approvals container
    # Returns approval_id for the ProposalCard

@ai_function
def propose_vm_deallocate(resource_id: str, justification: str) -> dict:
    """Propose VM deallocation. Does NOT execute."""

@ai_function
def propose_vm_resize(resource_id: str, target_size: str, justification: str) -> dict:
    """Propose VM resize. Does NOT execute."""

@ai_function
def propose_run_script(resource_id: str, script: str, justification: str) -> dict:
    """Propose running a script via Run Command. Does NOT execute."""
```

**Actual execution** (after human approval) is handled by the existing approval execution path in `services/api-gateway/approvals.py`. Add compute action handlers there.

---

### Phase 4: Observability (Platform Self-Monitoring)
**Goal:** The Observability tab shows real metrics about the platform itself, not mock data.
**Duration:** 1–2 weeks
**Can run parallel to Phase 3**

#### 4.1 — Real observability data endpoint

**File:** `services/web-ui/app/api/observability/route.ts` (replace mock with real data)

Query Application Insights via Azure Monitor Logs API:
```
GET /api/observability?timespan=PT1H

Response: {
  agent_latency: {
    p50_ms: float,
    p95_ms: float,
    p99_ms: float,
    by_agent: [{agent: str, p95_ms: float}]
  },
  pipeline_lag: {
    current_ms: float,
    p95_ms: float
  },
  active_errors: [{
    timestamp: str,
    service: str,
    error: str,
    count: int
  }],
  approval_queue: {
    pending: int,
    oldest_age_minutes: float | null
  },
  incident_throughput: {
    last_hour: int,
    last_24h: int
  }
}
```

#### 4.2 — Real charts in ObservabilityTab

Replace all mock `MetricCard` and `AgentLatencyCard` components with recharts-backed charts using real data:
- Agent latency: Line chart (p50/p95/p99 over time)
- Pipeline lag: Area chart
- Incident throughput: Bar chart (hourly)
- Error rate: Area chart
- Approval queue age: Gauge (or just a prominent number)

**Chart library:** Add `recharts` to `services/web-ui/package.json`. It's small, well-maintained, and works with shadcn/ui's design tokens.

---

### Phase 5: VM Metrics Charts & Proactive Signals
**Goal:** Operators can see CPU/memory/disk trends and the platform surfaces VMs trending toward failure before they alert.
**Duration:** 2 weeks
**Requires:** Phase 2 complete

#### 5.1 — VM metrics charts in VMDetailPanel

Wire the metrics endpoint from Phase 2.3 into real charts:
- CPU % — Line chart with 90% threshold line
- Available Memory — Area chart (inverted — low is bad)
- Disk Read/Write bytes — Combined area chart
- Network In/Out — Combined area chart
- Time range selector: 1h / 6h / 24h / 7d (calls metrics API with different timespan)

#### 5.2 — Proactive signals API

```
GET /api/v1/vms/signals
Query: subscriptions (required), lookback_hours (default 24)

Response: [{
  resource_id: str,
  resource_name: str,
  signal_type: "disk_fill_trend" | "cpu_baseline_rise" | "memory_pressure" | "ama_heartbeat_gap",
  severity: "warning" | "critical",
  message: str,           # "Disk filling at 2GB/day — estimated full in 4 days"
  current_value: float,
  threshold: float,
  unit: str,
  detected_at: str
}]
```

**Implementation:** Queries Azure Monitor metrics API for all VMs in selected subscriptions, applies trend detection:
- `disk_fill_trend`: Linear regression on disk usage over last 24h; alert if trend reaches 90% in <7d
- `cpu_baseline_rise`: Compare last 1h P95 CPU vs 7d P50 CPU; alert if >3x
- `memory_pressure`: `Available Memory Bytes` below 500MB for >15 minutes
- `ama_heartbeat_gap`: No heartbeat in Log Analytics for >30 minutes

#### 5.3 — Proactive signals panel in VMTab

Add a "Signals" section above the VM table in VMTab:
- Shows proactive signals as warning cards
- Each card: signal type icon | VM name | message | "Investigate" CTA
- Collapses after first view (remembered in localStorage)

---

### Phase 6: AKS Monitoring
**Goal:** AKS cluster health, node pool status, and pod failure triage follow the same pattern as VM.
**Duration:** 3 weeks
**Requires:** Phase 2–3 patterns established

#### Pattern (reuse for every resource type):
1. Diagnostic pipeline addition: add AKS-specific playbook (node health, control plane logs, pod crash events)
2. Inventory endpoint: `GET /api/v1/aks` — clusters with node pool health, pod failure count, version
3. Detail endpoint: `GET /api/v1/aks/{cluster_id_b64}` — cluster detail, node pools, recent events
4. Metrics endpoint: node CPU/memory, pod count, pending pods, OOM kills
5. AKSTab component (same pattern as VMTab)
6. AKSDetailPanel component (same pattern as VMDetailPanel)
7. Scoped AKS chat endpoint pointing to compute agent with AKS context

#### AKS-specific signals:
- Node NotReady
- Pending pod count > threshold
- OOMKill events in last 1h
- Control plane API server latency spike
- Node version out of date

---

### Phase 7–12: Resource Type Expansion

Each follows the same 6-step pattern from Phase 6.

| Phase | Resource Type | Key signals |
|-------|--------------|-------------|
| 7 | Azure SQL / SQL Managed Instance | DTU/vCore %, deadlocks, connection failures, long-running queries |
| 8 | App Service | HTTP 5xx rate, response time P95, memory working set, deployment failures |
| 9 | Container Apps | Replica count vs desired, container exits, CPU throttling |
| 10 | Storage Accounts | Throttling (503), availability, replication lag, access key age |
| 11 | Key Vault | Throttling (429), secret expiry within 30d, access denied rate |
| 12 | Service Bus / Event Hubs | Dead letter count, message backlog age, consumer lag |

---

### Phase 13: Networking (Foundational Layer)
**Goal:** NSG rule change correlation, VNet connectivity checks, ExpressRoute/VPN health.
**Duration:** 3–4 weeks
**Note:** Networking is foundational — its health affects every other resource. Saved for last because it's the most complex and the network agent already exists.

Key features:
- NSG change timeline (from activity log) correlating with compute/app incidents
- VNet topology visualization enhancement (link health state to topology nodes)
- ExpressRoute / VPN gateway health cards
- Private endpoint resolution check

---

## Logging Reference

### Log Format (all services)
```
2026-04-01T10:23:45.123Z INFO  services.api_gateway.diagnostic_pipeline pipeline: activity_log complete | incident_id=abc123 resource_id=/subscriptions/.../vm-prod-001 entries=3 duration_ms=245
```

### Key Log Events by Service

**API Gateway startup:**
```
INFO  services.api_gateway.main startup: COSMOS_ENDPOINT=set LOG_LEVEL=INFO
INFO  services.api_gateway.main startup: migrations complete
INFO  services.api_gateway.main startup: MCP client initialized tools=42
```

**Incident ingestion:**
```
INFO  services.api_gateway.main incident: ingested | incident_id={} severity={} domain={} resource={}
INFO  services.api_gateway.main incident: dedup=pass | incident_id={}
INFO  services.api_gateway.main incident: foundry_thread created | thread_id={} incident_id={}
INFO  services.api_gateway.main incident: pipeline queued | incident_id={}
```

**Diagnostic pipeline:**
```
INFO  pipeline: starting | incident_id={} resource_id={}
INFO  pipeline: activity_log complete | duration_ms={} entries={}
INFO  pipeline: resource_health complete | state={} duration_ms={}
INFO  pipeline: metrics complete | metrics={} duration_ms={}
INFO  pipeline: log_analytics complete | rows={} duration_ms={}
INFO  pipeline: evidence written | incident_id={} total_duration_ms={}
ERROR pipeline: step_failed | step=activity_log incident_id={} error={} — continuing
```

**Compute agent tools:**
```
INFO  aiops.compute query_activity_log: called | resources={} timespan_hours={}
INFO  aiops.compute query_activity_log: complete | entries={} duration_ms={}
ERROR aiops.compute query_activity_log: failed | resource={} error={} duration_ms={}
```

**Container Apps Log Stream access:**
```
az containerapp logs show \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --type system \
  --follow

# Filter by log level:
az containerapp logs show ... | grep "ERROR"

# Filter by incident:
az containerapp logs show ... | grep "incident_id=abc123"
```

---

## Documentation Requirements

Every phase must produce:

### Operator Documentation (in `docs/operator/`)
- What the feature does, in plain English
- What operators see in the UI
- How to interpret each signal / badge / chart
- What actions are available and what they do
- Common questions ("why is this VM showing Degraded?")

### Technical Documentation (in `docs/technical/`)
- API endpoint reference (request/response schema, auth requirements, error codes)
- Data flow diagram (where data comes from, how it's transformed, where it's stored)
- Environment variables required and their effect
- Failure modes and what they look like in logs

### Runbook (in `docs/troubleshooting/`)
- How to diagnose when a feature is not working
- Log patterns to search for
- Common errors and their causes
- How to test manually (curl examples, az cli commands)

### Example: Diagnostic Pipeline Troubleshooting Runbook

**Symptom:** VMDetailPanel shows "Pending investigation..." indefinitely

**Check 1 — Is the pipeline running?**
```bash
az containerapp logs show --name ca-api-gateway-prod ... | grep "pipeline: starting"
```
If no log line for the incident_id → pipeline was never queued. Check `POST /api/v1/incidents` logs.

**Check 2 — Did a step fail?**
```bash
az containerapp logs show ... | grep "pipeline: step_failed"
```
If yes → check the `error={}` field. Common causes:
- `AZURE_SUBSCRIPTION_ID` not set → activity log call fails
- `LOG_ANALYTICS_WORKSPACE_ID` not set → log analytics step skipped (warning, not error)
- Insufficient RBAC (Monitoring Reader missing) → resource health returns 403

**Check 3 — Was evidence written to Cosmos?**
Check Cosmos DB container `evidence`, look for document with `id == incident_id`.
If missing → pipeline completed but Cosmos write failed. Check COSMOS_ENDPOINT env var.

**Check 4 — Is the UI polling correctly?**
Open browser DevTools Network tab. Should see `GET /evidence` requests every 5s.
If not → check `VMDetailPanel.tsx` polling logic.

---

## Environment Variables

### API Gateway (new in this roadmap)
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LOG_ANALYTICS_WORKSPACE_ID` | Recommended | (none) | Workspace ID for log query step in diagnostic pipeline |
| `DIAGNOSTIC_PIPELINE_ENABLED` | Optional | `true` | Set `false` to disable pre-investigation pipeline |
| `DIAGNOSTIC_PIPELINE_TIMEOUT_SECONDS` | Optional | `30` | Max seconds for each pipeline step before timeout |
| `VM_INVENTORY_PAGE_SIZE` | Optional | `100` | Default page size for VM inventory endpoint |
| `METRICS_DEFAULT_TIMESPAN` | Optional | `PT24H` | Default timespan for metrics endpoint |

### Compute Agent (new)
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LOG_ANALYTICS_WORKSPACE_ID` | Recommended | (none) | Workspace ID for `query_log_analytics` calls |
| `AZURE_SUBSCRIPTION_IDS` | Required | (none) | Comma-separated subscription IDs to scope queries |

### All Agents (existing, documenting here for reference)
| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_PROJECT_ENDPOINT` | Required | Foundry project endpoint URL |
| `AZURE_CLIENT_ID` | Required (prod) | Managed identity client ID |
| `LOG_LEVEL` | Optional | `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`) |

---

## Testing Requirements

### Phase 1
- Unit tests for each wired diagnostic tool (mock Azure SDK, verify correct API calls and return shape)
- Unit tests for diagnostic pipeline (mock all tool calls, verify Cosmos write and evidence structure)
- Integration test: `POST /api/v1/incidents` triggers pipeline and writes evidence (mock Azure, real Cosmos test account)

### Phase 2
- Unit tests for VM inventory endpoint (mock ARG, mock Cosmos)
- Unit tests for VM detail endpoint
- Unit tests for metrics endpoint
- Component tests for VMTab (mock API responses via MSW)
- Component tests for VMDetailPanel states: loading, evidence_ready, pending, error

### Phase 3
- Unit tests for scoped chat endpoint (verify context injection)
- Unit tests for propose_* tools (verify Cosmos write, no actual Azure calls)
- Integration test: Investigate → chat → propose → approve full flow

### Coverage target: 80% for all new Python code, 70% for all new TypeScript components.

---

## Implementation Order

```
Phase 1.1  Wire compute tools (stubs → real SDK)          [CRITICAL PATH]
Phase 1.2  Diagnostic pipeline service                     [CRITICAL PATH]
Phase 1.3  Enrich IncidentSummary model                    [CRITICAL PATH]
Phase 1.4  Evidence API endpoint                           [CRITICAL PATH]
Phase 1.5  Logging audit (all services)                    [Run in parallel with 1.2]
Phase 2.1  VM inventory API                                [After Phase 1]
Phase 2.2  VM detail API                                   [After Phase 1]
Phase 2.3  VM metrics API                                  [After Phase 1.1]
Phase 2.4  Next.js proxy routes                            [After Phase 2.1–2.3]
Phase 2.5  VMTab component                                 [After Phase 2.4]
Phase 2.6  VMDetailPanel component                         [After Phase 2.4]
Phase 2.7  Alert row Investigate CTA                       [After Phase 2.6]
Phase 3.1  Scoped chat endpoint                            [After Phase 2]
Phase 3.2  Resource chat in VMDetailPanel                  [After Phase 3.1]
Phase 3.3  Remediation execution tools                     [After Phase 3.1]
Phase 4    Observability tab (real data)                   [Parallel to Phase 3]
Phase 5    VM metrics charts + proactive signals            [After Phase 2.3]
Phase 6    AKS monitoring                                  [After Phase 2–3 patterns]
Phase 7+   Resource type expansion                         [Sequential, one per sprint]
Phase 13   Networking                                      [Last — most complex]
```

---

## Definition of Done

A phase is complete when:
1. All new API endpoints return real data (verified with `curl`)
2. All new UI components render without errors in production build
3. All new tests pass in CI
4. Container Apps log stream shows correct log lines for the feature
5. Operator documentation written and committed
6. Technical documentation written and committed
7. No regression in existing tests

---

## What Is NOT in This Roadmap

- Multi-tenant support (deferred — single Entra tenant only)
- Fabric IQ / Operations Agent (Preview — keep off critical path)
- Entra Agent ID governance (Preview — provision but don't depend on)
- AutoGen or LangGraph (confirmed excluded)
- Mobile UI (desktop only, DesktopOnlyGate enforced)
- Cost management features (future roadmap)
- Capacity planning features (future roadmap)
