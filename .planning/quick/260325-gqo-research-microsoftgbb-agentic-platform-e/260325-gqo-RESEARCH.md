# Research: microsoftgbb/agentic-platform-engineering

> **Date:** 2026-03-25
> **Source:** https://github.com/microsoftgbb/agentic-platform-engineering
> **Context:** Microsoft GBB (Global Black Belt) reference implementation for agentic platform engineering
> **Purpose:** Extract patterns, ideas, and gap analysis for the Azure Agentic Platform (AAP)

---

## 1. Executive Summary

The `microsoftgbb/agentic-platform-engineering` repo is a **workshop/demo repository** created by Microsoft's GBB team (led by @dicasati). It demonstrates how platform engineering teams can use **GitHub Copilot agents + GitHub Actions + MCP servers** to automate Kubernetes cluster operations. It is NOT a production platform or a multi-agent AIOps system like AAP. However, it contains several patterns and architectural ideas that are directly transferable to AAP's design.

**Key insight:** This repo validates our core thesis (agents that observe, reason, and act with human approval) but approaches it from a completely different angle: **developer workflow automation via GitHub** rather than **enterprise AIOps via Azure Foundry**. The two approaches are complementary, not competing.

**Repo stats:** 24 stars, Shell-based, created 2026-02-16, last updated 2026-03-25. Actively maintained for conference demos (Tech Connect Feb 2026).

---

## 2. Architecture Analysis

### 2.1 Overall Structure

The repo is organized as a three-act workshop progression:

| Act | Theme | Pattern |
|-----|-------|---------|
| **Act 1** | Knowledge doesn't scale | Encode tribal knowledge into custom Copilot agents |
| **Act 2** | Standards exist but aren't enforced | Automate enforcement via CI/CD + Copilot CLI |
| **Act 3** | Kubernetes ops don't scale linearly | Event-driven agent workflows for cluster diagnosis |

The progression follows **Crawl-Walk-Run**:
- **Crawl:** Manual prompt invocation in IDE
- **Walk:** Automated issue creation from ArgoCD failures
- **Run:** Agent-triggered automated diagnosis + PR creation

### 2.2 Event-Driven Agent Pipeline (Act 3)

The most architecturally relevant pattern for AAP:

```
ArgoCD detects failure
    |
    v  (webhook: repository_dispatch)
GitHub Actions: argocd-deployment-failure.yml
    |
    v  (creates structured GitHub Issue with context)
GitHub Issue (labeled: cluster-doctor, argocd-deployment-failure)
    |
    v  (label trigger)
GitHub Actions: copilot.trigger-cluster-doctor.yml
    |
    v  (GitHub Copilot CLI + MCP servers)
Cluster Doctor Agent
    |
    +---> Reads issue via GitHub MCP Server
    +---> Queries cluster via AKS MCP Server (port-forwarded)
    +---> Posts diagnosis as issue comment
    +---> Creates PR with remediation
    |
    v
Human reviews PR, approves, merges
```

### 2.3 Agent Definition Pattern

The "Cluster Doctor" agent is defined as a single markdown file (`.github/agents/cluster-doctor.agent.md`) with these sections:

1. **Persona** -- Role: Senior Kubernetes Administrator, SRE, GitOps engineer
2. **Goals** -- Assess, verify, triage, remediate
3. **How the Agent Works** -- 5-phase workflow: Collect, Verify, Diagnose, Triage, Remediate
4. **Required Inputs** -- Credentials, integrations, access levels
5. **Permissions & Safety** -- Cluster Identity Certainty requirement, destructive change guardrails
6. **Behavior & Interaction Patterns** -- Autonomous mode, no interactive prompting
7. **Example Prompts & Diagnostic Flows**
8. **GitOps PR Template** -- Branch naming, change summary, test plan, rollback

### 2.4 MCP Server Configuration

Two MCP servers configured in `.copilot/mcp-config.json`:

```json
{
  "mcpServers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "tools": ["*"]
    },
    "aks-mcp": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "tools": ["*"]
    }
  }
}
```

- **GitHub MCP Server** -- Used for issue reading/writing, PR creation, repo operations
- **AKS MCP Server** -- Port-forwarded from the cluster for deep Kubernetes telemetry

---

## 3. Transferable Patterns for AAP

### 3.1 Cluster Identity Certainty (CRITICAL -- adopt this)

The Cluster Doctor agent has a mandatory safety check before any write operation:

> "Before performing any write or remediation action, the agent must confirm that the target cluster and namespace match the cluster referenced in the incident using at least two independent signals (API server URL vs recorded URL, TLS certificate fingerprint, cluster UID/ID)."

**AAP application:** Generalize this to a **Resource Identity Certainty** pattern. Before any remediation action on any Azure resource, the agent must verify the resource still matches the incident context using at least two signals:
1. Resource ID matches the incident record
2. Resource state (tags, configuration) matches the snapshot taken at triage time
3. Subscription/resource group haven't changed

This directly addresses our PITFALLS.md "Approve-Then-Stale Problem" and makes it a formal protocol rather than just a concern.

### 3.2 Agent-as-Markdown Definition

The entire Cluster Doctor agent is a single `.md` file with structured sections. This is GitHub Copilot's custom agent format. While we use Microsoft Agent Framework (Python) for runtime agents, the pattern of **agent specification as a human-readable markdown document** is valuable for:

- **Agent design reviews** -- stakeholders can read and comment on agent behavior before code is written
- **Version-controlled agent specs** -- Git history shows how agent behavior evolved
- **Onboarding docs** -- new team members understand agent scope from the spec, not the code

**AAP action:** Create a `docs/agents/` directory with markdown specifications for each domain agent (Compute, Network, Storage, Security, Arc, SRE, Orchestrator). These specs should mirror the Cluster Doctor format: Persona, Goals, Workflow, Permissions & Safety, Example Flows.

### 3.3 Event-Driven Incident-to-Agent Pipeline

The ArgoCD --> GitHub Issue --> Cluster Doctor pipeline is an excellent pattern for our Fabric Activator --> Agent Platform pipeline. Key transferable elements:

| GBB Pattern | AAP Equivalent |
|-------------|----------------|
| ArgoCD webhook fires on sync failure | Fabric Activator fires on KQL detection rule match |
| GitHub Actions creates structured issue | API Gateway creates incident record in Cosmos DB |
| Issue contains: error message, resource states, kubectl commands | Incident contains: alert payload, affected resources, KQL evidence |
| Issue deduplication (check for existing open issues) | Alert deduplication/correlation in our incident pipeline |
| Label-based agent triggering (`cluster-doctor` label) | Domain-based agent routing (orchestrator classifies domain) |
| Agent posts diagnosis as issue comment | Agent streams diagnosis via SSE token stream |
| Agent creates PR with fix | Agent creates remediation proposal card |

**AAP action:** The deduplication pattern is particularly well-implemented in their `argocd-deployment-failure.yml` workflow. We should replicate this logic in our incident creation endpoint -- check for existing open incidents for the same resource before creating a new one.

### 3.4 Chained Prompt Workflow (Diagnostic --> Analysis --> Remediation)

Act 2 demonstrates a three-prompt chain:

```
aks-check-pods (What's wrong?) --> aks-check-nodes (System-level?) --> aks-remediation (How to fix?)
```

Each prompt is:
- **Focused** -- one responsibility per prompt
- **Safe** -- analysis only, no autonomous changes (until remediation)
- **Actionable** -- provides specific next steps

**AAP application:** Our domain agents should follow this same phased approach internally:

1. **Diagnostic phase** -- Read-only queries (Log Analytics, Resource Health, metrics)
2. **Analysis phase** -- Correlate findings, generate hypotheses, rank by confidence
3. **Remediation phase** -- Propose actions with risk levels, require approval

This maps cleanly to our existing architecture but the explicit phase separation is a useful design constraint to enforce. Each phase should produce a distinct trace event type so the UI can show progress through the phases.

### 3.5 Two-Token Authentication Pattern

The GBB repo uses two separate tokens in CI/CD:
- `GITHUB_TOKEN` (workflow token) for repository operations via MCP
- `COPILOT_CLI_TOKEN` (PAT) for Copilot API authentication

**AAP parallel:** Our agents will need similar credential separation:
- **Agent managed identity** for Azure resource operations (via DefaultAzureCredential)
- **Foundry project credentials** for Foundry Agent Service API calls
- **MCP server credentials** for MCP tool invocations

Each credential scope should be explicitly documented and never conflated.

### 3.6 ArgoCD/GitOps Integration Pattern

The ArgoCD Notifications --> repository_dispatch --> GitHub Actions pattern is relevant for AAP's Arc Kubernetes monitoring:

- Arc-enabled K8s clusters using Flux/GitOps can trigger similar event flows
- When Flux reconciliation fails on an Arc cluster, this could feed into our detection pipeline
- The ArgoCD notification ConfigMap pattern (webhook service + trigger + template) maps to Azure Event Grid + webhook subscriptions

**AAP action:** Add Flux GitOps reconciliation failure detection as an explicit detection rule in our Fabric Eventhouse. The GBB repo's ArgoCD notification template is a good reference for what payload fields to capture.

### 3.7 AKS MCP Server as In-Cluster Tool Surface

The repo references an "AKS MCP Server" running inside the cluster (`http://localhost:8000/mcp`, port-forwarded). This is a dedicated MCP server for deep cluster telemetry -- separate from the Azure MCP Server.

**AAP relevance:** Our custom Arc MCP Server focuses on Azure ARM-level Arc resource management. We haven't planned a **cluster-internal MCP server** that provides pod-level, node-level, and workload-level Kubernetes telemetry from inside Arc-connected clusters. This is a gap.

**Consideration:** For MVP, this is out of scope (we'd need to deploy an MCP server into each Arc K8s cluster). But for Phase 2+, an in-cluster MCP server on Arc K8s clusters would significantly improve diagnostic depth. Could be deployed as a Helm chart via Flux.

---

## 4. Gap Analysis: What They Do That We Haven't Considered

### 4.1 GitOps-Native Remediation via PR

The GBB approach is **GitOps-first for remediation**: the agent creates a PR with the fix rather than executing commands against the cluster. This creates:
- An audit trail in Git history
- A human review step via PR approval
- A rollback path via `git revert`
- A test plan in the PR description

**AAP gap:** Our remediation design focuses on **direct API/CLI execution** (restart VM, scale resource, apply policy). We should add a GitOps remediation path for Arc K8s resources managed by Flux:
- For manifest issues (wrong resource limits, bad config), create a PR against the GitOps repo
- For infrastructure issues (node down, disk full), use direct remediation
- The choice between GitOps PR and direct action should be automatic based on resource type

### 4.2 Agent Specification as First-Class Artifact

The Cluster Doctor agent spec is a well-structured document that serves as both documentation and agent configuration. We have architecture docs that describe our agents but no **formal agent specification format**.

**AAP gap:** Create a standardized agent specification template that each domain agent must have:
```
docs/agents/{domain}-agent.spec.md
  - Persona & Expertise
  - Goals & Success Criteria
  - Workflow Phases (Collect, Verify, Diagnose, Triage, Remediate)
  - Tool Access (which MCP tools, which Azure APIs)
  - Permission Model (RBAC scope, read-only vs read-write)
  - Safety Constraints (Resource Identity Certainty, max blast radius)
  - Example Diagnostic Flows
  - Handoff Conditions (when to escalate to orchestrator or other agents)
```

### 4.3 Crawl-Walk-Run Deployment Strategy

The GBB repo explicitly stages capability delivery:
- **Crawl:** Manual agent invocation for ad-hoc diagnostics
- **Walk:** Automated event detection + issue creation (no agent action)
- **Run:** Full automated pipeline with agent diagnosis + remediation proposals

**AAP gap:** Our ROADMAP.md has phases but doesn't explicitly map to this maturity model per feature. We should add a maturity level to each feature:
- **L0 (Manual):** Operator invokes agent via chat for ad-hoc investigation
- **L1 (Monitored):** Alert fires, incident created, operator routes to agent manually
- **L2 (Assisted):** Alert fires, incident created, orchestrator auto-routes, human approves remediation
- **L3 (Supervised):** Full automation with human approval only for high-risk actions

### 4.4 Documentation-as-CI Pattern

Act 2 shows automated documentation generation via GitHub Actions + Copilot CLI on every commit. This is a lightweight but high-value pattern.

**AAP application:** Not directly applicable to AIOps, but useful for platform development:
- Auto-generate API docs for our REST endpoints
- Auto-update agent spec docs when agent code changes
- Auto-generate Terraform module docs via `terraform-docs` (already in FEATURES.md as a differentiator)

### 4.5 Structured Issue Templates as Incident Records

The ArgoCD failure handler creates GitHub Issues with a very structured format:
- Cluster Information (table)
- Application Status (table)
- Degraded Resources (per-resource detail)
- Troubleshooting Commands (pre-populated kubectl commands)
- Quick Links

**AAP application:** Our incident records in Cosmos DB should follow a similarly structured schema. The GBB pattern of including **pre-populated investigation commands** in the incident record is valuable -- our agents could include "suggested KQL queries" in the incident context that operators can run manually if they want to verify the agent's findings.

---

## 5. Anti-Patterns to Avoid (What NOT to Copy)

### 5.1 GitHub-Centric Architecture

The GBB repo uses GitHub Issues as the incident tracking system and GitHub Actions as the orchestration engine. This works for demos but:
- GitHub Issues are not a production incident management system
- GitHub Actions has cold start latency and run-time limits (6 hours)
- The `copilot` CLI requires a user PAT, not a service identity

**AAP decision:** Our Foundry Agent Service + Cosmos DB + Container Apps architecture is correct. Do not adopt GitHub-centric orchestration for production AIOps.

### 5.2 Port-Forwarded MCP Servers

The AKS MCP server is accessed via `kubectl port-forward` in the GitHub Actions runner. This is fragile and non-production-ready.

**AAP decision:** Our Container Apps-based MCP server deployment with internal ingress is the correct pattern. MCP servers should be always-on services, not port-forwarded sidecars.

### 5.3 Single-Agent Architecture

The GBB repo has one agent (Cluster Doctor) that does everything -- Kubernetes diagnosis, GitOps remediation, networking analysis, security posture assessment. This works for a demo but doesn't scale.

**AAP decision:** Our domain-specialist agent graph (Compute, Network, Storage, Security, Arc, SRE) is the correct architecture. Each agent should have focused expertise and scoped RBAC. The Cluster Doctor's breadth (CNI, NetworkPolicy, RBAC, cert management, service mesh, GitOps) would be split across our Network, Security, and Arc agents.

### 5.4 `--allow-all-tools` Flag

The workflows use `copilot --allow-all-tools` which grants the agent unrestricted access to all MCP tools. This is a security concern in production.

**AAP decision:** Our agents must have explicitly scoped tool access via `allowed_tools` lists in the MCP tool configuration. Never use wildcard tool access in production.

### 5.5 No Observability or Cost Tracking

The GBB repo has no telemetry, no cost tracking, no token budget management. Copilot CLI calls are fire-and-forget.

**AAP decision:** Our OpenTelemetry instrumentation, token budget tracking, and per-session cost accounting are essential for production. This is a confirmed need, not something to defer.

---

## 6. Technology Comparison

| Dimension | GBB Repo | AAP |
|-----------|----------|-----|
| **Agent Runtime** | GitHub Copilot (hosted by GitHub) | Microsoft Agent Framework (self-hosted on Foundry) |
| **Orchestration** | GitHub Actions workflows | Foundry Hosted Agents + HandoffOrchestrator |
| **MCP Servers** | GitHub MCP + AKS MCP (port-forwarded) | Azure MCP Server (GA) + Custom Arc MCP Server (Container Apps) |
| **Incident Store** | GitHub Issues | Cosmos DB + Foundry Threads |
| **Event Source** | ArgoCD webhook | Azure Monitor + Fabric Activator |
| **Remediation** | Git PR (GitOps-first) | Direct Azure API + approval workflow |
| **UI** | GitHub Issues/PRs | Fluent UI 2 + Next.js |
| **Human-in-Loop** | PR review/merge | Adaptive Cards + Web UI approval |
| **IaC** | None (manual setup) | Terraform (azurerm + azapi) |
| **Scope** | Single AKS cluster | Multi-subscription Azure + Arc estate |
| **Auth** | GitHub PAT + Azure Workload Identity | Entra Agent ID + Managed Identity per agent |
| **Observability** | None | OpenTelemetry + App Insights + Fabric OneLake |

---

## 7. Recommendations for AAP Planning Updates

### 7.1 ARCHITECTURE.md Updates

1. **Add Resource Identity Certainty protocol** to the Human-in-the-Loop section. Before any remediation execution, verify resource state matches the triage snapshot using at least two independent signals. This formalizes our existing "Approve-Then-Stale" pitfall into a mandatory protocol.

2. **Add agent specification format** as a deliverable in Phase 2 (Agent Core). Each agent should have a human-readable `.spec.md` before code is written.

3. **Add GitOps remediation path** for Arc K8s resources. When the root cause is a manifest issue managed by Flux, the agent should create a PR against the GitOps repo rather than applying changes directly.

### 7.2 FEATURES.md Updates

1. **Add "Suggested Investigation Queries" to incident records** -- pre-populated KQL queries that operators can run to verify agent findings. This is a Table Stakes feature for agent transparency.

2. **Add "In-Cluster MCP Server for Arc K8s" as a Phase 3 Differentiator** -- a Helm chart that deploys a lightweight MCP server into Arc K8s clusters for pod-level diagnostics.

3. **Add "Feature Maturity Levels" (L0-L3)** to each feature to track the crawl-walk-run progression explicitly.

### 7.3 PITFALLS.md Updates

1. **Promote "Approve-Then-Stale" to a formal protocol** with the Resource Identity Certainty pattern. Include the two-signal verification requirement.

2. **Add "Wildcard Tool Access" pitfall** -- agents must never have `tools: ["*"]` in production. Always use explicit `allowed_tools` lists.

### 7.4 ROADMAP.md Updates

1. **Add maturity levels per feature area:**
   - MVP ships at L1-L2 (automated detection, agent-assisted triage, human-approved remediation)
   - Phase 2 targets L2-L3 for core scenarios
   - L3 (supervised automation) only for low-risk actions with high confidence

2. **Add agent specification writing as a Phase 2 task** -- create .spec.md files for all domain agents before implementation begins.

---

## 8. Key Resources from the GBB Repo

| Resource | Relevance to AAP |
|----------|-----------------|
| [Cluster Doctor Agent Spec](https://github.com/microsoftgbb/agentic-platform-engineering/blob/main/.github/agents/cluster-doctor.agent.md) | Template for our domain agent specifications |
| [ArgoCD Failure Handler Workflow](https://github.com/microsoftgbb/agentic-platform-engineering/blob/main/.github/workflows/argocd-deployment-failure.yml) | Pattern for incident deduplication and structured incident creation |
| [Blog Post: Agentic Platform Engineering](https://devblogs.microsoft.com/all-things-azure/agentic-platform-engineering-with-github-copilot/) | High-level architecture context and Microsoft's positioning |
| [Cluster Doctor Video Part 1](https://youtu.be/M_YX74ATz0I) | Live demo of the agent workflow |
| [Cluster Doctor Video Part 2](https://youtu.be/sYM_X6tOgDw) | Configuration walkthrough |

---

## 9. Verdict

**Adoption level: Selective pattern adoption, not wholesale architecture import.**

The GBB repo is a workshop demo, not a production reference architecture. Its value to AAP is in the **patterns and design principles** it validates, not in its technology choices. The most impactful takeaways are:

1. **Resource Identity Certainty** -- formalize as a mandatory protocol
2. **Agent specification as markdown** -- adopt as a design artifact
3. **GitOps remediation path** -- add for Arc K8s/Flux-managed resources
4. **Incident deduplication** -- replicate the pattern in our incident creation flow
5. **Phased diagnostic workflow** -- enforce Collect/Verify/Diagnose/Triage/Remediate phases
6. **Crawl-Walk-Run maturity model** -- add feature maturity levels to ROADMAP.md

The GBB repo confirms that Microsoft's GBB team is thinking along the same lines as AAP's architecture -- agents that observe, reason, and act with human approval. The key difference is scope: they solve one problem (Kubernetes cluster diagnosis) with one agent; we solve the full Azure operations problem with a multi-agent domain-specialist architecture. Our approach is more ambitious but architecturally sound.

---

*Research completed: 2026-03-25. All content sourced from GitHub API, Microsoft DevBlogs, and direct file analysis.*
