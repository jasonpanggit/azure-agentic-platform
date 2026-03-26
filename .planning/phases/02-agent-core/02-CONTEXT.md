# Phase 2: Agent Core - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Deploy the full agent graph on Foundry Hosted Agents — `HandoffOrchestrator` routing incidents to 7 domain agents (Orchestrator, Compute, Network, Storage, Security, Arc, SRE), Azure MCP Server integrated as the primary tool surface for all non-Arc domains, `POST /api/v1/incidents` incident ingestion endpoint live as a standalone FastAPI Container App, agent identities (Entra Agent IDs) and RBAC provisioned via Terraform.

**Design-first gate:** All `.spec.md` files must be authored and PR-approved before any agent implementation code is written. This is the first deliverable, not the last.

No UI, no Arc-specific capabilities (those come in Phase 3), no runbook RAG (Phase 5). Pure agent runtime, identity, and incident ingestion layer.

</domain>

<decisions>
## Implementation Decisions

### Agent Spec Format (AGENT-009)
- **D-01:** Spec files are **freeform markdown** — no YAML frontmatter, no JSON schema requirement. Each spec is a human-readable document covering: Persona, Goals, Workflow steps, Tool permissions, Safety constraints, and Example flows.
- **D-02:** Spec files live at `docs/agents/{name}-agent.spec.md` (separate docs directory, not collocated with agent code). All 7 specs live in one place for easy cross-agent review.
- **D-03:** CI lint gate: a check in the PR pipeline verifies that for every agent container image being built (any `agents/{name}/` directory with `.py` files), a corresponding `docs/agents/{name}-agent.spec.md` file exists in the repo. CI fails if a spec is missing.
- **D-04:** "Reviewed and approved" = standard GitHub PR approval by a human reviewer (branch protection rule). No separate spec-only PR flow required — spec and implementation can land in the same PR as long as the spec file exists before the implementation files.

### Repository Layout & Container Structure
- **D-05:** Agents live under `agents/` at the repo root, with a subdirectory per domain: `agents/orchestrator/`, `agents/compute/`, `agents/network/`, `agents/storage/`, `agents/security/`, `agents/arc/`, `agents/sre/`.
- **D-06:** Shared utilities (typed message envelope, OpenTelemetry setup, `DefaultAzureCredential` auth helpers, Cosmos DB session client) live in `agents/shared/`. All agent containers import from `agents/shared/`.
- **D-07:** **Shared base Docker image** strategy: `agents/Dockerfile.base` installs all common Python dependencies (`agent-framework`, `azure-ai-projects`, `azure-identity`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`). Each domain agent's `Dockerfile` starts `FROM base-image` and copies only agent-specific code. Smaller per-agent layers, faster CI rebuilds when only one agent changes.
- **D-08:** The existing reusable `docker-push` workflow from Phase 1 CI is extended to handle per-agent image builds. Each agent gets its own image tag in ACR: `acrname.azurecr.io/agents/{name}:sha`.

### API Gateway & Incident Endpoint (DETECT-004)
- **D-09:** `POST /api/v1/incidents` lives in a **standalone FastAPI service** at `services/api-gateway/`. This service is deployed as its own Container App with public HTTPS ingress (not VNet-internal) so Fabric Activator (Phase 4) and other external callers can reach it.
- **D-10:** Callers authenticate using **Entra ID token authentication** — callers (Fabric User Data Function, Azure Monitor webhooks, manual test scripts) must obtain a Bearer token from Entra and pass it in the `Authorization` header. The API gateway validates the token using `azure-identity` / MSAL. No API keys or shared secrets.
- **D-11:** The gateway creates a Foundry thread and dispatches to the Orchestrator agent via the Foundry Agent Service SDK (`azure-ai-projects`). The incident payload (`incident_id`, `severity`, `domain`, `affected_resources`, `detection_rule`, `kql_evidence`) is the typed envelope defined in DETECT-004.
- **D-12:** API gateway service is Phase 2's non-agent application code deliverable. It is small by design — incident ingestion, Foundry thread creation, basic health check (`GET /health`), and auth middleware. No business logic; agents own the reasoning.

### Agent Identity & RBAC (INFRA-005, INFRA-006)
- **D-13:** **One system-assigned managed identity per domain agent, 7 total.** Each managed identity is attached to the corresponding Container App for that agent. AUDIT-005 attribution requires each agent to have its own distinct Entra identity.
- **D-14:** **Built-in Azure RBAC roles scoped to subscription or resource group per domain.** Examples:
  - Compute Agent → `Virtual Machine Contributor` on compute subscription
  - Network Agent → `Network Contributor` on network subscription
  - Storage Agent → `Storage Blob Data Reader` on storage subscription
  - Security Agent → `Security Reader` on all subscriptions
  - SRE Agent → `Reader` + `Monitoring Reader` cross-subscription
  - Arc Agent → `Azure Arc ScVmm VM Contributor` or equivalent on Arc resource groups
  - Orchestrator → `Reader` on platform subscription only (no resource write access)
- **D-15:** RBAC assignments are provisioned by Terraform (`azurerm_role_assignment`) in INFRA-006. All assignments are code-reviewed alongside agent identity provisioning. No manual RBAC assignments in production.
- **D-16:** Phase 7 Quality & Hardening will tighten RBAC to custom role definitions with minimal ARM operation lists, once we have production telemetry showing the exact operations each agent actually calls.

### Agent 365 Governance Layer
- **D-17:** **Agent 365 integration approach: provision Entra Agent IDs correctly now; Agent 365 auto-discovers them at GA (May 1, 2026).** No extra integration code needed in Phase 2. The Entra Agent ID provisioning via `azapi` (INFRA-005) IS the integration point — Agent 365 builds on Entra and will pick up the registered identities automatically.
- **D-18:** Agent 365 governance features (registry, lifecycle policies, audit logging) are noted as a future integration in Phase 7. The Entra Agent ID object IDs output from Terraform in Phase 2 must be preserved in Terraform outputs so Phase 7 can reference them.

### Claude's Discretion
- Exact Python package structure within each `agents/{name}/` directory (module layout, entry point naming)
- Foundry Hosted Agent entry point and `azure-ai-agentserver-agentframework` adapter configuration
- OpenTelemetry span schema details beyond what MONITOR-007 specifies (attribute names, sampling rate)
- Exact Cosmos DB session record schema for AGENT-007 token budget tracking
- Per-agent prompt text and classification logic (follows from `.spec.md` content)
- FastAPI middleware stack details (request logging, error handlers, correlation ID propagation)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Agent Framework & Foundry SDK
- `CLAUDE.md` §"Core Agent Framework" — Microsoft Agent Framework `1.0.0rc5` key APIs: `ChatAgent`, `HandoffOrchestrator`, `AgentTarget`, `@ai_function`, `AzureAIAgentClient`; orchestration patterns (Sequential, Handoff, Group Chat, Concurrent, Magentic); Foundry Hosted Agent deployment pattern; `azure-ai-agentserver-agentframework` adapter
- `CLAUDE.md` §"Azure Integration Layer" — `azure-ai-projects` 2.0.1 key classes; `azure-ai-agents` companion package
- `CLAUDE.md` §"What NOT to Use (and Why)" — confirms Semantic Kernel `AzureAIAgent` is Experimental/avoid; AutoGen in maintenance mode

### Agent Architecture
- `.planning/research/ARCHITECTURE.md` §2 "Agent Graph Architecture" — Orchestrator routing pattern with Python code example, typed message envelope JSON schema (`correlation_id`, `thread_id`, `source_agent`, `target_agent`, `message_type`), full agent graph design
- `.planning/research/ARCHITECTURE.md` §13 "Agent Specification Format" — spec format derived from GBB Cluster Doctor pattern (Persona, Goals, Workflow, Tool permissions, Safety constraints, Example flows)
- `.planning/research/SUMMARY.md` §2 "Key Architectural Decisions" — GBB patterns adopted: Agent Spec Format, Wildcard Tool Access Prevention, Resource Identity Certainty protocol

### Infrastructure (Terraform)
- `CLAUDE.md` §"Infrastructure as Code (Terraform)" — provider strategy (`azurerm ~>4.65`, `azapi ~>2.9`); INFRA-005 uses `azapi` for Entra Agent ID provisioning; RBAC via `azurerm_role_assignment`
- `.planning/REQUIREMENTS.md` §INFRA — INFRA-005 and INFRA-006 define exact requirements for managed identities and RBAC assignments

### Phase 2 Requirements
- `.planning/REQUIREMENTS.md` §AGENT — AGENT-001 through AGENT-009 (excluding AGENT-005/006 which are Phase 3 Arc)
- `.planning/REQUIREMENTS.md` §DETECT — DETECT-004 (incident endpoint contract)
- `.planning/REQUIREMENTS.md` §MONITOR — MONITOR-001, MONITOR-002, MONITOR-003, MONITOR-007
- `.planning/REQUIREMENTS.md` §TRIAGE — TRIAGE-001, TRIAGE-002, TRIAGE-003, TRIAGE-004
- `.planning/REQUIREMENTS.md` §REMEDI — REMEDI-001 (no remediation without approval — agents propose only)
- `.planning/REQUIREMENTS.md` §AUDIT — AUDIT-001, AUDIT-005
- `.planning/ROADMAP.md` §"Phase 2: Agent Core" — 6 success criteria define Phase 2 acceptance tests

### MCP Tool Surface
- `CLAUDE.md` §"Azure MCP Server (GA)" — covered services table, Arc coverage gap, mounting pattern in Foundry Hosted Agent
- `CLAUDE.md` §"Custom Arc MCP Server" — Arc MCP is Phase 3, NOT Phase 2; Arc Agent in Phase 2 gets a stub/placeholder that will be wired in Phase 3

### Agent 365 (Future)
- `https://www.microsoft.com/en-us/microsoft-agent-365` — Agent 365 product page; GA May 1, 2026; builds on Entra Agent ID; Entra Agent IDs provisioned in INFRA-005 auto-discovered at GA

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets from Phase 1
- `terraform/modules/` — all 7 Terraform modules (networking, foundry, databases, compute-env, keyvault, monitoring, private-endpoints) are fully defined with variables.tf and outputs.tf. Phase 2 adds new modules for agent identities and extends existing modules.
- `.github/workflows/` — reusable Docker push workflow (`workflow_call`) from Phase 1 CI is ready for agent image builds. Per-agent images extend this without duplication.
- Key Vault provisioned in Phase 1 and ready for agent secrets; binding of agent identity references to Key Vault is a Phase 2 task.

### Established Patterns (from Phase 1)
- Terraform module pattern: per-domain modules under `terraform/modules/`, consumed by `envs/dev/`, `envs/staging/`, `envs/prod/` environment roots
- OIDC / workload identity federation for CI — same pattern for agent identity provisioning
- Tagging convention: all resources tagged `environment`, `managed-by: terraform`, `project: aap`

### Integration Points
- `services/api-gateway/` — new in Phase 2; connects incident ingestion to Foundry thread creation
- `agents/` — new in Phase 2; each agent container connects to Foundry Hosted Agent runtime, Azure MCP Server, and Cosmos DB (session budget tracking)
- `terraform/modules/agent-identities/` — new Terraform module for INFRA-005; outputs Entra Agent ID object IDs consumed by RBAC module and needed by Phase 7 Agent 365 integration
- Foundry workspace provisioned in Phase 1 (outputs: endpoint, project ID) is the connection target for `AzureAIAgentClient` in every agent container

</code_context>

<specifics>
## Specific Ideas

- **Agent 365 design note:** Provision Entra Agent IDs via `azapi` as planned; ensure Terraform outputs the Entra Agent ID object IDs for each agent. Agent 365 (GA May 1) builds on Entra and will auto-discover these identities. No extra integration code needed in Phase 2.
- **Design-first gate is non-negotiable:** All 7 `docs/agents/{name}-agent.spec.md` files must exist and be PR-approved before any agent `.py` files are committed. CI enforces this.
- **Arc Agent in Phase 2 is a stub:** The Arc Agent container should exist and be deployed, but its tools are wired to the custom Arc MCP Server (Phase 3). In Phase 2, the Arc Agent responds with a clear "Arc-specific capabilities pending Phase 3" message when invoked.

</specifics>

<deferred>
## Deferred Ideas

- **Azure API Management (APIM)** — evaluated as an alternative to the standalone FastAPI gateway. Deferred to Phase 5/6 when multiple public APIs exist (chat API, runbook API, approval API, Teams webhook receiver). At that point APIM Standard v2 (~$400/month) centralises JWT validation, rate limiting, and analytics across all APIs. Not viable in Phase 2 because D-11 requires Python SDK (`azure-ai-projects`) for Foundry thread dispatch — APIM cannot run Python, so FastAPI would still be needed behind it, making APIM purely additive cost ($150–700/month) for a single endpoint. Target Phase 5/6 architecture: `APIM Standard v2 → [api-gateway, chat-api, approval-api, runbook-api]`.
- **Agent 365 governance features** (registry dashboards, lifecycle policies, audit logging via Agent 365) — deferred to Phase 7 Quality & Hardening when the GA APIs are stable and we have production telemetry to inform the integration.
- **Custom RBAC role definitions** — built-in roles used in Phase 2; custom roles with minimal ARM operation lists deferred to Phase 7 hardening once production operation data is available.
- **In-cluster MCP Server for Arc K8s** (Helm chart deploying lightweight MCP server into Arc K8s clusters) — identified in SUMMARY.md as a Phase 3 differentiator; not Phase 2 scope.
- **Runbook RAG** (pgvector retrieval, runbook library seeding) — Phase 5 scope.

</deferred>

---

*Phase: 02-agent-core*
*Context gathered: 2026-03-26*
