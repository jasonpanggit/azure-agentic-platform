# Phase 11: Patch Domain Agent - Context

**Gathered:** 2026-03-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Build a `patch-agent` domain specialist that queries Azure Resource Graph (ARG) Update Manager tables and Log Analytics `ConfigurationData` to expose patch status, compliance, installation history, and reboot-pending state across Azure VMs and Arc-enabled servers. Wire the agent into the orchestrator routing table (keyword routing + `RESOURCE_TYPE_TO_DOMAIN` + `DOMAIN_AGENT_MAP`). Agent follows the existing domain agent pattern: spec-first, `@ai_function` tools, explicit MCP allowlist, `ChatAgent`, Dockerfile, Terraform managed identity + RBAC.

No UI changes. No detection plane changes. No new Container App plumbing beyond what the existing agent deployment pattern already defines.

</domain>

<decisions>
## Implementation Decisions

### Patch Data Depth & Triage Workflow

- **D-01:** Agent surfaces the **full patch picture**: ARG `PatchAssessmentResources` (compliance state, missing patches), ARG `PatchInstallationResources` (installation runs, last 7 days), and a cross-subscription **compliance % rollup**.
- **D-02:** All patch **classifications** are tracked and surfaced: Critical, Security, UpdateRollup, FeaturePack, ServicePack, Definition, Tools, Updates.
- **D-03:** **Subscription scope** = all subscriptions accessible to the managed identity — enables cross-subscription compliance rollup.
- **D-04:** Installation history look-back window = **7 days**.
- **D-05:** **Reboot-pending status** per machine is included in every triage response — machines that installed patches but haven't rebooted yet are flagged explicitly.
- **D-06:** A **KB-to-CVE mapper** must be included — given a KB article number, the agent maps it to the list of CVEs it addresses. This enriches the triage response so operators know which vulnerabilities are fixed/pending per machine.

### ARG Access Pattern & Tool Strategy

- **D-07:** The patch agent calls Azure Resource Graph using **`azure-mgmt-resourcegraph` Python SDK** wrapped in `@ai_function` decorators — same pattern as the `query_activity_log` / `query_log_analytics` wrappers in `agents/compute/tools.py` and `agents/arc/tools.py`.
- **D-08:** The agent **always queries both** ARG and Log Analytics `ConfigurationData`:
  - **ARG** (`PatchAssessmentResources`, `PatchInstallationResources`) → Update Manager assessment/compliance/installation data for Azure VMs.
  - **Log Analytics `ConfigurationData` table** → software inventory (installed + pending patches) for all machines (Azure VMs + Arc-enabled servers) with AMA/MMA agent reporting to a workspace. Reference: https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata — KQL filter and field selection at Claude's discretion per the MS docs schema.
  - **Workspace targeting:** Query the Log Analytics workspace(s) **tied to the affected Arc/Azure resources**, not all accessible workspaces.
- **D-09:** When both ARG and ConfigurationData have data for the same machine, **merge by machine** (machine name / resource ID as join key) — ARG and ConfigurationData are complementary, not competing; ARG owns compliance state, ConfigurationData owns software inventory.
- **D-10:** The agent also mounts **Azure MCP Server** tools for correlated monitor signals — `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status` — same pattern as `arc-agent` mounting both custom and Azure MCP tools.
- **D-11:** `ALLOWED_MCP_TOOLS` explicit list (no wildcards, AGENT-001): `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status`. ARG and ConfigurationData queries are `@ai_function` wrappers, not MCP tools.

### Orchestrator Routing Keywords

- **D-12:** Keywords added to `QUERY_DOMAIN_KEYWORDS` in `agents/shared/routing.py` under a new `"patch"` entry:
  ```
  "patch", "patches", "patching", "update manager", "windows update",
  "security patch", "patch compliance", "patch status", "missing patches",
  "pending patches", "kb article", "hotfix"
  ```
  Deliberately excludes generic "update" / "updates" to avoid false-positive routing for queries like "storage update" or "update my VM size".
- **D-13:** `RESOURCE_TYPE_TO_DOMAIN` in `agents/orchestrator/agent.py` gets a new entry: `"microsoft.maintenance": "patch"` — maps Update Manager maintenance configuration resources to the patch domain.
- **D-14:** `DOMAIN_AGENT_MAP` in `agents/orchestrator/agent.py` gets: `"patch": "patch-agent"`.
- **D-15:** Orchestrator system prompt routing rules updated with: `"patch", "update manager", "windows update", "missing patches", "patch compliance" → **patch-agent**`.

### Remediation Scope

- **D-16:** Patch agent **proposes remediation** (does NOT execute) — consistent with all other domain agents and REMEDI-001.
- **D-17:** Two remediation action types the agent can propose:
  1. **Schedule AUM assessment run** — forces a fresh patch assessment scan. `risk_level: "low"`, `reversible: true`.
  2. **Schedule AUM patch installation** — installs patches via Update Manager. `risk_level` set by classification (see D-18). `reversible: false`.
- **D-18:** Risk level for patch installation proposals:
  - `Critical` / `Security` classifications → `risk_level: "high"`
  - All other classifications (UpdateRollup, FeaturePack, etc.) → `risk_level: "medium"`
  - Assessment runs → `risk_level: "low"`
- **D-19:** `target_resources` scoping for proposals:
  - Single-machine incident → target the individual machines from the incident envelope.
  - Compliance incident (subscription-wide non-compliance) → filter by subscription + patch classification.
  - Agent decides which scope applies based on incident type.
- **D-20:** Human approval is **always required** before any patch installation is executed (REMEDI-001). Assessment runs may be proposed at low risk but still require approval before execution.

### Agent Structure

- **D-21:** Agent lives at `agents/patch/` following the standard layout: `agent.py`, `tools.py`, `__init__.py`, `Dockerfile`, `requirements.txt`.
- **D-22:** Spec file required at `docs/agents/patch-agent.spec.md` before any implementation code (Phase 2 spec-gate, D-01/D-03/D-04 from Phase 2 context).
- **D-23:** Shared utilities from `agents/shared/` apply as-is: `auth.get_foundry_client`, `otel.setup_telemetry`, `envelope.IncidentMessage`, `approval_manager`, `runbook_tool`.
- **D-24:** Mandatory triage workflow steps (same pattern as compute/arc agents):
  1. Activity Log first (TRIAGE-003) — 2-hour look-back on affected resources.
  2. ARG `PatchAssessmentResources` + `PatchInstallationResources` query (all subscriptions, 7d history).
  3. Log Analytics `ConfigurationData` query (workspaces tied to affected resources).
  4. Merge ARG + ConfigurationData by machine.
  5. KB-to-CVE enrichment.
  6. Reboot-pending state flag per machine.
  7. Compliance % rollup across subscriptions.
  8. Correlate with Azure Monitor signals (`monitor.query_logs`, `monitor.query_metrics`).
  9. Produce diagnosis with confidence score (TRIAGE-004).
  10. Propose remediation if clear path exists (REMEDI-001).

### Claude's Discretion

- Exact KQL for `ConfigurationData` queries — follow the MS docs schema at https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata
- KB-to-CVE mapper implementation strategy (static lookup vs. MSRC API vs. NVD API)
- Exact ARG KQL for `PatchAssessmentResources` and `PatchInstallationResources`
- Agent system prompt text beyond what the spec and workflow above defines
- Test fixture design for ARG and ConfigurationData mocks
- Terraform RBAC role for patch agent (likely `Reader` + `Azure Update Manager Reader` on subscription scope)
- `PATCH_AGENT_ID` env var name for the Container App environment variable

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Domain Agent Pattern (replicate this structure)
- `agents/compute/agent.py` — `ChatAgent` setup, system prompt pattern, `@ai_function` tool registration, mandatory triage workflow structure
- `agents/compute/tools.py` — `ALLOWED_MCP_TOOLS` list, `@ai_function` decorator pattern, `instrument_tool_call`, `get_agent_identity` usage
- `agents/compute/Dockerfile` — `FROM ${BASE_IMAGE}`, `COPY requirements.txt`, `CMD ["python", "-m", "compute.agent"]`
- `agents/arc/agent.py` — pattern for mounting both `@ai_function` tools AND Azure MCP Server tools (`MCPTool`) in the same agent

### Orchestrator Routing (files to modify)
- `agents/orchestrator/agent.py` — `DOMAIN_AGENT_MAP`, `RESOURCE_TYPE_TO_DOMAIN`, orchestrator system prompt routing rules, `AgentTarget` list
- `agents/shared/routing.py` — `QUERY_DOMAIN_KEYWORDS` tuple — add `"patch"` entry with keyword list

### Shared Utilities (use without modification)
- `agents/shared/envelope.py` — `IncidentMessage` TypedDict, `VALID_MESSAGE_TYPES`
- `agents/shared/auth.py` — `get_foundry_client`, `get_agent_identity`, `get_credential`
- `agents/shared/otel.py` — `setup_telemetry`, `instrument_tool_call`
- `agents/shared/approval_manager.py` — approval request pattern for REMEDI-001
- `agents/shared/runbook_tool.py` — `retrieve_runbooks` for TRIAGE-005 runbook citation

### Spec Format Reference
- `docs/agents/compute-agent.spec.md` — spec format: frontmatter, Persona, Goals, Workflow, Tool Permissions, Safety Constraints, Example Flows

### Data Sources
- `https://learn.microsoft.com/en-us/azure/update-manager/query-logs` — ARG table schemas: `PatchAssessmentResources`, `PatchInstallationResources`, `PatchInstallationResourceErrors` — ROADMAP canonical ref
- `https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata` — ConfigurationData LAW table schema for software inventory (installed + pending patches across Azure + Arc)

### Phase Context
- `CLAUDE.md` §"Core Agent Framework" — `ChatAgent`, `@ai_function`, `AzureAIAgentClient`, `HandoffOrchestrator` APIs
- `CLAUDE.md` §"Azure Integration Layer" — `azure-ai-projects` 2.0.1
- `CLAUDE.md` §"Azure MCP Server (GA)" — `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status` tool names
- `.planning/phases/02-agent-core/02-CONTEXT.md` — Phase 2 decisions: spec-gate (D-01 to D-04), agent layout (D-05 to D-08), managed identity per agent (D-13), RBAC via Terraform (D-14/D-15)
- `.planning/REQUIREMENTS.md` §TRIAGE — TRIAGE-001 (classify before handoff), TRIAGE-002 (Log Analytics + Resource Health mandatory), TRIAGE-003 (Activity Log first), TRIAGE-004 (confidence score), TRIAGE-005 (runbook citation)
- `.planning/REQUIREMENTS.md` §REMEDI — REMEDI-001 (no execution without human approval)
- `.planning/REQUIREMENTS.md` §AUDIT — AUDIT-001 (preserve correlation_id), AUDIT-005 (agent attribution)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agents/shared/auth.py` — `get_foundry_client()`, `get_agent_identity()`, `get_credential()` — use directly, no changes needed
- `agents/shared/otel.py` — `setup_telemetry("aiops-patch-agent")` and `instrument_tool_call` — use directly
- `agents/shared/envelope.py` — `IncidentMessage` TypedDict — use for all inter-agent messages
- `agents/shared/approval_manager.py` — approval request submission — use for REMEDI-001 compliance
- `agents/shared/runbook_tool.py` — `retrieve_runbooks(query, domain="patch", limit=3)` — cite top-3 runbooks in triage response (TRIAGE-005)
- `agents/Dockerfile.base` — base image with all common Python deps pre-installed; patch agent's Dockerfile starts `FROM ${BASE_IMAGE:-aap-agents-base:latest}`

### Established Patterns
- `@ai_function` decorator: import from `agent_framework`, takes typed args, returns `Dict[str, Any]`, uses `instrument_tool_call` for OTel spans
- `ALLOWED_MCP_TOOLS: List[str]` — module-level explicit list, passed to `ChatAgent` constructor
- System prompt structure: Scope section → Mandatory Triage Workflow (numbered steps) → Safety Constraints section
- Agent entry point: `CMD ["python", "-m", "patch.agent"]` in Dockerfile
- Env var pattern: `os.environ.get("PATCH_AGENT_ID", "")` for Foundry agent ID

### Integration Points
- `agents/orchestrator/agent.py` — 3 locations to modify: `DOMAIN_AGENT_MAP`, `RESOURCE_TYPE_TO_DOMAIN`, system prompt routing rules, and `AgentTarget` list in the agent constructor
- `agents/shared/routing.py` — one location: `QUERY_DOMAIN_KEYWORDS` tuple — insert `"patch"` entry
- `agents/tests/integration/` — integration test directory for new agent handoff tests

### New Dependency
- `azure-mgmt-resourcegraph` — not yet in any agent `requirements.txt`. Must be added to `agents/patch/requirements.txt` (and possibly `agents/requirements-base.txt` if other agents will also use ARG in future)

</code_context>

<specifics>
## Specific Ideas

- **KB-to-CVE mapper**: User specifically requested a mapper that takes a KB article number and returns the list of CVEs it addresses. Implementation strategy (static lookup table, MSRC Security Update Guide API, or NVD CVE API) is at Claude's discretion — the feature itself is locked.
- **ConfigurationData reference**: User pointed to https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata for the exact schema — downstream agents should read this before writing KQL.
- **Merge key**: ARG and ConfigurationData are merged by machine name / resource ID — the merge logic should handle cases where a machine appears in one source but not the other (Arc-only machines won't be in ARG; pure Azure VMs may not have AMA agent reporting to LAW).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 11-patch-domain-agent*
*Context gathered: 2026-03-30*
