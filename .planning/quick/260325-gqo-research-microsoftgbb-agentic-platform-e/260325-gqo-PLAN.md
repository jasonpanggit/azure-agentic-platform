# Plan: Incorporate microsoftgbb/agentic-platform-engineering Research into Planning Docs

> **Type:** Quick
> **Created:** 2026-03-25
> **Source:** 260325-gqo-RESEARCH.md findings from microsoftgbb/agentic-platform-engineering repo analysis

---

## Objective

Additive updates to four planning docs (ARCHITECTURE.md, FEATURES.md, PITFALLS.md, SUMMARY.md) incorporating validated patterns from the GBB repo research. No deletions — append new sections/bullets with insights.

---

## Tasks

### Task 1: Update ARCHITECTURE.md — Add 3 New Sections

**File:** `.planning/research/ARCHITECTURE.md`

Add the following after existing content:

1. **Section 12: Resource Identity Certainty Protocol** (after Build Order)
   - Add a new section documenting the mandatory pre-execution verification protocol inspired by the GBB Cluster Doctor's "Cluster Identity Certainty" pattern
   - Content: Before any remediation execution, verify resource state matches triage snapshot using at least two independent signals:
     1. Resource ID matches the incident record
     2. Resource state (tags, config) matches snapshot taken at triage time
     3. Subscription/resource group haven't changed
   - Reference: Generalizes the "Approve-Then-Stale" pitfall (PITFALLS.md Section 10) into a formal protocol
   - Include a diagram showing the pre-execution check flow: `Agent executes → re-read resource → compare hash → if diverged: abort + notify → if match: proceed`

2. **Section 13: Agent Specification Format** (after Resource Identity Certainty)
   - Define a standardized agent specification template at `docs/agents/{domain}-agent.spec.md`
   - Template sections (derived from GBB Cluster Doctor format):
     - Persona & Expertise
     - Goals & Success Criteria
     - Workflow Phases (Collect, Verify, Diagnose, Triage, Remediate)
     - Tool Access (which MCP tools, which Azure APIs)
     - Permission Model (RBAC scope, read-only vs read-write)
     - Safety Constraints (Resource Identity Certainty, max blast radius)
     - Example Diagnostic Flows
     - Handoff Conditions (when to escalate to orchestrator or other agents)
   - Note: Specs are design artifacts written before agent code; version-controlled for design review

3. **Section 14: GitOps Remediation Path for Arc K8s** (after Agent Specification)
   - Add a dual remediation path for Arc K8s resources managed by Flux/GitOps:
     - **Manifest issues** (wrong resource limits, bad config): Agent creates a PR against the GitOps repo
     - **Infrastructure issues** (node down, disk full): Direct remediation via Arc MCP Server tools
   - Decision logic: automatic based on `root_cause_type` field in diagnosis result
   - Include pipeline diagram: `Agent diagnosis → classify root_cause_type → if manifest_drift: create GitOps PR → if infra_issue: propose direct action`
   - Reference GBB's ArgoCD → GitHub Issue → PR pattern as inspiration

**Verification:** All 3 sections appended, no existing content modified.

---

### Task 2: Update FEATURES.md and PITFALLS.md — Add New Features and Pitfalls

**File 1:** `.planning/research/FEATURES.md`

Add to existing sections:

1. **Section 3.2 (AI Triage)** — Add new row to RCA table:
   - **"Suggested Investigation Queries"** | Table Stakes | Pre-populated KQL queries included in incident records that operators can run to manually verify agent findings. Increases agent transparency and trust.

2. **Section 6.1 (Arc Features)** — Add new row:
   - **"In-Cluster MCP Server for Arc K8s"** | Differentiator (Phase 3) | Helm chart deploying a lightweight MCP server into Arc K8s clusters for pod-level, node-level, and workload-level diagnostics. Enables deeper K8s triage beyond ARM-level queries. Out of scope for MVP.

3. **Section 11 (MVP Feature Set)** — Add a new subsection **"11.4 Feature Maturity Levels"** after Phase 3:
   - Define maturity model (derived from GBB Crawl-Walk-Run pattern):
     - **L0 (Manual):** Operator invokes agent via chat for ad-hoc investigation
     - **L1 (Monitored):** Alert fires, incident created, operator routes to agent manually
     - **L2 (Assisted):** Alert fires, incident created, orchestrator auto-routes, human approves remediation
     - **L3 (Supervised):** Full automation with human approval only for high-risk actions
   - Map to phases: MVP ships at L1-L2; Phase 2 targets L2-L3 for core scenarios; L3 only for low-risk actions

4. **Section 2.1 (Alert Management)** — Add new row:
   - **"Incident deduplication at creation"** | Table Stakes | Before creating a new incident in Cosmos DB, check for existing open incidents affecting the same resource. Prevents duplicate parallel agent investigations. Pattern validated by GBB ArgoCD failure handler.

**File 2:** `.planning/research/PITFALLS.md`

Add two new entries:

1. **New Section 11: Wildcard Tool Access** (after Operational section)
   - Risk: Agents configured with `tools: ["*"]` or `allowed_tools: ["*"]` gain access to every tool in every connected MCP server. A compromised or misbehaving agent can invoke destructive tools it was never designed to use.
   - Prevention: Always use explicit `allowed_tools` lists in MCP tool configuration. Define per-agent tool allowlists in the agent specification (`.spec.md`). Add a CI lint rule that flags wildcard tool access in agent configuration files.
   - Phase: Agent registration — enforce before any agent is connected to MCP servers.

2. **New Section 12: Incident Deduplication Race Conditions** (after Wildcard Tool Access)
   - Risk: During alert storms, multiple concurrent Activator triggers for the same resource can race to create incident records in Cosmos DB. Without deduplication, parallel agent sessions launch for the same issue, wasting tokens and producing conflicting remediation proposals.
   - Prevention: Use Cosmos DB conditional writes (ETag-based optimistic concurrency) on incident creation keyed by `(resource_id, alert_type, time_window)`. The first write succeeds; subsequent writes for the same key within the deduplication window are rejected and correlated to the existing incident.
   - Phase: Incident creation endpoint — implement before production alert rules are enabled.

**Verification:** New rows/sections appended to correct locations, no existing content removed.

---

### Task 3: Create SUMMARY.md with Cross-Reference Research Synthesis

**File:** `.planning/research/SUMMARY.md`

This file doesn't exist yet. Create it as a research synthesis document with:

1. **Header:** Research Summary — Azure AIOps Agentic Platform
2. **Section: External Research Sources**
   - Reference the GBB repo research (date, repo URL, verdict: selective pattern adoption)
   - List of adopted patterns with cross-references to where they landed in planning docs
3. **Section: Key Architectural Decisions Informed by Research**
   - Resource Identity Certainty → ARCHITECTURE.md Section 12
   - Agent Specification Format → ARCHITECTURE.md Section 13
   - GitOps Remediation Path → ARCHITECTURE.md Section 14
   - Feature Maturity Levels (L0-L3) → FEATURES.md Section 11.4
   - Incident Deduplication → FEATURES.md Section 2.1 + PITFALLS.md Section 12
   - Wildcard Tool Access Prevention → PITFALLS.md Section 11
   - Suggested Investigation Queries → FEATURES.md Section 3.2
   - In-Cluster Arc K8s MCP Server → FEATURES.md Section 6.1
4. **Section: Anti-Patterns Confirmed to Avoid**
   - GitHub-centric orchestration (use Foundry + Container Apps)
   - Port-forwarded MCP servers (use Container Apps internal ingress)
   - Single-agent architecture (use domain-specialist graph)
   - `--allow-all-tools` / wildcard tool access
   - No observability or cost tracking
5. **Section: Stack Validation**
   - GBB repo confirms Microsoft alignment with agent-observe-reason-act-approve pattern
   - Key difference: GBB = single K8s cluster scope; AAP = multi-subscription Azure + Arc estate
   - Technology divergence is expected (GitHub Copilot CLI vs Foundry Agent Framework) — patterns transfer, tools don't

**Verification:** File created with all sections, cross-references are accurate.

---

## Execution Notes

- All updates are **additive** — no existing content is deleted or modified
- Each new section/entry clearly attributes the insight source (microsoftgbb/agentic-platform-engineering)
- Cross-references between docs use relative paths
- Task 1 and Task 2 can execute in parallel; Task 3 depends on knowing the final section numbers from Tasks 1 & 2

---

## Definition of Done

- [ ] ARCHITECTURE.md has 3 new sections (12, 13, 14)
- [ ] FEATURES.md has 4 new entries (Suggested Investigation Queries, In-Cluster MCP, Feature Maturity Levels, Incident Deduplication)
- [ ] PITFALLS.md has 2 new sections (11, 12)
- [ ] SUMMARY.md exists with cross-reference synthesis
- [ ] No existing content was deleted from any file
- [ ] All new content references the GBB repo as source
