# AAP World-Class AIOps Roadmap — Design Spec

**Date:** 2026-04-02
**Author:** Brainstorming session (research + platform audit)
**Status:** Approved by user

---

## Current Baseline (Phases 1–18 Complete)

Before defining the new phases, this is what Phase 18 delivered and what the platform can do today:

| Phase | What Was Built |
|-------|---------------|
| 1–4 | Infrastructure (Terraform, VNet, Cosmos, PostgreSQL, ACR), Agent Core (8 domain agents, Orchestrator, Foundry hosting), Arc MCP Server (9 tools), Detection Plane (Fabric Eventhouse + Activator — built but disabled in prod) |
| 5–8 | HITL approval gate (Cosmos + Teams Adaptive Cards), SSE streaming, runbook RAG (skeleton), Teams Bot integration, 60 seeded runbooks, OTel instrumentation, Playwright E2E suite, Azure validation |
| 9–10 | Web UI revamp (Tailwind + shadcn/ui, 7-tab dashboard), API gateway auth hardening |
| 11–12 | Patch domain agent (ARG tools, MSRC CVRF), EOL domain agent (endoflife.date + MS Lifecycle + PostgreSQL cache) |
| 13 | Patch Management Tab (full-stack: ARG endpoints + PatchTab UI with compliance/installation tables) |
| 14 | **Planned but not executed** — 12 tasks across 6 milestones; all work deferred |
| 15 | Diagnostic pipeline: compute agent tools wired to real Azure SDKs (Activity Log, Resource Health, Metrics, Log Analytics); BackgroundTask pre-fetches evidence; IncidentSummary enriched with resource metadata |
| 16 | VM Triage Path: `GET /api/v1/vms`, `/api/v1/vms/{id}`, `/api/v1/vms/{id}/metrics`; VMDetailPanel with health badge, sparkline charts, evidence, active incidents |
| 17 | Resource-scoped chat: `POST /api/v1/vms/{id}/chat` bypasses orchestrator, injects evidence context; VMDetailPanel inline chat with auto-summary |
| 18 | Observability charts: recharts BarCharts in AgentLatencyCard and IncidentThroughputCard; `/api/observability` returns incidentThroughput; all 12 containers wired to App Insights |

**Phase 19 starts from this baseline.** Phase 14's 12 deferred tasks remain the first priority.

---

## Context & Problem Statement

The Azure Agentic Platform (AAP) has completed 18 phases and has a **world-class architecture** — multi-agent orchestration, HITL approvals, Foundry-hosted agents, Fabric detection plane, VNet isolation, and comprehensive Terraform IaC. However, the platform is currently operating at **AIOps maturity Stage 2.5** because several critical production issues prevent the architecture from functioning as designed:

- Authentication is effectively disabled in prod (`AZURE_CLIENT_ID` not set)
- 4 of 8 domain agents broken (MCP tool groups not registered in Foundry)
- Detection plane disabled (`enable_fabric_data_plane = false`)
- Azure MCP Server publicly accessible with no auth
- Teams proactive alerting silently drops all cards

Beyond the production gaps, the platform is also missing the **Stage 4–5 intelligence capabilities** that define world-class AIOps:
- No resource topology graph (the biggest differentiator per Dynatrace/ServiceNow patterns)
- No alert correlation or noise suppression
- No change correlation engine
- No institutional memory / historical incident RAG
- No SLO tracking or error budget management
- No predictive analytics
- No closed-loop remediation verification

---

## AIOps Maturity Target

| Stage | Label | Current | Target (Post-Phase 28) |
|-------|-------|---------|------------------------|
| 1 | Reactive | ✅ Done | — |
| 2 | Correlated | ✅ Done | — |
| 3 | Predictive | ⚠️ Partial | ✅ Complete |
| 4 | Prescriptive | ❌ Blocked | ✅ Complete |
| 5 | Autonomous | ❌ Missing | ✅ Complete |

**World-class definition** (Stage 4+):
- Single deterministic root cause with evidence chain (not "top 3 probable causes")
- >90% alert noise reduction via topology-aware causal suppression
- MTTR <30 minutes with human approval gate
- Institutional memory: historical patterns surfaced automatically
- Change correlation: every incident cross-referenced with recent changes
- SLO-aware prioritization: incidents ranked by error budget impact
- Predictive prevention: anomalies caught before they become incidents
- Closed-loop remediation: detect → diagnose → propose → approve → execute → verify → rollback

---

## Three-Track Architecture

### Track 1 — Make It Real (Phases 19–21)
**Rationale:** Nothing else matters until the platform works in production. Track 1 resolves all blocking production issues, completes Phase 14's deferred work, activates the live detection loop, and wires all domain agents to their proper tool surfaces.

### Track 2 — Stage 4 Intelligence (Phases 22–25)
**Rationale:** The capabilities that separate an AIOps platform from "monitoring + chatbot." Topology graph, change correlation, alert noise reduction, and institutional memory are the four pillars of prescriptive operations. Each builds on the prior phase.

### Track 3 — Stage 5 Autonomy (Phases 26–28)
**Rationale:** The frontier capabilities that make AAP genuinely world-class. Predictive operations, closed-loop remediation, and platform-wide intelligence complete the vision of an autonomous operations platform where humans oversee rather than operate.

---

## Phase Specifications

---

### Phase 19: Production Stabilisation
**Track:** 1 — Make It Real
**Depends on:** Phase 18
**Goal:** Resolve all known BLOCKING and HIGH-severity production defects. When Phase 19 completes, the platform must be fully operational: authenticated, all agents functional, detection plane wiring ready to activate, and no internet-exposed unauthenticated endpoints.

**This is Phase 14 executed.** Phase 14's PLAN.md contains 12 tasks across 6 milestones that were deferred. Phase 19 executes all of them.

**Must-haves:**
1. **Auth fully enabled in prod** — `AZURE_CLIENT_ID` set on `ca-api-gateway-prod`; all requests validated against Entra; Web UI proxy routes forward MSAL Bearer tokens; end-to-end auth test passes
2. **Azure MCP Server secured** — ingress changed from external to internal; `--dangerously-disable-http-incoming-auth` removed; authenticated via managed identity; passes security scan
3. **All 8 agent MCP tool groups registered** — `Microsoft.Network`, `Microsoft.Security`, Arc MCP Server, SRE cross-domain tools all wired in Foundry; each agent can invoke its domain tools
4. **Arc MCP Server real image deployed** — real container built, pushed to ACR, running on `ca-arc-mcp-server-prod`; placeholder replaced
5. **Runbook RAG operational** — `PGVECTOR_CONNECTION_STRING` confirmed on gateway; `seed.py` run against prod PostgreSQL; `/api/v1/runbooks/search` returns results
6. **Hardcoded agent IDs removed** — all 8 Foundry agent IDs read from env vars at runtime; no hardcoded strings in `chat.py`
7. **Teams Bot Service registered** — Azure Bot Service created; `TEAMS_CHANNEL_ID` set; proactive Adaptive Cards delivered to channel on incident creation; reactive chat working
8. **Agent framework pinned to stable RC** — `agent-framework==1.0.0rc5`; `requirements.txt` updated; CI validates pinned version
9. **Stale todo items closed** — 4 incomplete PLAN-without-SUMMARY docs reconciled; Phase 8 formally closed

**Success criteria:** All 8 agents can be exercised end-to-end via the chat panel against a real Azure subscription. A simulated incident flows from ingestion → orchestrator routing → domain agent investigation (with domain tools firing) → HITL proposal → Teams approval card delivered. Auth token required for all non-health endpoints.

---

### Phase 20: Network & Security Agent Depth
**Track:** 1 — Make It Real
**Depends on:** Phase 19 (tool groups registered, MCP Server secured)
**Goal:** Give the Network and Security domain agents genuine diagnostic depth. Currently they have only 3 shared triage tools. After Phase 20, each agent has a rich set of domain-specific tools covering their full investigation surface.

**Network agent new tools:**
- `query_nsg_rules(resource_id)` — list effective NSG rules on a VM/subnet; flag overly permissive rules
- `query_vnet_topology(vnet_id)` — peering relationships, subnets, route tables, DNS
- `query_load_balancer_health(lb_id)` — backend pool health, probe status, rule configuration
- `query_network_watcher_flow_logs(vm_id, window_minutes)` — recent connection flow data
- `query_expressroute_health(circuit_id)` — circuit state, BGP peering status
- `diagnose_connectivity(source_id, dest_id)` — Azure Network Watcher connectivity check

**Security agent new tools:**
- `query_defender_alerts(subscription_id, severity)` — Defender for Cloud active alerts
- `query_secure_score(subscription_id)` — subscription-level and resource-level secure score
- `query_rbac_assignments(resource_id)` — current role assignments; flag anomalous permissions
- `query_key_vault_audit(vault_id, hours)` — recent Key Vault access audit events
- `query_policy_compliance(subscription_id)` — Azure Policy compliance state + non-compliant resources
- `scan_for_public_endpoints(subscription_id)` — identify resources with public internet exposure

**SRE agent new tools:**
- `query_service_health(subscription_id)` — Azure Service Health incidents affecting subscription
- `query_advisor_recommendations(resource_id)` — Azure Advisor reliability/performance recommendations
- `query_change_analysis(resource_id, hours)` — Azure Change Analysis for recent config changes
- `correlate_cross_domain(incident_id)` — synthesize findings from compute + network + storage for SRE-level analysis

**Must-haves:** Each new tool has unit tests with Azure SDK mocked; tools invoked during domain agent investigation flow; agent system prompts updated to describe when to use each tool.

**Success criteria:** A simulated network incident (e.g., NSG blocking traffic to a VM) produces a triage response from the Network agent that cites at least 3 NSG rule findings from `query_nsg_rules` and identifies the blocking rule. A simulated security incident (e.g., Defender alert for suspicious login) produces a triage response from the Security agent that surfaces the alert details and affected resource's RBAC assignments. Both agents complete their domain-specific investigation within 90 seconds of incident routing.

---

### Phase 21: Detection Plane Activation
**Track:** 1 — Make It Real
**Depends on:** Phase 19 (auth working, agents functional)
**Goal:** Enable the live detection loop in production. The Fabric Eventhouse + Activator infrastructure was built in Phase 4 and Terraform is complete — it is currently disabled via `enable_fabric_data_plane = false`. Phase 21 activates, validates, and operationalises this existing infrastructure against real Azure Monitor alerts. After Phase 21, real Azure Monitor alerts flow automatically into incidents without manual simulation.

**Note:** Phase 21 is an *activation and validation* phase, not greenfield provisioning. The KQL pipeline (`RawAlerts → EnrichedAlerts → DetectionResults`), Activator rules, and User Data Function all exist in code — the work here is deployment configuration, live testing, and pipeline observability.

**Must-haves:**
1. **`enable_fabric_data_plane = true`** in prod Terraform; Fabric Eventhouse and Activator provisioned
2. **Event Hub → Eventhouse pipeline live** — real Azure Monitor action groups fire into Event Hub; KQL streaming ingestion to Eventhouse confirmed
3. **KQL detection rules active** — `RawAlerts → EnrichedAlerts → DetectionResults` pipeline processing real alerts; classification rules tuned for the 8 agent domains
4. **Activator → API gateway wired** — Fabric Activator webhook triggers `POST /api/v1/incidents` on alert conditions; threshold: ≥1 Sev0/Sev1/Sev2 alert for target resource types
5. **Fabric User Data Function deployed** — enrichment function adds resource metadata + classification before firing webhook
6. **End-to-end live test** — trigger a real Azure Monitor alert (e.g., CPU threshold on test VM); observe it flow through Event Hub → Eventhouse → Activator → incident ingestion → orchestrator triage → domain agent → proposal within 5 minutes
7. **Alert deduplication validated** — duplicate alerts within 5-min window produce one incident, not multiple
8. **Monitoring of the detector** — detection pipeline itself monitored; dead-letter queue on Event Hub; alert if pipeline lag >10 minutes

**Success criteria:** The platform operates continuously without simulation scripts. An operator starting a fresh session can watch real Azure incidents being triaged automatically.

---

### Phase 22: Resource Topology Graph
**Track:** 2 — Stage 4 Intelligence
**Depends on:** Phase 21 (live data flowing, all agents functional)
**Goal:** Build and maintain a real-time property graph of Azure resources and their relationships. This is the single most differentiating capability of Stage 4 AIOps — it transforms RCA from "probable causes" to deterministic causal traversal.

**Graph schema:**
```
Nodes: VM, VMSS, VNet, Subnet, NSG, LoadBalancer, StorageAccount, KeyVault,
       LogAnalyticsWorkspace, AppInsights, AKSCluster, NodePool, ArcServer,
       ArcK8sCluster, SqlServer, PostgreSQLServer, EventHub, ServiceBus,
       ResourceGroup, Subscription, AppServicePlan, FunctionApp

Edges:
  VM → HOSTED_IN → Subnet
  VM → USES_DISK → ManagedDisk
  VM → READS_SECRET → KeyVault
  VM → SENDS_LOGS → LogAnalyticsWorkspace
  VM → MEMBER_OF → VMSS
  AKSCluster → USES_VNET → VNet
  AKSCluster → HAS_NODEPOOL → NodePool
  NodePool → CONTAINS → VM
  LoadBalancer → ROUTES_TO → VM
  NSG → PROTECTS → Subnet
  AppService → CALLS → StorageAccount (via network flow analysis)
  Service → DEPENDS_ON → Service (via OTel trace spans)
```

**Storage:** Cosmos DB NoSQL container `resource-topology` with composite index on `(type, id)`; Gremlin API considered but rejected in favour of adjacency-list representation given the platform's current scale (estimated <50,000 nodes per subscription). **Scale risk acknowledged:** if blast-radius traversal (TOPO-002: <2 seconds) degrades under Phase 26–28 load, the fallback is a Redis Graph or dedicated Azure Cosmos DB for Gremlin endpoint. A load test of the topology query patterns must be run at Phase 26 kick-off; if P95 latency exceeds 2 seconds at representative scale, the storage layer is migrated before Phase 26 proceeds.

**Snapshot retention:** Topology snapshots stored at 15-minute intervals; retained for 30 days; snapshots older than 30 days replaced with daily rollups. Storage estimate documented during Phase 22 implementation (expected: ~50MB/day for a 10,000-node graph at 15-min cadence).

**Sync strategy:**
- **Bootstrap:** ARG bulk query on deployment — query all resource types and relationships
- **Incremental sync:** Azure Resource Graph polling every 15 minutes for changes
- **Real-time enrichment:** Activity Log stream enriches the graph on resource create/update/delete events
- **OTel service dependency (best-effort enrichment):** Parse App Insights dependency telemetry to add `Service → CALLS → Service` edges (application-layer topology vs. infra-layer). This edge type requires that monitored applications are instrumented with distributed tracing. For VMs running uninstrumented custom apps or Arc servers, this telemetry may not exist. Treat these edges as optional enrichment — their absence does not block core topology functionality.

**Graph API endpoints:**
- `GET /api/v1/topology/graph?resource_id={id}&depth={n}` — subgraph centered on a resource, n hops out
- `GET /api/v1/topology/blast-radius?resource_id={id}` — what resources depend on this one
- `GET /api/v1/topology/path?from={id}&to={id}` — shortest dependency path between two resources
- `GET /api/v1/topology/snapshot?timestamp={iso}` — topology state at a past point in time (for incident replay)

**Agent integration:**
- Every domain agent investigation automatically calls `get_blast_radius(affected_resource_id)` as a mandatory triage step
- Orchestrator uses `get_topology_path` to identify cascade paths before routing
- Topology tab in Web UI replaced with interactive graph visualization (D3.js or Cytoscape.js)

**Must-haves:** Graph built for all resources in target subscription(s); blast-radius query returns results within 2 seconds; graph freshness lag <15 minutes; used by at least one agent tool during investigation.

---

### Phase 23: Change Correlation Engine
**Track:** 2 — Stage 4 Intelligence
**Depends on:** Phase 22 (topology graph enables change impact scoping)
**Goal:** Automatically correlate every incident with Azure resource changes that occurred in the preceding time window. "This database started failing 4 minutes after this VM was resized" should surface automatically, not require human investigation.

**Change sources (external only):**
- Azure Activity Log (ARM operations: create, update, delete, action)
- Azure Deployment events (template deployments, scale events)
- Kubernetes resource changes (AKS/Arc — pod restarts, configmap updates, image deployments)
- Policy compliance state changes

*Note: Internal platform changes (container image updates, agent framework version bumps) are explicitly excluded from the external change correlation pipeline to prevent false correlations. Platform-internal changes are tracked in a separate internal change log and surfaced only in the Platform Health dashboard (Phase 28).*

**Correlation algorithm:**
1. On incident creation: query Activity Log for all changes affecting the incident's resource and its topology neighbors (1–2 hops) in the preceding configurable window (default: 60 minutes)
2. Rank changes by: temporal proximity (closer = higher rank), topological distance (same resource > neighbor > 2-hop), change type (deployments > scale events > config changes > reads)
3. Surface top-3 correlated changes as structured `ChangeCorrelation` objects on the incident
4. Store correlation scores for feedback loop (operator can mark a correlation as "caused this" → train ranking model)

**Data model additions to `IncidentSummary`:**
```python
class ChangeCorrelation(BaseModel):
    change_id: str
    change_type: str  # "deployment" | "scale" | "config" | "delete"
    resource_id: str
    resource_name: str
    operator: str  # who made the change
    changed_at: datetime
    temporal_gap_minutes: float
    topological_distance: int  # 0 = same resource, 1 = direct dep, 2 = 2-hop
    correlation_score: float  # 0–1
    change_summary: str  # human-readable description of what changed

class IncidentSummary(BaseModel):
    # ... existing fields ...
    correlated_changes: list[ChangeCorrelation] = []
    change_correlation_window_minutes: int = 60
```

**UI integration:**
- AlertFeed row: "🔧 Recent change" badge when correlated_changes is non-empty
- VMDetailPanel: "Correlated Changes" section showing ranked changes with timeline
- Chat: orchestrator automatically includes top correlated change in its initial triage context

**Must-haves:** Change correlation computed within 30 seconds of incident creation; top-1 correlation is accurate (validated against 10 simulated change→failure test cases); surfaced in Web UI and agent investigation context.

---

### Phase 24: Alert Intelligence & Noise Reduction
**Track:** 2 — Stage 4 Intelligence
**Depends on:** Phase 22 (topology graph), Phase 23 (change correlation)
**Goal:** Reduce alert noise by ≥80% through topology-aware causal suppression, temporal deduplication, and incident severity scoring. Transform alert floods into actionable incident streams.

**Capabilities:**

**1. Topology-aware causal suppression:**
When a root-cause resource is identified as degraded, automatically suppress alerts from resources that are topologically downstream. If `db-primary` is failing and 5 services that call it start alerting, only `db-primary` creates an incident. The downstream services are linked as "affected" rather than generating independent incidents.
- Uses Phase 22 topology graph to identify downstream dependencies
- Suppression window: configurable (default: 30 minutes)
- Suppression is never permanent — if root cause resolves but downstream continues, downstream graduates to its own incident

**2. Multi-dimensional alert correlation:**
Group alerts into incidents using three dimensions simultaneously:
- **Temporal:** alerts within a configurable window (default: 5 min)
- **Topological:** alerts on resources within 2 topology hops of each other
- **Semantic:** embedding similarity of alert title/description (cosine similarity >0.85)
Any two alerts that match on ≥2 dimensions are grouped into the same incident. The cosine similarity threshold (default: 0.85) is exposed as a configurable parameter and calibrated against a corpus of ≥50 simulated alerts before shipping. A Phase 24 must-have validates threshold precision/recall before the feature is considered complete.

**3. Incident severity scoring:**
Replace raw alert severity (Sev0–Sev4) with a composite score:
```
composite_severity = (
  alert_severity_score * 0.3 +
  blast_radius_score * 0.3 +        # how many resources affected
  slo_risk_score * 0.25 +            # Phase 25: how close to SLO breach
  business_tier_score * 0.15         # resource business tier (critical/standard/low)
)
```

**4. Noise metrics dashboard:**
- "Alert noise ratio" — what % of raw alerts were suppressed/grouped
- "Incidents created per day" vs. "alerts fired per day"
- Suppression accuracy (operator feedback: was this suppression correct?)

**Must-haves:** Measurable noise reduction on simulated alert storm (20 related alerts → 1–3 incidents); causal suppression used during at least one live incident; noise ratio visible in Observability tab.

---

### Phase 25: Institutional Memory & SLO Tracking
**Track:** 2 — Stage 4 Intelligence
**Depends on:** Phase 24 (enriched incident data to learn from)
**Goal:** Give the platform memory. Every resolved investigation becomes institutional knowledge. New incidents automatically benefit from historical pattern matching. SLOs are tracked per service tier with error budget awareness.

**Institutional Memory:**

**Incident embedding store (pgvector):**
On incident resolution, generate an embedding from: `incident_type + affected_resource_type + root_cause_summary + resolution_steps`. Store in `incident_memory` pgvector table alongside the full investigation transcript.

**Retrieval during triage:**
When a new incident arrives, query for top-3 similar historical incidents (cosine similarity). Surface as:
```
📚 Similar historical incidents (3 matches):
  1. [2026-03-15] db-westus-01: Memory pressure → slow queries — resolved by scaling to D4s_v3 (similarity: 0.94)
  2. [2026-02-28] db-eastus-02: Same pattern, caused by runaway batch job — resolved by job termination (similarity: 0.91)
  3. [2026-01-10] db-centralus-01: Memory leak in application v2.3.1 — resolved by rollback (similarity: 0.87)
```

**Postmortem ingestion:**
- `POST /api/v1/postmortems` — ingest structured postmortem documents (markdown)
- Chunked, embedded, stored in pgvector alongside incident history
- Runbook search now queries both runbooks and postmortems

**Pattern detection (weekly scheduled job):**
A scheduled Container App job (preferred; aligns with platform's container-native architecture and has direct access to both Cosmos DB and PostgreSQL) runs weekly. Fabric Notebook is an acceptable alternative if Fabric capacity is already provisioned and operational (Phase 21). The job:
- Clusters last 30 days of incidents by root-cause pattern
- Identifies systemic issues: "database memory pressure accounts for 8/23 P1 incidents this month"
- Stores pattern report in Cosmos DB; surfaced in new "Patterns" section of Observability tab

**SLO Tracking:**

**SLO definition model:**
```python
class SLODefinition(BaseModel):
    id: str
    name: str  # "VM Availability - Production"
    resource_tier: str  # "production" | "staging" | "development"
    resource_tags: dict  # {"env": "prod", "criticality": "high"}
    target_availability_pct: float  # 99.9
    window_days: int  # 30
    error_budget_minutes: float  # computed: window * (1 - target) * 1440
```

**Error budget tracking:**
- Computed in real-time from incident duration data in Cosmos DB
- `GET /api/v1/slo` — list all SLOs with current error budget remaining
- `GET /api/v1/slo/{id}/burn-rate` — current burn rate (1.0 = consuming at exactly target rate; >3.0 = fast burn alert)
- Alert when burn rate >2x for 1 hour or >3x for 15 minutes (Google SRE-inspired burn rate alerts)

**SLO-aware incident prioritization:**
- Every incident enriched with `slo_impact: { slo_id, minutes_until_breach, current_burn_rate }`
- Incidents with `minutes_until_breach < 120` get auto-escalated to P1 regardless of raw alert severity
- Observability tab: SLO health cards with error budget burn meters

**Must-haves:** Historical match surfaces in at least 1 of every 3 incidents (validated against simulated incident corpus); SLO breach prediction alerts firing correctly; pattern report runs weekly and appears in Observability tab.

---

### Phase 26: Predictive Operations
**Track:** 3 — Stage 5 Autonomy
**Depends on:** Phase 25 (historical data, SLO tracking)
**Goal:** Move from reactive alerting to proactive prevention. The platform should identify resources heading toward failure before they alert, giving operators a window to act before user impact.

**Forecasting capabilities:**

**1. Time-series anomaly detection (Azure Monitor Metrics):**
For each monitored resource, maintain a rolling baseline of metric behavior:
- Compute: CPU utilization, memory commit bytes, disk queue length
- Network: bytes in/out, dropped packets, connection timeouts
- Storage: IOPS, latency, capacity remaining
- Database: DTU/vCore utilization, connection count, deadlocks/min

Detection method: Azure Monitor Dynamic Thresholds (built-in, handles intra-day/intra-week seasonality) used for threshold-based detection. Custom ARIMA-based forecasting used specifically for capacity exhaustion projections and time-to-breach estimates — these require "when will X be reached at current rate" predictions that Azure Monitor Dynamic Thresholds don't natively produce. Custom forecasting is limited to capacity-type metrics (disk fill rate, connection pool exhaustion, memory growth rate); all other anomaly detection delegates to Azure Monitor.

**2. Capacity exhaustion forecasting:**
For storage and quota-constrained resources:
- Project disk fill rate → "Disk `datadisk-01` will be full in 14 days at current write rate"
- Project memory growth → "Container memory will OOM in ~4 hours if growth rate continues"
- Project connection pool exhaustion → "PostgreSQL max_connections will be reached in ~2 hours"

**3. Seasonal baseline learning:**
- Per-resource daily/weekly seasonality profiles stored in Cosmos DB time-series
- "Monday morning CPU spike" is baseline, not an alert
- First occurrence of a metric exceeding seasonal baseline by >2σ triggers investigation

**4. Pre-incident early warning signals:**
- Subtle log error rate increases (5% above baseline for 15 min = early warning)
- Increasing latency trend (P95 growing while P50 is stable = connection pool or GC pressure)
- Dependency health degradation (upstream service response time trending up)

**New endpoints:**
- `GET /api/v1/forecasts` — list active forecasts with time-to-breach estimates
- `GET /api/v1/forecasts/{resource_id}` — detailed forecast for a resource
- `POST /api/v1/forecasts/refresh` — trigger re-computation of all forecasts

**UI integration:**
- New "Forecasts" tab in dashboard (or section within Observability)
- Resources tab: "⚠️ Forecast" badge on resources with active forecasts
- VMDetailPanel: forecast section below metrics charts

**Must-haves:** At least 3 metric types forecasted per VM; seasonal baseline learning handles weekday/weekend patterns; forecast accuracy validated against historical incident corpus (predicted at least 70% of past incidents ≥30 min before they would have alerted); forecasts visible in Web UI.

---

### Phase 27: Closed-Loop Remediation
**Track:** 3 — Stage 5 Autonomy
**Depends on:** Phase 26 (predictive data), Phase 25 (institutional memory for runbook selection), Phase 22 (topology for blast-radius gating)
**Goal:** Complete the remediation loop. The platform already has HITL approval gates. Phase 27 adds execution, verification, and rollback — making the platform capable of running a remediation action end-to-end with a single human approval, then automatically verifying it worked.

**Remediation pipeline:**
```
Incident → Triage → Root Cause → Runbook Selection (RAG) → Proposal Generation →
Human Approval → Pre-flight Checks → Execution → Verification → Resolution OR Rollback
```

**Pre-flight checks (before execution, after approval):**
1. Blast radius: confirm no new failures appeared since approval was given
2. Resource state: confirm target resource still exists and is in expected state (ETag check)
3. Change freeze: check if resource is in a tagged change freeze window
4. Cost estimate: calculate additional cost of the remediation action (scale-up, etc.)
5. Rollback plan: confirm automated rollback is possible; if not, require manual acknowledgment

**Execution layer (new `RemediationExecutor` service):**
- `restart_vm(resource_id)` — ARM `POST .../restart`; safe for non-production or approved production
- `scale_vm(resource_id, new_size)` — ARM resize; requires approval + blast-radius check
- `drain_and_restart_aks_node(cluster_id, node_name)` — cordons node, drains pods, restarts
- `flush_redis_key_pattern(endpoint, pattern)` — for cache poisoning scenarios
- `restart_container_app_revision(app_id)` — zero-downtime rolling restart via Container Apps
- `apply_nsg_rule(nsg_id, rule)` — add/modify NSG rule with mandatory review window
- `run_arc_command(machine_id, command)` — Arc Run Command for shell-level remediation (highest privilege; requires explicit operator confirmation in addition to standard approval)
- `trigger_aks_gitops_sync(cluster_id, repo_path)` — Flux reconcile for GitOps-managed clusters

**Verification step (after execution, automated):**
1. Wait configurable settling period (default: 3 minutes)
2. Re-query the primary symptom metric(s) from the incident
3. Compare to pre-incident baseline
4. Decision:
   - `RESOLVED` → mark incident resolved; post resolution card to Teams; update institutional memory
   - `IMPROVED` → metrics improved but not fully resolved; offer escalation or additional action
   - `DEGRADED` → metrics worsened or new failures appeared → **auto-rollback triggered**
   - `TIMEOUT` → verification inconclusive after 10 minutes → escalate to human

**Rollback:**
Every remediation action generates a rollback plan before execution:
- Scale-up → rollback: scale back to original size after 30 minutes if no human confirmation to keep
- NSG rule add → rollback: remove rule after configurable window if no confirmation
- Restart → rollback: N/A (idempotent); log only
- Run Command → rollback: N/A (operator-defined); require explicit "rollback plan" field in proposal

**Atomicity and write-ahead log:**
All remediation actions use a write-ahead log pattern: the audit record is written with `status: pending` to `remediation-audit` *before* any ARM API call is made. After the action completes (success or failure), the record is updated to `status: completed` or `status: failed`. If the executor crashes mid-action, the `pending` record triggers an automatic alert — an operator is notified of an action with unknown outcome. Non-idempotent actions (NSG rule add, scale) are checked for duplicate `pending` records before execution to prevent double-application.

**Immutable audit trail:**
Every automated action written to append-only Cosmos DB container `remediation-audit`:
```json
{
  "incident_id": "...",
  "action": "scale_vm",
  "resource_id": "...",
  "approved_by": "user@contoso.com",
  "approved_at": "2026-04-02T12:00:00Z",
  "executed_at": "2026-04-02T12:00:05Z",
  "execution_result": "success",
  "verification_result": "RESOLVED",
  "rollback_plan": {...},
  "pre_flight_checks": {...}
}
```
Exposed via `GET /api/v1/remediation-audit` for compliance export.

**Must-haves:** Full pipeline executed end-to-end on at least one simulated incident (scale action or restart); verification step fires and correctly classifies RESOLVED vs. DEGRADED; rollback triggered when verification returns DEGRADED; audit trail written and exportable; pre-flight blast-radius check prevents execution when new failures detected post-approval.

---

### Phase 28: Platform Intelligence
**Track:** 3 — Stage 5 Autonomy
**Depends on:** Phase 27 (full remediation data), Phase 25 (institutional memory mature)
**Goal:** Synthesize everything the platform has learned into actionable platform-wide intelligence. Identify systemic issues, quantify their business impact, and drive continuous improvement. Complete the learning loop so the platform gets measurably better over time.

**Capabilities:**

**1. Systemic pattern analysis:**
Weekly analysis job (Azure Function or Fabric Notebook) scans all resolved incidents:
- K-means clustering of incident embeddings → identifies recurring pattern families
- "Top 5 systemic issues" report: root cause pattern, frequency, total MTTR consumed, estimated cost impact
- Trend detection: is a pattern improving or worsening month-over-month?
- Surfaced in "Intelligence" section of Observability tab

**2. Team/service health scoring:**
Per subscription, resource group, and application owner tag:
- Incident rate (per resource per week)
- Mean time to detection (MTTD)
- Mean time to resolution (MTTR)
- Auto-remediation success rate
- SLO compliance percentage
- Stored as time-series; trend visible over 30/60/90 day windows

**3. FinOps integration:**

**Operator configuration:**
- `POST /api/v1/admin/business-tiers` — operators configure revenue-per-hour per resource tier (e.g., `{"tier": "production-critical", "revenue_per_hour_usd": 15000}`)
- Default config seeded with zero values on Phase 28 deployment; operators update to match actual business context
- Business tier derived from resource tags (`env`, `criticality`, `team`)

**Cost metrics tracked:**
- Incident cost impact: `incident_cost_per_hour = wasted_compute_cost + estimated_revenue_impact`
  - Wasted compute: Azure Cost Management API → cost of degraded resources during incident window
  - Revenue impact: configurable revenue-per-hour per resource tier (from admin config above)
- "Cost saved by auto-remediation" metric: sum of incident_cost * (hours_without_auto_remediation - actual_hours)
- FinOps tab in dashboard: top 10 costliest incident patterns, cost savings from automation

**4. Continuous learning loop:**
- Every operator action (approved/rejected proposal, feedback on correlation accuracy) is logged
- Weekly feedback digest: "18 approvals, 2 rejections — what did rejected proposals have in common?"
- Agent system prompts evolve: monthly review proposes system prompt improvements based on feedback patterns
- Runbook quality scoring: which runbooks are used + effective vs. retrieved but not acted on

**5. Platform health dashboard:**
A new high-level "Platform Health" view visible to administrators:
- Detection pipeline lag (P50, P95)
- Agent response time (P50, P95 per agent)
- Auto-remediation success rate (last 30 days)
- SLO compliance across all monitored resources
- Error budget burn rates (portfolio view)
- Alert noise ratio (raw alerts vs. incidents created)
- Cost savings from automation (rolling 30 days)

**Must-haves:** Systemic pattern report runs on schedule and surfaces in UI; at least 3 FinOps metrics tracked and displayed; platform health dashboard functional with real data; continuous learning feedback loop captures operator approve/reject decisions.

---

## Dependency Graph

```
Phase 18 (Complete)
    └── Phase 19: Production Stabilisation
            ├── Phase 20: Network & Security Agent Depth
            └── Phase 21: Detection Plane Activation
                    └── Phase 22: Resource Topology Graph
                            ├── Phase 23: Change Correlation Engine
                            │       └── Phase 24: Alert Intelligence
                            │               └── Phase 25: Institutional Memory & SLO
                            │                       ├── Phase 26: Predictive Operations
                            │                       │       └── Phase 27: Closed-Loop Remediation
                            │                       │               └── Phase 28: Platform Intelligence
                            │                       └── Phase 28 (also depends on 27)
                            └── Phase 24 (also depends directly on topology graph)
```

**Sequential execution required across all 10 phases** — each builds on prior infrastructure. Phases 20 and 21 can run in parallel after Phase 19.

---

## Requirements Added (v2.0)

### PROD (Production Readiness)
| ID | Requirement |
|----|-------------|
| PROD-001 | Entra authentication enforced on all non-health API endpoints |
| PROD-002 | Azure MCP Server authenticated via managed identity; no external-ingress unauthenticated access |
| PROD-003 | All 8 domain agent MCP tool groups registered in Foundry; each agent exercises its domain tools in integration test |
| PROD-004 | Live alert detection loop operational without simulation scripts |
| PROD-005 | Teams proactive alerting delivers Adaptive Cards within 2 minutes of incident creation |

### TOPO (Topology)
| ID | Requirement |
|----|-------------|
| TOPO-001 | Resource property graph maintains all Azure resource types and their relationships |
| TOPO-002 | Blast-radius query returns results within 2 seconds |
| TOPO-003 | Topology graph freshness lag <15 minutes |
| TOPO-004 | Topology used by domain agents as mandatory triage step |
| TOPO-005 | Blast-radius query latency validated at representative production scale (≥10,000 nodes) before Phase 26 kicks off; if P95 >2s, storage layer migration is planned before proceeding |

### INTEL (Intelligence)
| ID | Requirement |
|----|-------------|
| INTEL-001 | Alert noise reduction ≥80% on correlated alert storm simulations |
| INTEL-002 | Change correlation surfaces correct cause within 30 seconds of incident creation |
| INTEL-003 | Historical incident match surfaces in ≥33% of new incidents |
| INTEL-004 | SLO breach prediction alerts fire before threshold is crossed |
| INTEL-005 | Forecasts predict metric breaches ≥30 minutes in advance with ≥70% accuracy |

### REMEDI (Enhanced Remediation)
*Extends REMEDI-001 through REMEDI-008 from Phase 5; REMEDI-009 is reserved for closed-loop verification audit (previously informal, now formalised here).*

| ID | Requirement |
|----|-------------|
| REMEDI-009 | Closed-loop verification step fires within 10 minutes after remediation execution; result classified as RESOLVED / IMPROVED / DEGRADED / TIMEOUT |
| REMEDI-010 | Automated remediation includes pre-flight blast-radius check; aborts if new failures detected post-approval |
| REMEDI-011 | Write-ahead log pattern: audit record written with `status: pending` before any ARM API call; updated after completion; `pending` records >10 min trigger operator alert |
| REMEDI-012 | Auto-rollback triggered when verification returns DEGRADED |
| REMEDI-013 | Immutable audit trail written for every automated action; exportable for compliance |

### PLATINT (Platform Intelligence)
| ID | Requirement |
|----|-------------|
| PLATINT-001 | Systemic pattern analysis runs on schedule; top-5 issues surfaced in UI |
| PLATINT-002 | FinOps integration tracks incident cost impact and automation savings |
| PLATINT-003 | Operator feedback (approve/reject) captured and fed to learning loop |
| PLATINT-004 | `POST /api/v1/admin/business-tiers` endpoint available; default zero-value config seeded on deployment |

---

## Success Criteria for "World-Class"

When all 10 phases complete, the platform should demonstrate:

1. **MTTR <30 minutes** for 80% of P1/P2 incidents (measured from detection to resolution)
2. **Alert noise reduction >90%** (raw alerts to actionable incidents ratio)
3. **Auto-remediation rate >40%** (incidents resolved via automated action with human approval, no manual investigation needed)
4. **SLO compliance >99.5%** for production-tier resources
5. **Zero manual simulation scripts** — all incidents flow from real Azure Monitor detection
6. **Complete audit trail** — every automated action attributable, reviewable, and exportable
7. **Predictive prevention** — at least 30% of incidents caught in "forecast" state before they alert
8. **Institutional memory recall** — historical pattern match for >50% of repeating incident types
