# Phase 2: Agent Core - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-26
**Phase:** 02-agent-core
**Areas discussed:** Agent spec format & gate, Repo layout & container structure, Incident API design, RBAC scoping & managed identity strategy (including Agent 365 research)

---

## Agent Spec Format & Gate

| Option | Description | Selected |
|--------|-------------|----------|
| Freeform markdown, existence check | One .spec.md per agent, freeform markdown, CI checks file existence only | ✓ |
| YAML frontmatter + markdown body, schema-validated | Machine-parseable frontmatter + markdown; CI validates schema and flags wildcard tools | |
| JSON schema + rendered markdown | Separate JSON schema file; CI validates against master spec schema | |

**User's choice:** Freeform markdown, existence check

---

| Option | Description | Selected |
|--------|-------------|----------|
| PR lint gate + PR approval | CI blocks agent containers without spec; PR approval = "reviewed" | ✓ |
| Two-PR flow: spec first, then implementation | Separate spec PR required before implementation PR can open | |
| Convention only, no CI enforcement | No formal CI gate; convention tracked in plan checklist | |

**User's choice:** PR lint gate + PR approval

---

| Option | Description | Selected |
|--------|-------------|----------|
| agents/{name}/agent.spec.md (collocated) | Spec lives alongside agent code | |
| docs/agents/{name}-agent.spec.md (separate docs dir) | Specs in dedicated docs directory; easier cross-agent review | ✓ |
| You decide | Claude's discretion | |

**User's choice:** docs/agents/{name}-agent.spec.md (separate docs dir)

---

## Repo Layout & Container Structure

| Option | Description | Selected |
|--------|-------------|----------|
| agents/ monorepo with agents/shared/ utilities | agents/ at repo root; per-domain subdirs; agents/shared/ for utilities | ✓ |
| Python packages under src/ with src/common/ | Python packages under src/; installable src/common/ | |
| Full microservice isolation | Separate packages/repos per agent | |

**User's choice:** agents/ monorepo with agents/shared/ utilities

---

| Option | Description | Selected |
|--------|-------------|----------|
| Shared base image + per-agent layer | agents/Dockerfile.base + FROM base in each agent Dockerfile | ✓ |
| Fully independent Dockerfiles per agent | Each agent has full independent Dockerfile | |
| Multi-stage single Dockerfile | Multiple image targets in one Dockerfile | |

**User's choice:** Shared base image + per-agent layer

---

## Incident API Design

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone FastAPI gateway Container App | services/api-gateway/ as own Container App with public HTTPS | ✓ |
| Embedded in Orchestrator container | Incident endpoint part of Orchestrator container | |
| Azure API Management (APIM) layer | APIM as gateway; requires extra Terraform provisioning | |

**User's choice:** Standalone FastAPI gateway Container App

---

| Option | Description | Selected |
|--------|-------------|----------|
| Direct caller authentication (API key or managed identity) | Shared secret or managed identity; simple | |
| Entra ID token authentication | Bearer token from Entra; callers get token via service principal | ✓ |
| VNet-internal only, no public ingress | No public access; all callers must be in VNet | |

**User's choice:** Entra ID token authentication

---

## RBAC Scoping & Managed Identity Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| One identity per domain agent, 7 total | System-assigned MI per agent; all RBAC for that agent uses one identity | ✓ |
| One identity per agent per subscription | Separate MI per agent per subscription; maximum isolation | |
| Shared platform identity | One shared MI for all agents; violates AUDIT-005 | |

**User's choice:** One identity per domain agent, 7 total

---

### Agent 365 Research (Mid-Discussion)

User asked to research "agent 365" mid-discussion. Research finding:

**Microsoft Agent 365** is a new Microsoft product (GA: May 1, 2026) described as "the control plane for agents" — providing IT teams centralized observability, governance, and security management for AI agents across an organization. It builds on Entra Agent ID, Microsoft Defender, Microsoft Purview, and M365 Admin Center.

| Option | Description | Selected |
|--------|-------------|----------|
| Note for Phase 7, continue Phase 2 plan | Entra Agent IDs auto-discovered by Agent 365 at GA; no Phase 2 changes | |
| Spike Agent 365 early access in Week 1 | Try early access APIs Week 1; integrate what's available | |
| Defer to Phase 7 | GA APIs will be stable by Phase 7; less rework risk | |
| Full Agent 365 integration in Phase 2 | First-class deliverable (scope expansion) | Initially selected |

**Notes:** After selecting "Full Agent 365 integration in Phase 2," user was presented with the reality that Agent 365 integration APIs are not publicly documented pre-GA (GA May 1). The Entra Agent IDs provisioned via INFRA-005 will auto-discover at GA. User revised to pragmatic approach.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Provision Entra Agent IDs now; Agent 365 auto-discovers at GA | INFRA-005 provisioning IS the integration; no extra code needed | ✓ |
| Spike Agent 365 early access in Week 1 | Test early access registration APIs | |
| Defer to Phase 7 | Stable GA APIs | |

**User's choice:** Provision Entra Agent IDs now; Agent 365 auto-discovers at GA

---

| Option | Description | Selected |
|--------|-------------|----------|
| Built-in roles, subscription/resource group scope | Azure built-in roles per domain; fast to provision | ✓ |
| Custom roles with minimal ARM operation list | Minimal permissions per agent; high maintenance | |
| Built-in now, tighten to custom roles in Phase 7 | Phase 7 hardening step | |

**User's choice:** Built-in roles, subscription/resource group scope

---

## Claude's Discretion

- Python package structure within agent directories
- Foundry Hosted Agent entry point and adapter configuration
- OpenTelemetry span schema details beyond MONITOR-007
- Cosmos DB session record schema for token budget (AGENT-007)
- Per-agent prompt text and routing classification logic
- FastAPI middleware stack details

## Deferred Ideas

- Agent 365 governance features (registry, lifecycle policies) → Phase 7 when GA APIs stable
- Custom RBAC role definitions with minimal ARM operations → Phase 7 hardening
- In-cluster Arc K8s MCP Server → Phase 3
- Runbook RAG → Phase 5
