# Azure Agentic Platform (AAP) — Requirements

> Version: 1.0 | Date: 2026-03-25
> Derived from: PROJECT.md (Active requirements) · FEATURES.md (table stakes) · ARCHITECTURE.md

---

## REQ-ID Format

`{CATEGORY}-{NNN}` — e.g., `INFRA-001`

---

## Categories

| Prefix | Domain |
|---|---|
| **INFRA** | Infrastructure, Terraform, networking, identity |
| **AGENT** | Agent framework, orchestration, domain agents, MCP servers |
| **DETECT** | Fabric detection plane, alerting, incident ingestion |
| **MONITOR** | Multi-subscription monitoring, resource inventory, Arc resources |
| **TRIAGE** | AI triage, RCA, runbook RAG, troubleshooting |
| **REMEDI** | Remediation proposals, HITL approval flow, audit trail |
| **UI** | Web UI (chat + dashboard), dual SSE streaming, agent trace panel |
| **TEAMS** | Teams bot, Adaptive Cards, two-way interaction |
| **AUDIT** | Audit logs, compliance, agent action history |
| **E2E** | E2E testing with Playwright against Container Apps |

---

## INFRA — Infrastructure, Terraform, Networking, Identity

| REQ-ID | Requirement | Phase |
|---|---|---|
| INFRA-001 | Terraform provisions all platform infrastructure (VNet, subnets, private endpoints, NSGs) using `azurerm ~>4.65` with remote state in Azure Storage and state locking | Phase 1 |
| INFRA-002 | Terraform provisions Azure AI Foundry workspace, project, and gpt-4o model deployment using `azapi ~>2.9` (no azurerm equivalent) | Phase 1 |
| INFRA-003 | Terraform provisions Cosmos DB Serverless account (multi-region) with `incidents` and `approvals` containers, and PostgreSQL Flexible Server with pgvector extension enabled | Phase 1 |
| INFRA-004 | Terraform provisions Azure Container Apps environment with VNet integration and Container Registry; all agent and service images pushed to ACR via GitHub Actions | Phase 1 |
| INFRA-005 | Terraform provisions one system-assigned managed identity (Entra Agent ID) per domain agent (Orchestrator, Compute, Network, Storage, Security, Arc, SRE) using `azapi` | Phase 2 |
| INFRA-006 | Terraform provisions cross-subscription RBAC role assignments scoped per domain agent (e.g., VM Contributor for Compute Agent on compute subscription only) | Phase 2 |
| INFRA-007 | Terraform provisions Fabric capacity, Eventhouse (KQL database), Activator workspace, and OneLake lakehouse using `azapi` | Phase 4 |
| INFRA-008 | Terraform enforces dev/staging/prod environment isolation via separate `tfvars` files and per-environment remote state backends; CI runs `terraform plan` on PR and `terraform apply` on merge to main | Phase 1 |

---

## AGENT — Agent Framework, Orchestration, Domain Agents, MCP Servers

| REQ-ID | Requirement | Phase |
|---|---|---|
| AGENT-001 | Orchestrator agent uses Microsoft Agent Framework `HandoffOrchestrator` to classify incoming incidents by domain and route to the correct domain `AgentTarget`; supports cross-domain re-routing when a domain agent returns `needs_cross_domain: true` | Phase 2 |
| AGENT-002 | All agent-to-agent messages use the typed JSON envelope with `correlation_id`, `thread_id`, `source_agent`, `target_agent`, and `message_type` fields; raw strings are never passed between agents | Phase 2 |
| AGENT-003 | Six domain agents are deployed as Foundry Hosted Agents on Azure Container Apps: Compute, Network, Storage, Security, Arc, and SRE; each is a self-contained Python container from a shared base image | Phase 2 |
| AGENT-004 | Azure MCP Server (`msmcp-azure` GA) is integrated as the primary tool surface for all non-Arc resource domains (ARM, Monitor, Log Analytics, Advisor, Policy, Resource Health) | Phase 2 |
| AGENT-005 | Custom Arc MCP Server is built with FastMCP (`mcp[cli]==1.26.0`) and deployed as an internal-only Container App; exposes tools for Arc Servers (`HybridComputeManagementClient`), Arc K8s (`ConnectedKubernetesClient`), and Arc Data Services (`AzureArcDataManagementClient`) | Phase 3 |
| AGENT-006 | All Arc MCP Server list tools exhaust `nextLink` pagination and return `total_count`; no tool silently returns a partial estate | Phase 3 |
| AGENT-007 | Per-session token budget is tracked in Cosmos DB; sessions are aborted at a configurable threshold (default $5); `max_iterations` is capped at ≤10 per agent session with exponential backoff on tool retries | Phase 2 |
| AGENT-008 | All agent containers authenticate to Azure APIs using `DefaultAzureCredential` resolving the system-assigned managed identity via IMDS; no service principal secrets or credentials are stored in code or environment variables | Phase 2 |

---

## DETECT — Fabric Detection Plane, Alerting, Incident Ingestion

| REQ-ID | Requirement | Phase |
|---|---|---|
| DETECT-001 | Azure Monitor Action Groups on all subscriptions forward fired alerts to Azure Event Hub (Standard tier, 10 partitions); Event Hub is the single ingest point for the detection pipeline | Phase 4 |
| DETECT-002 | Fabric Eventhouse ingests raw alerts from Event Hub via streaming connector into a `RawAlerts` table; KQL update policies enrich alerts into `EnrichedAlerts` (joined with resource inventory) and classify into `DetectionResults` using the `classify_domain()` function | Phase 4 |
| DETECT-003 | Fabric Activator triggers on new rows in `DetectionResults` where `domain != null`; routes to Power Automate flow (simple alerts) or Fabric User Data Function (complex enrichment) which posts to `POST /api/v1/incidents` on the API gateway | Phase 4 |
| DETECT-004 | The `POST /api/v1/incidents` endpoint accepts a structured incident payload (`incident_id`, `severity`, `domain`, `affected_resources`, `detection_rule`, `kql_evidence`) and creates a new Foundry thread dispatched to the Orchestrator | Phase 2 |
| DETECT-005 | Alert deduplication collapses repeated alerts for the same resource within a configurable time window (default: 5 min) into a single incident record in Cosmos DB using ETag optimistic concurrency | Phase 4 |
| DETECT-006 | Alert state transitions (New → Acknowledged → Closed) are tracked in Cosmos DB with timestamps and actor; state is bidirectionally synced back to Azure Monitor | Phase 4 |
| DETECT-007 | Azure Monitor alert processing rules are respected by the platform; suppressed alerts are not routed to agents | Phase 4 |

---

## MONITOR — Multi-Subscription Monitoring, Resource Inventory, Arc Resources

| REQ-ID | Requirement | Phase |
|---|---|---|
| MONITOR-001 | Operator can query Azure Monitor metrics (CPU, memory, disk I/O, network throughput) and logs (activity logs, resource logs) across all in-scope subscriptions from a single UI session | Phase 2 |
| MONITOR-002 | Operator can query Log Analytics workspaces across all subscriptions via ad-hoc KQL through the agent chat interface | Phase 2 |
| MONITOR-003 | System surfaces Azure Resource Health signals and Service Health events alongside resource metrics to distinguish platform-caused from configuration-caused incidents | Phase 2 |
| MONITOR-004 | Arc-enabled server connectivity status (Connected/Disconnected/Expired, last heartbeat, agent version) is inventoried and surfaced via the Arc MCP Server; prolonged disconnection triggers an alert | Phase 3 |
| MONITOR-005 | Arc-enabled server extension health (AMA, VM Insights, Policy, Change Tracking) — install status, version, last operation — is inventoried per Arc machine via the Arc MCP Server | Phase 3 |
| MONITOR-006 | Arc-enabled Kubernetes cluster health (nodes ready/not-ready, pod status rollup, Flux GitOps reconciliation status) is surfaced via the Arc MCP Server | Phase 3 |
| MONITOR-007 | OpenTelemetry spans from all agent containers are exported to Azure Application Insights (real-time traces) and Fabric OneLake (long-term audit); each span includes `agent`, `tool`, `action_id`, `resource_id`, and `duration_ms` | Phase 2 |

---

## TRIAGE — AI Triage, RCA, Runbook RAG, Troubleshooting

| REQ-ID | Requirement | Phase |
|---|---|---|
| TRIAGE-001 | Orchestrator agent classifies every incoming incident by domain (compute/network/storage/security/arc/sre) and routes to the appropriate specialist domain agent with a typed handoff message | Phase 2 |
| TRIAGE-002 | Each domain agent queries Log Analytics (via Azure MCP Server) and Azure Resource Health as part of every triage; no domain agent produces a diagnosis without consulting both signal sources | Phase 2 |
| TRIAGE-003 | Each domain agent automatically checks the Azure Activity Log and Change Tracking for changes in the prior 2 hours as the first-pass RCA step for every incident | Phase 2 |
| TRIAGE-004 | Each domain agent presents its top root-cause hypothesis with supporting evidence (log excerpts, metric values, resource health state) and a confidence score; operators can see the reasoning trail | Phase 2 |
| TRIAGE-005 | Runbook library is stored in PostgreSQL with pgvector; agents retrieve the top-3 semantically relevant runbooks via vector search (`pgvector`) and cite them (with version) in the triage response | Phase 5 |
| TRIAGE-006 | The Arc Agent performs Arc-specific triage using Arc MCP Server tools: connectivity check, extension health check, and GitOps reconciliation status before proposing any remediation | Phase 3 |
| TRIAGE-007 | SSE stream delivers both `event:token` (LLM text delta) and `event:trace` (tool calls, handoffs, approval gates) with monotonic sequence numbers; client reconnects using `Last-Event-ID` cursor after a dropped connection | Phase 5 |

---

## REMEDI — Remediation Proposals, HITL Approval Flow, Audit Trail

| REQ-ID | Requirement | Phase |
|---|---|---|
| REMEDI-001 | No remediation action is executed without an explicit human approval; every action is proposed with: description, target resource(s), estimated impact, risk level, and reversibility statement | Phase 2 |
| REMEDI-002 | Remediation proposals with `risk_level: high | critical` trigger a HITL approval gate: an Adaptive Card is posted to Teams and the Foundry thread is parked (no polling); the thread resumes only on webhook callback from the approval endpoint | Phase 5 |
| REMEDI-003 | Approval records are written to Cosmos DB with `{ id, action_id, thread_id, status, expires_at }` using ETag concurrency; proposals expire after a configurable timeout (default: 30 min) and are never executed after expiry | Phase 5 |
| REMEDI-004 | Pre-execution safety check: the agent takes a resource state snapshot at approval time and compares it against the current state before executing; the action is aborted if the resource has diverged since approval | Phase 5 |
| REMEDI-005 | Operator can approve or reject any remediation proposal from either the Web UI or Teams; approval from either surface updates the same Cosmos DB record and resumes the same Foundry thread | Phase 5 |
| REMEDI-006 | Remediation actions are rate-limited per agent per subscription (max N actions/minute); agents cannot act on resources tagged "protected"; production-subscription actions require explicit subscription scope confirmation | Phase 5 |
| REMEDI-007 | Every executed remediation action (and every rejected proposal) is recorded in Fabric OneLake with the full action log schema (`agentId`, `toolName`, `toolParameters`, `approvedBy`, `outcome`, `durationMs`) | Phase 7 |

---

## UI — Web UI, Dual SSE Streaming, Agent Trace Panel

| REQ-ID | Requirement | Phase |
|---|---|---|
| UI-001 | Web UI is a Next.js App Router application with Fluent UI 2 (`@fluentui/react-components` v9) deployed as a Container App; operator authenticates via MSAL PKCE flow (`@azure/msal-browser`) | Phase 5 |
| UI-002 | UI displays a split-pane layout: left panel shows conversational chat with streaming token output (sub-second first token); right panel shows tabbed operational views (Topology, Alerts, Resources, Audit Log) | Phase 5 |
| UI-003 | Chat panel renders `event:token` SSE chunks as character-by-character streaming into Fluent UI 2 chat bubbles annotated with agent name; agent handoff gaps show a "thinking" indicator | Phase 5 |
| UI-004 | Agent trace panel renders `event:trace` SSE events as an expandable JSON tree showing tool calls (name + args + response), agent handoffs, and approval gate markers; collapsed by default | Phase 5 |
| UI-005 | Operator can view and act on remediation proposal cards (action description, impact, expiry timer, Approve/Reject buttons) directly in the chat panel without leaving the UI | Phase 5 |
| UI-006 | Alert/incident feed shows real-time alert stream (pushed via SSE from Cosmos DB change feed) filterable by subscription, severity, domain, and status; updates without page refresh | Phase 5 |
| UI-007 | Web UI supports multi-subscription context: operator can select one or more subscriptions and the alert feed, resource views, and agent queries scope to the selection | Phase 5 |
| UI-008 | SSE route handler (`/api/stream`) sends a 20-second heartbeat event to prevent Container Apps 240s connection termination; client reconnects with `Last-Event-ID` on drop | Phase 5 |

---

## TEAMS — Teams Bot, Adaptive Cards, Two-Way Interaction

| REQ-ID | Requirement | Phase |
|---|---|---|
| TEAMS-001 | Teams bot (`@microsoft/teams.js`) is deployed as a Container App and supports two-way conversation: operator can send natural-language messages that are routed to the Orchestrator agent and responses stream back inline | Phase 6 |
| TEAMS-002 | When an alert fires, the bot posts a structured Adaptive Card (v1.5) to the configured Teams channel including resource, severity, subscription, timestamp, and an "Investigate" action button | Phase 6 |
| TEAMS-003 | Remediation approval Adaptive Cards are posted to Teams; operator can Approve or Reject directly in Teams without opening the Web UI; the card updates in-place to reflect the decision | Phase 6 |
| TEAMS-004 | Teams bot and Web UI share the same Foundry thread ID for any given incident; both surfaces show the same conversation state and the operator can switch between them without losing context | Phase 6 |
| TEAMS-005 | If an approval card is not acted on within N minutes, the bot re-posts an escalation reminder to the channel | Phase 6 |
| TEAMS-006 | After an approved remediation action executes, the bot posts an outcome card (success/failure, duration, resource state) to close the loop with the operator | Phase 6 |

---

## AUDIT — Audit Logs, Compliance, Agent Action History

| REQ-ID | Requirement | Phase |
|---|---|---|
| AUDIT-001 | Every agent tool call is recorded as an OpenTelemetry span exported to Fabric OneLake with the full action log schema (timestamp, correlationId, agentId, agentName, toolName, toolParameters, outcome, durationMs) | Phase 2 |
| AUDIT-002 | All remediation approval records (proposed, approved/rejected, executed/expired) are stored in both Cosmos DB (hot query) and Fabric OneLake (long-term retention ≥2 years) | Phase 5 |
| AUDIT-003 | Azure Activity Log is exported from all in-scope subscriptions to Log Analytics and mirrored to Fabric OneLake; retention is ≥2 years in OneLake | Phase 4 |
| AUDIT-004 | Operator can query the full agent action history for any incident from the Web UI Audit Log tab, filterable by agent, action type, resource, and time range | Phase 5 |
| AUDIT-005 | Agent action log entries are attributable to a specific Entra Agent ID object ID; no actions are logged under a generic "system" identity | Phase 2 |
| AUDIT-006 | A remediation activity report (all agent actions in a period with approval chain) can be exported from the Audit Log viewer; covers SOC 2 and internal audit requirements | Phase 7 |

---

## E2E — End-to-End Testing with Playwright

| REQ-ID | Requirement | Phase |
|---|---|---|
| E2E-001 | Playwright E2E test suite runs against deployed Container Apps (not mocks); CI gate blocks merge if any E2E test fails | Phase 7 |
| E2E-002 | E2E test verifies the full incident flow: inject synthetic alert → Eventhouse → Activator → `POST /api/v1/incidents` → Orchestrator → domain agent → SSE stream → UI renders correctly | Phase 7 |
| E2E-003 | E2E test verifies the HITL approval flow: agent proposes high-risk action → Adaptive Card posted to Teams → operator approves via webhook → Foundry thread resumes → action executes → outcome card posted | Phase 7 |
| E2E-004 | E2E test verifies cross-subscription RBAC: each domain agent can authenticate and call its target subscription's Azure API using its system-assigned managed identity | Phase 7 |
| E2E-005 | E2E test verifies SSE reconnect: simulate a dropped connection mid-stream and confirm the client reconnects using `Last-Event-ID` and receives all missed events | Phase 7 |
| E2E-006 | E2E test verifies the Arc MCP Server against a seeded Arc estate with >100 Arc servers; confirms `nextLink` pagination is exhausted and `total_count` matches the full inventory | Phase 3 |

---

## v2 Requirements (Deferred)

These requirements are explicitly out of scope for v1 and are tracked here for future planning.

| REQ-ID | Requirement | Target Version |
|---|---|---|
| V2-001 | Multi-tenant support: platform serves multiple Entra tenants with isolated agent identity and data scoping | v2 |
| V2-002 | Auto-remediation mode: operator can whitelist low-risk action classes (e.g., VM restart, container restart) for automatic execution without approval | v2 |
| V2-003 | Mobile application: native iOS/Android app with push notifications for alerts and approval actions | v2 |
| V2-004 | SLA reporting: automated MTTA/MTTR reports by subscription, resource type, and domain with trend analysis | v2 |

---

## Out of Scope

| Item | Reason |
|---|---|
| Copilot Studio / Power Platform agents | Wrong abstraction level for programmatic AIOps; not developer-first |
| AutoGen / AG2 | AutoGen in maintenance mode; AG2 has no Microsoft enterprise support |
| AKS as primary compute | Using Container Apps; AKS added only if Container Apps proves insufficient |
| Non-Azure cloud resources | AWS/GCP out of scope; Arc bridges hybrid/on-prem |
| Fabric IQ as primary agent framework | Preview; used only as detection/semantic plane |
| Semantic Kernel `AzureAIAgent` | Experimental path; direct `azure-ai-projects` SDK used instead |

---

## Traceability Summary

| Phase | REQ-IDs |
|---|---|
| Phase 1 — Foundation | INFRA-001, INFRA-002, INFRA-003, INFRA-004, INFRA-008 |
| Phase 2 — Agent Core | INFRA-005, INFRA-006, AGENT-001, AGENT-002, AGENT-003, AGENT-004, AGENT-007, AGENT-008, DETECT-004, MONITOR-001, MONITOR-002, MONITOR-003, MONITOR-007, TRIAGE-001, TRIAGE-002, TRIAGE-003, TRIAGE-004, REMEDI-001, AUDIT-001, AUDIT-005 |
| Phase 3 — Arc MCP Server | AGENT-005, AGENT-006, MONITOR-004, MONITOR-005, MONITOR-006, TRIAGE-006, E2E-006 |
| Phase 4 — Detection Plane | INFRA-007, DETECT-001, DETECT-002, DETECT-003, DETECT-005, DETECT-006, DETECT-007, AUDIT-003 |
| Phase 5 — Triage & Remediation | TRIAGE-005, TRIAGE-007, REMEDI-002, REMEDI-003, REMEDI-004, REMEDI-005, REMEDI-006, UI-001, UI-002, UI-003, UI-004, UI-005, UI-006, UI-007, UI-008, AUDIT-002, AUDIT-004 |
| Phase 6 — Teams Integration | TEAMS-001, TEAMS-002, TEAMS-003, TEAMS-004, TEAMS-005, TEAMS-006 |
| Phase 7 — Quality & Hardening | REMEDI-007, AUDIT-006, E2E-001, E2E-002, E2E-003, E2E-004, E2E-005 |
