# Azure Agentic Platform (AAP) — Roadmap

> Version: 1.0 | Date: 2026-03-25
> Granularity: Standard (7 phases)
> Derived from: PROJECT.md · ARCHITECTURE.md · REQUIREMENTS.md

---

## Phase Map

```
Phase 1: Foundation          ████████░░░░░░░░░░░░░░░░░░░░░░  Week 1–2
Phase 2: Agent Core          ░░░░████████████░░░░░░░░░░░░░░  Week 2–3   ← longest depends on P1
Phase 3: Arc MCP Server      ░░░░░░░░████████░░░░░░░░░░░░░░  Week 2–3   ← parallel, longest pole
Phase 4: Detection Plane     ░░░░░░░░░░░░████████░░░░░░░░░░  Week 3–4   ← parallel with P2/P3
Phase 5: Triage & Remediation░░░░░░░░░░░░░░░░████████████░░  Week 4–5   ← after P2+P3+P4 done
Phase 6: Teams Integration   ░░░░░░░░░░░░░░░░░░████████░░░░  Week 4–5   ← parallel with P5
Phase 7: Quality & Hardening ░░░░░░░░░░░░░░░░░░░░░░████████  Week 5–6
```

**Critical path:**
`networking → foundry → agent-identities → rbac → Arc MCP Server → Arc Agent → E2E → prod`

---

## Phase 1 — Foundation

**Goal:** All Azure infrastructure is provisioned by Terraform and ready to receive agent workloads.

**UI hint:** No
**IaC hint:** Yes

### Success Criteria

1. `terraform apply` on the dev environment completes without errors; all resources are visible in the Azure portal
2. VNet, subnets, private endpoints, NSGs, Log Analytics workspace, Application Insights, Event Hub, and ACR are provisioned
3. Azure AI Foundry workspace, project, and gpt-4o model deployment are live and reachable from the platform subscription
4. Cosmos DB (serverless, multi-region) and PostgreSQL Flexible Server (with pgvector extension enabled) are provisioned with correct private endpoints
5. GitHub Actions CI runs `terraform plan` on PRs and `terraform apply` on merge to main against the dev backend

### Requirements

| REQ-ID | Requirement |
|---|---|
| INFRA-001 | Terraform provisions VNet, subnets, private endpoints, NSGs with remote state |
| INFRA-002 | Terraform provisions Foundry workspace, project, gpt-4o deployment via azapi |
| INFRA-003 | Terraform provisions Cosmos DB Serverless + PostgreSQL with pgvector |
| INFRA-004 | Terraform provisions Container Apps environment + ACR |
| INFRA-008 | Dev/staging/prod environment isolation; CI plan/apply gates |

---

## Phase 2 — Agent Core

**Goal:** The full agent graph is running on Foundry Hosted Agents with the HandoffOrchestrator, non-Arc domain agents wired to Azure MCP Server, and the incident ingestion endpoint live.

**UI hint:** No
**IaC hint:** Yes

### Success Criteria

1. `POST /api/v1/incidents` with a synthetic Sev2 compute incident creates a Foundry thread and returns a `thread_id` in <2 seconds
2. Orchestrator correctly classifies the incident domain and hands off to the Compute agent (verified via agent trace log)
3. Compute, Network, Storage, Security, and SRE agents each produce a diagnosis with supporting Log Analytics evidence and a confidence score
4. All agent-to-agent messages include `correlation_id`, `thread_id`, and `message_type` fields (verified by message contract unit tests)
5. Each domain agent's managed identity can authenticate to its target subscription; `az role assignment list` confirms correct cross-subscription RBAC
6. Per-session token cost is tracked in Cosmos DB; a session that exceeds the $5 threshold is aborted with an error event on the SSE stream

### Requirements

| REQ-ID | Requirement |
|---|---|
| INFRA-005 | One system-assigned managed identity per domain agent (7 total) |
| INFRA-006 | Cross-subscription RBAC role assignments per domain agent |
| AGENT-001 | HandoffOrchestrator routes incidents to domain agents; cross-domain re-routing supported |
| AGENT-002 | Typed JSON message envelope on all inter-agent messages |
| AGENT-003 | Six domain agents deployed as Foundry Hosted Agents on Container Apps |
| AGENT-004 | Azure MCP Server (msmcp-azure GA) integrated for non-Arc domains |
| AGENT-007 | Per-session token budget enforcement; max_iterations ≤ 10 |
| AGENT-008 | DefaultAzureCredential via IMDS; no secrets in code or env vars |
| DETECT-004 | POST /api/v1/incidents endpoint creates Foundry thread |
| MONITOR-001 | Operator can query Azure Monitor metrics/logs across subscriptions via agents |
| MONITOR-002 | Agents query Log Analytics KQL across all subscriptions |
| MONITOR-003 | Resource Health and Service Health signals available to agents |
| MONITOR-007 | OpenTelemetry spans exported to App Insights and Fabric OneLake |
| TRIAGE-001 | Orchestrator classifies and routes incidents to domain agents |
| TRIAGE-002 | Domain agents query Log Analytics + Resource Health in every triage |
| TRIAGE-003 | Change tracking / Activity Log checked as first-pass RCA |
| TRIAGE-004 | Top root-cause hypothesis with evidence and confidence score |
| REMEDI-001 | No remediation executed without explicit human approval |
| AUDIT-001 | Every tool call recorded as OTel span in OneLake |
| AUDIT-005 | Agent actions attributable to specific Entra Agent ID |

---

## Phase 3 — Arc MCP Server

**Goal:** Custom Arc MCP Server is deployed as an internal Container App and the Arc Agent is fully operational with paginated Arc estate tooling.

**UI hint:** No
**IaC hint:** Yes

> ⚠️ **Longest-pole phase** — starts in parallel with Phase 2 (Week 2). Compose three separate Azure SDKs (`azure-mgmt-hybridcompute`, `azure-mgmt-hybridkubernetes`, `azure-mgmt-azurearcdata`), validate managed identity passthrough across all Arc resource types, and integration-test against real Arc-onboarded resources. Do not block Phases 2, 4, 5 on this phase.

### Success Criteria

1. Arc MCP Server container is running as an internal Container App (port 8080, streamable-http); not reachable from public internet
2. `arc_servers_list` tool returns all Arc servers in a seeded test subscription including servers beyond the first 100 (pagination exhausted)
3. `arc_k8s_gitops_status` returns Flux reconciliation state for a connected Arc K8s cluster
4. Arc Agent calls Arc MCP Server tools using its system-assigned managed identity; `DefaultAzureCredential` resolves without fallback to CLI
5. Arc Agent produces a triage diagnosis for a synthetic "Arc server disconnected" incident using connectivity + extension health tools
6. Playwright E2E confirms Arc estate >100 resources returns correct `total_count` (AGENT-006 / E2E-006)

### Requirements

| REQ-ID | Requirement |
|---|---|
| AGENT-005 | Custom Arc MCP Server (FastMCP) deployed as internal Container App |
| AGENT-006 | All Arc MCP list tools exhaust nextLink pagination; return total_count |
| MONITOR-004 | Arc server connectivity status inventoried; prolonged disconnection alerts |
| MONITOR-005 | Arc server extension health inventoried per machine |
| MONITOR-006 | Arc K8s cluster health + Flux GitOps status surfaced |
| TRIAGE-006 | Arc Agent performs connectivity + extension + GitOps checks before proposing remediation |
| E2E-006 | Playwright E2E against >100-record Arc estate validates pagination |

---

## Phase 4 — Detection Plane

**Goal:** The end-to-end Fabric detection pipeline is live: Azure Monitor alerts flow from Event Hub through Eventhouse KQL enrichment to Fabric Activator and trigger the agent platform's incident endpoint.

**UI hint:** No
**IaC hint:** Yes

### Success Criteria

1. A synthetic Azure Monitor metric alert fires, reaches Event Hub, and appears in the Eventhouse `RawAlerts` table within 60 seconds
2. KQL update policies enrich the alert into `EnrichedAlerts` and `DetectionResults` within 90 seconds of ingest; `classify_domain()` correctly assigns domain
3. Fabric Activator triggers and a `POST /api/v1/incidents` call arrives at the API gateway within 30 seconds of the `DetectionResults` row being written
4. Alert deduplication collapses 10 identical alerts within a 5-minute window into a single Cosmos DB incident record
5. Alert suppression rules are respected: suppressed alerts do not reach the agent graph
6. Azure Activity Log from all subscriptions is flowing into Fabric OneLake (verified by KQL query on `ActivityLog` table)

### Requirements

| REQ-ID | Requirement |
|---|---|
| INFRA-007 | Terraform provisions Fabric capacity, Eventhouse, Activator, OneLake |
| DETECT-001 | Azure Monitor Action Groups forward alerts to Event Hub |
| DETECT-002 | Fabric Eventhouse ingests from Event Hub; KQL update policies enrich + classify |
| DETECT-003 | Fabric Activator triggers Power Automate / User Data Function → POST /api/v1/incidents |
| DETECT-005 | Alert deduplication collapses repeated alerts in Cosmos DB |
| DETECT-006 | Alert state transitions tracked in Cosmos DB; bidirectional sync to Azure Monitor |
| DETECT-007 | Azure Monitor alert processing rules respected; suppressed alerts not routed |
| AUDIT-003 | Azure Activity Log exported to Log Analytics and mirrored to OneLake |

---

## Phase 5 — Triage & Remediation + Web UI

**Goal:** Operators can investigate and act on incidents entirely through the Web UI: dual SSE streaming shows agent reasoning in real time, runbook RAG is active, and the full HITL approval flow is operational.

**UI hint:** Yes
**IaC hint:** No

### Success Criteria

1. Browser opens the Web UI and receives both `event:token` and `event:trace` SSE events for a live incident; chat panel shows streaming tokens; trace panel shows tool calls and handoffs in real time
2. A remediation proposal card appears in the chat panel with Approve/Reject buttons; clicking Approve posts the decision and the agent resumes execution
3. Runbook vector search returns the top-3 most relevant runbooks for a query like "restart unhealthy Arc agent" with cosine similarity score
4. Dropping the SSE connection mid-stream and reconnecting with `Last-Event-ID` delivers all missed events without duplication
5. Multi-subscription selector restricts the alert feed and resource views to the selected subscriptions
6. A high-risk action proposes only after taking a resource state snapshot; a resource changed after approval causes the action to be aborted with a `stale_approval` error event

### Requirements

| REQ-ID | Requirement |
|---|---|
| TRIAGE-005 | Runbook RAG via pgvector; top-3 runbooks cited with version in triage response |
| TRIAGE-007 | Dual SSE (token + trace) with monotonic seq numbers; Last-Event-ID reconnect |
| REMEDI-002 | HITL approval gate: Adaptive Card to Teams; Foundry thread parked and resumed |
| REMEDI-003 | Approval records in Cosmos DB with ETag; 30-min expiry enforced |
| REMEDI-004 | Pre-execution stale-approval safety check; abort if resource diverged |
| REMEDI-005 | Approve/reject from Web UI or Teams updates same Cosmos record + resumes thread |
| REMEDI-006 | Rate limiting, "protected" tag enforcement, production-scope confirmation |
| UI-001 | Next.js + Fluent UI 2 Container App; MSAL PKCE authentication |
| UI-002 | Split-pane layout: streaming chat (left) + tabbed operational views (right) |
| UI-003 | Chat panel renders token SSE stream as streaming bubbles with agent labels |
| UI-004 | Agent trace panel renders trace SSE events as expandable JSON tree |
| UI-005 | Remediation proposal cards with expiry timer in chat panel |
| UI-006 | Real-time alert feed via SSE from Cosmos change feed |
| UI-007 | Multi-subscription context selector |
| UI-008 | 20s SSE heartbeat; Last-Event-ID reconnect on Container Apps 240s cut |
| AUDIT-002 | Approval records in Cosmos + OneLake (≥2 year retention) |
| AUDIT-004 | Audit Log tab: searchable agent action history per incident |

---

## Phase 6 — Teams Integration

**Goal:** The Teams bot is a co-equal interface to the Web UI: operators receive alert cards, can investigate by chat, approve or reject remediation actions, and share Foundry thread context across both surfaces.

**UI hint:** Yes
**IaC hint:** No

### Success Criteria

1. Alert notification Adaptive Card arrives in the correct Teams channel within 60 seconds of Fabric Activator firing
2. Operator types "@AAP investigate inc_01" in Teams; bot routes to Orchestrator and streams response back inline in the Teams thread
3. Approval Adaptive Card appears in Teams for a high-risk action; operator clicks Approve; the Web UI for the same incident updates to show the approval and the agent resumes
4. Teams and Web UI display the same conversation state for the same `thread_id` (verify by comparing message history on both surfaces)
5. A non-actioned approval card receives a reminder post after the configured escalation interval
6. After action execution, an outcome card (success/failure, duration) is posted to the same Teams thread

### Requirements

| REQ-ID | Requirement |
|---|---|
| TEAMS-001 | Two-way Teams bot; natural language routed to Orchestrator; responses streamed inline |
| TEAMS-002 | Alert notification Adaptive Card (v1.5) posted to Teams channel on alert fire |
| TEAMS-003 | Approval Adaptive Card in Teams; approve/reject updates in-place |
| TEAMS-004 | Shared Foundry thread ID between Teams and Web UI; same conversation state |
| TEAMS-005 | Escalation reminder posted if approval not acted on within N minutes |
| TEAMS-006 | Outcome card posted after approved action executes |

---

## Phase 7 — Quality & Hardening

**Goal:** The platform is production-ready: full Playwright E2E suite runs in CI, observability is complete, runbook library is seeded, security review is passed, and Terraform prod environment is applied.

**UI hint:** No
**IaC hint:** Yes

### Success Criteria

1. Full Playwright E2E suite passes against deployed Container Apps in CI; suite covers incident flow, HITL approval, SSE reconnect, Arc pagination, and cross-subscription auth
2. `terraform apply` on prod environment completes without errors; all resources provisioned with private endpoints and no public exposure except the Web UI and API gateway
3. Security review passes: no secrets in code or environment variables, all managed identities verified, Checkov static analysis clean
4. Runbook library seeded with at least one runbook per domain (6 domains × 2 runbooks minimum); vector search returns relevant results for 5 test queries
5. Load test confirms SSE streaming handles 50 concurrent incident streams without dropped connections or OOM errors on the Container Apps
6. Remediation activity report can be exported from the Audit Log viewer covering a 7-day period

### Requirements

| REQ-ID | Requirement |
|---|---|
| REMEDI-007 | Every executed action + rejected proposal recorded in Fabric OneLake with full schema |
| AUDIT-006 | Remediation activity report exportable from Audit Log viewer |
| E2E-001 | Playwright E2E suite against Container Apps; CI gate blocks merge on failure |
| E2E-002 | Full incident flow E2E: synthetic alert → Eventhouse → agent → SSE → UI |
| E2E-003 | HITL approval flow E2E: proposal → Teams card → approve → resume → outcome |
| E2E-004 | Cross-subscription RBAC E2E: each domain agent authenticates to its target sub |
| E2E-005 | SSE reconnect E2E: drop connection mid-stream; verify Last-Event-ID recovery |

---

## Requirement Coverage Matrix

| Category | Total v1 Reqs | Covered Across Phases |
|---|---|---|
| INFRA | 8 | P1(5), P2(2), P4(1) |
| AGENT | 8 | P2(7), P3(2) |
| DETECT | 7 | P2(1), P4(6) |
| MONITOR | 7 | P2(4), P3(3) |
| TRIAGE | 7 | P2(4), P3(1), P5(2) |
| REMEDI | 7 | P2(1), P5(6), P7(1) |
| UI | 8 | P5(8) |
| TEAMS | 6 | P6(6) |
| AUDIT | 6 | P2(2), P4(1), P5(2), P7(1) |
| E2E | 6 | P3(1), P7(5) |
| **Total** | **70** | **100% covered** |

---

## Dependencies Graph

```
P1 Foundation
 └─► P2 Agent Core ──────────────────────────────────────┐
      └─► P4 Detection Plane                              │
           └─► P5 Triage & Remediation ◄──────────────── P3 Arc MCP Server
                ├─► P6 Teams Integration                  │
                └─► P7 Quality & Hardening ◄──────────────┘
```

> **Arc MCP Server (P3)** starts in parallel with P2 (Week 2). P5 cannot complete until both P2 and P3 are done, because P5 wires the full Arc Agent triage flow into the remediation and UI paths.
