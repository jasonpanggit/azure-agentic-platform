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

## Phase 7: Quality & Hardening

**Goal:** Platform is production-ready — full Playwright E2E suite running in CI, observability complete, runbook library seeded, security review passed, Terraform prod environment applied.

**UI:** No | **IaC:** Yes (prod environment)

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

## Dependencies Graph

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
