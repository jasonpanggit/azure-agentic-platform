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
**Status:** In progress
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
**Status:** Not started
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 20 to break down)

---

### Phase 21: Detection Plane Activation

**Goal:** Enable the live detection loop in production. The Fabric Eventhouse + Activator infrastructure was built in Phase 4 and is complete in Terraform — it is currently disabled via `enable_fabric_data_plane = false`. This phase activates, validates, and operationalises the existing pipeline against real Azure Monitor alerts. No simulation scripts required after this phase.
**Requirements**: PROD-004
**Depends on:** Phase 19
**Status:** In progress — Plan 21-1 complete (1/1 Terraform plan done)
**Plans:** 1 plan

Plans:
- [x] 21-1: Terraform Activation — flip enable_fabric_data_plane = true, add operator runbook comment, terraform fmt passes

---

### Phase 22: Resource Topology Graph

**Goal:** Build and maintain a real-time property graph of all Azure resources and their relationships. This is the single most differentiating Stage 4 capability — it enables causal RCA, blast-radius estimation, and topology-aware alert suppression in later phases. The graph is stored in Cosmos DB (adjacency-list), bootstrapped via ARG bulk query, synced every 15 minutes, and enriched by the Activity Log stream. New API endpoints expose blast-radius, path, and snapshot queries. All domain agents gain topology traversal as a mandatory triage step.
**Requirements**: TOPO-001, TOPO-002, TOPO-003, TOPO-004, TOPO-005
**Depends on:** Phase 21
**Status:** Not started
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 22 to break down)

---

### Phase 23: Change Correlation Engine

**Goal:** Automatically correlate every incident with Azure resource changes in the preceding time window. When a DB degrades 4 minutes after a VM resize, that correlation surfaces automatically. Sources: Activity Log (ARM operations), deployment events, Kubernetes resource changes, policy compliance changes. Algorithm ranks by temporal proximity + topological distance + change type and stores top-3 ChangeCorrelation objects on IncidentSummary. Surfaces in AlertFeed badge and VMDetailPanel.
**Requirements**: INTEL-002
**Depends on:** Phase 22
**Status:** Not started
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 23 to break down)

---

### Phase 24: Alert Intelligence and Noise Reduction

**Goal:** Reduce alert noise by ≥80% through topology-aware causal suppression, multi-dimensional alert correlation, and composite incident severity scoring. Causal suppression uses the Phase 22 topology graph to suppress downstream cascade alerts when an upstream root cause is identified. Multi-dimensional correlation groups alerts by temporal + topological + semantic similarity. Composite severity weights alert severity, blast radius, SLO risk, and business tier. Noise metrics surface in the Observability tab.
**Requirements**: INTEL-001
**Depends on:** Phase 22, Phase 23
**Status:** Not started
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 24 to break down)

---

### Phase 25: Institutional Memory and SLO Tracking

**Goal:** Give the platform memory. Every resolved investigation becomes institutional knowledge surfaced for future incidents via pgvector embeddings over resolved incident summaries and investigation transcripts. New incidents automatically get top-3 historical pattern matches. A weekly Container App job identifies systemic recurring patterns. SLO tracking adds SLODefinition model, error budget computation, burn-rate alerts (>2x for 1h or >3x for 15min), and SLO-aware incident auto-escalation with SLO health cards in the Observability tab.
**Requirements**: INTEL-003, INTEL-004
**Depends on:** Phase 24
**Status:** Not started
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 25 to break down)

---

### Phase 26: Predictive Operations

**Goal:** Move from reactive alerting to proactive prevention. Azure Monitor Dynamic Thresholds handle anomaly detection; custom ARIMA-based forecasting handles capacity exhaustion projections (disk fill rate, connection pool exhaustion, memory growth) with time-to-breach estimates. Per-resource seasonal baseline profiles in Cosmos DB. Pre-incident early warning signals detect subtle trends (error rate creep, latency drift). New /api/v1/forecasts endpoints and a Forecasts section in the dashboard. TOPO-005 scale validation must pass before this phase starts.
**Requirements**: INTEL-005
**Depends on:** Phase 25
**Status:** Not started
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 26 to break down)

---

### Phase 27: Closed-Loop Remediation

**Goal:** Complete the remediation loop by adding execution, verification, and rollback to the existing HITL approval gate. Full pipeline: Incident → Triage → RCA → Runbook Selection (RAG) → Proposal → Human Approval → Pre-flight Checks → Execution → Verification → Resolution OR Rollback. Pre-flight checks include blast-radius confirmation, resource state ETag, change freeze windows, and cost estimation. Verification classifies: RESOLVED / IMPROVED / DEGRADED (auto-rollback) / TIMEOUT (escalate). Write-ahead log pattern ensures audit atomicity. Immutable remediation-audit Cosmos container with compliance export endpoint.
**Requirements**: REMEDI-009, REMEDI-010, REMEDI-011, REMEDI-012, REMEDI-013
**Depends on:** Phase 26, Phase 25, Phase 22
**Status:** Not started
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 27 to break down)

---

### Phase 28: Platform Intelligence

**Goal:** Synthesise everything the platform has learned into actionable platform-wide intelligence. Weekly systemic pattern analysis (k-means clustering, top-5 recurring issues, trend detection). Team and service health scoring with 30/60/90-day trends. FinOps integration: POST /api/v1/admin/business-tiers for operator-configured revenue tiers, wasted compute via Cost Management API, cost-saved-by-automation metric, FinOps tab in dashboard. Continuous learning loop captures operator approve/reject feedback. Platform Health dashboard for administrators showing detection pipeline lag, agent P50/P95, auto-remediation success rate, SLO compliance, error budget portfolio, noise ratio, and automation savings.
**Requirements**: PLATINT-001, PLATINT-002, PLATINT-003, PLATINT-004
**Depends on:** Phase 27
**Status:** Not started
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 28 to break down)

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

---

## World-Class Success Criteria

When all phases 19–28 complete:

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
