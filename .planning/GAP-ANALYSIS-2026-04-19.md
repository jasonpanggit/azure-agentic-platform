# AAP Gap Analysis — 2026-04-19

> Scope: Full platform audit across Azure resource coverage, agent tool capabilities, and UI/dashboard completeness.
> Method: Direct inspection of source files — `services/api-gateway/`, `agents/*/tools.py`, `services/web-ui/components/`.

---

## 1. Executive Summary

The platform has a **strong operational core** — incident management, VM/VMSS/AKS diagnostics, patching, EOL detection, NSG audits, cost monitoring, and Defender integration are all genuinely implemented. The multi-agent framework (13 specialist agents), MCP wiring, and detection plane are well-architected.

However, three classes of gaps stand out:

| Category | Gap Severity | Operator Impact |
|----------|-------------|----------------|
| **Orphaned UI tabs** — 9 fully-built tabs not wired into any hub | 🔴 Critical | Working features invisible to operators |
| **Storage agent stubs** — 3 tools return empty payloads (no SDK calls) | 🔴 Critical | Storage investigations produce no data |
| **Network coverage holes** — Firewall, DNS, VPN Gateway, Bastion absent from agent + UI | 🟠 High | Common Azure network resources undiagnosable |
| **No dedicated UI for 4 new agents** — ContainerApps, Messaging, Database, FinOps agents exist but have zero UI surfaces | 🟠 High | Agent investment wasted without UI |
| **AuditHub too narrow** — only 2 sub-tabs (audit log, agent traces); missing runbook history, alert rules, lock audit, tagging | 🟡 Medium | Compliance/governance workflows buried |

### Priority Matrix

```
Impact ↑
  HIGH │ [Storage stubs] [Orphaned tabs]
       │ [Missing network types] [Agent-UI disconnect]
MEDIUM │ [AuditHub gaps] [SRE remediation] [Security agent: no firewall/WAF]
   LOW │ [AKS depth] [APIM/CDN/DNS coverage]
       └──────────────────────────────────→ Effort
              LOW        MEDIUM       HIGH
```

---

## 2. Azure Resource Coverage

### 2.1 Coverage Table

| Azure Domain | Resource Type | API Gateway Coverage | Agent Coverage | UI Tab | Gap Level |
|---|---|---|---|---|---|
| **Compute** | Virtual Machines | ✅ `vm_inventory.py`, `vm_detail.py` | ✅ Compute agent — 20+ tools | ✅ `VMTab`, `VMDetailPanel` | None |
| **Compute** | VMSS | ✅ `vmss_endpoints.py` | ✅ Compute agent | ✅ `VMSSTab`, `VMSSDetailPanel` | None |
| **Compute** | AKS | ✅ `aks_endpoints.py`, `aks_health_endpoints.py` | ✅ Compute agent (`query_aks_cluster_health`, `query_aks_node_pools`, `query_aks_upgrade_profile`) | ✅ `AKSTab`, `AKSDetailPanel`, `AKSHealthTab` | Shallow — no workload (pod/deployment) drill-down in agent |
| **Compute** | App Service / Functions | ✅ `app_service_endpoints.py`, `app_service_health_service.py` | ✅ AppService agent (`get_app_service_health`, `get_function_app_health`, `propose_app_service_restart`) | ⚠️ `AppServiceHealthTab` exists but **orphaned** — not wired into any HubTab | **HIGH: tab not accessible** |
| **Compute** | Azure Disks | ✅ `disk_audit_endpoints.py` | Compute agent (via `query_disk_health`) | ✅ `DiskAuditTab` in ResourcesHub | None |
| **Networking** | NSG | ✅ `nsg_audit_service.py` | ✅ Network agent (`query_nsg_rules`) | ⚠️ `NsgAuditTab` **orphaned** | HIGH |
| **Networking** | VNet / Peering | ✅ `vnet_peering_endpoints.py` | ✅ Network agent (`query_vnet_topology`, `query_peering_status`) | ✅ `VNetPeeringTab`, `NetworkTopologyTab` | None |
| **Networking** | Load Balancer | ✅ `lb_health_endpoints.py` | ✅ Network agent (`query_load_balancer_health`) | ✅ `LBHealthTab` | None |
| **Networking** | Private Endpoints | ✅ `private_endpoint_endpoints.py` | Partial (network topology includes PE data) | ✅ `PrivateEndpointTab` | None |
| **Networking** | ExpressRoute | — | ✅ Network agent (`query_expressroute_health`) | ❌ No UI tab | MEDIUM |
| **Networking** | **Azure Firewall** | ❌ No endpoint | ❌ No agent tool | ❌ No UI tab | **HIGH** |
| **Networking** | **Azure DNS / Private DNS** | ❌ No endpoint | ❌ No agent tool | ❌ No UI tab | MEDIUM |
| **Networking** | **VPN Gateway / Bastion** | ❌ No endpoint | ❌ No agent tool | ❌ No UI tab | MEDIUM |
| **Networking** | **Azure Front Door / CDN** | ❌ No endpoint | ❌ No agent tool | ❌ No UI tab | LOW |
| **Storage** | Storage Accounts | ✅ `storage_security_endpoints.py` | ⚠️ Storage agent — 3 tools that **return empty payloads** (no SDK calls) | ✅ `StorageSecurityTab` | **CRITICAL: agent stubs** |
| **Storage** | Azure File Sync | — | ⚠️ `query_file_sync_health` — stub (returns empty `sync_errors: []`) | — | HIGH |
| **Storage** | Azure Managed Lustre | ❌ | ❌ | ❌ | LOW |
| **Databases** | Cosmos DB | — | ✅ Database agent (`get_cosmos_account_health`, `get_cosmos_throughput_metrics`, `query_cosmos_diagnostic_logs`, `propose_cosmos_throughput_scale`) | ❌ **No UI tab** | HIGH |
| **Databases** | PostgreSQL Flexible | — | ✅ Database agent (`get_postgres_server_health`, `query_postgres_slow_queries`, `propose_postgres_sku_scale`) | ❌ **No UI tab** | HIGH |
| **Databases** | Azure SQL | — | ✅ Database agent (`get_sql_database_health`, `get_sql_dtu_metrics`, `query_sql_query_store`, `propose_sql_elastic_pool_move`) | ❌ **No UI tab** | HIGH |
| **Databases** | **Azure Redis Cache** | ❌ No endpoint | ❌ No agent tool | ❌ No UI tab | MEDIUM |
| **Containers** | Container Apps | — | ✅ ContainerApps agent (`list_container_apps`, `get_container_app_health`, `get_container_app_metrics`, `propose_container_app_scale`) | ❌ **No dedicated UI tab** | HIGH |
| **Containers** | Container Instances (ACI) | ❌ | ❌ (deferred per CLAUDE.md) | ❌ | N/A (by design) |
| **Containers** | ACR | Partial (inventory via ARG) | — | Partial (ResourcesTab) | LOW |
| **Messaging** | Service Bus | ✅ `queue_depth_endpoints.py` | ✅ Messaging agent (`get_servicebus_namespace_health`, `list_servicebus_queues`, `get_servicebus_metrics`, `propose_servicebus_dlq_purge`) | ✅ `QueueDepthTab` — BUT **orphaned** (not in any HubTab) | HIGH |
| **Messaging** | Event Hubs | ✅ `queue_depth_endpoints.py` | ✅ Messaging agent (`get_eventhub_namespace_health`, `list_eventhub_consumer_groups`, `get_eventhub_metrics`) | ⚠️ Same QueueDepthTab (orphaned) | HIGH |
| **Messaging** | Event Grid | ❌ | ❌ | ❌ | LOW |
| **Security** | Defender for Cloud | ✅ `defender_endpoints.py` | ✅ Security agent (`query_defender_alerts`, `query_secure_score`) | ✅ `DefenderTab` (in SecurityHub) | None |
| **Security** | Key Vault | ✅ (cert_expiry, identity_risk) | ✅ Security agent (`query_keyvault_diagnostics`) | ✅ `CertExpiryTab` | None |
| **Security** | RBAC / IAM | ✅ `identity_risk_endpoints.py` | ✅ Security agent (`query_iam_changes`, `query_rbac_assignments`) | ✅ `IdentityRiskTab` | None |
| **Security** | CVE / Vulnerability | ✅ `cve_endpoints.py` | ✅ Patch agent (`lookup_kb_cves`) | ✅ `CVETab` (in VMDetailPanel only) | MEDIUM — not in fleet-level SecurityHub |
| **Security** | **Azure WAF / DDoS** | ❌ | ❌ | ❌ | MEDIUM |
| **Monitoring** | Azure Monitor / Log Analytics | ✅ (used throughout) | ✅ (used throughout) | ✅ `ObservabilityTab` | None |
| **Monitoring** | Application Insights | — | AppService agent (`query_app_insights_failures`) | ❌ No standalone UI | MEDIUM |
| **Monitoring** | Alert Rules | ✅ `alert_rule_audit_endpoints.py` | — | ⚠️ `AlertRuleAuditTab` **orphaned** | HIGH |
| **Monitoring** | Azure Monitor Workbooks | ❌ | ❌ | ❌ | LOW |
| **Governance** | Azure Policy | ✅ `policy_compliance_service.py` | ✅ Security agent (`query_policy_compliance`) | ⚠️ `PolicyComplianceTab` **orphaned** | HIGH |
| **Governance** | Resource Locks | ✅ `lock_audit_endpoints.py` | — | ⚠️ `LockAuditTab` **orphaned** | MEDIUM |
| **Governance** | Tagging Compliance | ✅ `tagging_endpoints.py` | — | ⚠️ `TaggingComplianceTab` **orphaned** | MEDIUM |
| **Cost** | Cost Management | ✅ `cost_endpoints.py` | ✅ FinOps agent (`get_subscription_cost_breakdown`, `get_cost_forecast`, `get_top_cost_drivers`) | ✅ `CostTab` | None |
| **Cost** | Cost Anomaly | ✅ `finops_endpoints.py` | ✅ FinOps agent | ⚠️ `CostAnomalyTab` **orphaned** | HIGH |
| **Cost** | Reserved Instances | — | ✅ FinOps agent (`get_reserved_instance_utilisation`) | ❌ No UI | MEDIUM |
| **DevOps** | AKS Upgrade | — | ✅ Compute agent (`query_aks_upgrade_profile`) | ❌ No UI surface | LOW |
| **Identity** | Azure Arc | ✅ Custom Arc MCP server | ✅ Arc agent (9 tools) | ✅ PatchTab (Arc VMs) | None (known gap: PR #38) |
| **PaaS** | **Azure API Management** | ❌ | ❌ | ❌ | LOW |
| **PaaS** | **Azure Automation / Logic Apps** | ❌ | ❌ | ❌ | LOW |

---

## 3. Agent Tool Capability Gaps

### 3.1 Per-Agent Gap Table

| Agent | Tools Count | Real SDK Calls? | Key Gaps |
|---|---|---|---|
| **Orchestrator** | 3 helpers (not `@ai_function` tools) | N/A | No self-routing debug capability; no multi-domain status summary tool |
| **Compute** | 20 `@ai_function` tools | ✅ Full (ARG, Monitor, Log Analytics, ComputeManagementClient) | Missing: `query_container_app_health` delegates to SRE; no AKS workload (pod inventory) tool; no VM run-command execution tool |
| **Network** | 7 tools | ✅ Full (NetworkManagementClient + ARG) | Missing: Azure Firewall policy query; DNS zone health; VPN Gateway tunnel status; Azure Bastion session audit; application gateway health |
| **Storage** | 3 tools | 🔴 **STUBS** — all return empty payloads | `query_storage_metrics` → `"metrics": []`; `query_blob_diagnostics` → `"recent_operations": []`; `query_file_sync_health` → `"sync_errors": []`. No `from azure` import. Entirely relies on MCP `storage` namespace but tool bodies never dispatch MCP calls. |
| **Security** | 7 tools | ✅ Full (SecurityCenter, ARG, Monitor) | Missing: WAF/Firewall policy query; DDoS protection status; Managed Identity risk; privileged identity management (PIM) alerts |
| **Arc** | 8 tools | ✅ Full (HybridCompute SDK + MCP) | Missing: Arc data services (SQL MI, PostgreSQL) health; Arc-enabled K8s GitOps status |
| **SRE** | 9 tools | ✅ Full (Monitor, Advisor, ARG) | `propose_remediation` creates a recommendation but has no approval-gate wiring to the approval queue; missing SLO burn-rate alerting tool |
| **Patch** | 10 tools | ✅ Full (ARG, Log Analytics) | Missing: patch rollback proposal; WSUS/Update Manager compliance reporting tool |
| **EOL** | 10 tools | ✅ Full (endoflife.date API + MS Lifecycle + ARG) | None significant |
| **ContainerApps** | 6 tools | ✅ Full (Container Apps SDK) | Missing: ingress health / TLS termination check; revision traffic split query |
| **Messaging** | 8 tools | ✅ Full (Service Bus + Event Hubs SDK) | Missing: Event Grid topic/subscription health; dead-letter replay proposal; connection string rotation proposal |
| **FinOps** | 7 tools | ✅ Full (Cost Management API) | Missing: Reserved Instance purchase recommendation; cost allocation tag analysis; savings plan utilization |
| **Database** | 12 tools | ✅ Full (Cosmos, PostgreSQL, SQL SDKs) | Missing: Redis Cache health; Azure SQL Managed Instance (separate from Azure SQL); MySQL Flexible Server |
| **AppService** | 6 tools | ✅ Full (App Service SDK + App Insights) | Missing: deployment slot swap health check; App Service plan scaling proposal; custom domain / TLS certificate expiry |

### 3.2 Critical: Storage Agent Stubs

**File:** `agents/storage/tools.py` (165 lines)

The storage agent has **no Azure SDK imports**. All three tools return hardcoded empty responses:

```python
# query_storage_metrics — line 64
return {
    "metrics": [],          # always empty
    "query_status": "success",
}

# query_blob_diagnostics — line 111
return {
    "error_summary": {},    # always empty
    "recent_operations": [], # always empty
    "query_status": "success",
}

# query_file_sync_health — line 158
return {
    "sync_health": "Unknown",  # always Unknown
    "sync_errors": [],         # always empty
    "query_status": "success",
}
```

The storage agent's `ALLOWED_MCP_TOOLS` list (`["storage", "fileshares", "monitor", "resourcehealth"]`) indicates the intent is to use Azure MCP Server's `storage` namespace — but the tool bodies never invoke MCP. The agent will always return empty data when invoked on a storage incident.

### 3.3 Network Agent: Missing Resource Types

`agents/network/tools.py` covers NSG, VNet topology, Load Balancer, VNet Peering, Flow Logs, ExpressRoute, and connectivity checks. Absent:

- **Azure Firewall** (`Microsoft.Network/azureFirewalls`) — no `query_firewall_policy` or `query_firewall_logs` tool
- **Application Gateway / WAF** — no health or rule query tool
- **VPN Gateway** (`Microsoft.Network/virtualNetworkGateways`) — no tunnel status tool
- **Azure Bastion** — no session or host health tool
- **Azure DNS / Private DNS Zones** — no zone listing or record health tool

These are common resources in enterprise environments and are the most likely targets for network-related incidents.

---

## 4. UI / Dashboard Gap Analysis

### 4.1 Hub Tab Coverage Summary

| Hub Tab | Sub-Tabs | Completeness |
|---|---|---|
| **Dashboard** (OpsTab) | Live incident feed, correlation groups, advisory panel, approval queue | ✅ Full |
| **Alerts** | Alert feed, filters, timeline | ✅ Full |
| **Resources** | All Resources, VMs, Scale Sets, Kubernetes, Disks, AZ Coverage, Resource Hierarchy | ✅ Full |
| **Network** | Topology Map, VNet Peerings, Load Balancers, Private Endpoints | ⚠️ Missing: NSG Audit, ExpressRoute, Application Gateway, Firewall |
| **Security** | Security Score, Compliance, Identity Risk, Certificates, Backup, Storage Security | ⚠️ Missing: CVE fleet view, Policy Compliance, Alert Rules, WAF |
| **Cost** | Cost & Advisor, Budgets | ⚠️ Missing: Cost Anomaly, Forecast, Reserved Instance utilization |
| **Capacity & Quota** | Quota Usage, Capacity, Quota Limits | ✅ Full |
| **Change** | Patch Management, Deployments, IaC Drift, Maintenance | ✅ Full |
| **Operations** | Runbooks, Simulations, Observability, SLA, Quality | ✅ Full |
| **Audit** | Audit Log, Agent Traces | ⚠️ Missing: Runbook History, Alert Rule Audit, Lock Audit, Tagging Compliance |
| **Admin** | Monitored Subscriptions, Settings | ✅ Full |

### 4.2 Orphaned Tabs (Built but Not Wired Into Any Hub)

These components are fully implemented, pass their own tests, but are **not imported by any HubTab** and therefore completely inaccessible in the UI:

| Component File | Lines | Logical Home | Missing Connection |
|---|---|---|---|
| `AppServiceHealthTab.tsx` | ~400 | ResourcesHub or new "PaaS" sub-tab | Should be in ResourcesHubTab under "App Services" |
| `QueueDepthTab.tsx` | ~350 | New "Messaging" hub or ResourcesHub | No hub includes it |
| `CostAnomalyTab.tsx` | ~370 | CostHubTab | Should be a 3rd sub-tab in `CostHubTab` |
| `AlertCoverageTab.tsx` | ~300 | SecurityHub or AuditHub | Should be in AuditHub under "Alert Coverage" |
| `AlertRuleAuditTab.tsx` | ~250 | AuditHub | Missing from `AuditHubTab` sub-tab list |
| `VMExtensionAuditTab.tsx` | ~350 | ResourcesHub (VM sub-area) or AuditHub | Not wired anywhere |
| `LockAuditTab.tsx` | ~280 | AuditHub | Missing from `AuditHubTab` sub-tab list |
| `TaggingComplianceTab.tsx` | ~300 | AuditHub or SecurityHub | Not wired anywhere |
| `PolicyComplianceTab.tsx` | ~400 | SecurityHub | Should be in SecurityHub under "Policy" |
| `NsgAuditTab.tsx` | ~400 | NetworkHub | Should be a 5th sub-tab in `NetworkHubTab` |

**Total: 10 orphaned tabs** — a significant portion of the UI's operational governance surface.

### 4.3 Missing UI Surfaces for Implemented Agents

The following agents have full tool implementations but **zero dedicated UI tabs**:

| Agent | Tools Available | Missing UI |
|---|---|---|
| **Database** | 12 tools (Cosmos, PostgreSQL, SQL) | No `DatabaseTab` or sub-tab in any Hub |
| **ContainerApps** | 6 tools | `AppServiceHealthTab` covers App Service but no Container Apps panel |
| **Messaging** | 8 tools | `QueueDepthTab` exists but orphaned |
| **FinOps** | 7 tools | Only surfaced via `CostTab`; no RI utilization or idle resource view |

### 4.4 AuditHub — Too Narrow

`AuditHubTab.tsx` (48 lines) has only 2 sub-tabs: **Audit Log** and **Agent Traces**.

The following fully-implemented tabs should logically live here:
- `RunbookHistoryTab` (exists, wired in `RunbookTab` internally — should also be in AuditHub)
- `AlertRuleAuditTab` (orphaned)
- `LockAuditTab` (orphaned)
- `TaggingComplianceTab` (orphaned)
- `AlertCoverageTab` (orphaned)

### 4.5 SecurityHub — Missing CVE Fleet View

`CVETab` is wired **only** inside `VMDetailPanel` (per-VM drill-down). There's no fleet-level CVE exposure view in SecurityHub. Operators can't see "which VMs have critical CVEs" without clicking each VM individually.

---

## 5. Top 10 Highest-Impact Gaps

Prioritized by: (operator daily workflow impact × ease of fix)

### #1 🔴 Fix Storage Agent Stubs
**File:** `agents/storage/tools.py`
**Impact:** Storage incidents always return empty diagnostics. The agent is deployed but functionally useless for real storage triage.
**Fix effort:** Medium — implement MCP `storage` namespace dispatch (or direct `azure-mgmt-storage` SDK calls) in the 3 tool bodies. Pattern exists in `agents/network/tools.py`.

### #2 🔴 Wire 10 Orphaned Tabs Into Hub Navigation
**Files:** `NetworkHubTab.tsx`, `SecurityHubTab.tsx`, `CostHubTab.tsx`, `AuditHubTab.tsx`, `ResourcesHubTab.tsx`
**Impact:** NSG Audit, Policy Compliance, Alert Rules, Cost Anomaly, Queue Depth, App Service Health, VM Extension Audit, Lock Audit, Tagging Compliance, NsgAudit are all built and tested but invisible.
**Fix effort:** Low — each requires adding an import + sub-tab entry + render branch (10–20 lines per hub).

### #3 🟠 Add Azure Firewall Coverage to Network Agent
**Missing:** `query_firewall_policy`, `query_firewall_logs`, `query_firewall_threat_intel` in `agents/network/tools.py`
**Impact:** Azure Firewall is a Tier-1 network resource; blocked traffic and threat intel hits are common incident triggers.
**Fix effort:** Medium — add tools using `NetworkManagementClient.azure_firewalls` + Log Analytics KQL for `AzureDiagnostics | where Category == "AzureFirewallNetworkRule"`.

### #4 🟠 Add Database Hub Sub-Tab to Resources or New Hub
**Impact:** Database agent has 12 tools with Cosmos, PostgreSQL, and SQL coverage — but operators have no UI to view database health. The investment in `agents/database/` is invisible.
**Fix effort:** Medium — create `DatabaseHealthTab.tsx` (~300 lines) + wire into `ResourcesHubTab` or standalone hub.

### #5 🟠 Add CVE Fleet View to SecurityHub
**Files:** `CVETab.tsx` (works per-VM), `SecurityHubTab.tsx`
**Impact:** Security team can't see estate-wide CVE exposure without clicking each VM in a fleet of hundreds.
**Fix effort:** Low-Medium — create `CVEFleetTab.tsx` that calls `GET /api/v1/cve/fleet?subscription_ids=...` (endpoint already exists), wire into SecurityHub.

### #6 🟠 Add NsgAuditTab to NetworkHub
**Files:** `NsgAuditTab.tsx` (fully built, ~400 lines), `NetworkHubTab.tsx`
**Impact:** NSG rule auditing is a daily operational task — finding overly-permissive rules, 0.0.0.0/0 ingress, etc. The tab is built but unreachable.
**Fix effort:** Very Low — 3-line change to `NetworkHubTab.tsx`.

### #7 🟠 Wire QueueDepthTab into a Hub
**Files:** `QueueDepthTab.tsx` (orphaned), no parent hub
**Impact:** Service Bus and Event Hubs dead-letter queue depth is a Tier-1 metric for messaging-dependent workloads.
**Fix effort:** Low — add "Messaging" sub-tab to `ResourcesHubTab` or create `MessagingHubTab`.

### #8 🟡 Add Application Gateway / WAF Agent Tools
**Impact:** App Gateway is the standard ingress for enterprise workloads. WAF rule violations, backend pool health failures, and SSL termination issues are common incident types with no current diagnostic path.
**Fix effort:** Medium — add `query_appgw_backend_health`, `query_appgw_waf_logs` to `agents/network/tools.py`.

### #9 🟡 Expand AuditHub with Governance Tabs
**Files:** `AuditHubTab.tsx` (48 lines), 5 orphaned governance tabs
**Impact:** Compliance officers and SREs need lock audit, tagging compliance, alert coverage in one place. Currently requires knowing to directly access orphaned components (impossible in the UI).
**Fix effort:** Low — add 5 import + render branches to `AuditHubTab.tsx`.

### #10 🟡 Add Redis Cache Coverage to Database Agent
**Missing:** `get_redis_cache_health`, `get_redis_metrics`, `query_redis_slow_operations` in `agents/database/tools.py`
**Impact:** Redis Cache is a common dependency for session management and caching tiers; its eviction and memory pressure patterns are frequent incident triggers.
**Fix effort:** Medium — add tools using `azure-mgmt-redis` SDK (already available in the `azure` namespace).

---

## 6. Detailed Findings by Domain

### 6.1 Compute Agent — Deep but AKS Gaps

`agents/compute/tools.py` (3,856 lines) is the most mature agent. Notable gap: AKS workload depth.

Current AKS tools: `query_aks_cluster_health`, `query_aks_node_pools`, `query_aks_upgrade_profile`

Missing:
- `query_aks_workload_summary` — pod counts by namespace/deployment (KubePodInventory KQL). Partially implemented in `aks_chat_tools.py` (gateway side) but not in the agent itself.
- `query_aks_node_not_ready` — nodes in NotReady state (critical for scheduling failures)
- `propose_aks_node_pool_scale` — autoscaler override

### 6.2 SRE Agent — `propose_remediation` Not Wired to Approval Queue

`agents/sre/tools.py` has `propose_remediation` which creates a recommendation dict. However:
- The proposal is **not written to Cosmos DB** (where the approval queue reads from)
- `ApprovalQueueCard.tsx` reads from `GET /api/v1/approvals` — which reads Cosmos
- The SRE agent's proposals are currently log-only

This means SRE-initiated remediations never appear in the human-approval queue in the UI.

### 6.3 Security Hub — Missing Policy Compliance

`PolicyComplianceTab.tsx` (~400 lines) calls `GET /api/v1/compliance/policy` and is fully implemented. `policy_compliance_service.py` (317 lines) is also complete. But `PolicyComplianceTab` is **not imported** by `SecurityHubTab.tsx`. The tab renders nothing accessible.

### 6.4 Cost Hub — CostAnomalyTab Orphaned

`CostHubTab.tsx` has exactly 2 sub-tabs: "Cost & Advisor" and "Budgets". `CostAnomalyTab.tsx` (~370 lines) calls `GET /api/v1/cost/anomalies`, is fully built, but is never mounted. Cost anomaly detection is a key FinOps workflow.

### 6.5 Change Hub — Deployment Tab Has No ResourceGroup

`DeploymentTab` is mounted as:
```tsx
{activeSubTab === 'deployments' && <DeploymentTab resourceGroup={undefined} />}
```

`resourceGroup={undefined}` means the tab loads with no subscription scope — it will show an empty state or make unscoped API calls. This is a likely functional bug.

---

## 7. What Is Covered Well (Non-Gaps)

For completeness — areas with solid end-to-end coverage:

- **VM diagnostics + chat**: `VMDetailPanel` with inline chat, metrics, activity log, resource health, patch status, EOL detection, CVE lookup — excellent depth.
- **Incident lifecycle**: Detection plane → Cosmos → AlertFeed → triage → approval queue → audit trail — complete.
- **AKS cluster health**: Three-layer coverage (ARG, Monitor metrics, Container Insights via Log Analytics).
- **Network topology**: VNet map with connectivity checker, peering state, flow logs — genuinely useful.
- **Patch management**: Arc + Azure Update Manager with KQL-based assessment, cross-workspace GUID resolution.
- **EOL detection**: endoflife.date + MS Lifecycle + PostgreSQL cache — thorough implementation.
- **FinOps**: Cost breakdown, forecast, idle resource identification, RI utilization — complete.
- **Multi-agent orchestration**: 13 agents with proper handoff, concurrent orchestration, group chat support.

---

*Generated: 2026-04-19 | Analyst: Claude Code gap analysis*
