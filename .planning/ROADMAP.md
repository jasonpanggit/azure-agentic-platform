# Azure Agentic Platform (AAP) — Milestone v1.0 Roadmap

> Version: 1.0 | Date: 2026-03-25
> Derived from: PROJECT.md · ARCHITECTURE.md · REQUIREMENTS.md

---

## Phase Map

```
Week    1         2         3         4         5         6         7
        ├─────────┼─────────┼─────────┼─────────┼─────────┼─────────┤

Ph 1    ██████████
        Foundation
        (INFRA-001–004, INFRA-008)

Ph 2              ████████████████████
                  Agent Core
                  (21 reqs — design-first: AGENT-009 spec docs week 2)

Ph 3              █████████████████████████████
                  Arc MCP Server  ← longest pole; starts Week 2 in parallel
                  (7 reqs)

Ph 4                                  ████████████
                                      Detection Plane
                                      (8 reqs)

Ph 5                                            ████████████
                                                Triage & Remediation + Web UI
                                                (18 reqs)

Ph 6                                                      ████████████
                                                          Teams Integration
                                                          (6 reqs)

Ph 7                                                                ████████
                                                                    Quality & Hardening
                                                                    (7 reqs)
```

**Critical path:**
`networking → foundry → agent-identities → rbac → Arc MCP Server → Arc Agent → E2E → prod`

> **Phase 3 note:** Arc MCP Server begins in parallel with Phase 2 (Week 2) because it is the
> longest-pole deliverable. Phases 2, 4, and 5 do NOT block on Phase 3 completing —
> Arc-specific capabilities are simply unavailable until Phase 3 lands.

---

## Phase 1: Foundation

**Goal:** All Azure infrastructure provisioned by Terraform, ready for agent workloads.

**UI:** No | **IaC:** Yes

### Success Criteria

1. `terraform apply` on a clean subscription completes without error for all Phase 1 resources — VNet, subnets, private endpoints, NSGs, Container Apps environment, ACR, Cosmos DB, PostgreSQL, Foundry workspace, and Key Vault are all present and reachable within the VNet.
2. `terraform plan` runs as a required CI gate on every PR; `terraform apply` runs automatically on merge to `main`; state is stored in Azure Storage with lease-based locking — no manual `terraform state` operations are required.
3. Separate `dev.tfvars`, `staging.tfvars`, and `prod.tfvars` files exist; `terraform workspace select dev` and `terraform workspace select prod` each target different state backends with zero resource bleed-over — confirmed by `terraform plan` showing no diff after a clean apply.
4. Foundry workspace and project provision successfully using `azurerm_cognitive_account` (kind = "AIServices") and `azurerm_cognitive_account_project`; `gpt-4o` model deployment is reachable at the Foundry endpoint via `DefaultAzureCredential` from within the VNet.
5. PostgreSQL Flexible Server starts with the `pgvector` extension enabled; a test connection from within the VNet succeeds; Cosmos DB Serverless account has `incidents` and `approvals` containers with correct partition keys defined.
6. All provisioned resources are tagged with `environment`, `managed-by: terraform`, and `project: aap`; untagged resources cause a `terraform plan` lint failure in CI via a `required_tags` policy check.

### Requirements

| REQ-ID | Description |
|---|---|
| INFRA-001 | Terraform provisions VNet, subnets, private endpoints, and NSGs using `azurerm ~>4.65`; remote state in Azure Storage with locking |
| INFRA-002 | Terraform provisions Foundry workspace, project, and gpt-4o model deployment using `azapi ~>2.9` |
| INFRA-003 | Terraform provisions Cosmos DB Serverless (multi-region) with `incidents`/`approvals` containers and PostgreSQL Flexible Server with pgvector |
| INFRA-004 | Terraform provisions Container Apps environment with VNet integration and Container Registry; agent images pushed to ACR via GitHub Actions |
| INFRA-008 | Dev/staging/prod environment isolation via separate `tfvars` and per-environment state backends; CI runs `terraform plan` on PR and `terraform apply` on merge to main |

---

## ✅ Phase 2: Agent Core

**Goal:** Full agent graph running on Foundry Hosted Agents with `HandoffOrchestrator`, all non-Arc domain agents wired to Azure MCP Server, incident ingestion endpoint live.

**UI:** No | **IaC:** Yes (agent identities and RBAC)

**Status:** ✅ Complete (2026-03-26) — 98/98 tests pass, all requirements satisfied

> **Design-first gate (AGENT-009):** `.spec.md` files for all 7 domain agents must be committed
> and reviewed before any agent implementation code is written. This is the first deliverable
> of Phase 2, not the last.

### Plan Progress

| Plan | Title | Status | Requirements |
|---|---|---|---|
| 02-01 | Agent Specs + CI Lint Gate + Terraform Identity/RBAC | ✅ Complete | AGENT-009, INFRA-005, INFRA-006, AUDIT-005 |
| 02-02 | Shared Agent Infrastructure | ✅ Complete | AGENT-002, AGENT-007, AGENT-008, MONITOR-007, AUDIT-001, AUDIT-005 |
| 02-03 | API Gateway — Incident Endpoint | ✅ Complete | DETECT-004, MONITOR-001, MONITOR-002, MONITOR-003 |

### Success Criteria

1. `.spec.md` files for all 7 domain agents (Orchestrator, Compute, Network, Storage, Security, Arc, SRE) are committed to `agents/<name>/agent.spec.md` and reviewed/approved before any agent implementation code is written; CI enforces presence of these spec files as a required lint gate on the agent container images.
2. `POST /api/v1/incidents` with a synthetic payload creates a Foundry thread, dispatches to the Orchestrator, and the Orchestrator routes to the correct domain agent via `HandoffOrchestrator` — confirmed by OpenTelemetry traces showing the full handoff chain in Application Insights within 5 seconds end-to-end.
3. A domain agent (e.g., Compute) calls at least one Azure MCP Server tool (`compute.list_vms`), returns a structured response, and the tool call is logged as an OpenTelemetry span with `agentId`, `toolName`, `toolParameters`, `outcome`, and `durationMs` fields exported to Fabric OneLake.
4. A synthetic remediation proposal is generated by the SRE agent and confirmed NOT executed without an explicit approval call — verified by checking that no Azure ARM write calls were made from the agent's managed identity in the subscription activity log.
5. A session budget threshold of $5 is enforced: a test session forced to exceed the limit is aborted with a `budget_exceeded` event on the SSE stream; the Cosmos DB session record reflects `status: aborted` with the final cost snapshot.
6. All 6 domain agents authenticate to Azure APIs exclusively via `DefaultAzureCredential` resolving a system-assigned managed identity; no service principal secrets exist in environment variables, Key Vault references in code, or container image layers — confirmed by `trivy` container image scanning and `az role assignment list` RBAC verification.

### Requirements

| REQ-ID | Description |
|---|---|
| INFRA-005 | Terraform provisions one system-assigned managed identity (Entra Agent ID) per domain agent (7 total) using `azapi` |
| INFRA-006 | Terraform provisions cross-subscription RBAC role assignments scoped per domain agent (e.g., VM Contributor for Compute Agent on compute subscription only) |
| AGENT-001 | Orchestrator uses `HandoffOrchestrator` to classify incidents and route to domain `AgentTarget`; supports cross-domain re-routing on `needs_cross_domain: true` |
| AGENT-002 | All agent-to-agent messages use typed JSON envelope with `correlation_id`, `thread_id`, `source_agent`, `target_agent`, `message_type`; no raw strings between agents |
| AGENT-003 | Six domain agents deployed as Foundry Hosted Agents on Container Apps from a shared base image |
| AGENT-004 | Azure MCP Server (`msmcp-azure` GA) integrated as primary tool surface for all non-Arc resource domains |
| AGENT-007 | Per-session token budget tracked in Cosmos DB; sessions aborted at configurable threshold (default $5); `max_iterations` capped at ≤10 with exponential backoff |
| AGENT-008 | All agent containers authenticate via `DefaultAzureCredential` resolving system-assigned managed identity via IMDS; no credentials in code or env vars |
| AGENT-009 | Each domain agent has a `.spec.md` defining Persona, Goals, Workflow steps, Tool permissions, Safety constraints, and Example flows — reviewed and approved before implementation begins |
| DETECT-004 | `POST /api/v1/incidents` accepts structured incident payload (`incident_id`, `severity`, `domain`, `affected_resources`, `detection_rule`, `kql_evidence`) and creates a Foundry thread dispatched to the Orchestrator |
| MONITOR-001 | Operator can query Azure Monitor metrics and logs across all in-scope subscriptions from a single agent session |
| MONITOR-002 | Operator can query Log Analytics workspaces across subscriptions via ad-hoc KQL through the agent chat interface |
| MONITOR-003 | System surfaces Azure Resource Health and Service Health events alongside metrics to distinguish platform-caused from config-caused incidents |
| MONITOR-007 | OpenTelemetry spans from all agent containers exported to Application Insights (real-time) and Fabric OneLake (long-term audit) with full span fields |
| TRIAGE-001 | Orchestrator classifies every incident by domain and routes to the appropriate specialist with a typed handoff message |
| TRIAGE-002 | Each domain agent queries Log Analytics and Azure Resource Health as part of every triage; no diagnosis produced without both signal sources |
| TRIAGE-003 | Each domain agent checks Activity Log and Change Tracking for changes in the prior 2 hours as the first-pass RCA step for every incident |
| TRIAGE-004 | Each domain agent presents top root-cause hypothesis with supporting evidence (log excerpts, metric values, resource health state) and a confidence score |
| REMEDI-001 | No remediation action is executed without explicit human approval; every proposal includes description, target resource(s), estimated impact, risk level, and reversibility statement |
| AUDIT-001 | Every agent tool call recorded as OpenTelemetry span exported to Fabric OneLake with full action log schema (timestamp, correlationId, agentId, agentName, toolName, toolParameters, outcome, durationMs) |
| AUDIT-005 | Agent action log entries attributable to a specific Entra Agent ID object ID; no actions logged under a generic "system" identity |

---

## Phase 3: Arc MCP Server

**Goal:** Custom Arc MCP Server deployed as an internal-only Container App; Arc Agent fully operational with paginated Arc estate tooling.

**UI:** No | **IaC:** Yes (Arc MCP Container App)

**Status:** ✅ Complete (2026-03-26) — All 7 requirements satisfied, all 4 plans complete

> **Parallelism note:** This phase starts in Week 2 alongside Phase 2. It is the longest-pole
> deliverable and does NOT block Phases 2, 4, or 5. Arc-specific capabilities (TRIAGE-006,
> MONITOR-004–006) are unavailable until this phase completes.

### Plan Progress

| Plan | Title | Status | Requirements |
|---|---|---|---|
| 03-01 | Arc MCP Server — Core + Terraform | ✅ Complete | AGENT-005, AGENT-006, MONITOR-004, MONITOR-005, MONITOR-006 |
| 03-02 | Arc Agent Upgrade | ✅ Complete | TRIAGE-006, AGENT-005, AGENT-006 |
| 03-03 | Unit Tests + CI | ✅ Complete | AGENT-005, AGENT-006, MONITOR-004, MONITOR-005, MONITOR-006 |
| 03-04 | E2E-006 Playwright Test | ✅ Complete | E2E-006 |

### Success Criteria

1. Arc MCP Server Container App is deployed as an internal (no public ingress) Container App within the same VNet as the agent layer; the Arc Agent resolves it via internal DNS and successfully calls `arc_servers_list` in an integration test without any public internet egress.
2. `arc_servers_list` and `arc_k8s_list` tools exhaust all `nextLink` pages for a seeded Arc estate of >100 Arc servers; the `total_count` field in the response matches the actual count — no page is silently dropped — confirmed by comparing `total_count` to a direct ARM API count call.
3. Arc MCP Server tools cover all three Arc resource types: `HybridComputeManagementClient` (servers), `ConnectedKubernetesClient` (Kubernetes), and `AzureArcDataManagementClient` (data services); each resource type has at least one list and one get tool, all Pydantic-validated with explicit parameter schemas.
4. Arc Agent performs a complete pre-triage sequence for a simulated Arc server incident: connectivity check → extension health check → GitOps reconciliation status (if K8s cluster) → produces a structured triage summary with findings from each step before any remediation proposal is emitted.
5. A Playwright E2E test provisions a mock Arc estate of >100 servers, calls `arc_servers_list`, and asserts that `total_count` matches the seeded count and all `nextLink` pages were followed to completion — test runs in CI and blocks merge on failure.
6. A prolonged Arc server disconnection (exceeding the configurable threshold) triggers an alert via `POST /api/v1/incidents`; the Arc Agent receives the incident, opens a triage thread, and produces a diagnosis citing the last heartbeat timestamp and the connectivity duration.

### Requirements

| REQ-ID | Description |
|---|---|
| AGENT-005 | Custom Arc MCP Server built with FastMCP (`mcp[cli]==1.26.0`), deployed as internal Container App; tools for Arc Servers (`HybridComputeManagementClient`), Arc K8s (`ConnectedKubernetesClient`), Arc Data Services (`AzureArcDataManagementClient`) |
| AGENT-006 | All Arc MCP Server list tools exhaust `nextLink` pagination and return `total_count`; no tool silently returns a partial estate |
| MONITOR-004 | Arc server connectivity status (Connected/Disconnected/Expired, last heartbeat, agent version) inventoried via Arc MCP Server; prolonged disconnection triggers an alert |
| MONITOR-005 | Arc server extension health (AMA, VM Insights, Policy, Change Tracking) — install status, version, last op — inventoried per Arc machine |
| MONITOR-006 | Arc K8s cluster health (nodes ready/not-ready, pod status rollup, Flux GitOps reconciliation status) surfaced via Arc MCP Server |
| TRIAGE-006 | Arc Agent performs Arc-specific triage using Arc MCP Server tools: connectivity check, extension health check, GitOps reconciliation status before proposing any remediation |
| E2E-006 | Playwright E2E verifies Arc MCP Server against a seeded Arc estate with >100 Arc servers; confirms `nextLink` pagination is exhausted and `total_count` matches the full inventory |

---

## Phase 4: Detection Plane

**Goal:** End-to-end Fabric detection pipeline live — Azure Monitor alerts flow from Event Hub through Eventhouse KQL enrichment to Fabric Activator and trigger the agent platform's incident endpoint.

**UI:** No | **IaC:** Yes (Fabric resources)

**Status:** ✅ Complete (2026-03-26) — all 4 plans complete, 92 unit tests passing, 18 integration stubs scaffolded, CI workflows live

### Plan Progress

| Plan | Title | Status | Requirements |
|---|---|---|---|
| 04-01 | Infrastructure: Fabric, Event Hub, Networking & Activity Log | ✅ Complete | INFRA-007, DETECT-001, AUDIT-003 |
| 04-02 | KQL Pipeline — Table Schemas, classify_domain(), Update Policies | ✅ Complete | DETECT-002, DETECT-007 |
| 04-03 | Fabric Activator + User Data Function (DETECT-003) | ✅ Complete | DETECT-003, DETECT-005, DETECT-006 |
| 04-04 | Dedup, State Sync, Processing Rules & Tests (DETECT-005/006/007) | ✅ Complete | DETECT-005, DETECT-006 |

### Success Criteria

1. A fired Azure Monitor alert appears in the Eventhouse `RawAlerts` table within 30 seconds of firing; KQL update policies enrich it into `EnrichedAlerts` (with resource inventory join) and classify it into `DetectionResults` with a non-null `domain` value — confirmed by querying the Eventhouse tables after injecting a synthetic alert via the Azure Monitor API.
2. Fabric Activator fires a trigger on a new `DetectionResults` row and the Fabric User Data Function posts to `POST /api/v1/incidents`; the full round-trip from alert fire to Orchestrator thread creation completes in under 60 seconds — measured via OpenTelemetry trace timestamps at both ends.
3. Alert deduplication works at both layers: 10 identical alerts (same `resource_id`, same rule) within a 5-minute window collapse into a single Cosmos DB incident record via ETag optimistic concurrency (layer 1); a second distinct alert for a resource that already has an open incident is correlated to the existing incident rather than spawning a new agent thread (layer 2) — both behaviours confirmed by a targeted load test.
4. Alert state transitions (New → Acknowledged → Closed) are written to Cosmos DB with actor and timestamp; a bidirectional sync call updates the originating Azure Monitor alert state — confirmed by checking the Azure Monitor alert state via ARM API after a simulated close event.
5. Azure Monitor processing rules that suppress an alert class are respected: suppressed alerts do NOT appear in `DetectionResults` and do NOT trigger agent threads — verified by creating a suppression rule, firing a matching alert, and asserting no Cosmos DB incident record is created.
6. Azure Activity Log from all in-scope subscriptions is exported to Log Analytics and mirrored to Fabric OneLake; a KQL query on the OneLake `ActivityLog` table returns events with timestamps within 5 minutes of the source event.

### Requirements

| REQ-ID | Description |
|---|---|
| INFRA-007 | Terraform provisions Fabric capacity, Eventhouse (KQL database), Activator workspace, and OneLake lakehouse using `azapi` |
| DETECT-001 | Azure Monitor Action Groups on all subscriptions forward fired alerts to Azure Event Hub (Standard tier, 10 partitions); Event Hub is the single ingest point |
| DETECT-002 | Fabric Eventhouse ingests raw alerts from Event Hub into `RawAlerts`; KQL update policies enrich into `EnrichedAlerts` and classify into `DetectionResults` using `classify_domain()` |
| DETECT-003 | Fabric Activator triggers on new `DetectionResults` rows where `domain != null`; routes to Fabric User Data Function which POSTs to `POST /api/v1/incidents` |
| DETECT-005 | Two-layer deduplication: (1) time-window collapse (5-min window, ETag optimistic concurrency) into single Cosmos DB record; (2) open-incident check correlates new alerts to existing open incidents rather than spawning duplicate threads |
| DETECT-006 | Alert state transitions (New → Acknowledged → Closed) tracked in Cosmos DB with timestamps and actor; state bidirectionally synced back to Azure Monitor |
| DETECT-007 | Azure Monitor alert processing rules are respected; suppressed alerts are not routed to agents |
| AUDIT-003 | Azure Activity Log exported from all in-scope subscriptions to Log Analytics and mirrored to Fabric OneLake; retention is ≥2 years in OneLake |

---

## Phase 5: Triage & Remediation + Web UI

**Goal:** Operators can investigate and act on incidents through the Web UI — dual SSE streaming, runbook RAG active, full HITL approval flow operational.

**UI:** Yes | **IaC:** No

**Status:** ✅ Complete (7/7 plans)

### Plan Progress

| Plan | Title | Status | Requirements |
|---|---|---|---|
| 05-00 | Wave 0 — Test Infrastructure & Stubs | ✅ Complete | UI-001, UI-002, TRIAGE-005, TRIAGE-007, UI-008, REMEDI-002–006, REMEDI-008, AUDIT-002, AUDIT-004 |
| 05-01 | Web UI Shell | Not started | UI-001, UI-002, UI-007 |
| 05-02 | SSE Streaming | Not started | UI-002, UI-003, UI-004, UI-008, TRIAGE-007 |
| 05-03 | Runbook RAG | Not started | TRIAGE-005, REMEDI-008 |
| 05-04 | HITL Approval Gate | Not started | REMEDI-002, REMEDI-003, REMEDI-004, REMEDI-005, REMEDI-006 |
| 05-05 | Audit Trail + Remediation UI | Not started | AUDIT-002, AUDIT-004, UI-005, UI-006 |
| 05-06 | Phase 5 Integration | Not started | Full integration + E2E |

### Success Criteria

1. The Web UI loads, authenticates the operator via MSAL PKCE, and renders the split-pane layout (chat left, tabbed dashboard right) with a first meaningful paint under 2 seconds on a cold load — confirmed by Playwright timing assertions; the `event:token` SSE stream delivers the first token within 1 second of the agent starting its response.
2. `event:token` and `event:trace` SSE events arrive on two concurrent streams with monotonic sequence numbers; after a simulated 10-second connection drop, the client reconnects using `Last-Event-ID` and receives all missed events in order with zero duplication — confirmed by sequence number continuity assertions in a Playwright test.
3. Runbook RAG is active: a domain agent triage response cites the top-3 most semantically relevant runbooks (by pgvector cosine similarity score) including runbook name and version; a test query for a known incident type returns runbooks with >0.75 cosine similarity in under 500ms.
4. A high-risk remediation proposal activates the HITL gate: an Adaptive Card is posted to Teams and the Foundry thread parks (no polling loop); the thread resumes within 5 seconds of the webhook approval callback; an expired approval (>30 minutes) is never executed and records `status: expired` with an expiry timestamp in Cosmos DB.
5. Pre-execution Resource Identity Certainty is enforced: before executing any remediation, the agent takes a resource state snapshot and verifies the target using at least 2 independent signals (resource ID + ARM resource health + tags match); a test where the resource changes state after approval is granted causes the action to abort with a `stale_approval` error event — confirmed by the Cosmos DB approval record showing `abort_reason: stale_approval`.
6. For an Arc K8s cluster with Flux detected as the GitOps controller, the agent creates a PR against the GitOps repo instead of applying directly via kubectl; for a non-GitOps Arc K8s cluster, the direct-apply path is used — both branches confirmed by separate Playwright tests asserting the correct execution path.

### Requirements

| REQ-ID | Description |
|---|---|
| TRIAGE-005 | Runbook library stored in PostgreSQL with pgvector; agents retrieve top-3 semantically relevant runbooks via vector search and cite them (with version) in triage response |
| TRIAGE-007 | SSE stream delivers `event:token` and `event:trace` with monotonic sequence numbers; client reconnects using `Last-Event-ID` after dropped connection |
| REMEDI-002 | High-risk/critical remediation proposals trigger HITL gate: Adaptive Card posted to Teams, Foundry thread parked (no polling) until webhook callback |
| REMEDI-003 | Approval records written to Cosmos DB with `{ id, action_id, thread_id, status, expires_at }` using ETag concurrency; proposals expire after configurable timeout (default 30 min) and are never executed after expiry |
| REMEDI-004 | Pre-execution Resource Identity Certainty: 2+ independent signals before execution; diverged resource state since approval causes abort with `stale_approval` error event |
| REMEDI-005 | Operator can approve or reject any remediation from Web UI or Teams; both surfaces update the same Cosmos DB record and resume the same Foundry thread |
| REMEDI-006 | Remediation actions rate-limited per agent per subscription; agents cannot act on `protected`-tagged resources; prod-subscription actions require explicit scope confirmation |
| REMEDI-008 | GitOps Remediation Path: Flux/ArgoCD-managed Arc K8s clusters → agent creates PR against GitOps repo; non-GitOps clusters → direct-apply path |
| UI-001 | Next.js App Router + Fluent UI 2 (`@fluentui/react-components` v9) deployed as Container App; operator authenticates via MSAL PKCE (`@azure/msal-browser`) |
| UI-002 | Split-pane layout: streaming chat panel (left) + tabbed operational views — Topology, Alerts, Resources, Audit Log (right) |
| UI-003 | Chat panel renders `event:token` SSE chunks as character-by-character streaming into Fluent UI 2 chat bubbles annotated with agent name; handoff gaps show "thinking" indicator |
| UI-004 | Agent trace panel renders `event:trace` SSE events as expandable JSON tree showing tool calls (name + args + response), agent handoffs, and approval gate markers; collapsed by default |
| UI-005 | Operator can view and act on remediation proposal cards (action description, impact, expiry timer, Approve/Reject) directly in the chat panel without leaving the UI |
| UI-006 | Alert/incident feed shows real-time alert stream (pushed via SSE from Cosmos DB change feed) filterable by subscription, severity, domain, and status; updates without page refresh |
| UI-007 | Multi-subscription context: operator selects one or more subscriptions; alert feed, resource views, and agent queries scope to the selection |
| UI-008 | SSE route handler (`/api/stream`) sends a 20-second heartbeat event to prevent Container Apps 240s connection termination; client reconnects with `Last-Event-ID` on drop |
| AUDIT-002 | All remediation approval records (proposed, approved/rejected, executed/expired) stored in Cosmos DB (hot query) and Fabric OneLake (long-term retention ≥2 years) |
| AUDIT-004 | Operator can query full agent action history for any incident from the Web UI Audit Log tab, filterable by agent, action type, resource, and time range |

---

## Phase 6: Teams Integration

**Goal:** Teams bot is a co-equal interface to the Web UI — alert cards, investigate by chat, approve/reject remediation, shared Foundry thread context across both surfaces.

**UI:** Yes (Teams bot) | **IaC:** No

**Status:** ✅ Complete (2026-03-27) — all 5 plans complete, 100 tests at 92.34% coverage, 6 TEAMS requirements satisfied

### Plan Progress

| Plan | Title | Status | Requirements |
|---|---|---|---|
| 06-01 | Teams Bot Scaffold + Card Builders + CI | ✅ Complete | TEAMS-001, TEAMS-002, TEAMS-003, TEAMS-005, TEAMS-006 |
| 06-02 | Bot Framework Adapter + Proactive Messaging | ✅ Complete | TEAMS-001, TEAMS-004 |
| 06-03 | API Gateway Changes + Cross-Surface Thread Sharing | ✅ Complete | TEAMS-003, TEAMS-004, TEAMS-005 |
| 06-04 | Escalation Scheduler + Proactive Card Posting | ✅ Complete | TEAMS-002, TEAMS-005, TEAMS-006 |
| 06-05 | Teams App Manifest + Integration Tests + Deployment Config | ✅ Complete | TEAMS-001, TEAMS-002, TEAMS-003, TEAMS-004, TEAMS-005, TEAMS-006 |

### Success Criteria

1. A natural-language message sent to the Teams bot is routed to the Orchestrator, processed by the appropriate domain agent, and the response streams back inline in Teams — confirmed by an integration test sending "investigate the CPU alert on vm-prod-01" and receiving a structured triage summary within 30 seconds.
2. When an alert fires, the bot posts a structured Adaptive Card (v1.5) to the configured Teams channel within 10 seconds of the Cosmos DB incident record being created; the card includes resource name, severity, subscription, timestamp, and a functional "Investigate" action button that opens the correct incident in the Web UI.
3. A high-risk remediation approval Adaptive Card is posted to Teams; an operator clicks Reject directly in Teams; the Cosmos DB approval record updates to `status: rejected`, the Foundry thread closes cleanly, and the card in Teams updates in-place to show "Rejected by <operator UPN>" — confirmed end-to-end.
4. The Teams bot and Web UI share the same `thread_id` for a given incident: after starting an investigation in the Web UI, the operator sends a follow-up question in Teams and receives a contextually correct response referencing the prior conversation — confirmed by asserting the same `thread_id` in both Foundry thread history payloads.
5. An unacted approval card triggers an escalation reminder posted to the Teams channel after the configurable escalation interval (default N minutes); the reminder includes the original action description and a direct link to the Web UI approval view.
6. After an approved remediation action executes, the bot posts an outcome card (success/failure, action description, duration, resulting resource state) to the Teams channel within 60 seconds of execution completing — confirmed by end-to-end test with a synthetic low-risk action.

### Requirements

| REQ-ID | Description |
|---|---|
| TEAMS-001 | Teams bot (`@microsoft/teams.js`) deployed as Container App; supports two-way conversation routed to Orchestrator with inline streaming responses |
| TEAMS-002 | Bot posts structured Adaptive Card (v1.5) to Teams channel on alert fire: resource, severity, subscription, timestamp, "Investigate" action button |
| TEAMS-003 | Remediation approval Adaptive Cards posted to Teams; operator can Approve/Reject directly in Teams without opening the Web UI; card updates in-place on decision |
| TEAMS-004 | Teams bot and Web UI share the same Foundry `thread_id` per incident; both surfaces show the same conversation state; operator can switch between them without losing context |
| TEAMS-005 | Unacted approval card triggers escalation reminder posted to Teams channel after configurable timeout |
| TEAMS-006 | After approved remediation executes, bot posts outcome card (success/failure, duration, resource state) to close the loop with the operator |

---

## ✅ Phase 7: Quality & Hardening

**Goal:** Platform is production-ready — full Playwright E2E suite running in CI, observability complete, runbook library seeded, security review passed, Terraform prod environment applied.

**UI:** No | **IaC:** Yes (prod environment)

**Status:** ✅ Complete (2026-03-27) — all 6 plans complete, 7 requirements satisfied (E2E-001–005, REMEDI-007, AUDIT-006), 60 runbooks seeded, security CI live, Terraform prod 12-module config complete

### Plan Progress

| Plan | Title | Status | Requirements |
|---|---|---|---|
| 07-01 | OTel Auto-Instrumentation + Observability Tab | ✅ Complete | D-05, D-06, D-07 |
| 07-02 | Remediation Audit Trail + Audit Export | ✅ Complete | REMEDI-007, AUDIT-006 |
| 07-03 | Runbook Library Seed | ✅ Complete | D-08, D-09, D-10 |
| 07-04 | Terraform Prod + Security Review | ✅ Complete | D-11, D-12, D-13, D-14, D-15 |
| 07-05 | E2E Infrastructure + Real Endpoint Migration | ✅ Complete | E2E-001 |
| 07-06 | E2E Specs — Incident Flow, HITL, RBAC, SSE Reconnect | ✅ Complete | E2E-002, E2E-003, E2E-004, E2E-005, AUDIT-006 |

### Success Criteria

1. Full Playwright E2E suite runs against deployed Container Apps (not mocks or stubs) in CI; no test targets `localhost` or stubs Azure APIs — all tests use real deployed endpoints; CI blocks merge if any E2E test fails; the full suite completes in under 15 minutes.
2. The full incident flow E2E test passes end-to-end: synthetic alert injected → Eventhouse `RawAlerts` → KQL enrichment → `DetectionResults` → Activator → `POST /api/v1/incidents` → Orchestrator → domain agent triage → `event:token` SSE stream → UI renders the triage response correctly — asserted via Playwright DOM assertions and SSE event log.
3. HITL approval E2E test passes: agent proposes high-risk action → Adaptive Card posted to Teams (confirmed via Teams API) → operator approves via webhook call → Foundry thread resumes → action executes → outcome card posted to Teams — all steps verified with correlated timestamps and `thread_id`.
4. Cross-subscription RBAC E2E passes both positive and negative paths: each domain agent's managed identity successfully authenticates and calls its target subscription's ARM API (positive); an RBAC-scope violation test (Compute Agent attempting a Storage API call on the storage subscription) is rejected with `403 Forbidden` (negative).
5. SSE reconnect E2E passes: a simulated network drop mid-stream is followed by client reconnect using `Last-Event-ID`; all buffered events are delivered in sequence order with zero duplication or gaps — confirmed by sequence number continuity assertion across the drop boundary.
6. A remediation activity report covering all agent actions in a 30-day window (with full approval chain) is exported from the Audit Log viewer as a structured document; the export contains every `REMEDI-*` event with `agentId`, `toolName`, `approvedBy`, and `outcome` fields populated — confirming SOC 2 audit readiness.
7. `terraform apply` on the `prod` environment completes without errors; all prod resources are tagged, private-endpoint-isolated, and RBAC-constrained; a subsequent `terraform plan` on prod shows zero resource changes.

### Requirements

| REQ-ID | Description |
|---|---|
| REMEDI-007 | Every executed remediation action and every rejected proposal recorded in Fabric OneLake with full action log schema (`agentId`, `toolName`, `toolParameters`, `approvedBy`, `outcome`, `durationMs`) |
| AUDIT-006 | Remediation activity report (all agent actions in a period with approval chain) exportable from the Audit Log viewer; covers SOC 2 and internal audit requirements |
| E2E-001 | Playwright E2E suite runs against deployed Container Apps (not mocks); CI gate blocks merge if any E2E test fails |
| E2E-002 | E2E test verifies full incident flow: synthetic alert → Eventhouse → Activator → `/api/v1/incidents` → Orchestrator → domain agent → SSE stream → UI renders correctly |
| E2E-003 | E2E test verifies HITL approval flow: high-risk proposal → Adaptive Card to Teams → operator approves via webhook → Foundry thread resumes → action executes → outcome card posted |
| E2E-004 | E2E test verifies cross-subscription RBAC: each domain agent authenticates to its target subscription using system-assigned managed identity; scope violations are rejected with `403` |
| E2E-005 | E2E test verifies SSE reconnect: dropped connection mid-stream → client reconnects with `Last-Event-ID` → all missed events delivered in order without duplication |

---

## Phase 8: Azure Validation & Incident Simulation

**Goal:** Validate the production environment end-to-end — close provisioning gaps, run live incident simulations, and confirm the platform works against real Azure infrastructure.

**UI:** No | **IaC:** No (ops commands only)

**Status:** ⚠️ Plans Complete (2026-03-29) — all 5 plans executed; validation FAIL (2 BLOCKING findings: F-01 Foundry RBAC, F-02 runbook search 500 — require operator action before phase closes)

### Plan Progress

| Plan | Title | Status | Notes |
|---|---|---|---|
| 08-01 | Fix Provisioning Gaps | ✅ Complete | Task 08-01-01 committed (--create flag); tasks 08-01-02 through 08-01-06 require operator execution |
| 08-02 | Critical-Path Validation | ✅ Complete | E2E strict mode (no test.skip), 22/30 tests pass, VALIDATION-REPORT.md: 2 BLOCKING (F-01 RBAC, F-02 runbook 500), 6 DEGRADED |
| 08-03 | Incident Simulation | ✅ Complete | 7/7 scenarios PASS, 8/8 Foundry runs completed; CI gate (simulation job) wired into staging-e2e-simulation.yml; F-09/F-10/F-11 (MCP tool groups) logged |
| 08-04 | Deferred Phase 7 Work | ✅ Complete | instrumentation.py (foundry_span/mcp_span/agent_span); foundry.py/chat.py/approvals.py instrumented; e2e-teams-roundtrip.spec.ts (3 tests); 08-04-06 operator-only |
| 08-05 | Validation Closeout | ✅ Complete | VALIDATION-REPORT.md finalized (OTel section, summary counts, conclusion, backlog items); BACKLOG.md created (11 items); STATE.md updated |



```
Phase 1 (Foundation)
│
│  Must complete before Phase 2 and Phase 3 can start
│
├──► Phase 2 (Agent Core) ──────────────────────────────────────────────────► Phase 5 (Triage & Remediation + Web UI)
│         │                                                                              │
│         │  DETECT-004 (incident endpoint) required by Phase 4                         │
│         └──────────────────────────────────────────────────────────────► Phase 4 (Detection Plane)
│                                                                                        │
├──► Phase 3 (Arc MCP Server) ─────────────────────────────────────────────► Phase 5 (Arc REMEDI-008, TRIAGE-006)
│         │                                                                              │
│         │  Parallel to Phase 2 — does NOT block Phase 4 or Phase 5 (non-Arc paths)   │
│                                                                                        │
│    Phase 4 complete ──────────────────────────────────────────────────────► Phase 5   │
│                                                                                        ▼
│    Phase 2 + Phase 3 + Phase 4 complete ──────────────────────────────────► Phase 5 (fully unblocked)
│
│    Phase 5 complete ──────────────────────────────────────────────────────► Phase 6 (Teams shares Foundry threads)
│
│    Phase 5 + Phase 6 complete ────────────────────────────────────────────► Phase 7 (E2E covers full stack)
│
└── Critical path: P1 → P2 → P4 → P5 → P6 → P7
    Parallel track: P1 → P3 (starts Week 2 alongside P2)
```

### Hard Dependencies

| Phase | Depends On | Reason |
|---|---|---|
| Phase 2 | Phase 1 complete | Agent identities need Foundry workspace and Container Apps environment |
| Phase 3 | Phase 1 complete | Arc MCP Server is a Container App; needs ACR and VNet |
| Phase 4 | Phase 2 (DETECT-004) | Fabric Activator POSTs to `/api/v1/incidents`; endpoint must be live |
| Phase 5 (non-Arc) | Phase 2 + Phase 4 complete | SSE streaming, runbook RAG, and HITL gate build on the agent core and live detection pipeline |
| Phase 5 (Arc) | Phase 3 complete | REMEDI-008 and TRIAGE-006 require Arc MCP Server operational |
| Phase 6 | Phase 5 complete | Teams shares Foundry threads with Web UI; REMEDI-002 HITL gate must be live |
| Phase 7 | Phases 5 + 6 complete | E2E suite covers the full stack end-to-end |

### Phase 9: Web UI Revamp — Modern Portal with Tailwind + shadcn/ui

**Goal:** Tear down and rebuild the web UI from scratch. Replace Fluent UI / Griffel with Tailwind CSS + shadcn/ui. Redesign the full portal: scrollable chat panel with fixed input, dashboard, and layout — using a frontend specialist for visual design quality.
**Requirements**: UI-001 through UI-008 (re-addressed)
**Depends on:** Phase 8
**Plans:** 6 plans

Plans:
- [x] 09-01 Tailwind + shadcn/ui Foundation
- [x] 09-02 Layout Foundation
- [x] 09-03 Chat Components
- [x] 09-04 Dashboard Components
- [x] 09-05 Observability Components
- [x] 09-06 Cleanup + Verification

### Phase 10: API Gateway Hardening

**Goal:** Harden the API gateway control plane by removing implicit auth bypass, validating audit query inputs before KQL execution, and making runbook search fail truthfully when its data plane is unavailable.
**Requirements:** Hardening for DETECT-004, TRIAGE-005, AUDIT-004
**Depends on:** Phase 8
**Plans:** 2 plans

Plans:
- [x] 10-01 API Gateway Auth & Audit Hardening
- [x] 10-02 Runbook Search Availability Hardening

### Phase 11: Patch Domain Agent

**Goal:** Build a Patch domain agent that uses Azure Resource Graph (ARG) to query Update Manager tables (`PatchAssessmentResources`, `PatchInstallationResources`, etc.) and expose patch status, compliance, and history to the orchestrator. Wire the agent into the orchestrator's routing table so patch-related incidents and queries are dispatched to the Patch domain agent.
**Requirements**: TRIAGE-002, TRIAGE-003, TRIAGE-004, TRIAGE-005, REMEDI-001, AGENT-001, AGENT-002, AGENT-008, AGENT-009, AUDIT-001, AUDIT-005
**Depends on:** Phase 10
**Reference:** https://learn.microsoft.com/en-us/azure/update-manager/query-logs
**Plans:** 3/3 plans complete

Plans:
- [x] 11-01 Patch Agent Spec + Implementation + Unit Tests
- [x] 11-02 Orchestrator Routing + Integration
- [x] 11-03 Terraform + CI/CD

### Phase 12: add a new patch management tab and show all the patch related information

**Goal:** [To be planned]
**Requirements**: TBD
**Depends on:** Phase 11
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 12 to break down)

### Phase 13: Patch Management Tab

**Goal:** Add a Patch Management tab to the web UI dashboard showing per-machine compliance data and installation history from Azure Update Manager via Azure Resource Graph.
**Requirements**: UI-002 (extended), D-01 through D-16 (phase-specific)
**Depends on:** Phase 11 (Patch Domain Agent), Phase 9 (Web UI Revamp)
**Status:** ✅ Complete + Verified (2026-03-31) — 1/1 plan, 15 unit tests pass, tsc exits 0, 5/5 format-relative-time tests pass, 18/18 must_haves confirmed, 16/16 D-requirements met

Plans:
- [x] 13-01 Patch Management Tab — Full Stack Implementation

### Phase 14: Production Stabilisation

**Goal:** Make the production deployment fully functional by resolving all known BLOCKING and HIGH-severity production blockers. Wire agents to MCP-enabled instances, fix MCP tool groups, deploy real Arc MCP Server, fix runbook RAG, remove hardcoded agent IDs, and restore Teams proactive alerting.
**Requirements**: Stabilisation — resolves Backlog F-02, F-04, F-09, F-10, F-11; CONCERNS BUG-001, BUG-002, DEBT-002, DEP-003, DEP-005, GAP-001, GAP-002, GAP-003, GAP-004, GAP-009
**Depends on:** Phase 13
**Status:** Not started
**Plans:** 1 plan (12 tasks across 6 milestones)

Plans:
- [ ] 14-01 through 14-12 — see `.planning/phases/14-prod-stabilisation/PLAN.md`

---

## Requirement Coverage Matrix

| Category | Total v1 Reqs | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 | Phase 6 | Phase 7 |
|---|---|---|---|---|---|---|---|---|
| INFRA | 8 | 5 | 2 | — | 1 | — | — | — |
| AGENT | 9 | — | 7 | 2 | — | — | — | — |
| DETECT | 7 | — | 1 | — | 6 | — | — | — |
| MONITOR | 7 | — | 4 | 3 | — | — | — | — |
| TRIAGE | 7 | — | 4 | 1 | — | 2 | — | — |
| REMEDI | 8 | — | 1 | — | — | 6 | — | 1 |
| UI | 8 | — | — | — | — | 8 | — | — |
| TEAMS | 6 | — | — | — | — | — | 6 | — |
| AUDIT | 6 | — | 2 | — | 1 | 2 | — | 1 |
| E2E | 6 | — | — | 1 | — | — | — | 5 |
| **Total** | **72** | **5** | **21** | **7** | **8** | **18** | **6** | **7** |

> All 72 v1 requirements are covered across the 7 phases. No requirement is unassigned.

---

## v2.0 Roadmap — World-Class AIOps (Phases 19–28)

> Defined: 2026-04-02. Full design spec: `docs/superpowers/specs/2026-04-02-world-class-aiops-roadmap-design.md`
>
> Three tracks: Track 1 (19–21) makes the platform work in production. Track 2 (22–25) adds Stage 4 intelligence. Track 3 (26–28) completes Stage 5 autonomous operations.

### Phase 19: Production Stabilisation

**Goal:** Resolve all known BLOCKING and HIGH-severity production defects so the platform is fully operational: authenticated, all agents functional, detection plane wiring ready, no unauthenticated external endpoints, Teams proactive alerting delivering cards. Executes all 12 tasks deferred from Phase 14 across 6 milestones: agent MCP tool group registration, auth enablement, Azure MCP Server security, Arc MCP Server real image, runbook RAG, hardcoded ID removal, Teams Bot registration, and agent framework RC5 pin.
**Requirements**: PROD-001, PROD-002, PROD-003, PROD-005
**Depends on:** Phase 18
**Status:** ✅ Complete (2026-04-02) — 5/5 plans complete
**Plans:** 5/5 plans complete

Plans:
- [x] 19-1: MCP Security Hardening — COMPLETE (2026-04-02): Terraform module azure-mcp-server created, internal-only ingress, Dockerfile auth-bypass flag removed, import block for ca-azure-mcp-prod, azure_mcp_server_url wired from internal FQDN (SEC-001 + DEBT-013 resolved)
- [x] 19-2: Authentication Enablement — COMPLETE (2026-04-02): Terraform wired Entra auth, staging validation script, E2E service principal docs
- [x] 19-3: MCP Tool Registration — COMPLETE (2026-04-02): azapi_resource MCP connection blocks for Azure MCP + Arc MCP, operator runbook (PROD-003 code complete; operator must run terraform apply)
- [x] 19-4: Runbook RAG Seeding — COMPLETE (2026-04-02): scripts/ops/19-4-seed-runbooks.sh (60 runbook upsert with temp firewall rule + validate.py post-check), docs/ops/runbook-seeding.md (full operator guide), pgvector_connection_string placeholder in terraform.tfvars (BUG-002 / F-02 code complete; operator must run seeding script)
- [x] 19-5: Teams Proactive Alerting — COMPLETE (2026-04-02): manifest packaging script, E2E test script, teams_channel_id tfvars placeholder (PROD-005 code complete; operator must install bot and set channel ID)

---

### Phase 20: Network & Security Agent Depth

**Goal:** Give the Network, Security, and SRE domain agents genuine diagnostic depth. Currently each has only 3 shared triage tools. After this phase each agent has a rich domain-specific investigation surface: 6 new Network tools (NSG rules, VNet topology, load balancer health, flow logs, ExpressRoute, connectivity diagnostics), 6 new Security tools (Defender alerts, secure score, RBAC assignments, Key Vault audit, Policy compliance, public endpoint scan), and 4 new SRE tools (Service Health, Advisor recommendations, Change Analysis, cross-domain correlation).
**Requirements**: PROD-003
**Depends on:** Phase 19
**Status:** ✅ Complete (2026-04-10) — 4/4 plans complete
**Plans:** 4/4 plans complete

Plans:
- [x] 20-1: Network Agent Depth — NSG rules, VNet topology, load balancer health, flow logs, ExpressRoute, connectivity diagnostics (6 tools) — COMPLETE
- [x] 20-2: Security Agent Depth — Defender alerts, secure score, RBAC assignments, Key Vault audit, Policy compliance, public endpoint scan (6 tools) — COMPLETE
- [x] 20-3: SRE Agent Depth — Service Health, Advisor recommendations, Change Analysis, cross-domain correlation (4 tools) — COMPLETE
- [x] 20-4: Integration + Verification — orchestrator routing, end-to-end tests, PROD-003 satisfied — COMPLETE

---

### Phase 21: Detection Plane Activation

**Goal:** Enable the live detection loop in production. The Fabric Eventhouse + Activator infrastructure was built in Phase 4 and is complete in Terraform — it is currently disabled via `enable_fabric_data_plane = false`. This phase activates, validates, and operationalises the existing pipeline against real Azure Monitor alerts. No simulation scripts required after this phase.
**Requirements**: PROD-004
**Depends on:** Phase 19
**Status:** Complete — All 3 plans done (2026-04-03)
**Plans:** 3 plans

Plans:
- [x] 21-1: Terraform Activation — flip enable_fabric_data_plane = true, add operator runbook comment, terraform fmt passes
- [x] 21-2: Validation & Operator Runbook — scripts/ops/21-2-activate-detection-plane.sh (Phase 0 pre-flight, Steps 1-7, PROD-004 checklist), docs/ops/detection-plane-activation.md (architecture diagram, domain classification reference, troubleshooting, rollback)
- [x] 21-3: Pipeline Health Monitoring — scripts/ops/21-3-detection-health-check.sh (7-check health monitor: Fabric capacity, workspace, Event Hub, API gateway, det- incidents, Container App), docs/ops/detection-plane-activation.md updated with Ongoing Health Monitoring section + recommended schedule

---

### Phase 22: Resource Topology Graph

**Goal:** Build and maintain a real-time property graph of all Azure resources and their relationships. This is the single most differentiating Stage 4 capability — it enables causal RCA, blast-radius estimation, and topology-aware alert suppression in later phases. The graph is stored in Cosmos DB (adjacency-list), bootstrapped via ARG bulk query, synced every 15 minutes, and enriched by the Activity Log stream. New API endpoints expose blast-radius, path, and snapshot queries. All domain agents gain topology traversal as a mandatory triage step.
**Requirements**: TOPO-001, TOPO-002, TOPO-003, TOPO-004, TOPO-005
**Depends on:** Phase 21
**Status:** ✅ Complete (2026-04-03) — 4/4 plans complete
**Plans:** 4/4 plans complete

Plans:
- [x] 22-1: Cosmos topology container — adjacency-list schema, partition key `/resource_id`, indexes — COMPLETE
- [x] 22-2: Topology service core — ARG bulk bootstrap, 15-min sync loop, Activity Log enrichment — COMPLETE
- [x] 22-3: Topology API endpoints — blast-radius, path query, snapshot — COMPLETE
- [x] 22-4: Domain agent topology integration + load test — mandatory triage step, TOPO-005 ≥10k nodes validated — COMPLETE

---

### Phase 23: Change Correlation Engine

**Goal:** Automatically correlate every incident with Azure resource changes in the preceding time window. When a DB degrades 4 minutes after a VM resize, that correlation surfaces automatically. Sources: Activity Log (ARM operations), deployment events, Kubernetes resource changes, policy compliance changes. Algorithm ranks by temporal proximity + topological distance + change type and stores top-3 ChangeCorrelation objects on IncidentSummary. Surfaces in AlertFeed badge and VMDetailPanel.
**Requirements**: INTEL-002
**Depends on:** Phase 22
**Status:** ✅ Complete (2026-04-03) — 2/2 plans complete
**Plans:** 2/2 plans complete

Plans:
- [x] 23-1: Change correlator service — temporal + topological + change-type ranking, top-3 ChangeCorrelation on IncidentSummary — COMPLETE
- [x] 23-2: Incident wiring + UI — AlertFeed badge, VMDetailPanel surface, INTEL-002 satisfied — COMPLETE

---

### Phase 24: Alert Intelligence and Noise Reduction

**Goal:** Reduce alert noise by ≥80% through topology-aware causal suppression, multi-dimensional alert correlation, and composite incident severity scoring. Causal suppression uses the Phase 22 topology graph to suppress downstream cascade alerts when an upstream root cause is identified. Multi-dimensional correlation groups alerts by temporal + topological + semantic similarity. Composite severity weights alert severity, blast radius, SLO risk, and business tier. Noise metrics surface in the Observability tab.
**Requirements**: INTEL-001
**Depends on:** Phase 22, Phase 23
**Status:** ✅ Complete (2026-04-04) — 3/3 plans complete
**Plans:** 3/3 plans complete

Plans:
- [x] 24-1: Noise reducer service — topology-aware causal suppression, multi-dimensional correlation, composite severity scoring — COMPLETE
- [x] 24-2: Incident wiring — suppression applied at ingestion, composite severity on IncidentSummary — COMPLETE
- [x] 24-3: Observability tab metrics — noise ratio, suppression count, INTEL-001 ≥80% reduction verified — COMPLETE

---

### Phase 25: Institutional Memory and SLO Tracking

**Goal:** Give the platform memory. Every resolved investigation becomes institutional knowledge surfaced for future incidents via pgvector embeddings over resolved incident summaries and investigation transcripts. New incidents automatically get top-3 historical pattern matches. A weekly Container App job identifies systemic recurring patterns. SLO tracking adds SLODefinition model, error budget computation, burn-rate alerts (>2x for 1h or >3x for 15min), and SLO-aware incident auto-escalation with SLO health cards in the Observability tab.
**Requirements**: INTEL-003, INTEL-004
**Depends on:** Phase 24
**Status:** ✅ Complete (2026-04-04) — 3/3 plans complete
**Plans:** 3/3 plans complete

Plans:
- [x] 25-1: Incident memory service — pgvector embeddings over resolved summaries + transcripts, top-3 historical pattern match — COMPLETE
- [x] 25-2: SLO tracking service — SLODefinition model, error budget computation, burn-rate alerts (>2x/1h, >3x/15min), auto-escalation — COMPLETE
- [x] 25-3: Observability tab SLO cards + weekly pattern job — INTEL-003 + INTEL-004 satisfied — COMPLETE

---

### Phase 26: Predictive Operations

**Goal:** Move from reactive alerting to proactive prevention. Azure Monitor Dynamic Thresholds handle anomaly detection; custom ARIMA-based forecasting handles capacity exhaustion projections (disk fill rate, connection pool exhaustion, memory growth) with time-to-breach estimates. Per-resource seasonal baseline profiles in Cosmos DB. Pre-incident early warning signals detect subtle trends (error rate creep, latency drift). New /api/v1/forecasts endpoints and a Forecasts section in the dashboard. TOPO-005 scale validation must pass before this phase starts.
**Requirements**: INTEL-005
**Depends on:** Phase 25
**Status:** ✅ Complete (2026-04-04) — 4/4 plans complete
**Plans:** 4/4 plans complete

Plans:
- [x] 26-1: Cosmos baselines container — per-resource seasonal baseline profiles, partition key `/resource_id` — COMPLETE
- [x] 26-2: Forecaster service — ARIMA-based capacity exhaustion projections (disk fill, connection pool, memory), time-to-breach estimates — COMPLETE
- [x] 26-3: Forecast endpoints — GET /api/v1/forecasts, pre-incident early warning signals, dynamic threshold integration — COMPLETE
- [x] 26-4: Dashboard Forecasts section — INTEL-005 satisfied, TOPO-005 scale validation passed — COMPLETE

---

### Phase 27: Closed-Loop Remediation

**Goal:** Complete the remediation loop by adding execution, verification, and rollback to the existing HITL approval gate. Full pipeline: Incident → Triage → RCA → Runbook Selection (RAG) → Proposal → Human Approval → Pre-flight Checks → Execution → Verification → Resolution OR Rollback. Pre-flight checks include blast-radius confirmation, resource state ETag, change freeze windows, and cost estimation. Verification classifies: RESOLVED / IMPROVED / DEGRADED (auto-rollback) / TIMEOUT (escalate). Write-ahead log pattern ensures audit atomicity. Immutable remediation-audit Cosmos container with compliance export endpoint.
**Requirements**: REMEDI-009, REMEDI-010, REMEDI-011, REMEDI-012, REMEDI-013
**Depends on:** Phase 26, Phase 25, Phase 22
**Status:** ✅ Complete (2026-04-04) — 3/3 plans complete
**Plans:** 3/3 plans complete

Plans:
- [x] 27-1: remediation_audit Cosmos container + Terraform — write-ahead log, immutable audit trail, partition key `/incident_id` — COMPLETE
- [x] 27-2: Remediation executor service — pre-flight checks (blast-radius, ETag, freeze window, cost), RESOLVED/IMPROVED/DEGRADED/TIMEOUT classification, auto-rollback — COMPLETE
- [x] 27-3: Execute endpoint + wiring — POST /api/v1/remediations/{id}/execute, REMEDI-009 through REMEDI-013 satisfied — COMPLETE

---

### Phase 28: Platform Intelligence

**Goal:** Synthesise everything the platform has learned into actionable platform-wide intelligence. Weekly systemic pattern analysis (k-means clustering, top-5 recurring issues, trend detection). Team and service health scoring with 30/60/90-day trends. FinOps integration: POST /api/v1/admin/business-tiers for operator-configured revenue tiers, wasted compute via Cost Management API, cost-saved-by-automation metric, FinOps tab in dashboard. Continuous learning loop captures operator approve/reject feedback. Platform Health dashboard for administrators showing detection pipeline lag, agent P50/P95, auto-remediation success rate, SLO compliance, error budget portfolio, noise ratio, and automation savings.
**Requirements**: PLATINT-001, PLATINT-002, PLATINT-003, PLATINT-004
**Depends on:** Phase 27
**Status:** COMPLETE (3/3 plans complete)
**Plans:** 3/3 plans complete

Plans:
- [x] 28-1: Cosmos DB containers — pattern_analysis (/analysis_date) + business_tiers (/tier_name), both no-TTL, outputs added (PLATINT-001, PLATINT-004) — COMPLETE
- [x] 28-2: Pattern Analyzer — ApprovalAction feedback fields, process_approval_decision feedback persistence, 5 new Pydantic models, pattern_analyzer.py (8 pure-Python functions, 7 env vars, no numpy/sklearn), 21 tests passing (PLATINT-001, PLATINT-002, PLATINT-003) — COMPLETE
- [x] 28-3: Intelligence Endpoints — GET /api/v1/intelligence/patterns, GET /api/v1/intelligence/platform-health, POST/GET /api/v1/admin/business-tiers, default tier seeding, pattern analysis background loop, feedback passthrough (approve/reject), 12 tests passing (PLATINT-001, PLATINT-002, PLATINT-003, PLATINT-004) — COMPLETE

---

### Phase 29: Foundry Platform Migration

**Goal:** Migrate all 8 domain agents from the legacy `azure-ai-projects` client pattern to the Microsoft Agent Framework (`agent-framework 1.0.0rc5`). Update the Orchestrator with connected-agent handoffs. Wire OTel auto-instrumentation to Application Insights via `AIProjectInstrumentor`.
**Depends on:** Phase 28
**Status:** ✅ Complete (2026-04-11) — 1/1 plan complete
**Plans:** 1/1 plans complete

Plans:
- [x] 29-1: Foundry SDK migration — all 8 domain agents on `ChatAgent` + `@ai_function`, Responses API (`azure-ai-projects` 2.0.x), shared `telemetry.py` with `AIProjectInstrumentor`, orchestrator A2A topology registration, Terraform A2A connections, 7 smoke tests passing — COMPLETE

---

### Phase 30: SOP Engine

**Goal:** Build the SOP (Standard Operating Procedure) engine. PostgreSQL-backed SOP storage with pgvector semantic search for incident-specific SOP retrieval. Multi-channel notification dispatch. New `/api/v1/sops` endpoints. SOP upload script with SHA-256 idempotency.
**Depends on:** Phase 29
**Status:** ✅ Complete (2026-04-11) — 1/1 plan complete
**Plans:** 1/1 plans complete

Plans:
- [x] 30-1: SOP engine — `services/api-gateway/sop/` package, PostgreSQL migration `003_create_sops_table.py`, pgvector semantic search, multi-channel notify (`sop_notify.py`), upload script, shared `sop_loader.py` + `sop_store.py`, Teams SOP cards, 30+ tests passing — COMPLETE

---

### Phase 31: SOP Library

**Goal:** Populate the SOP library with production-ready runbooks covering all domain incident types. Each SOP maps to domain agent tool sequences. Lint tool and library coverage validation.
**Depends on:** Phase 30
**Status:** ✅ Complete (2026-04-11) — 1/1 plan complete
**Plans:** 1/1 plans complete

Plans:
- [x] 31-1: SOP library — 34 production SOPs across compute (7), Arc (4), AKS (4), VMSS (3), patch (4), EOL (3), network (3), security (3), SRE (3), schema template; `scripts/lint_sops.py`, library coverage tests — COMPLETE

---

### Phase 32: VM Domain Depth

**Goal:** Deepen VM domain agent capabilities with 19 new compute/VMSS/AKS/Arc tools. Fix stubs in Patch and EOL agents with real SDK calls.
**Depends on:** Phase 31
**Status:** ✅ Complete (2026-04-11) — 1/1 plan complete
**Plans:** 1/1 plans complete

Plans:
- [x] 32-1: VM domain depth — 5 stub fixes (Patch + EOL real SDK calls), 7 Azure VM tools (extensions, boot-diag, SKU, disk, `propose_vm_restart/deallocate/resize`), 4 VMSS tools (instances, autoscale, rolling-upgrade, `propose_vmss_scale`), 4 AKS tools (cluster-health, node-pools, upgrade-profile, `propose_aks_node_pool_scale`), 4 Arc tools (extension-health, guest-config, connectivity, `propose_arc_assessment`), smoke tests — COMPLETE

---

### Phase 33: Foundry Evaluation + Quality Gates

**Goal:** Instrument every agent with `azure-ai-evaluation` agentic evaluators. Build 4 custom AIOps evaluators. Create a CI eval pipeline that gates on quality scores. GitHub Actions workflow runs weekly + on PR to main.
**Depends on:** Phase 29, Phase 30
**Status:** ✅ Complete (2026-04-11) — 1/1 plan complete
**Plans:** 1/1 plans complete

Plans:
- [x] 33-1: Evaluation harness — 4 custom evaluators (`SopAdherenceEvaluator`, `TriageCompletenessEvaluator`, `RemediationSafetyEvaluator`, `DiagnosisGroundingEvaluator`), `agent_evaluators.py` (standard SDK wrappers + safe score extraction), `eval_pipeline.py` (4 quality gates: TaskAdherence ≥ 4.0, TriageCompleteness ≥ 0.95, RemediationSafety ≥ 1.0, SopAdherence ≥ 3.5), `tests/eval/agent_traces_sample.jsonl` (3 representative traces), `.github/workflows/agent-eval.yml` (weekly Monday 06:00 UTC + PR to main), 25/25 tests passing — COMPLETE

---

### Phase 34: Activate Phase 32 VM Tools

**Goal:** Wire all 15 unregistered Phase 32 tools into `compute/agent.py` so the compute agent can actually use them. Fix AMA status hardcoded "unknown" in the fleet inventory endpoint. This is a zero-new-code phase — the tools are fully implemented in `tools.py` but the agent never sees them.
**Depends on:** Phase 32
**Status:** 🔲 Not started
**Plans:** 0/1 plans complete

---

### Phase 35: Post-Remediation Intelligence Loop

**Goal:** Close the verification feedback loop between `remediation_executor.py` and the originating Foundry agent thread. After human approval → execution → verification, the originating agent receives the outcome and re-diagnoses: "Did the CPU spike resolve? Did the disk error clear?" Adds iterative hypothesis testing, MTTR tracking per issue type, and a "Did it work?" UI prompt 5 minutes post-execution.
**Depends on:** Phase 27, Phase 34
**Status:** 🔲 Not started
**Plans:** 3/3 plans complete

---

### Phase 36: OS-Level In-Guest VM Diagnostics

**Goal:** See inside the VM, not just around it. Add Azure Run Command tool for safe in-guest script execution. Parse Azure boot diagnostics serial log for kernel panics, OOM kills, disk errors. Add VM Guest Health heartbeat/memory/CPU/disk pressure tools. Resolve AMA heartbeat status from ARM (replacing hardcoded "unknown"). Surface guest OS metrics via AMA → Log Analytics.
**Depends on:** Phase 34
**Status:** 🔲 Not started
**Plans:** 0/1 plans complete

---

### Phase 37: VM Performance Intelligence & Forecasting

**Goal:** Shift from reactive to predictive. Expose `forecaster.py` as an agent-callable `@ai_function` tool. Add `query_vm_performance_baseline` (P50/P95/P99 over 30 days) and `detect_performance_drift` (drift score + narrative vs baseline). Surface anomaly scoring in the VM detail panel. Add weekly fleet performance digest SOP.
**Depends on:** Phase 26, Phase 34
**Status:** 🔲 Not started
**Plans:** 3/3 plans complete

---

### Phase 38: VM Security & Compliance Depth

**Goal:** Make per-VM security posture a first-class diagnostic signal alongside metrics and logs. Add tools: Defender TVM CVE count, JIT access status + active sessions, effective NSG rules at NIC level, Azure Backup RPO/last-backup, Azure Site Recovery replication health. Surface VM compliance score in the VM detail panel.
**Depends on:** Phase 34
**Status:** 🔲 Not started
**Plans:** 3/3 plans complete

---

### Phase 39: VM Cost Intelligence & Rightsizing

**Goal:** Surface wasteful spend and enable operators to act on it through the existing HITL approval workflow. Add tools: Azure Advisor rightsizing recommendations with estimated monthly savings, Azure Cost Management 7-day spend per VM, HITL-gated `propose_vm_sku_downsize`. Add fleet cost dashboard showing top-10 underutilized VMs. Add cost-aware SOP for <5% CPU VMs.
**Depends on:** Phase 34
**Status:** 🔲 Not started
**Plans:** 1/1 plans complete

---

### Phase 40: Arc Agent Completion

**Goal:** Bring Arc-connected resources to feature parity with Azure-native VMs. Replace the 3 stub tools in `agents/arc/tools.py` (`query_activity_log`, `query_log_analytics`, `query_resource_health`) with real implementations via the Arc MCP server. Add Arc-specific tools: connectivity status, extension inventory, guest configuration compliance, HITL-gated extension install. Arc VM detail panel matches Azure-native VM panel.
**Depends on:** Phase 34
**Status:** 🔲 Not started
**Plans:** 1/1 plans complete

---

### Phase 41: VMSS + AKS Web UI Tabs

**Goal:** Add dedicated VMSS and AKS tabs to the web UI dashboard, giving operators first-class visibility into Virtual Machine Scale Sets and AKS clusters. Follows the established VMTab → VMDetailPanel pattern: list view with badges → click opens a tabbed detail panel with AI chat. Tab order becomes: Alerts · Audit · Topology · Resources · VMs · VMSS · AKS · Observability · Patch.
**Design spec:** `docs/superpowers/specs/2026-04-11-vmss-aks-tabs-design.md`
**Depends on:** Phase 34 (backend VMSS/AKS agent tools), Phase 9 (Tailwind/shadcn UI foundation)
**Status:** 🔲 Not started
**Plans:** 0/2 plans complete

**Deliverables:**
- `VMSSTab.tsx` — list view: name, SKU, instance health count badge, power state, health, alerts
- `VMSSDetailPanel.tsx` — 5 tabs: Overview / Instances / Metrics / Scaling / AI Chat
- `AKSTab.tsx` — list view: cluster, K8s version badge, node pool health, system pod health, upgrade badge, alerts
- `AKSDetailPanel.tsx` — 5 tabs: Overview / Node Pools / Workloads / Metrics / AI Chat
- 8 new proxy routes (`/api/proxy/vmss/**`, `/api/proxy/aks/**`)
- `types/azure-resources.ts` — shared type definitions extracted from inline component types
- `DashboardPanel.tsx` + `AlertFeed.tsx` updates to register and route to new tabs

**Backend prerequisite note:** Proxy routes call `/api/v1/vmss/...` and `/api/v1/aks/...` endpoints that must be implemented in `services/api-gateway/`. Phase 32 agent tools exist; gateway REST endpoints are the remaining backend work. Frontend can be built first — proxy routes gracefully return empty arrays when upstream is unavailable.

**Out of scope (deferred to future phases):**
- VMSS instance-level drill-down chat
- AKS log streaming / kubectl-style output
- Arc-connected AKS clusters (Arc agent, separate tab)
- Command palette (Cmd+K) global resource search
- Resource relationship graph view
- Bulk alert actions, CSV export on all tabs, one-click patch remediation from PatchTab

---

## v2.0 Requirements

### PROD (Production Readiness)
| ID | Requirement |
|----|-------------|
| PROD-001 | Entra authentication enforced on all non-health API endpoints in production |
| PROD-002 | Azure MCP Server authenticated via managed identity; internal ingress only; no unauthenticated external access |
| PROD-003 | All 8 domain agent MCP tool groups registered in Foundry; each exercises domain tools in integration test |
| PROD-004 | Live alert detection loop operational without simulation scripts |
| PROD-005 | Teams proactive alerting delivers Adaptive Cards within 2 minutes of incident creation |

### TOPO (Topology)
| ID | Requirement |
|----|-------------|
| TOPO-001 | Resource property graph maintains all Azure resource types and their relationships |
| TOPO-002 | Blast-radius query returns results within 2 seconds |
| TOPO-003 | Topology graph freshness lag <15 minutes |
| TOPO-004 | Topology traversal used by domain agents as a mandatory triage step |
| TOPO-005 | Blast-radius query latency validated at ≥10,000 nodes before Phase 26 proceeds |

### INTEL (Intelligence)
| ID | Requirement |
|----|-------------|
| INTEL-001 | Alert noise reduction ≥80% on correlated alert storm simulations |
| INTEL-002 | Change correlation surfaces correct cause within 30 seconds of incident creation |
| INTEL-003 | Historical incident match surfaces in ≥33% of new incidents |
| INTEL-004 | SLO breach prediction alerts fire before threshold is crossed |
| INTEL-005 | Capacity exhaustion forecasts predict metric breaches ≥30 minutes in advance with ≥70% accuracy |

### REMEDI v2 (Enhanced Remediation)
| ID | Requirement |
|----|-------------|
| REMEDI-009 | Closed-loop verification step fires within 10 min after execution; classified RESOLVED / IMPROVED / DEGRADED / TIMEOUT |
| REMEDI-010 | Pre-flight blast-radius check required; aborts if new failures detected post-approval |
| REMEDI-011 | Write-ahead log: audit record written status:pending before ARM call; pending records >10 min trigger operator alert |
| REMEDI-012 | Auto-rollback triggered when verification returns DEGRADED |
| REMEDI-013 | Immutable audit trail for every automated action; exportable for compliance |

### PLATINT (Platform Intelligence)
| ID | Requirement |
|----|-------------|
| PLATINT-001 | Systemic pattern analysis runs on schedule; top-5 issues surfaced in UI |
| PLATINT-002 | FinOps integration tracks incident cost impact and automation savings |
| PLATINT-003 | Operator feedback (approve/reject) captured and fed to learning loop |
| PLATINT-004 | POST /api/v1/admin/business-tiers available; zero-value default config seeded on Phase 28 deployment |

### Phase 42: surface runbooks in web-ui

**Goal:** [To be planned]
**Requirements**: TBD
**Depends on:** Phase 41
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 42 to break down)

### Phase 43: Centralized Logging — Wire Enable Logging to Central LAW Across VM, VMSS, and AKS

**Goal:** The existing "Enable" logging button on VMDetailPanel (and equivalent surfaces on VMSS/AKS) routes DCR-based logs to the platform's central Log Analytics Workspace. Operators can enable or update logging on any resource to target the central LAW instead of per-resource LAWs. The Terraform wiring gap (`LOG_ANALYTICS_WORKSPACE_RESOURCE_ID` env var not injected into api-gateway) is fixed. RBAC for the api-gateway managed identity is provisioned. Enable Logging surfaces on VMSS and AKS detail panels in addition to VM.

**Requirements**:
- CENTRAL-001: Fix Terraform — inject `LOG_ANALYTICS_WORKSPACE_RESOURCE_ID` (ARM resource ID) into api-gateway container app env vars (currently only the GUID workspace ID is injected; the ARM ID is needed by the enable-logging backend)
- CENTRAL-002: Provision RBAC — api-gateway managed identity needs `Monitoring Contributor` + `Virtual Machine Contributor` on the subscription (or resource groups) to create DCRs, DCR associations, and install AMA extensions
- CENTRAL-003: Add "Enable Logging" button to VMSSDetailPanel (Overview tab) — calls new `/api/v1/vmss/{id}/diagnostic-settings` endpoint that creates DCR + AMA for scale sets
- CENTRAL-004: Add "Enable Logging" button to AKSDetailPanel (Overview tab) — calls new `/api/v1/aks/{id}/diagnostic-settings` endpoint using Azure Monitor Container Insights DCR pattern
- CENTRAL-005: Fix Arc VM block — currently the VM enable-logging endpoint returns HTTP 400 for Arc VMs; add Arc-specific DCR path using the `Microsoft.HybridCompute` extension type and Arc DCR association API
- CENTRAL-006: Align GET/POST `os_type` defaults (GET defaults `windows`, POST defaults `linux`) and forward POST body in proxy route

**Depends on:** Phase 41
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 43 to break down)

---

## World-Class Success Criteria

When all phases 19–33 complete (v2.0 milestone):

| Metric | Target |
|--------|--------|
| MTTR (P1/P2 incidents) | <30 min for 80% |
| Alert noise reduction | >90% raw alerts to actionable incidents |
| Auto-remediation rate | >40% incidents resolved via automated action with approval |
| SLO compliance (production tier) | >99.5% |
| Live detection | Zero manual simulation scripts |
| Audit completeness | Every automated action attributable, reviewable, exportable |
| Predictive prevention | ≥30% of incidents caught in forecast state before alerting |
| Institutional memory recall | Historical pattern match for >50% of repeating incident types |

## World-Class VM AIOps — Extended Criteria (Phases 34–40)

When all phases 34–40 complete:

| Metric | Target |
|--------|--------|
| Compute agent tool coverage | All 20 tools in `tools.py` registered and reachable by the agent |
| Remediation loop closure | Originating agent receives verification outcome for every executed remediation |
| In-guest diagnostics | Run Command + serial log parsing + Guest Health available for all Azure VMs |
| Forecasting agent access | Forecaster exposed as `@ai_function`; agents can query time-to-breach for any metric |
| Per-VM security posture | TVM CVE count, JIT status, effective NSG, Backup RPO surfaced in triage |
| Cost visibility | Rightsizing recommendations surfaced via HITL proposal for all underutilized VMs |
| Arc parity | Arc agent 0 stubs; tool quality matches Azure-native compute agent |

---

## v3.0 — Autonomous AIOps (Phases 44–63)

### Strategic Themes

- **Domain completeness before autonomy**: Fill every coverage gap (Storage, Databases, App Services, Messaging) so the platform can reason over the full Azure estate — not just the domains that happen to have agents. An AIOps platform with blind spots is a liability.
- **Autonomy where safety is provable**: Shift from human-in-loop to human-on-loop for low-blast-radius actions using policy-driven auto-approval, confidence gates, and continuous rollback monitoring. Never skip HITL — make it optional per action class.
- **Multi-subscription operational intelligence**: Break the single-subscription ceiling with federated inventory, cross-subscription blast-radius, and cost intelligence that spans the entire enterprise account hierarchy.
- **Enterprise hardening**: Multi-operator incident war rooms, compliance framework mapping, SLA dashboards, and PWA for on-call operators. This is what separates a demo from a production AIOps platform.

---

### Phase 44: Operations Dashboard ✅ COMPLETE

**Goal:** Give shift operators a real-time situational awareness tab — the first thing they open to understand the entire fleet at a glance before diving into any specific incident.
**Deliverables:**
- `OpsTab.tsx` — 6-KPI header row (MTTR, noise reduction, SLO compliance, auto-remediation rate, pipeline lag, savings 30d) with color-coded thresholds; active P1/P2 incident table; imminent breach bars; top recurring pattern cards; error budget portfolio stacked bars; 30s auto-refresh via parallel `Promise.allSettled()`
- 3 proxy routes: `/api/proxy/ops/platform-health`, `/api/proxy/ops/patterns`, `/api/proxy/ops/imminent-breaches`
- `DashboardPanel.tsx` updated: Ops is now the first and default tab (12 tabs total)
**Complexity:** M
**Depends on:** Phase 28 (platform intelligence endpoints), Phase 26 (forecasts)
**Status:** 🟩 Complete

---

### Phase 45: Storage Agent Depth

**Goal:** Give operators the ability to investigate, diagnose, and safely remediate Azure Storage incidents without leaving the platform — replacing the current 3-stub agent with a production-ready 12-tool surface.

**Why it matters:** Storage is the second most common source of Azure incidents (after compute) and currently has the widest tool gap on the platform. Every blob/queue/file incident today requires the operator to manually open the portal.

**Deliverables:**
- `get_storage_account_health` — access tier, replication status, failover state, last failover time, service availability from Azure Monitor
- `list_storage_containers` / `get_container_metrics` — container count, blob count estimate, storage consumed, access policy, soft-delete status
- `query_storage_metrics` — E2E latency, availability, transactions, ingress/egress, throttling errors with anomaly flag vs. baseline
- `get_storage_key_rotation_status` — last key rotation date, rotation recommendation if >90 days, Key Vault integration status
- `propose_enable_soft_delete` / `propose_enable_versioning` — HITL-gated remediation proposals following WAL pattern
- 40+ unit tests; orchestrator routing for `domain: storage` incidents

**Complexity:** M
**Depends on:** Phase 43
**Success metric:** `POST /api/v1/incidents` with `domain: storage` routes to Storage agent; agent calls ≥3 real SDK tools and produces a triage summary citing metrics, health, and change correlation within 60 seconds

---

### Phase 46: Database Agent

**Goal:** Surface health, performance, and compliance diagnostics for Azure Cosmos DB, PostgreSQL Flexible Server, and Azure SQL Database — the three database engines in the platform's own estate and those most commonly used by monitored workloads.

**Why it matters:** Database degradation is the most impactful incident type by business revenue risk, yet the platform has zero database-specific tools. A slow query or Cosmos DB 429 today produces a generic triage with no actionable diagnosis.

**Deliverables:**
- Cosmos DB tools: `get_cosmos_account_health`, `get_cosmos_throughput_metrics` (RU/s utilised vs provisioned, throttle rate, hot partition detection), `query_cosmos_diagnostic_logs`, `propose_cosmos_throughput_scale`
- PostgreSQL tools: `get_postgres_server_health`, `get_postgres_metrics` (connections, CPU, storage, IOPS, replication lag), `query_postgres_slow_queries` via Log Analytics, `propose_postgres_sku_scale`
- Azure SQL tools: `get_sql_database_health`, `get_sql_dtu_metrics`, `query_sql_query_store`, `propose_sql_elastic_pool_move`
- New `ca-database-prod` Container App; orchestrator routing; 50+ unit tests

**Complexity:** L
**Depends on:** Phase 45
**Success metric:** Database agent triages a simulated Cosmos DB 429 throttle incident: surfaces RU utilisation %, hot partition key, and proposes throughput increase via HITL in <90 seconds

---

### Phase 47: App Service + Function App Agent

**Goal:** Monitor, diagnose, and propose safe restarts/scaling for Azure App Service plans, Web Apps, and Function Apps — filling the PaaS compute coverage gap.

**Why it matters:** App Service and Functions are the most widely deployed PaaS compute surfaces in Azure, yet the platform treats any App Service incident as unroutable. Operators investigating slow API latency or Function timeouts have no in-platform diagnostics.

**Deliverables:**
- `get_app_service_health` — site status, slot state, SSL cert expiry, custom domain health
- `get_app_service_metrics` — requests/sec, response time P50/P95, HTTP 5xx rate, CPU %, memory vs plan limits
- `get_function_app_health` — invocation count, failure rate, duration P95, throttle count
- `query_app_insights_failures` — exceptions and dependencies from Application Insights
- `propose_app_service_restart` / `propose_function_app_scale_out` — HITL-gated
- New `ca-appservice-prod` Container App; orchestrator routing; 40+ unit tests

**Complexity:** M
**Depends on:** Phase 45
**Success metric:** Function App with >5% failure rate routes to App Service agent; agent surfaces failure rate, top exception type from App Insights, and proposes restart through HITL in <60 seconds

---

### Phase 48: Container Apps Operational Agent

**Goal:** Add self-monitoring capability to the Container Apps platform that runs AAP itself — and extend this to all Container Apps in monitored subscriptions.

**Why it matters:** Container Apps is the deployment target for all 9 agents. Today the platform cannot diagnose itself. An agent crashing or a revision failing to deploy produces no in-platform alert.

**Deliverables:**
- `list_container_apps` / `get_container_app_health` — revision status, replica count vs desired, active revision, ingress config
- `get_container_app_metrics` — request count, response time, replica count history, CPU/memory per replica
- `get_container_app_logs` — last 100 log lines from `ContainerAppConsoleLogs_CL`, filterable by severity
- `get_container_app_revisions` — revision history with creation time, traffic weight, active/inactive status
- `propose_container_app_scale` / `propose_container_app_revision_activate` — HITL-gated
- Self-monitoring: API gateway Container App registered as a monitored resource

**Complexity:** M
**Depends on:** Phase 47
**Success metric:** Simulated Container App revision failure (forced 0 replicas) triggers `domain: container-apps` incident; agent diagnoses replica count = 0, traces to revision config change in Activity Log, proposes scale-out

---

### Phase 49: Messaging Agent (Service Bus + Event Hub)

**Goal:** Bring Service Bus namespace health, queue/topic backlogs, dead-letter monitoring, and Event Hub consumer lag into the operational intelligence surface.

**Why it matters:** Message queue backlogs are one of the most common precursors to cascading failures — a dead-letter queue filling up silently is a ticking clock. None of these signals are currently reachable from any agent.

**Deliverables:**
- Service Bus tools: `get_servicebus_namespace_health`, `list_servicebus_queues` (depth, DLQ count), `get_servicebus_metrics`, `propose_servicebus_dlq_purge`
- Event Hub tools: `get_eventhub_namespace_health`, `list_eventhub_consumer_groups` (consumer lag per partition), `get_eventhub_metrics`
- New `ca-messaging-prod` Container App; orchestrator routing; 35+ unit tests
- Detection plane KQL `classify_domain()` extended: `microsoft.servicebus` and `microsoft.eventhub` → `messaging`

**Complexity:** M
**Depends on:** Phase 48
**Success metric:** Event Hub consumer lag >10,000 messages routes to Messaging agent; agent surfaces lag per partition, consumer group name, last event time; identifies stalled consumer in <60 seconds

---

### Phase 50: Cross-Subscription Federated View

**Goal:** Break the single-subscription ceiling — all inventory endpoints, alert feeds, topology queries, and agent investigations operate across all subscriptions in the Entra tenant simultaneously.

**Why it matters:** Real enterprise Azure estates span dozens of subscriptions. The current single-subscription filter means an operator investigating a cross-subscription networking issue sees only half the picture.

**Deliverables:**
- `subscription_registry.py` — ARG-backed subscription registry, auto-discovers all subscriptions the managed identity can Reader; refreshes every 6 hours; stored in Cosmos `subscriptions` container
- All inventory endpoints accept optional `subscriptions[]` query param; default = all
- Topology graph extended: cross-subscription edges (VNet peering, Private Endpoint, ExpressRoute)
- UI subscription selector: multi-select with "All subscriptions" default
- Agent context: all `@ai_function` tools auto-detect subscription from ARM ID

**Complexity:** L
**Depends on:** Phase 49
**Success metric:** With 3 test subscriptions registered: `GET /api/v1/vms` returns VMs from all 3; topology blast-radius for cross-subscription peered VNet shows resources from both sides

**Plans:** 4/4 plans complete

Plans:
- [x] 50-01-PLAN.md — Subscription registry (SubscriptionRegistry + Cosmos container + GET /api/v1/subscriptions + startup wiring)
- [x] 50-02-PLAN.md — Inventory endpoint federation (subscriptions param Optional, default=all from registry)
- [x] 50-03-PLAN.md — Cross-subscription topology edges (VNet peering, Private Endpoint, ExpressRoute)
- [x] 50-04-PLAN.md — UI "All subscriptions" default + agents/shared/subscription_utils.py

---

### Phase 51: Autonomous Remediation Policies

**Goal:** Let operators define rule-based auto-approval policies for known-safe, low-blast-radius remediation classes — so the platform can self-heal predictable issues without paging anyone at 3am.

**Why it matters:** 40-60% of production incidents involve the same 10 remediation actions (scale out, restart, flush cache, rotate token). Requiring human approval for an action approved 200 times creates alert fatigue without adding safety.

**Deliverables:**
- `AutoRemediationPolicy` model: `{ action_class, resource_tag_filter, max_blast_radius, max_daily_executions, require_slo_healthy, maintenance_window_exempt }`
- `POST/GET/DELETE /api/v1/admin/remediation-policies` CRUD; stored in PostgreSQL `remediation_policies`
- Policy evaluation engine in `remediation_executor.py`: if matching policy + all guards pass → auto-execute + log `auto_approved_by_policy`
- Safety guards: blast-radius check, daily execution cap, SLO health gate, resource tag exclusion (`aap-protected: true` blocks all auto-approval)
- UI: Remediation Policies panel in Settings; last 10 auto-executed actions per policy; success rate
- Automatic learning suggestion: after 5 HITL-approved identical actions with 0 rollbacks, platform suggests creating a policy

**Complexity:** L
**Depends on:** Phase 50
**Success metric:** Policy defined for `restart_container_app` on resources tagged `tier: dev`; next matching incident auto-executes without HITL; audit record shows `auto_approved_by_policy: <policy_id>`; DEGRADED verification triggers auto-rollback regardless of policy

---

### Phase 52: FinOps Intelligence Agent

**Goal:** Build a dedicated FinOps agent that reasons over Azure Cost Management data to surface wasteful spend, forecast monthly bills, and propose cost-saving actions through the existing HITL workflow.

**Why it matters:** Wasted cloud spend is the highest-ROI, lowest-risk intervention available. The current cost surface (Advisor rightsizing on VMs) is a tiny slice of total waste. A FinOps agent that explains "your top 3 cost drivers and how to address them" pays for the entire platform.

**Deliverables:**
- `get_subscription_cost_breakdown` — Cost Management API: costs by resource group, resource type, tag; 7/30/90 day views; MoM delta
- `get_resource_cost` — per-resource spend including amortized reserved instance cost
- `identify_idle_resources` — resources with <2% CPU + 0 network for 72h with monthly cost; generates HITL-gated `propose_deallocate`
- `get_reserved_instance_utilisation` — RI/savings plan utilisation rate, unused hours, estimated waste
- `get_cost_forecast` — Azure native cost forecast for current billing period vs budget; burn rate alert if >110% on-track
- New `ca-finops-prod` Container App; FinOps tab in UI with cost breakdown chart + waste list + savings proposals

**Complexity:** L
**Depends on:** Phase 50
**Success metric:** Agent surfaces top-3 cost line items, identifies ≥1 idle resource with monthly cost, generates HITL proposal citing `$X/month` saving

---

### Phase 53: Incident War Room

**Goal:** Enable multi-operator real-time collaboration on P0 incidents — shared investigation thread, live presence indicators, role-based annotation, and structured handoff when shifts change.

**Why it matters:** P0 incidents are never single-operator events. The current platform has no concept of multiple operators working the same thread simultaneously — investigation notes exist only in Teams channels not linked to the incident record.

**Deliverables:**
- War room data model: `IncidentWarRoom { incident_id, participants[], annotations[], timeline[], handoff_summary }` in Cosmos `war_rooms`
- `POST /api/v1/incidents/{id}/war-room` — create/join war room; SSE push to all participants when new annotation arrives
- Presence indicators in UI: AvatarGroup showing operators with open incident tabs (30s heartbeat)
- Annotation layer: operators pin text + code notes to any agent trace event; persisted to war room timeline
- Structured handoff: "End my shift" generates GPT-4o handoff summary covering current hypothesis, open questions, pending approvals, recommended next steps
- Teams war room thread: joining creates a dedicated Teams thread; messages sync bidirectionally

**Complexity:** L
**Depends on:** Phase 51
**Success metric:** Two operators join same incident war room; both see each other's annotations in real time (SSE push <2s); handoff summary generated in <30 seconds

---

### Phase 54: Compliance Framework Mapping

**Goal:** Map every security finding, policy compliance result, and Defender recommendation to CIS Benchmark, NIST SP 800-53, and Azure Security Benchmark (ASB) controls — giving compliance teams a continuous audit trail without manual mapping work.

**Why it matters:** Security teams spend weeks preparing audit evidence because findings from Defender, Policy, and Advisor exist in separate systems with no common taxonomy.

**Deliverables:**
- Compliance mapping library in PostgreSQL `compliance_mappings` table: `{ finding_type, defender_rule_id, cis_control_id, nist_control_id, asb_control_id, severity, remediation_sop_id }` — seeded with 150+ mappings across CIS v8, NIST 800-53 Rev 5, ASB v3
- `GET /api/v1/compliance/posture` — aggregated compliance score per framework, per subscription; 30-day trend
- `GET /api/v1/compliance/export` — structured PDF/CSV report of all control statuses for audit
- Compliance tab in UI: heat-map of controls (passing/failing/not-assessed) per framework; click-through to findings list

**Complexity:** L
**Depends on:** Phase 52
**Success metric:** Compliance posture endpoint returns scores for CIS v8, NIST 800-53, ASB for at least 50 controls; export generates valid audit report with every finding attributed to ≥1 control ID

---

### Phase 55: SLA Dashboard + External Reporting

**Goal:** Surface customer-facing SLA compliance as a first-class operational view — separate from internal SLO tracking — with exportable monthly reports suitable for stakeholder distribution.

**Deliverables:**
- `SLADefinition` model: `{ sla_id, name, target_availability_pct, covered_resources[], measurement_period, customer_name, report_recipients[] }`
- `POST/GET /api/v1/admin/sla-definitions` CRUD; `GET /api/v1/sla/compliance` — current period attainment per SLA
- SLA compliance calculation: tick-based availability from Azure Resource Health + incident-based downtime annotations
- Automated monthly SLA report generation: GPT-4o narrative + attainment table + incident log → PDF; emailed to recipients on 1st of month
- SLA Dashboard tab in UI: attainment gauge per SLA, 12-month trend sparkline, incidents-contributing-to-breach list

**Complexity:** M
**Depends on:** Phase 54
**Success metric:** SLA definition created with 99.9% target; compliance endpoint returns current period attainment; auto-report generated and emailed with correct attainment percentage ± 0.01%

---

### Phase 56: Mobile PWA for On-Call Operators

**Goal:** Give on-call operators a mobile-first experience — push notifications for P0/P1 incidents, approve/reject remediations from a phone at 3am, and see current platform health without opening a laptop.

**Why it matters:** An operator paged at 3am opens their phone, not their laptop. If the approval flow requires a laptop, the HITL gate becomes a bottleneck at the worst possible time.

**Deliverables:**
- Next.js PWA: `next-pwa` manifest, service worker with offline fallback
- Push notification service: Web Push API; `POST /api/v1/notifications/subscribe` stores device subscription in Cosmos; sends push on P0/P1 incident creation (<30s target)
- Mobile-optimised incident card: severity badge, affected resource, 1-tap "Investigate", 1-tap "Approve"/"Reject" with biometric confirm (WebAuthn)
- Mobile-first Approvals screen: pending approvals sorted by expiry countdown; approve/reject in <3 taps
- Offline mode: service worker caches last known incident list; queues approve/reject for replay on reconnect

**Complexity:** M
**Depends on:** Phase 55
**Success metric:** P0 incident triggers push to test device in <30s; approval submitted from mobile completes HITL flow; PWA installs via "Add to Home Screen" and loads offline from cache

---

### Phase 57: Capacity Planning Engine

**Goal:** Give infrastructure architects a forward-looking capacity view — subscription quota headroom, growth rate projections, and lead-time-aware procurement recommendations.

**Why it matters:** Teams hit vCPU limits or IP space exhaustion mid-deployment and face 2-4 week quota increase lead times. This phase makes capacity constraints visible 90 days in advance.

**Deliverables:**
- `get_subscription_quota_headroom` — all compute/network/storage quotas; current usage %, growth rate via linear regression, days to exhaustion
- `get_ip_address_space_headroom` — VNet CIDR utilisation, available IPs per subnet, projected exhaustion
- `get_aks_node_quota_headroom` — per-cluster node count vs max, node pool SKU quota
- Capacity forecast model: linear + seasonal growth curve; 90-day projections with confidence intervals
- `GET /api/v1/capacity/headroom` — top-10 resources approaching exhaustion (<30 days)
- Capacity tab in UI: quota headroom table with traffic-light indicators; 90-day forecast chart

**Complexity:** M
**Depends on:** Phase 52 (cost forecasting foundation)
**Success metric:** For a subscription with known quota constraints, headroom endpoint correctly identifies the constrained resource and projects exhaustion date within ±7 days

---

### Phase 58: IaC Drift Detection

**Goal:** Continuously detect when live Azure infrastructure deviates from the Terraform state it was provisioned from — surfacing drift as incidents the platform can route, reason over, and propose remediations for.

**Why it matters:** Manual portal changes, emergency hotfixes, and control-plane drift accumulate silently. The next `terraform apply` can reverse a critical production fix with no warning.

**Deliverables:**
- `TerraformStateStore`: reads Terraform state files from Azure Blob Storage; parses `terraform.tfstate` JSON into `TerraformResource` models
- `DriftDetector`: compares Terraform-declared resource properties against live ARM API state; produces `DriftFinding { resource_id, attribute_path, terraform_value, live_value, drift_severity }`
- Drift scan scheduled Container Job: runs every 4 hours; writes findings to Cosmos `drift_findings`; sends `POST /api/v1/incidents` with `domain: drift` for HIGH/CRITICAL severity
- `GET /api/v1/drift/findings` — current findings by resource, age, severity
- Drift tab in UI: findings table with terraform_value vs live_value diff view; "Propose Terraform fix" generates PR-ready `.tf` patch via GPT-4o

**Complexity:** L
**Depends on:** Phase 57
**Success metric:** Manual portal change to a monitored Container App env var detected as HIGH drift finding within 4 hours; drift incident routes through orchestrator; "Propose Terraform fix" generates valid HCL that reconciles the diff

---

### Phase 59: Security Posture Scoring Dashboard

**Goal:** Surface a unified, continuously updated security posture score across all monitored subscriptions — aggregating Defender secure score, policy compliance, and exposure management into a single operator-facing view.

**Why it matters:** Secure Score in the Azure portal is subscription-scoped and doesn't aggregate, doesn't show trends, and doesn't connect findings to remediation SOPs. Security teams export scores to spreadsheets monthly.

**Deliverables:**
- `SecurityPostureService`: aggregates Defender Secure Score, Policy compliance %, custom control scores; stored in Cosmos `security_posture` with 1h TTL
- `GET /api/v1/security/posture` — composite score + sub-scores + 30-day trend
- `GET /api/v1/security/findings` — top-25 open high/critical findings with recommendation + mapped compliance control + SOP link
- Security Posture tab in UI: composite score gauge (0-100), breakdown radar chart (Identity, Network, Data, Compute, Applications), findings list with "Remediate via agent" action
- Weekly posture digest: emailed to configured security contacts with score delta and new critical findings

**Complexity:** M
**Depends on:** Phase 54 (compliance framework)
**Success metric:** Security posture endpoint returns composite score across 3 test subscriptions; score moves when a Defender finding is resolved; weekly digest email sent with correct score delta

---

### Phase 60: GitOps Integration + Deployment Intelligence

**Goal:** Connect the platform to Azure DevOps pipelines and GitHub Actions to correlate infrastructure incidents with the deployment that caused them — surfacing deployment-to-incident causation in under 60 seconds and enabling one-click pipeline rollbacks through HITL.

**Why it matters:** The change correlation engine (Phase 23) covers ARM-level changes. Deployment-level changes — application code, Helm chart updates, Terraform applies — require a separate integration currently missing entirely.

**Deliverables:**
- Deployment event ingestion: webhook receiver at `POST /api/v1/deployments` accepting GitHub Actions `deployment` events and Azure DevOps service hook payloads; stored in Cosmos `deployments`
- `DeploymentCorrelator` enhancement: extends Phase 23 with deployment events as a higher-weighted correlation source
- `get_recent_deployments` agent tool: returns last 5 deployments to a resource/resource group with pipeline URL, commit SHA, author
- `propose_pipeline_rollback` HITL tool: posts pipeline rerun/rollback API call through HITL approval gate
- Deployment badge in incident detail panel: "Deployed 4 min before incident by @user — commit abc123" with link to diff

**Complexity:** M
**Depends on:** Phase 58
**Success metric:** GitHub Actions deployment to a Container App followed within 10 minutes by a service degradation alert; incident surfaces "Deployment 4 min before incident" correlation badge; HITL rollback proposal executes pipeline re-run

---

### Phase 61: Multi-Agent Parallel Investigation

**Goal:** Replace sequential orchestrator handoff with parallel multi-agent fan-out for complex incidents — enabling simultaneous investigation of compute, network, and security dimensions with synthesised root cause narrative.

**Why it matters:** P0 incidents rarely have a single-domain cause. Sequential handoff means the operator waits for domain A to finish before domain B starts — doubling or tripling MTTR.

**Deliverables:**
- `ConcurrentOrchestrator` pattern using Microsoft Agent Framework `concurrent` execution: dispatch up to 3 domain agents simultaneously; collect partial results with timeout (45s per domain)
- `OrchestratorIntelligence` layer: uses institutional memory (Phase 25) to pre-select optimal agent set per incident; confidence score per domain selection
- `correlate_multi_domain` synthesis tool: takes partial findings from N agents and produces a ranked hypothesis list with cross-domain evidence linking
- `event:fan_out` SSE event type: UI shows N parallel investigation streams with per-agent progress spinners; merges into unified finding when all complete
- Orchestrator routing decision explained in trace: "Dispatching to [Compute, Network] in parallel — historical match: 73% of similar incidents involved both domains"

**Complexity:** XL
**Depends on:** Phase 60
**Success metric:** Simulated incident with compute + network cause: both agents complete in parallel (total time < max(individual) + 10s); synthesis produces correlated finding citing both domains

---

### Phase 62: Runbook Automation Studio

**Goal:** Let operators build, test, and publish automation runbooks directly in the platform UI — without writing Python — using a visual step builder backed by the existing HITL approval and WAL execution engine.

**Why it matters:** The SOP library (Phase 31) provides runbooks as documentation. The remediation executor (Phase 27) executes individual tool calls. The gap is composable multi-step automation: "if CPU >90% for 10 min, try restart; if still >90%, propose scale up".

**Deliverables:**
- Runbook schema extension: add `automation_steps[]` to `Runbook` model — each step is `{ tool_name, parameters_template, condition, on_failure }` with Jinja2 template variables resolved from incident context
- `RunbookExecutor` service: executes automation steps sequentially; each step uses WAL + HITL gate if `require_approval: true`; `on_failure: rollback | continue | abort` per step
- Visual Runbook Builder in UI (Runbooks tab): drag-and-drop step editor; step library shows all available `@ai_function` tools; parameter template editor with `{{ incident.resource_id }}` interpolation; one-click dry-run mode
- `POST /api/v1/runbooks/{id}/execute` — execute runbook against an incident; returns step results via SSE
- 10 pre-built automation runbooks: VM high CPU response, disk full cleanup, certificate renewal, AKS node drain, Service Bus DLQ drain

**Complexity:** L
**Depends on:** Phase 61
**Success metric:** Automation runbook with 3 steps built in UI; executed against a test incident; all 3 steps execute in order; step 2 triggers HITL correctly; WAL record shows all 3 steps with outcomes

---

### Phase 63: AIOps Quality Flywheel

**Goal:** Make the platform continuously smarter by closing the loop between operator decisions and model behaviour — automatic eval regression testing, anomaly detector retraining from confirmed incidents, and SOP quality scoring from execution outcomes.

**Why it matters:** The evaluation harness (Phase 33) runs quality gates on static traces. Every HITL approve/reject and post-remediation outcome is a labelled training example. The platform should be measurably better at diagnosis every month.

**Deliverables:**
- `FeedbackCapture` pipeline: every `approve/reject` decision + `RESOLVED/DEGRADED` verification outcome → written to `eval_feedback` PostgreSQL table with operator decision, verification outcome, response quality score
- Eval regression suite: weekly GitHub Actions re-runs all 4 custom evaluators against latest 50 production traces from Fabric OneLake; fails CI if any score drops >0.2 from prior week's P50
- Forecaster retraining: Holt smoothing parameters auto-tuned monthly using confirmed breach incidents as ground truth; accuracy score tracked in Observability tab
- SOP effectiveness scoring: `sop_effectiveness_score` = fraction of incidents where cited SOP led to RESOLVED outcome within 1 MTTR window; low-scoring SOPs flagged for review
- Monthly AIOps Quality Report: auto-generated PDF covering eval scores, MTTR trend, forecasting MAE, SOP effectiveness

**Complexity:** L
**Depends on:** Phase 62
**Success metric:** Weekly eval workflow produces quality score report; SOP effectiveness scores computed for ≥10 SOPs; forecaster retraining runs monthly with improved MAE vs. prior month's baseline

---

### Phase 64: Enterprise Multi-Tenant Gateway

**Goal:** Make AAP a multi-tenant AIOps platform — operators from different business units each have isolated data planes, scoped agent permissions, and their own SLA/compliance reporting, all managed through a single platform control plane.

**Why it matters:** Enterprise organizations run dozens of teams with separate Azure subscriptions, separate SLA commitments, and separate compliance requirements. A single shared alert feed and audit log forces all teams together.

**Deliverables:**
- `Tenant` model: `{ tenant_id, name, subscriptions[], sla_definitions[], compliance_frameworks[], operator_group_id }` in PostgreSQL `tenants`
- Tenant-scoped middleware: all API endpoints filter Cosmos and PostgreSQL queries by `tenant_id` derived from Entra group membership
- Per-tenant agent context: orchestrator injects `tenant_id` into every agent thread; agents scope all ARG/ARM queries to `tenant.subscriptions`
- Tenant admin UI: platform administrators create tenants, assign subscriptions, configure SLA definitions
- Tenant isolation validation: automated test suite proves operator from Tenant A cannot read incidents, runbooks, or audit records from Tenant B

**Complexity:** XL
**Depends on:** Phase 63
**Success metric:** Two tenants provisioned with different subscriptions; operator from Tenant A gets 403 attempting to read Tenant B incidents; both see correct separate incident feeds

### Phase 45: Azure MCP Server v2 Upgrade and New Capabilities

**Goal:** Upgrade from Azure MCP Server v1 (`@azure/mcp`, archived `Azure/azure-mcp` repo) to v2 (`Azure.Mcp.Server 2.0.0`, `microsoft/mcp` repo). Wire two new high-value namespaces: `advisor` into the SRE agent and `containerapps` for platform self-monitoring. Update CLAUDE.md package references.
**Requirements**: Update package reference and Docker image; smoke-test existing tools; wire `advisor` tools into SRE agent; wire `containerapps` tools into Orchestrator or SRE agent for self-monitoring
**Depends on:** Phase 44
**Plans:** 3/3 plans complete

Plans:
- [x] 45-1: MCP v2 Upgrade + Tool Name Migration (All Agents) — Wave 1
- [x] 45-2: SRE Container Apps Self-Monitoring Tool — Wave 2

### Phase 66: CVE database and tracking tab and show list of CVEs that affects the selected VM shown in VM details panel. also show which of the CVEs are already patched by the installed patches and which are pending based on the pending patches. this will help to provide complete view about the patch status and also the list of CVEs that's not patched for the selected VM.

**Goal:** [To be planned]
**Requirements**: TBD
**Depends on:** Phase 65
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 66 to break down)

### Phase 67: Quota Tab

**Goal:** Add quota tab to allow one to check quota allocation of the subscription. This will be very useful for capacity planning and scalability.
**Status:** ✅ Complete (2026-04-17) — 1/1 plans complete

Plans:
- [x] 67-1: Quota Tab (backend + frontend + proxy routes)

### Phase 68: Subscription Management Tab

**Goal:** Give operators a dedicated UI tab to manage all Azure subscriptions under monitoring — view discovery status, label subscriptions, toggle monitoring per subscription, and inspect per-subscription health stats.
**Status:** ✅ Complete (2026-04-17) — 1/1 plans complete

Plans:
- [x] 68-1: Subscription Management Tab (backend + frontend + proxy routes)

### Phase 69: Simulation Tab

**Goal:** Give operators a simulation panel to trigger realistic incident scenarios, validating that agents respond correctly, routing works, and the detection-to-triage pipeline is healthy end-to-end. 10 predefined scenarios covering all domains with dry-run support and run history.
**Status:** ✅ Complete (2026-04-17) — 1/1 plans complete

Plans:
- [x] 69-1: Simulation Tab (backend + frontend + proxy routes)

### Phase 70: Agent Health Monitor + Auto-Recovery

**Goal:** Proactively monitor all 9 domain agents' health: heartbeat, response latency, error rates, model token usage. Surface a live "Agent Health" panel in the Ops tab and trigger auto-remediation (restart Container App) when an agent goes unhealthy. This closes the self-healing gap — the platform must watch itself with the same rigor it watches customer infrastructure.

**Requirements:**
- Poll `/health` endpoint on each agent Container App every 60s (background task in API gateway)
- Track consecutive failures → mark agent DEGRADED or OFFLINE after 3 failures
- Emit `incident` for OFFLINE agent (domain=platform, sev=Sev1)
- REST endpoints: `GET /api/v1/agents/health`, `GET /api/v1/agents/{name}/health`
- UI: AgentHealthPanel in Ops tab showing agent name, status badge, last heartbeat, latency p50/p95, error rate
- Auto-restart: call Azure Container Apps revision management API to restart Container App on OFFLINE (behind HITL approval for prod)
- Cosmos persistence: `agent_health` container with 24h TTL for timeseries

**Complexity:** M
**Depends on:** Phase 44 (Ops Dashboard)
**Plans:** 0 plans (run /gsd-plan-phase 70 to break down)

### Phase 71: Live Agent Trace Viewer

**Goal:** Give operators real-time visibility into what agents are "thinking" — show live tool call traces, intermediate reasoning steps, and token usage per conversation turn. Surfaces in the Chat panel as a collapsible "Agent Trace" section and in a dedicated Traces tab. Essential for trust-building and debugging agent misbehavior.

**Requirements:**
- Stream Foundry agent run events (tool_call, tool_result, message_delta) via SSE
- Chat panel: collapsible "🔍 Agent Trace" section below each assistant message showing tool calls in chronological order
- Traces tab: full trace history with search by incident_id, agent name, time range
- Tool call display: tool name, input (collapsed JSON), output (collapsed JSON), duration_ms
- Token usage per run: prompt_tokens, completion_tokens, total_tokens
- Store traces in Cosmos `agent_traces` container (7-day TTL)
- Proxy SSE stream from `/api/v1/chat/stream` through Next.js `/api/stream/`

**Complexity:** L
**Depends on:** Phase 29 (Foundry Migration), Phase 44 (Ops Dashboard)
**Plans:** 0 plans (run /gsd-plan-phase 71 to break down)

### Phase 72: Alert Correlation Timeline

**Goal:** Visualise how a cluster of related alerts arrived and were collapsed into a single incident. Show operators the timeline of raw Azure Monitor alerts, the correlation logic that fired (temporal, topological, causal), and the resulting composite incident. Replaces the "black box" impression of noise reduction with transparent reasoning.

**Requirements:**
- `GET /api/v1/incidents/{id}/alert-timeline` endpoint returning raw alert events with correlation annotations
- AlertTimeline component: horizontal timeline with alert bubbles, grouped by resource, with arrows showing correlation edges
- Correlation reason chips: "Temporal (within 2 min)", "Topological (same VNet)", "Causal (blast radius)"
- Displayed in Incident detail panel as a new "Timeline" tab
- Powered by existing `change_correlator.py` and `noise_reducer.py` data

**Complexity:** M
**Depends on:** Phase 23 (Change Correlator), Phase 24 (Noise Reducer)
**Plans:** 0 plans (run /gsd-plan-phase 72 to break down)

### Phase 73: Predictive Incident Prevention

**Goal:** Move from reactive to predictive: surface early-warning indicators BEFORE incidents occur. Extend the forecaster to detect anomaly precursors (CPU trending up 3 hours before alert threshold), correlate leading indicators across domains (disk growth → storage alert), and generate "Pre-Incident Advisories" that operators can act on before SLO breach.

**Requirements:**
- Extend `forecaster.py` with anomaly detection (z-score on 7-day rolling baseline, threshold: >2.5σ)
- New Cosmos container: `pre_incident_advisories` (partition /subscription_id, 48h TTL)
- New endpoint: `GET /api/v1/advisories` with filter by severity/domain
- Advisory card in Ops tab: "⚠️ VM my-vm-01: CPU trending to 95% in ~3h. Historical pattern: 4 of 5 similar trends led to alert."
- Link advisory to historical incident patterns from `pattern_analyzer.py`
- Advisory dismissed via PATCH /api/v1/advisories/{id}/dismiss

**Complexity:** L
**Depends on:** Phase 26 (Predictive Ops), Phase 28 (Platform Intelligence)
**Plans:** 0 plans (run /gsd-plan-phase 73 to break down)

### Phase 74: Operator Shift Handover Report

**Goal:** Auto-generate a shift handover briefing at the end of each 8-hour shift: open incidents, resolved since shift start, SLO status, top-3 patterns, pending approvals, and recommended focus areas for the next shift. Delivered via Teams message and available as a download from the UI.

**Requirements:**
- `POST /api/v1/reports/shift-handover` — generates report for a given time window (defaults to last 8h)
- Pulls data from: Cosmos incidents, approvals, SLO tracker, pattern analyzer
- Output formats: JSON (for Teams card), Markdown (for download)
- Teams proactive message: Adaptive Card with sections for each category
- UI: "Generate Handover" button in Ops tab, opens modal with rendered report + download button
- Schedule: auto-generate every 8h (00:00, 08:00, 16:00 UTC) via background task

**Complexity:** M
**Depends on:** Phase 25 (Institutional Memory), Phase 28 (Platform Intelligence), Phase 55 (SLA Dashboard)
**Plans:** 0 plans (run /gsd-plan-phase 74 to break down)

### Phase 75: Resource Tagging Compliance

**Goal:** Give operators visibility into tagging hygiene across all Azure resources. Enforce a mandatory tag schema (Environment, Owner, CostCenter, Application) and surface non-compliant resources by subscription, resource group, and resource type. Auto-generate remediation scripts.

**Requirements:**
- `GET /api/v1/tagging/compliance` — ARG-based scan of all resources, grouped by compliance status
- Configurable required tags stored in PostgreSQL `platform_settings`
- TaggingComplianceTab.tsx in the dashboard
- Non-compliance summary: total resources, compliant %, by-subscription breakdown
- "Generate Fix Script" button: downloads Azure CLI script to apply missing tags to non-compliant resources
- Agent integration: Security/SRE agents can query tagging compliance as a tool

**Complexity:** M
**Depends on:** Phase 50 (Cross-Subscription View)
**Plans:** 0 plans (run /gsd-plan-phase 75 to break down)

---

## World-Class v4.0 Success Criteria

When all phases 70–75 complete:

| Metric | Target |
|--------|--------|
| **Agent self-healing** | OFFLINE agent detected in <60s, HITL restart approval delivered via Teams in <2 min |
| **Trace transparency** | 100% of agent conversations have queryable tool-call trace |
| **Pre-incident prevention** | >30% of Sev2 incidents preceded by actionable advisory ≥2h in advance |
| **Shift handover** | Zero manual data collection for shift handover; auto-generated in <5s |
| **Tagging compliance** | Non-compliant resources identified across all subscriptions; remediation script generated in 1 click |
| **Alert timeline** | Operators can explain correlation logic for any incident within 30 seconds |

---

## World-Class v3.0 Success Criteria

When all phases 44–64 complete:

| Metric | Target |
|--------|--------|
| **Domain coverage** | All 10 Azure service domains covered by dedicated agent (Compute, Network, Storage, Database, App Service, Container Apps, Messaging, Arc, Security, FinOps) |
| **MTTR (P1/P2)** | <15 min for 80% of incidents — down from <30 min at v2.0 |
| **Alert noise reduction** | >95% raw alerts collapsed to actionable incidents |
| **Auto-remediation rate** | >60% of repeating incidents resolved by policy-approved automation without HITL |
| **Cross-subscription coverage** | All subscriptions in tenant covered; zero blind spots |
| **Forecasting accuracy** | Capacity exhaustion predicted ≥48 hours in advance with ≥80% accuracy |
| **Compliance automation** | CIS, NIST 800-53, ASB posture continuously tracked; monthly audit export generated without manual effort |
| **IaC drift** | Drift detected and incident raised within 4 hours of any out-of-band change |
| **SLA reporting** | Monthly SLA reports auto-generated and emailed; zero manual data collection |
| **Institutional memory** | Historical pattern match for >75% of repeating incident types |
| **Eval quality gates** | All 4 custom evaluators score above threshold on weekly regression; no month-over-month regression >0.1 |
| **Parallel investigation** | P0 incidents with multi-domain cause: parallel fan-out completes in <60 seconds |
| **Mobile HITL** | P0 approval submitted from mobile in <3 taps; push notification received in <30 seconds |
| **Multi-tenant isolation** | Zero cross-tenant data leakage; proven by automated isolation test suite on every deploy |
