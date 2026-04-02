# Azure Agentic Platform (AAP)

## Current Milestone: v1.0 Azure Agentic Platform MVP

**Goal:** Build the full AAP platform — multi-agent AIOps across Azure subscriptions with Arc support, Fabric detection, Web UI, Teams bot, and human-in-the-loop remediation.

**Target features:**
- 7-phase delivery: Foundation → Agent Core → Arc MCP Server → Detection Plane → Triage & Remediation + Web UI → Teams Integration → Quality & Hardening
- Resource Identity Certainty: 2-signal pre-execution verification before any remediation (strengthens REMEDI-004)
- GitOps Remediation Path: conditional PR-based path for Flux/ArgoCD-managed Arc K8s clusters
- Agent Spec Documents: `.spec.md` per domain agent as Phase 2 design deliverable
- Incident Dedup Protocol: open-incident check before creating new incidents (extends DETECT-005)

---

## What This Is

An enterprise-grade AI operations platform that uses a domain-specialist multi-agent architecture to perform continuous monitoring, auditing, alerting, triage, troubleshooting, and automated remediation across all Azure subscriptions and Arc-enabled resources (servers, Kubernetes, data services). The platform exposes a hybrid web UI (Tailwind CSS + shadcn/ui + Next.js) with co-equal conversational chat and live operational dashboards, and integrates with Microsoft Teams for two-way agent interaction, alert delivery, and human-in-the-loop remediation approvals.

## Core Value

Operators can understand, investigate, and resolve any Azure infrastructure issue — across all subscriptions and Arc-connected resources — through a single intelligent platform that shows its reasoning transparently and never acts without human approval.

## Requirements

### Validated

**Infrastructure as Code (Terraform)** — Validated in Phase 1: Foundation
- [x] Terraform modules for all platform infrastructure: Foundry, Container Apps, Cosmos DB, PostgreSQL, VNet, private endpoints
- [x] Environment-specific configs: dev, staging, prod (tfvars per environment)
- [x] Terraform remote state in Azure Storage with state locking
- [x] CI/CD integration: Terraform plan on PR, Terraform apply on merge to main
- [x] Azure RBAC assignments via Terraform (agent identities scoping deferred to Phase 2)
- [x] Private networking: VNet integration for Container Apps, private endpoints for all data services centralized in dedicated module

### Active

**Agentic Architecture**
- [ ] Multi-agent orchestration using Microsoft Agent Framework (Python) deployed on Azure AI Foundry as Hosted Agents
- [ ] Domain-specialist agent graph: Compute Agent, Network Agent, Storage Agent, Security Agent, Arc Agent, SRE Agent
- [ ] Orchestrator agent routes user intent to the correct domain specialist(s)
- [ ] Each agent communicates via structured messages; all input/output JSON is captured and streamed to UI
- [ ] Human-in-the-loop always: agent proposes actions, user approves in UI or Teams before execution
- [ ] Agents have Entra Agent ID (first-class service principal) with scoped RBAC per domain
- [ ] Runbook library stored in PostgreSQL + vector search; agents retrieve relevant runbooks via RAG

**Azure Integration**
- [ ] Azure MCP Server (GA) as primary tool surface for ARM, Monitor, Log Analytics, Advisor, Policy, Resource Health
- [x] Custom Arc MCP Server bridging the Azure MCP Server gap for Arc-enabled servers, Kubernetes, and data services — Validated in Phase 3: Arc MCP Server
- [ ] Single Entra tenant, multi-subscription: agents authenticate via managed identity with cross-subscription RBAC
- [ ] Integration with Azure Monitor Alerts as the native incident detection trigger
- [ ] Arc-enabled resources (servers, K8s, SQL, data services) fully inventoried and managed

**Fabric Detection Plane**
- [ ] Microsoft Fabric Eventhouse ingests Azure Monitor telemetry streams for real-time issue detection
- [ ] Fabric Activator fires triggers to the agent platform's REST API when detection rules are met
- [ ] Fabric IQ Operations Agent provides semantic inventory and business-context layer
- [ ] OneLake as the central store for audit logs, alert history, and resource inventory snapshots
- [ ] Fabric Real-Time Intelligence pipeline: Event Hub → Eventhouse → Activator → Agent Platform

**Web UI (Tailwind CSS + shadcn/ui + Next.js)** — Validated in Phase 9: Web UI Revamp
- [x] Hybrid split-pane: left = conversational agent chat, right = live resource topology/dashboard — Validated in Phase 9
- [x] Full token streaming for conversational responses (sub-second first token) — SSE logic preserved in Phase 9
- [x] Parallel structured event stream for agent trace: shows every agent-to-agent message, tool call, and response in JSON — Validated in Phase 9
- [x] Agent communication visualizer: expandable JSON tree showing input/output between agents — Validated in Phase 9
- [x] Multi-subscription resource topology map with health status overlays — Validated in Phase 9
- [x] Alert/incident feed with triage status and assigned agent — Validated in Phase 9
- [x] Remediation proposal cards: proposed action + estimated impact + approve/reject buttons — Validated in Phase 9
- [x] Audit log viewer with full agent decision trail — Validated in Phase 9
- [x] Fluent UI / Griffel fully replaced with Tailwind CSS v4 + shadcn/ui — Validated in Phase 9

**Teams Integration** — Validated in Phase 6: Teams Integration
- [x] Full two-way Teams bot: users can chat with agents, run investigations, approve/reject remediation
- [x] Alert notifications posted to Teams channels with structured Adaptive Cards (buildAlertCard, buildApprovalCard, buildOutcomeCard, buildReminderCard)
- [x] Remediation approval flow via Teams Adaptive Cards using Action.Execute (in-place card update on approve/reject)
- [x] Teams as a co-equal interface alongside the web UI — cross-surface thread sharing via Foundry thread_id
- [x] Escalation scheduler: reminders for unacted approvals after configurable threshold (default 15 min)

**Data Platform (Polyglot Persistence)**
- [ ] Microsoft Foundry Agent Service manages conversation threads and agent state (managed, hosted)
- [ ] Azure Cosmos DB: hot-path conversation metadata, real-time alert state, agent session context
- [ ] Azure PostgreSQL Flexible Server: runbook library, RBAC config, subscription/resource config, platform settings
- [ ] Microsoft Fabric (Eventhouse + OneLake): telemetry, alert history, audit logs, resource inventory
- [ ] pgvector on PostgreSQL for runbook RAG (semantic search over runbook knowledge base)

**Compute / Deployment**
- [ ] Foundry Hosted Agents (Container Apps-backed) for the AI agent layer
- [ ] Azure Container Apps for custom services: Next.js frontend, API gateway, custom MCP servers
- [ ] Private networking: VNet integration for Container Apps, private endpoints for data services
- [ ] CI/CD via GitHub Actions + Azure Container Registry

**Observability**
- [ ] OpenTelemetry instrumentation across all agents and services
- [ ] Azure Application Insights for agent tracing (per-agent span, tool call latency, error rates)
- [ ] Foundry Agent Service built-in agent tracing dashboards
- [ ] Fabric Real-Time dashboard for platform health metrics

**Infrastructure as Code (Terraform)**
- [ ] Terraform modules for all platform infrastructure: Foundry, Container Apps, Cosmos DB, PostgreSQL, Fabric, VNet, private endpoints
- [ ] Terraform modules for agent identity provisioning: Entra Agent ID (service principals + managed identities per domain agent)
- [ ] Terraform modules for Azure MCP Server deployment — Terraform module for custom Arc MCP Server validated in Phase 3: Arc MCP Server
- [ ] Environment-specific configs: dev, staging, prod (tfvars per environment)
- [ ] Terraform remote state in Azure Storage with state locking
- [ ] CI/CD integration: Terraform plan on PR, Terraform apply on merge to main
- [ ] Azure RBAC assignments via Terraform (agent identities → subscription/resource group scopes)
- [ ] Fabric workspace + Eventhouse + Activator provisioning via Terraform (azurerm + azapi providers)

### Out of Scope

- **Copilot Studio / Power Platform agents** — wrong abstraction level for programmatic AIOps; not developer-first
- **AutoGen / AG2** — AutoGen in maintenance mode; AG2 has no Microsoft enterprise support
- **Multi-tenant / cross-tenant support** — single Entra tenant in scope; multi-tenant deferred to future milestone
- **Azure Kubernetes Service (AKS)** — using Container Apps instead; AKS added only if Container Apps proves insufficient for scale
- **Fabric IQ as primary agent framework** — Fabric IQ is Preview and not a developer SDK; used only as detection/semantic plane
- **Non-Azure cloud resources** — AWS/GCP resources out of scope; Arc bridges hybrid/on-prem

## Context

**The Microsoft Agentic Stack (as of March 2026):**
- **Microsoft Foundry** (GA) — the platform layer; hosts agents, manages identity, provides tool catalog
- **Foundry Agent Service** — the runtime; Prompt Agents (GA), Workflow Agents (Preview), Hosted Agents (Preview)
- **Microsoft Agent Framework** (Python, early stage but high-velocity) — graph-based orchestration with streaming, checkpointing, human-in-loop; being deployed as Hosted Agents on Foundry; positioned as successor to AutoGen
- **Semantic Kernel** (GA core; Preview orchestration) — alternative SDK path; AzureAIAgent wrapper is Experimental
- **Azure MCP Server** (GA) — 40+ Azure services exposed via MCP; notable gap: Arc resources
- **Azure SRE Agent** (GA March 2026) — purpose-built Azure AIOps agent; complements this platform rather than replaces it; can be treated as one specialist agent among many
- **Entra Agent ID** (Preview) — service principal identity for agents; enables RBAC governance per agent
- **Fabric IQ** (Preview) — Fabric's AI workload including Operations Agent and ontology layer
- **Teams channel** — first-class publishing target from Foundry Agent Service

**Key Architectural Decisions Made:**
- Domain-specialist agent graph (not operation-type agents) — cleaner cognitive load per agent, better tool scoping
- Human-in-the-loop always for remediation — compliance, safety, trust-building
- Both token streaming + structured agent trace events — satisfies latency concern AND agent transparency
- Polyglot data: each service for what it does best (Foundry threads, Cosmos hot-path, PostgreSQL operational, Fabric analytics)
- Arc gap addressed by custom Arc MCP Server (bridge to Azure Arc REST API + CLI)
- Foundry Hosted Agents + Azure Container Apps (not AKS) for compute

## Constraints

- **Framework**: Microsoft Agent Framework (Python) — may still have breaking changes as it matures
- **Arc MCP gap**: Azure MCP Server does not cover Arc; requires custom MCP server development
- **Foundry Hosted Agents**: Still Preview; no private networking yet — Container Apps fill this gap
- **SK AzureAIAgent**: Experimental — avoid this path; use direct Foundry SDK (`azure-ai-projects`)
- **Fabric IQ**: Preview — Operations Agent and IQ workloads not GA; architect with graceful degradation
- **Entra Agent ID**: Preview — governance layer may change before GA
- **Timeline**: Phased delivery; MVP (core monitoring + chat + Teams alerts) in 3-6 months
- **Single tenant**: Multi-subscription within one Entra tenant; cross-tenant support deferred

## Key Decisions

| Decision | Rationale | Outcome |
|---|---|---|
| Microsoft Agent Framework (Python) over Semantic Kernel | Aligns with Microsoft's stated direction (successor to AutoGen); graph-based orchestration fits domain-specialist pattern; native Foundry Hosted Agent deployment | — Pending |
| Domain-specialist agents (Compute/Network/Storage/Security/Arc/SRE) | Cleaner tool scoping; each agent owns its Azure resource type; easier to add new domains | — Pending |
| Human-in-the-loop always for remediation | Trust, compliance, safety; agents propose, humans approve via UI or Teams Adaptive Cards | — Pending |
| Polyglot persistence (Foundry + Cosmos + PostgreSQL + Fabric) | Each service optimized for its use case; future-proof; avoids over-fitting to one data model | — Pending |
| Custom Arc MCP Server | Azure MCP Server has no Arc support; Arc estate is full scope (servers + K8s + data); must bridge this gap | ✅ Validated Phase 3 — FastMCP server with 9 tools, Terraform Container App module, internal ingress |
| Both token streaming + agent trace events | Addresses latency concern (token stream = fast first response) + transparency (trace events = agent JSON visibility) | — Pending |
| Container Apps over AKS | Simpler ops; event-driven scaling fits agent workloads; Foundry Hosted Agents already container-backed; add AKS if scale demands it | — Pending |
| Fabric as detection plane (not primary data store) | Fabric Eventhouse + Activator is best-in-class for real-time telemetry and rule-based triggers; not suited for hot-path transactional writes | ✅ Validated Phase 4 — Eventhouse KQL pipeline, classify_domain() routing, Activator trigger, dedup + state machine |

---

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-02 — Phase 19: Production Stabilisation complete (5/5 plans, PROD-001/002/003/005 code-complete). Azure MCP Server secured (internal-only ingress, auth bypass removed), Entra auth enabled in Terraform, MCP tool group connections registered via azapi, runbook seeding script + docs created, Teams alerting operator runbooks created. All changes await operator `terraform apply` + activation steps.*
