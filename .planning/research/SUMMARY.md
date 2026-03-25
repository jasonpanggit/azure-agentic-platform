# Research Summary — Azure AIOps Agentic Platform

> Last updated: 2026-03-25

---

## 1. External Research Sources

### 1.1 microsoftgbb/agentic-platform-engineering

| Attribute | Value |
|---|---|
| **Repository** | [microsoftgbb/agentic-platform-engineering](https://github.com/microsoftgbb/agentic-platform-engineering) |
| **Research date** | 2026-03-25 |
| **Repo type** | Workshop/demo — Microsoft GBB (Global Black Belt) reference for agentic platform engineering |
| **Scope** | Single AKS cluster diagnosis via GitHub Copilot agents + GitHub Actions + MCP servers |
| **Verdict** | **Selective pattern adoption** — not wholesale architecture import. Patterns and design principles transfer; technology choices do not. |
| **Full analysis** | [260325-gqo-RESEARCH.md](../quick/260325-gqo-research-microsoftgbb-agentic-platform-e/260325-gqo-RESEARCH.md) |

---

## 2. Key Architectural Decisions Informed by Research

| Decision | Source Pattern | Landing Location | Impact |
|---|---|---|---|
| **Resource Identity Certainty protocol** | GBB Cluster Doctor "Cluster Identity Certainty" — two-signal verification before write ops | [ARCHITECTURE.md Section 12](./ARCHITECTURE.md#12-resource-identity-certainty-protocol) | Formalizes the Approve-Then-Stale pitfall into a mandatory pre-execution protocol with state hash comparison |
| **Agent Specification Format** | GBB Cluster Doctor `.agent.md` — structured markdown defining persona, goals, workflow, permissions | [ARCHITECTURE.md Section 13](./ARCHITECTURE.md#13-agent-specification-format) | Establishes `docs/agents/{domain}-agent.spec.md` as a required design artifact before agent code is written |
| **GitOps Remediation Path for Arc K8s** | GBB ArgoCD → GitHub Issue → PR remediation pattern | [ARCHITECTURE.md Section 14](./ARCHITECTURE.md#14-gitops-remediation-path-for-arc-k8s) | Adds dual remediation path: manifest drift → GitOps PR; infrastructure issue → direct remediation |
| **Feature Maturity Levels (L0-L3)** | GBB Crawl-Walk-Run deployment strategy | [FEATURES.md Section 11.4](./FEATURES.md#114-feature-maturity-levels) | Defines L0 (Manual) → L1 (Monitored) → L2 (Assisted) → L3 (Supervised) progression per feature area |
| **Incident Deduplication at Creation** | GBB ArgoCD failure handler deduplication logic | [FEATURES.md Section 2.1](./FEATURES.md#21-alert-management) + [PITFALLS.md Section 12](./PITFALLS.md#12-incident-deduplication-race-conditions) | Cosmos DB conditional writes prevent duplicate parallel agent investigations during alert storms |
| **Wildcard Tool Access Prevention** | GBB `--allow-all-tools` flag identified as anti-pattern | [PITFALLS.md Section 11](./PITFALLS.md#11-wildcard-tool-access) | Explicit `allowed_tools` lists required; CI lint rule flags wildcard access in agent config |
| **Suggested Investigation Queries** | GBB Cluster Doctor "troubleshooting commands" in issue templates | [FEATURES.md Section 3.2](./FEATURES.md#32-root-cause-analysis-rca) | Pre-populated KQL queries in incident records for operator verification of agent findings |
| **In-Cluster MCP Server for Arc K8s** | GBB AKS MCP Server deployed inside cluster for pod-level diagnostics | [FEATURES.md Section 6.1](./FEATURES.md#61-unique-aiops-capabilities-for-arc-enabled-resources) | Phase 3 differentiator: Helm chart deploying lightweight MCP server into Arc K8s clusters |

---

## 3. Anti-Patterns Confirmed to Avoid

These patterns from the GBB repo were evaluated and explicitly rejected for AAP:

| Anti-Pattern | GBB Approach | AAP Decision | Rationale |
|---|---|---|---|
| **GitHub-centric orchestration** | GitHub Issues as incident store; GitHub Actions as orchestration engine | Use Foundry Agent Service + Cosmos DB + Container Apps | GitHub Issues are not a production incident management system; Actions has cold start and 6-hour run limits |
| **Port-forwarded MCP servers** | AKS MCP Server accessed via `kubectl port-forward` in CI runner | Use Container Apps internal ingress for MCP server deployment | Port-forwarding is fragile and non-production-ready; Container Apps provides always-on, VNet-integrated services |
| **Single-agent architecture** | One Cluster Doctor agent handles all domains (K8s, networking, security, GitOps) | Use domain-specialist agent graph (Compute, Network, Storage, Security, Arc, SRE) | Single-agent doesn't scale; focused agents enable scoped RBAC and specialized expertise |
| **`--allow-all-tools` / wildcard tool access** | `copilot --allow-all-tools` grants unrestricted MCP tool access | Explicit `allowed_tools` lists per agent; CI lint rule flags wildcards | Security concern: compromised/misbehaving agent can invoke destructive tools it was never designed to use |
| **No observability or cost tracking** | No telemetry, no token budgets, fire-and-forget Copilot CLI calls | OpenTelemetry instrumentation, per-session token budget, cost tracking in Cosmos DB | Essential for production operations; untracked costs can escalate to thousands of dollars during incidents |

---

## 4. Stack Validation

### 4.1 Alignment Confirmed

The GBB repo validates Microsoft's alignment with the **agent-observe-reason-act-approve** pattern that underpins AAP's architecture. Key confirmation points:

- **Agents as first-class operational actors** — not just chatbots, but participants in incident response workflows
- **Human-in-the-loop for remediation** — PR approval (GBB) maps to Adaptive Card approval (AAP); both enforce human review before execution
- **Structured incident records** — GitHub Issues with structured tables (GBB) maps to Cosmos DB incident documents (AAP); both prioritize machine-readable incident context
- **Phased diagnostic workflow** — Collect → Verify → Diagnose → Triage → Remediate pattern is validated by both architectures

### 4.2 Key Differences

| Dimension | GBB Repo | AAP |
|---|---|---|
| **Scope** | Single Kubernetes cluster | Multi-subscription Azure estate + Arc-enabled resources |
| **Agent Runtime** | GitHub Copilot (hosted by GitHub) | Microsoft Agent Framework on Foundry Hosted Agents |
| **Orchestration** | GitHub Actions workflows | HandoffOrchestrator + domain agent graph |
| **Incident Store** | GitHub Issues | Cosmos DB + Foundry Threads |
| **Event Source** | ArgoCD webhook | Azure Monitor + Fabric Activator |
| **Remediation** | GitOps PR (always) | Direct Azure API + GitOps PR (for Arc K8s manifest issues) |
| **UI** | GitHub Issues/PRs | Fluent UI 2 + Next.js + Teams Adaptive Cards |
| **IaC** | None (manual setup) | Terraform (azurerm + azapi) |
| **Observability** | None | OpenTelemetry + App Insights + Fabric OneLake |

### 4.3 Technology Divergence

Technology divergence between the GBB repo and AAP is expected and intentional:

- **GitHub Copilot CLI vs. Foundry Agent Framework** — Different runtimes serving different deployment models. Patterns transfer; tools don't.
- **GitHub Actions vs. Container Apps** — GitHub Actions is suitable for CI/CD orchestration but not for always-on AIOps workflows with sub-second latency requirements.
- **ArgoCD vs. Flux** — Both are GitOps controllers. AAP uses Flux because it's the Azure-native GitOps solution for Arc-enabled Kubernetes (deployed via the Flux extension).

The GBB repo is a valuable **design validation** for AAP's architecture, not a code source to fork or port.

---

*Research synthesis completed: 2026-03-25. All cross-references verified against ARCHITECTURE.md, FEATURES.md, and PITFALLS.md as of this date.*
