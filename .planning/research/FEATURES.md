# AAP Feature Inventory — By Dimension

> Research date: 2026-03-25
> Platform scope: Azure Agentic Platform (AAP) — single-tenant, multi-subscription Azure + Arc-enabled resources (servers, K8s, data services). Domain-specialist multi-agent architecture (Compute, Network, Storage, Security, Arc, SRE). Hybrid UI (Fluent UI 2 + Next.js) + Teams bot. Human-in-the-loop always for remediation.

---

## Legend

| Tag | Meaning |
|---|---|
| **Table Stakes** | Must-have. Absence causes users to dismiss the platform immediately. |
| **Differentiator** | Competitive advantage if done well; not universally expected. |
| **Anti-Feature** | Deliberate omission — adds complexity without commensurate value, or is a trap. |
| ⚠️ | Has notable complexity, dependency, or risk callout |

---

## 1. Monitoring & Observability

### 1.1 Signal Types to Surface

| Feature | Category | Notes |
|---|---|---|
| **Azure resource metrics** — CPU, memory, disk I/O, network throughput from all subscriptions via Azure Monitor | Table Stakes | Native via `azure-ai-projects` + Azure MCP Server. Multi-subscription aggregation needed. |
| **Azure resource logs** — activity logs (control-plane), resource logs (data-plane), diagnostic settings | Table Stakes | Activity log is the authoritative "who changed what" trail; 90-day native retention, must export to Log Analytics for longer. |
| **Log Analytics KQL query results** — ad-hoc + saved queries surfaced in chat and dashboard | Table Stakes | Core investigation surface. Agents call Log Analytics via Azure MCP Server. |
| **Application Insights traces + APM** — request rates, failure rates, latency percentiles, dependency calls | Table Stakes for app-hosting subs | Especially for App Service, Container Apps, Functions in scope. |
| **Prometheus/OpenTelemetry metrics from Arc-enabled K8s** — cluster, node, pod, container metrics via Container Insights extension | Table Stakes for Arc K8s | Collected via `microsoft.azuremonitor.containers` extension; PromQL + KQL both needed. |
| **Windows/Linux event logs and syslog from Arc servers** — via Azure Monitor Agent extension | Table Stakes for Arc servers | Critical for hybrid server ops. AMA extension must be tracked as a dependency. |
| **Azure Resource Health signals** — per-resource health events (Degraded, Unavailable, Unknown) | Table Stakes | Native Azure signal; surfaces platform-side issues vs. customer-side. Must be shown alongside metrics. |
| **Service Health / Azure Status** — maintenance windows, outages, service degradation | Table Stakes | Distinguishes "Azure is broken" from "your config is broken" — saves enormous triage time. |
| **Azure Advisor recommendations** — cost, security, reliability, performance, operational excellence | Differentiator | Surfaced proactively by agents as context alongside alerts; not just a link to the portal. |
| **Azure Policy compliance state** — per-resource compliance, non-compliant reasons | Differentiator | Especially for Arc-enabled resources where policy is the primary governance mechanism. |
| **Arc extension health** — agent version, extension install status, last heartbeat | Table Stakes for Arc | Arc-specific: the monitoring agent itself can fail; must surface extension operational status. |
| **Arc connectivity status** — connected/disconnected, last sync, connection latency | Table Stakes for Arc | A disconnected Arc server is invisible; must alert on prolonged disconnection. |
| **Container Insights workload metrics** — deployment replicas, pod restarts, OOMkilled events, HPA scaling events on Arc K8s | Differentiator | Deeper than node metrics; needed for meaningful K8s triage. |
| **SQL MI on Arc metrics** — CPU, connections, query store, wait stats, transaction log growth | Differentiator | High-value for data services; requires custom Arc MCP Server tooling. |
| **Change tracking** — resource configuration changes, VM software inventory changes via Change Tracking extension | Differentiator | Correlating alerts to "what changed 10 minutes ago" is a high-value triage signal. |
| **OpenTelemetry spans from AAP agents** — per-agent span, tool call latency, token counts, error rates | Table Stakes (platform self) | Via Application Insights; required for platform ops, not customer resource ops. |

### 1.2 Resource Type Coverage Priority

| Resource Type | Priority | Monitoring Surface |
|---|---|---|
| Arc-enabled servers (Windows/Linux) | **P0** | AMA agent → Log Analytics; VM Insights (performance + map); Change Tracking; Windows Event Log / syslog |
| Arc-enabled Kubernetes clusters | **P0** | Container Insights extension; Prometheus metrics; Flux GitOps reconciliation status |
| Azure VMs (native) | **P0** | Same as Arc servers but lighter burden — fully native Azure Monitor |
| Azure Container Apps | **P1** | Built-in Console logs + metrics; Application Insights integration |
| Arc-enabled SQL MI | **P1** | Arc data services monitoring; query performance; connection health |
| Azure PostgreSQL Flexible Server | **P1** | Native Azure Monitor metrics; Intelligent Performance; slow query logs |
| Azure Cosmos DB | **P1** | RU consumption, throttling (429s), latency percentiles, partition key hot-spots |
| Microsoft Fabric / Eventhouse | **P2** | Pipeline health, ingestion lag, query performance — platform self-monitoring |
| VNet / NSG / Private Endpoints | **P2** | Network Watcher; NSG flow logs; connection monitor probes |
| Azure Storage (Blob, queue, files) | **P2** | Availability, latency, transaction metrics, throttling |
| Arc VMware vSphere / SCVMM VMs | **P2** | Projected into ARM; same AMA-based monitoring path as Arc servers |

### 1.3 Table-Stakes vs. Differentiator Summary

**Table Stakes:**
- Unified metric/log/trace view across all subscriptions in a single pane
- Azure Monitor as the collection backbone (no competing agent installs required)
- Alert-correlated log navigation (from alert → relevant logs in one click/command)
- Resource health overlays on topology view

**Differentiators:**
- Semantic resource topology map (shows dependency relationships, not just a flat list)
- Cross-signal correlation: "CPU spike at 14:32 → pod OOMKill at 14:33 → failed deployment at 14:34"
- Proactive Advisor recommendations surfaced in agent responses with actionable context
- Change tracking integrated into incident timeline (most platforms make this manual)

**Anti-Features:**
- ❌ Custom metrics collection agents (avoid deploying your own sidecar agents; use AMA)
- ❌ Replicating Azure Monitor's built-in workbooks — link to them, don't duplicate them
- ❌ Per-resource dashboards that duplicate the Azure portal — focus on cross-resource operational views only

---

## 2. Alerting & Incident Management

### 2.1 Alert Management

| Feature | Category | Notes |
|---|---|---|
| **Azure Monitor alert ingestion** — consume all fired alerts across all subscriptions via Azure Monitor REST API or webhook | Table Stakes | The native incident detection source. Fire-and-forget from Azure Monitor → Fabric Activator → Agent Platform REST API. |
| **Alert state tracking** — New → Acknowledged → Closed, with timestamps and actor | Table Stakes | Agents update alert state; must be bidirectional (platform state synced back to Azure Monitor). |
| **Alert enrichment** — auto-annotate with resource owner, environment tag, subscription, resource group, related open alerts | Table Stakes | Without enrichment, alert feed is noise. Run enrichment before routing to agents. |
| **Alert deduplication** — group repeated alerts for same resource within configurable time windows | Table Stakes | Alert storms (e.g., 100 metric alerts in 2 minutes for same VM) must collapse to one incident. |
| **Alert suppression** — maintenance windows, known-issue silencing with expiry | Table Stakes | Must support scheduled suppression (planned maintenance) and ad-hoc suppression (acknowledged known issue). |
| **Multi-subscription alert aggregation** — unified feed across all subscriptions | Table Stakes | Per-subscription alert views are the portal default; cross-subscription aggregation is a gap agents fill. |
| **Dynamic thresholds** — Azure Monitor smart alerts using ML-based baselines (not static thresholds) | Differentiator | Reduces false positives substantially; native Azure Monitor feature — surface it, don't re-implement it. |
| **Alert correlation into incidents** — group topologically or temporally related alerts into a single incident record | Differentiator | This is the core AIOps value-add. Agents correlate; structured incident record in Cosmos DB. |
| **Confidence scoring** — agent-assigned probability that a correlated alert cluster represents a real incident | Differentiator | Gate incident creation behind confidence threshold to avoid incident noise. |
| **PagerDuty / ServiceNow integration** — push incidents to ITSM; sync state back | Differentiator | Expected by enterprise teams with existing tooling. Azure SRE Agent already does this — use same pattern. |
| **Alert processing rules** — Azure Monitor native suppression + action group modifications | Table Stakes | Must configure these in Terraform and respect them in the platform (don't route suppressed alerts to agents). |
| **Recommended alert rules at-scale** — deploy baseline alert rules via Azure Policy across all subscriptions | Differentiator | Azure Monitor Baseline Alerts (AMBA) pattern; Terraform manages at-scale deployment. |

### 2.2 Incident Lifecycle

```
Detection (Azure Monitor fires)
  → Enrichment (resource metadata, owner, environment, related alerts)
  → Deduplication (collapse alert storm to one incident)
  → Correlation (group related alerts by topology / time window)
  → Triage (agent assigns severity, probable root cause, domain)
  → Assignment (route to domain specialist agent: Compute/Network/Storage/Security/Arc/SRE)
  → Investigation (agent queries logs, metrics, traces; builds evidence bundle)
  → Remediation Proposal (agent proposes action; human approves)
  → Execution (approved action runs; outcome logged)
  → Resolution (alert resolves; incident closed)
  → Postmortem (AI-generated timeline + contributing factors)
```

| Lifecycle Stage | Table Stakes Features |
|---|---|
| Detection | Azure Monitor alert ingestion; webhook receiver or polling; Fabric Activator trigger |
| Enrichment | Resource tags (owner, env, cost-center); subscription name; Resource Health status |
| Triage | Severity scoring; domain classification; duplicate detection |
| Assignment | Domain agent routing; clear "assigned to: Compute Agent" state |
| Investigation | Evidence bundle: logs, metrics, related alerts, change events |
| Remediation | Proposal card with proposed action + estimated impact; approve/reject |
| Resolution | Alert auto-resolve detection; manual close with reason |
| Postmortem | AI-generated timeline; MTTR recorded; runbook coverage gap flagged |

### 2.3 Anti-Features

- ❌ Building a full ITSM — route incidents to ServiceNow/PagerDuty for ticket management, don't replicate ITSM workflow engine
- ❌ Per-alert runbook auto-execution without approval — human-in-the-loop is a design principle, not a limitation
- ❌ Alert fatigue through over-alerting on low-severity signals — enforce severity tiering at ingestion

---

## 3. AI Triage & Troubleshooting

### 3.1 AI-Powered vs. Rule-Based Triage

| Triage Type | What It Covers | Where It Lives |
|---|---|---|
| **Rule-based** | Known patterns: specific error codes, threshold breaches, known-bad config states | Alert processing rules + Fabric Activator triggers |
| **AI-powered** | Novel patterns, cross-signal correlation, natural-language investigation, hypothesis generation | Domain specialist agents |

Rule-based runs first (fast, cheap, predictable). AI escalates when rules don't match or confidence is low.

### 3.2 Root Cause Analysis (RCA)

| Feature | Category | Notes |
|---|---|---|
| **Signal correlation across metrics/logs/traces** — agent identifies temporal relationship between CPU spike, error log burst, and user-facing failure | Table Stakes | Core AI triage capability. Azure Monitor Observability Agent (Preview) does this natively — our agents extend it. |
| **Change correlation** — agent checks Azure Activity Log and Change Tracking for "what changed in the last 2 hours" as first-pass RCA | Table Stakes | Statistically, most incidents correlate with a recent change; this check should be automatic. |
| **Resource Health timeline** — surface Azure platform health events alongside resource metrics to distinguish platform-caused vs. config-caused incidents | Table Stakes | Agents query Resource Health API as part of every triage. |
| **Dependency chain traversal** — identify upstream dependencies that may be the actual root cause (e.g., slow database causing slow API causing alert) | Differentiator | Requires semantic topology or service map. Complex to build correctly. |
| **Runbook RAG retrieval** — agent retrieves relevant runbooks via vector search (pgvector) and cites them in its investigation | Differentiator | Encodes institutional knowledge; turns tribal knowledge into agent context. |
| **Hypothesis ranking** — agent presents top 3 probable root causes with supporting evidence and confidence scores | Differentiator | Transparency and auditability: operators can see why the agent thinks what it thinks. |
| **Cross-incident pattern detection** — "this looks like the incident from 2025-11-14; that was caused by X" | Differentiator | Requires historical incident embeddings; high-value but Phase 2+. |
| **Automated investigation plans** — agent generates an ordered list of investigation steps before executing them | Differentiator | Operator can review and redirect the plan before the agent acts. High trust-building value. |

### 3.3 Agent Transparency

Operators want to see:

| Transparency Element | Category | Implementation |
|---|---|---|
| **Every tool call the agent made** — what API was called, with what parameters, what was returned | Table Stakes | Structured agent trace event stream; expandable in UI. |
| **Agent-to-agent messages** — which domain agent was called, what was the handoff message | Table Stakes | JSON event stream per PROJECT.md design. |
| **Reasoning narrative** — plain English explanation of why the agent took each step | Table Stakes | Token stream in chat panel; not just a final answer. |
| **Confidence levels** — "I'm 80% confident this is a disk I/O saturation issue, 20% chance it's network" | Differentiator | Calibrated confidence prevents over-trust. |
| **Evidence bundle** — the set of log queries, metric charts, and resource states the agent used | Table Stakes | Persisted in incident record (Cosmos DB); shown in audit log. |
| **Investigation duration + cost** — tokens consumed, latency per agent hop | Differentiator | Useful for platform ops and cost governance. |

### 3.4 Knowledge Base / Runbook Integration

| Feature | Category | Notes |
|---|---|---|
| **Runbook storage in PostgreSQL + pgvector** — full text + vector embeddings for semantic search | Table Stakes | Per PROJECT.md architecture. |
| **Semantic runbook retrieval** — agent queries "restart unhealthy Arc agent" and gets relevant runbooks ranked by similarity | Table Stakes | RAG pattern over runbook corpus. |
| **Runbook versioning** — runbooks have version history; agent always cites version used | Differentiator | Audit trail: "agent followed runbook v3.2 on 2026-03-25". |
| **Runbook feedback loop** — after incident resolution, operator can mark which runbook steps were effective | Differentiator | Improves future retrieval quality. |
| **Runbook coverage gap reporting** — after incidents not matched to a runbook, flag for runbook authoring | Differentiator | Systematic knowledge base growth. |
| **Runbook dry-run mode** — agent can simulate runbook steps without executing them | Differentiator | High trust-building for new runbooks. |

### 3.5 Anti-Features

- ❌ Re-implementing Azure Monitor Observability Agent — it already does signal correlation; our agents consume its output and extend it
- ❌ Fully autonomous RCA with no human review path — always present findings for confirmation, not just action
- ❌ Black-box RCA with no evidence — if the agent can't show its reasoning, operators won't trust the conclusion

---

## 4. Remediation

### 4.1 Table-Stakes Azure Remediation Actions

| Remediation Action | Domain Agent | Risk Level |
|---|---|---|
| Restart Azure VM / Arc-enabled VM | Compute | Medium — causes downtime |
| Deallocate and reallocate VM (clear transient state) | Compute | Medium |
| Scale up VM SKU | Compute | Low-Medium — requires VM stop |
| Trigger VM auto-heal (App Service) | Compute | Low |
| Restart Container App revision | Compute | Low |
| Force Pod restart on Arc K8s | Compute / Arc | Low |
| Drain and cordon Arc K8s node | Arc | Medium |
| Apply NSG rule change | Network | Medium — security impact |
| Flush Azure DNS resolver cache | Network | Low |
| Modify load balancer backend pool | Network | High |
| Expand managed disk (online expand) | Storage | Low |
| Snapshot disk before risky operation | Storage | Low — always propose as pre-step |
| Rotate storage account key | Storage | Medium — breaks clients using old key |
| Run Azure Policy remediation task | Security | Low-Medium |
| Update Arc extension (AMA, policy, GitOps) | Arc | Low |
| Force Arc agent reconnection / re-onboarding | Arc | Medium |
| Apply Flux GitOps configuration reconciliation | Arc | Medium — may overwrite manual changes |
| Trigger Azure Advisor recommendation fix | SRE | Varies |
| Run custom runbook via Azure Automation / CLI | SRE | Varies |

### 4.2 Approval Workflow UX

**Principles:**
- Every remediation action must be proposed, never executed silently
- Proposal must include: action description, target resource(s), estimated impact, reversibility, confidence level
- Approval available in both Web UI and Teams (co-equal)
- Time-boxed approvals: if no response in N minutes, action expires (no silent execution)
- Emergency override path: designated approvers can fast-track in Teams

| Approval UX Element | Category | Notes |
|---|---|---|
| **Proposal card** — action + target + impact + reversibility statement | Table Stakes | In web UI: Remediation Proposal Card component. In Teams: Adaptive Card. |
| **Approve / Reject buttons** with comment field | Table Stakes | Both surfaces. Comment becomes part of audit record. |
| **Action expiry** — proposal expires after configurable timeout (default: 30 min) | Table Stakes | Prevents stale approvals being actioned on a resource that has since changed. |
| **Approval notification** — push to Teams channel AND web UI notification | Table Stakes | Must reach on-call operator wherever they are. |
| **Dry-run mode** — "simulate this action without executing" | Differentiator | Agent describes what would happen; high trust-builder for new actions. |
| **Rollback plan attached to proposal** — "if this fails, here's how to undo it" | Differentiator | Dramatically reduces approval anxiety. |
| **Multi-approval for high-risk actions** — require 2 approvers for High-risk tier | Differentiator | Risk-tiered approval workflow. |
| **Approval history on incident** — full chain: proposed → approved by → executed → outcome | Table Stakes | Audit requirement. |

### 4.3 Runbook Library Structure

```
runbooks/
├── compute/
│   ├── restart-vm.md          # Azure VM restart procedure
│   ├── scale-vm-sku.md
│   └── drain-aca-revision.md
├── network/
│   ├── update-nsg-rule.md
│   └── flush-dns.md
├── storage/
│   ├── expand-managed-disk.md
│   └── rotate-storage-key.md
├── security/
│   ├── apply-policy-remediation.md
│   └── rotate-secret.md
├── arc/
│   ├── reconnect-arc-agent.md
│   ├── update-arc-extension.md
│   └── force-flux-reconciliation.md
└── sre/
    ├── scale-container-app.md
    └── run-custom-script.md
```

Each runbook document contains: description, target resource types, pre-conditions, steps (CLI commands / REST calls), estimated duration, risk level, rollback steps, related runbooks, version history.

### 4.4 Safety Guardrails

Even with approval, these limits exist:

| Guardrail | Rationale |
|---|---|
| Production-subscription actions require explicit subscription scope confirmation | Prevent "wrong subscription" accidents |
| No bulk destructive actions (e.g., delete all resources matching tag) without named-resource confirmation | Blast radius protection |
| Read-only mode per subscription — configurable — blocks all write actions regardless of approval | Controlled rollout of write permissions |
| Action rate limiting per agent per subscription — max N actions/minute | Prevents runaway agent loops |
| No action on resources flagged "protected" via a resource tag | Operator escape hatch |
| Every write action preceded by a snapshot/backup step where applicable | Data protection reflex |
| RBAC scope enforcement — agents can only act within their Entra Agent ID RBAC assignment | Principle of least privilege, enforced at identity layer |

### 4.5 Anti-Features

- ❌ Auto-remediation without approval — violates the core design principle; breaks operator trust
- ❌ Runbooks stored as executable scripts with no human-readable rationale — operators must be able to read and validate them
- ❌ Cross-subscription destructive actions — limit blast radius at the architecture level
- ❌ Remediation of security group rules without network team review — even with approval, some action classes need second-opinion workflow

---

## 5. Audit & Compliance

### 5.1 Required Audit Trail

| Audit Record Type | Retention | Storage | Category |
|---|---|---|---|
| **Agent action log** — every tool call: timestamp, agent identity, tool name, parameters, response, outcome | 2 years+ | Fabric OneLake | Table Stakes |
| **Remediation approval record** — proposal, who approved/rejected, timestamp, comment, outcome | 2 years+ | Fabric OneLake + PostgreSQL | Table Stakes |
| **Azure Activity Log export** — all ARM control-plane changes across all subscriptions | 2 years+ (requires export to Log Analytics) | Log Analytics → Fabric OneLake | Table Stakes |
| **Agent conversation thread** — full conversation history with timestamps per session | 90 days+ | Foundry Agent Service + Cosmos DB | Table Stakes |
| **Alert state transition log** — New/Acknowledged/Closed, by whom, when | 1 year | Fabric OneLake | Table Stakes |
| **Runbook version log** — which version was used, when, by which agent, for which incident | 2 years | PostgreSQL | Differentiator |
| **RBAC assignment change log** — who changed agent permissions, when | Permanent | Azure Activity Log | Table Stakes |
| **Failed action log** — attempts that were rejected, timed out, or errored | 1 year | Fabric OneLake | Table Stakes |

### 5.2 Compliance Reports

| Report Type | Common Ask | Category |
|---|---|---|
| **Remediation activity report** — all agent actions taken in a period, with approval chain | SOC 2, internal audit | Table Stakes |
| **Alert resolution report** — MTTA/MTTR by subscription, resource type, domain | SRE metrics | Differentiator |
| **Access review report** — which agent identities have which RBAC roles | Entra ID governance | Table Stakes |
| **Policy compliance trend** — non-compliant resources over time, by subscription | ISO 27001, CIS benchmark | Differentiator |
| **Change management report** — resource changes correlated with incidents | ITIL CAB requirements | Differentiator |
| **Arc connectivity report** — hours disconnected per Arc resource per period | SLA tracking | Differentiator |

### 5.3 Agent Action Logging Requirements

Every agent action log entry MUST contain:

```json
{
  "timestamp": "ISO-8601",
  "correlationId": "incident or session ID",
  "agentId": "Entra Agent ID object ID",
  "agentName": "ComputeAgent | NetworkAgent | ...",
  "agentVersion": "semver",
  "toolName": "azure_mcp_restart_vm | arc_mcp_reconnect_agent | ...",
  "toolParameters": { "...sanitized..." },
  "toolResponseSummary": "human-readable outcome",
  "subscriptionId": "...",
  "resourceId": "/subscriptions/...full ARM ID...",
  "approvedBy": "UPN or null if read-only action",
  "approvalTimestamp": "ISO-8601 or null",
  "outcome": "success | failure | timeout | rejected",
  "durationMs": 1234
}
```

### 5.4 Anti-Features

- ❌ Storing raw LLM conversation content with customer data in external LLM provider logs indefinitely — review data residency carefully
- ❌ Audit logs only in application DB (Cosmos DB) — must also land in Fabric OneLake for long-term immutable storage
- ❌ Agent anonymization in logs — every action must be attributable to a specific Entra Agent ID, not a generic "system"

---

## 6. Arc-Specific Features

### 6.1 Unique AIOps Capabilities for Arc-Enabled Resources

| Feature | Category | Notes |
|---|---|---|
| **Arc connectivity health monitoring** — track connected/disconnected/expired state; alert on prolonged disconnection | Table Stakes | Custom Arc MCP Server: query `Microsoft.HybridCompute/machines` connectivity status. |
| **Arc extension health inventory** — list all extensions, versions, install status, last operation per machine | Table Stakes | Extensions can fail to install/update silently; must surface this. |
| **Arc extension update management** — agent proposes and (with approval) updates outdated AMA, policy, GitOps extensions | Differentiator | Keeps monitoring agent current; reduces blind spots. |
| **Arc server inventory with OS details** — OS version, patch level, last heartbeat, machine type | Table Stakes | Custom Arc MCP Server wraps `Microsoft.HybridCompute/machines` API. |
| **VM Insights map for Arc servers** — process dependency map showing network connections between hybrid machines | Differentiator | Requires Dependency Agent alongside AMA; high-value for network-level triage. |
| **GitOps reconciliation health (Flux)** — monitor Flux kustomization and HelmRelease sync status on Arc K8s | Table Stakes for Arc K8s | Flux drift = silent config divergence; must alert on failed reconciliation. |
| **Arc Policy compliance** — which Azure Policy assignments are non-compliant on Arc resources | Differentiator | Policy is the primary governance control for Arc; compliance drift must surface. |
| **Arc data services health** — SQL MI on Arc: CPU, connections, query store, log growth, replica health | Differentiator | Requires custom tooling; no Azure MCP coverage today. |
| **Arc agent log collection** — Windows/Linux event logs and syslog via AMA extension on Arc servers | Table Stakes | Standard VM Insights path; must confirm AMA extension is installed as part of onboarding. |
| **Hybrid connectivity monitoring** — express route / VPN health affecting Arc agent connectivity | Differentiator | Network Watcher connection monitor to track latency/packet loss on connectivity paths. |
| **Arc-enabled K8s cluster health summary** — nodes ready/not-ready, pods running/pending/failed, PVC claims | Table Stakes for Arc K8s | Container Insights via Arc extension provides this. |
| **Custom location health** — Azure services deployed at Arc custom locations (Container Apps, data services) | Differentiator | Surfaces health of the Azure-at-edge pattern. |

### 6.2 Arc Extensions — What They Unlock for AIOps

| Extension | What It Enables for AAP |
|---|---|
| **Azure Monitor Agent (AMA)** | Windows/Linux event logs, syslog, performance counters, custom log collection → Log Analytics → alerts → agent triage |
| **VM Insights (Dependency Agent + AMA)** | Process/network dependency map; performance charts; enables correlated "this process is consuming 100% CPU" analysis |
| **Container Insights** | Node/pod/container CPU/memory/network metrics; namespace-level rollup; Prometheus scraping on Arc K8s |
| **Azure Policy** | Enforce monitoring config, deny non-compliant resources, auto-remediate misconfigurations on Arc K8s |
| **Flux (GitOps)** | Track configuration drift; agent can trigger reconciliation; audit config change history via Git commits |
| **Microsoft Defender for Containers** | Runtime threat detection on Arc K8s; alerts feed directly into Security Agent |
| **Azure Key Vault Secrets Provider** | Ensure secrets are current on Arc K8s; agent can check for expiring secrets |
| **Change Tracking** | Software inventory + change events on Arc servers; critical for "what changed before this incident?" triage |

### 6.3 Arc Monitoring Gap (Custom MCP Server Scope)

The Azure MCP Server (GA) does NOT cover:

- `Microsoft.HybridCompute/machines` API — Arc server inventory, connectivity status, extension status
- `Microsoft.Kubernetes/connectedClusters` API — Arc K8s cluster health
- `Microsoft.AzureArcData/sqlManagedInstances` API — Arc SQL MI
- Flux / GitOps configuration status
- Arc custom location status

The **custom Arc MCP Server** must bridge these gaps. It is a P0 dependency for meaningful Arc operations.

### 6.4 Anti-Features

- ❌ Trying to manage Arc resources via the standard Azure MCP Server (it has no Arc coverage — this wastes agent token budget on failed calls)
- ❌ Assuming Arc connectivity — always check connection status before issuing commands to Arc resources
- ❌ Ignoring extension versions — AMA, Dependency Agent, and Policy extension updates can silently break monitoring; must be tracked

---

## 7. UI/UX Features

### 7.1 Web UI Layout Architecture

**Primary Layout: Split-Pane Hybrid**

```
┌─────────────────────────────────────────────────────────────────┐
│  Header: [Subscription selector] [Health summary] [Active alerts]│
├───────────────────────┬─────────────────────────────────────────┤
│                       │                                         │
│  CHAT PANEL (left)    │  OPERATIONAL PANEL (right)              │
│  ─────────────────    │  ─────────────────────────────────────  │
│  Agent conversation   │  [Tab: Topology] [Tab: Alerts]          │
│  with streaming       │  [Tab: Resources] [Tab: Audit Log]      │
│  token output         │                                         │
│                       │  Live resource topology map             │
│  Agent trace          │  OR alert feed                          │
│  (expandable)         │  OR resource drill-down                 │
│                       │  OR audit log viewer                    │
│  Remediation          │                                         │
│  proposal cards       │                                         │
│                       │                                         │
└───────────────────────┴─────────────────────────────────────────┘
```

| UI Component | Category | Notes |
|---|---|---|
| **Split-pane: chat left + operational right** | Table Stakes | Chat is co-equal to dashboards; not a modal or sidebar. |
| **Token streaming in chat** — sub-second first token, character-by-character rendering | Table Stakes | Latency anxiety is real; streaming reduces perceived response time dramatically. |
| **Agent trace panel** — expandable JSON tree for each agent hop, tool call, and response | Table Stakes | Per PROJECT.md: parallel structured event stream. Collapsed by default; expandable for power users. |
| **Subscription selector / switcher** — multi-subscription context in a single UI session | Table Stakes | Must aggregate across subscriptions, not force subscription switching. |
| **Resource topology map** — graph view of resources with health status overlays (red/yellow/green) | Differentiator | Not a flat list — shows dependency edges between resources. Force-directed graph or hierarchical layout. |
| **Alert/incident feed** — real-time alert stream with severity, resource, triage status, assigned agent | Table Stakes | Updates in real-time via WebSocket or SSE. Filterable by subscription, severity, domain, status. |
| **Remediation proposal cards** — proposed action + impact + approve/reject buttons | Table Stakes | Prominent, cannot be missed. Show timer for expiry. |
| **Audit log viewer** — searchable, filterable by agent, action type, resource, time | Table Stakes | Tabular with expandable detail rows. KQL-style filtering UX. |
| **Notification system** — toasts for new alerts, approval requests, action outcomes | Table Stakes | Must not rely on page refresh; push via SSE or WebSocket. |
| **Keyboard shortcuts** — quick-navigate between panels, dismiss notifications, approve/reject | Differentiator | Power user efficiency; esp. for on-call operators. |
| **Dark mode** | Differentiator | On-call operations happen at 3am. |
| **Mobile responsive (read-only)** — alert feed and approval cards work on mobile | Differentiator | Teams is primarily used on mobile; complementary read path. |

### 7.2 Agent Communication Transparency

What operators want to see about how agents reason:

| Signal | Where Shown | Format |
|---|---|---|
| **Current agent activity** | Chat status bar | "Compute Agent: querying Log Analytics..." |
| **Tool calls in flight** | Agent trace panel | Live-updating JSON nodes |
| **Token streaming** | Chat bubble | Character-by-character; markdown-rendered |
| **Agent handoffs** | Trace panel | Visual edge: "Orchestrator → Compute Agent" |
| **Evidence bundle** | Collapsible section in response | Metric charts, log excerpts, resource health snapshot |
| **Confidence indicators** | Inline in response | "High confidence (87%)" inline badge |
| **Investigation steps taken** | Ordered list in response | Numbered, with ✓ completed / ⚠ uncertain |

### 7.3 Dashboard Patterns for Hybrid Azure + Arc

**Dashboard Views (right panel tabs):**

1. **Global Health** — subscription-level health tiles; active alert counts by severity; Arc connectivity summary
2. **Resource Topology** — interactive dependency graph; filter by subscription / resource group / resource type
3. **Alert Feed** — real-time alert stream; group by incident; triage status badges
4. **Arc Estate** — Arc server connectivity map; extension health grid; K8s cluster rollup; GitOps sync status
5. **Audit Log** — agent action history; approval chains; exportable
6. **Incidents** — open incidents with assigned agent, severity, last update, SLA timer

**Data refresh pattern:**
- Alert feed: real-time (WebSocket/SSE push from Cosmos DB change feed)
- Metrics charts: 60-second polling or push
- Resource health: 5-minute polling
- Topology graph: on-demand refresh + 5-minute background

### 7.4 Anti-Features

- ❌ Building a full Grafana alternative — embed Managed Grafana dashboards via iframe for metric visualization; don't rebuild charting
- ❌ Recreating Azure Resource Graph Explorer — use it as a backend, not a feature to replicate
- ❌ Per-resource detail pages that duplicate the Azure portal — deep-link to portal for resource-level config; focus AAP on cross-resource operational views
- ❌ Complex drag-and-drop dashboard builder — adds weeks of development for marginal value; ship fixed layouts first
- ❌ Custom notification sound settings and other preference sprawl — YAGNI; ship defaults that work

---

## 8. Teams Integration

### 8.1 Bot UX Patterns

| Feature | Category | Notes |
|---|---|---|
| **Two-way conversational bot** — users send chat messages, bot routes to agents, streams responses | Table Stakes | Teams is a first-class interface; not a notification-only bot. |
| **Alert notification cards** — structured Adaptive Card pushed to Teams channel when alert fires | Table Stakes | Must include: resource, severity, subscription, timestamp, "Investigate" action button. |
| **Remediation approval via Adaptive Card** — approve/reject without leaving Teams | Table Stakes | Adaptive Card with approve/reject buttons; response updates card state in-place. |
| **Investigation request** — user types "@AAP investigate VM cpu-alert" in Teams; agent responds inline | Table Stakes | Natural language trigger; bot forwards to orchestrator agent. |
| **Approval expiry notification** — bot re-posts if approval not acted on within N minutes | Table Stakes | On-call operators miss cards; must escalate with reminder. |
| **Action outcome notification** — bot posts outcome card after approved action executes | Table Stakes | Closes the loop; operator knows the action succeeded or failed. |
| **Multi-channel support** — alert routing to correct Teams channel by subscription or domain | Differentiator | E.g., "#prod-network-alerts" for network alerts in prod subscriptions. |
| **Thread-based incident tracking** — all messages for a single incident stay in one Teams thread | Differentiator | Reduces channel noise; preserves investigation context. |
| **@mention domain agents directly** — "@NetworkAgent why is latency high?" | Differentiator | Power-user pattern; agent responds in thread. |
| **Adaptive Card state management** — card updates in-place (approved/rejected/expired/executed) | Table Stakes | Stale approval cards cause confusion; must update card state after action. |

### 8.2 Adaptive Card Schema for Alert Notification

```json
{
  "type": "AdaptiveCard",
  "version": "1.5",
  "body": [
    { "type": "TextBlock", "text": "🔴 High Severity Alert", "weight": "Bolder", "size": "Large" },
    { "type": "FactSet", "facts": [
      { "title": "Resource", "value": "/subscriptions/.../VMs/my-vm" },
      { "title": "Alert", "value": "CPU > 95% for 15 min" },
      { "title": "Subscription", "value": "prod-east-001" },
      { "title": "Time", "value": "2026-03-25T14:32:00Z" }
    ]},
    { "type": "TextBlock", "text": "Agent triage: disk I/O saturation likely root cause", "wrap": true }
  ],
  "actions": [
    { "type": "Action.Execute", "title": "Investigate", "verb": "investigate", "data": { "alertId": "..." } },
    { "type": "Action.OpenUrl", "title": "Open in AAP", "url": "https://aap.internal/incidents/..." }
  ]
}
```

### 8.3 Anti-Features

- ❌ One-way notification-only bot — without two-way conversation, Teams integration is just email replacement
- ❌ Posting full investigation output as raw text in Teams — use cards + "view full investigation in AAP" deep-link
- ❌ Requiring Teams for approvals — Web UI must be a fully functional approval surface; Teams is additive
- ❌ Per-user Teams bot installation — use channel/group bot deployment at the org level

---

## 9. IaC / Platform Management (Terraform)

### 9.1 Module Coverage

| Module | Scope | Category |
|---|---|---|
| `modules/foundry` | Azure AI Foundry workspace, Foundry Agent Service, agent deployment configs | Table Stakes |
| `modules/container-apps` | Container Apps environment + apps (frontend, API gateway, Arc MCP server, Azure MCP server) | Table Stakes |
| `modules/cosmos-db` | Cosmos DB account, databases, containers, throughput, private endpoint | Table Stakes |
| `modules/postgresql` | PostgreSQL Flexible Server, pgvector extension, databases, firewall rules | Table Stakes |
| `modules/fabric` | Fabric workspace, Eventhouse, Activator, OneLake — via `azapi` provider | Table Stakes |
| `modules/networking` | VNet, subnets, private DNS zones, private endpoints for all data services, NSGs | Table Stakes |
| `modules/agent-identities` | Managed identities per domain agent, Entra Agent ID registration, RBAC assignments | Table Stakes |
| `modules/monitoring` | Log Analytics workspace, Application Insights, diagnostic settings, alert rules at-scale | Table Stakes |
| `modules/storage` | Storage account for Terraform remote state, boot diagnostics | Table Stakes |
| `modules/arc-mcp-server` | Container App for custom Arc MCP Server; managed identity; Arc API RBAC | Table Stakes |
| `modules/event-hub` | Event Hub namespace + hub for telemetry ingestion into Fabric | Table Stakes |
| `modules/container-registry` | ACR for agent/service container images | Table Stakes |
| `modules/teams-bot` | Bot Framework registration, Teams app manifest, channel configuration | Differentiator |

### 9.2 Module Structure Pattern

```
terraform/
├── modules/
│   └── <module-name>/
│       ├── main.tf          # Primary resources
│       ├── variables.tf     # Input variables with descriptions + validation
│       ├── outputs.tf       # Output values consumed by other modules
│       ├── versions.tf      # Provider version constraints
│       └── README.md        # (auto-generated by terraform-docs)
├── environments/
│   ├── dev/
│   │   ├── main.tf          # Environment root — composes modules
│   │   ├── terraform.tfvars # Non-secret environment-specific values
│   │   └── backend.tf       # Remote state config (Azure Storage)
│   ├── staging/
│   └── prod/
└── shared/
    └── naming.tf            # Naming convention module (consistent resource names)
```

### 9.3 Enterprise Terraform Expectations

| Practice | Category | Notes |
|---|---|---|
| **Remote state in Azure Storage** with state locking (Azure Blob lease) | Table Stakes | Per PROJECT.md requirement. |
| **Terraform plan on PR, apply on merge** via GitHub Actions | Table Stakes | Per PROJECT.md. Checkov static analysis in CI. |
| **Per-environment tfvars** (dev/staging/prod) | Table Stakes | Parameterize all environment-specific values. |
| **Input variable validation blocks** — validate resource names, SKUs, region values | Differentiator | Catches misconfiguration before apply. |
| **Output-driven module composition** — no hardcoded resource IDs between modules; use outputs | Table Stakes | Standard Terraform practice. |
| **Terraform provider pinning** — exact provider versions in `versions.tf` | Table Stakes | Prevents unexpected upgrades breaking infra. |
| **`azapi` provider for Fabric + Activator** — resources not yet in `azurerm` | Table Stakes | Fabric Eventhouse + Activator provisioning requires `azapi`. |
| **RBAC assignments via Terraform** — agent identities → subscription/RG scopes | Table Stakes | Per PROJECT.md. Entra Agent ID service principals managed in Terraform. |
| **Checkov static analysis in CI** — security/compliance checks on every PR | Differentiator | Catches hardcoded secrets, overly permissive NSGs, missing private endpoints. |
| **terraform-docs** for auto-generated module documentation | Differentiator | Low-cost, high-value for team onboarding. |
| **Terratest or native Terraform test framework** for module testing | Differentiator | End-to-end tests validate modules deploy cleanly; especially important for complex networking modules. |
| **Naming convention module** — enforces `{product}-{env}-{region}-{type}` pattern | Differentiator | Consistent names reduce operational confusion across subscriptions. |

### 9.4 Anti-Features

- ❌ Monolithic single `main.tf` — unmaintainable at scale; everything in modules
- ❌ Hardcoded subscription IDs or resource IDs in module code — use data sources or variables
- ❌ Local Terraform state — immediate problem in team environments
- ❌ Manual RBAC assignments — anything not in Terraform is configuration drift

---

## 10. Feature Complexity & Dependency Map

### Critical Path Dependencies

```
Arc MCP Server (custom)
  └── Required by: Arc Agent tools, Arc estate monitoring, Arc remediation
  └── Risk: P0 unblocked work; no Azure MCP coverage; must be built before Arc domain features

Fabric Eventhouse + Activator
  └── Required by: Real-time alert detection, audit log long-term storage
  └── Risk: Fabric IQ still Preview; azapi provider required for Terraform; graceful degradation needed

Agent Identity (Entra Agent ID)
  └── Required by: All agent RBAC enforcement, audit attribution, scoped tool access
  └── Risk: Still Preview; may change before GA; minimize coupling to Entra Agent ID-specific APIs

pgvector Runbook RAG
  └── Required by: Knowledge base retrieval, contextual triage
  └── Risk: Dependent on runbook corpus quality; empty corpus = no retrieval value at MVP

Resource Topology Map
  └── Required by: Visual context for operators during incidents
  └── Risk: Most complex UI component; force-directed graph rendering; start with simple list+health if schedule tight
```

### Complexity Tiers

| Tier | Features | Build Strategy |
|---|---|---|
| **Low** (< 1 week) | Alert ingestion webhook, alert state tracking, Teams notification cards, Terraform modules (individual), Audit log append | Build in Phase 1; foundation for everything else |
| **Medium** (1-3 weeks) | Domain agent tool integration, remediation proposal workflow, Teams approval cards, Agent trace UI, Arc connectivity monitoring | Phase 1-2 |
| **High** (3-6 weeks) | Alert correlation engine, resource topology map, runbook RAG with quality corpus, multi-subscription alert aggregation, Arc MCP Server | Phase 2; some may slip to Phase 3 |
| **Very High** (6+ weeks) | Cross-incident pattern detection, dependency chain RCA, compliance reporting framework, advanced GitOps drift management | Phase 3+ |

---

## 11. MVP Feature Set (3–6 Month Target)

The smallest set of features that delivers the core value proposition: *"Operators can understand, investigate, and resolve any Azure infrastructure issue through a single intelligent platform."*

### Phase 1 MVP (Must Ship)

**Monitoring:** Multi-subscription Azure Monitor metric + alert ingestion; Arc connectivity status; basic alert feed in UI

**Alerting:** Alert ingestion → enrichment → deduplication → Cosmos DB state; Teams alert notification card; alert state management (New/Ack/Closed)

**AI Triage:** Orchestrator routes to domain agents; each agent queries Log Analytics + Resource Health; streaming response in UI; agent trace panel (collapsed)

**Remediation:** Proposal card in Web UI + Teams Adaptive Card; approve/reject with comment; basic audit log; action expiry

**Arc:** Custom Arc MCP Server with server inventory + connectivity status + extension health; AMA onboarding check

**Teams:** Two-way bot; alert notifications; approval cards

**IaC:** All core Terraform modules; GitHub Actions CI/CD; dev + prod environments

### Phase 2 (High Value)

- Alert correlation into incidents
- Resource topology map
- Runbook RAG with initial runbook corpus
- Arc K8s Container Insights integration
- Arc GitOps reconciliation monitoring
- Compliance reports (remediation activity, access review)
- Dynamic alert thresholds (surface Azure Monitor smart alerts)

### Phase 3 (Differentiators)

- Cross-incident pattern detection
- Dependency chain RCA
- Multi-approval for high-risk actions
- Arc SQL MI monitoring
- Full compliance reporting framework
- PagerDuty/ServiceNow integration

---

*Sources: Azure Monitor docs (Feb 2026), Azure Arc docs (Aug 2025), Azure SRE Agent docs (Dec 2025), Azure Monitor Observability Agent docs (Feb 2026), Azure Arc Kubernetes extensions (Mar 2026), Azure Monitor Alerts overview, Microsoft Teams bot overview, Terraform best practices docs. All fetched 2026-03-25.*
