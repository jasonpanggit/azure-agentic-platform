# Phase 11: Patch Domain Agent — Research

**Researched:** 2026-03-30
**Phase:** 11-patch-domain-agent
**Objective:** What do I need to know to PLAN this phase well?

---

## 1. Existing Domain Agent Pattern (Code-Verified)

### 1.1 File Layout

Every domain agent follows an identical structure. The patch agent MUST replicate this exactly:

```
agents/patch/
  __init__.py          # empty
  agent.py             # ChatAgent factory, system prompt, entry point
  tools.py             # @ai_function tools, ALLOWED_MCP_TOOLS list
  Dockerfile           # FROM ${BASE_IMAGE}, COPY requirements.txt, CMD ["python", "-m", "patch.agent"]
  requirements.txt     # Agent-specific deps beyond base image
```

**Verified files:** `agents/compute/agent.py` (129 lines), `agents/compute/tools.py` (216 lines), `agents/compute/Dockerfile` (12 lines), `agents/compute/requirements.txt` (3 lines — comment only since compute has no extra deps).

### 1.2 Agent Factory Pattern

```python
# From agents/compute/agent.py:
def create_compute_agent() -> ChatAgent:
    client = get_foundry_client()
    return ChatAgent(
        name="compute-agent",
        description="...",
        system_prompt=COMPUTE_AGENT_SYSTEM_PROMPT,
        client=client,
        tools=[query_activity_log, query_log_analytics, ...],
    )
```

For agents that also mount MCP tools (like arc-agent), the pattern adds `tool_resources=[MCPTool(...)]` to the constructor. The patch agent mounts Azure MCP Server tools via `MCPTool` (same as arc-agent pattern), so it follows the arc-agent constructor style.

### 1.3 Tool Function Pattern

```python
@ai_function
def query_activity_log(resource_ids: List[str], timespan_hours: int = 2) -> Dict[str, Any]:
    agent_id = get_agent_identity()
    tool_params = {...}
    with instrument_tool_call(tracer=tracer, agent_name="patch-agent", agent_id=agent_id,
                               tool_name="query_activity_log", tool_parameters=tool_params,
                               correlation_id="", thread_id=""):
        return {... "query_status": "success"}
```

Key observations:
- All tools are decorated with `@ai_function` from `agent_framework`
- Every tool call wraps its body in `instrument_tool_call` for OTel span emission
- Return types are always `Dict[str, Any]`
- Current implementations return stub data (Phase 2 scaffolding pattern); actual Azure SDK calls will be wired in the future
- The `ALLOWED_MCP_TOOLS` list is a module-level `List[str]` — no wildcards (AGENT-001)

### 1.4 System Prompt Structure

Verified across compute-agent and arc-agent:
1. **Scope** section — what resource types the agent covers
2. **Mandatory Triage Workflow** — numbered steps the LLM must follow
3. **Safety Constraints** — hard rules (REMEDI-001, TRIAGE-002/003/004)
4. **Allowed Tools** — dynamically injected via `.format()`

### 1.5 Shared Utilities (No Modifications Needed)

| Module | Usage |
|---|---|
| `agents.shared.auth.get_foundry_client()` | Creates `AgentsClient` for Foundry |
| `agents.shared.auth.get_agent_identity()` | Returns `AGENT_ENTRA_ID` for AUDIT-005 |
| `agents.shared.auth.get_credential()` | Returns cached `DefaultAzureCredential` |
| `agents.shared.otel.setup_telemetry(name)` | Configures OTel tracer; use `"aiops-patch-agent"` |
| `agents.shared.otel.instrument_tool_call(...)` | Wraps tool calls in OTel spans |
| `agents.shared.envelope.IncidentMessage` | TypedDict for inter-agent messages |
| `agents.shared.approval_manager.create_approval_record(...)` | Cosmos DB approval write for REMEDI-001 |
| `agents.shared.runbook_tool.retrieve_runbooks(query, domain, limit)` | TRIAGE-005 runbook citation |

---

## 2. Orchestrator Routing (Files to Modify)

### 2.1 `agents/shared/routing.py`

The `QUERY_DOMAIN_KEYWORDS` tuple currently has 5 entries: arc, compute, network, storage, security. A new `"patch"` entry must be added.

**Ordering matters:** The keywords are scanned top-to-bottom; the first match wins. Patch keywords like `"patch"`, `"patching"`, `"patch compliance"` don't overlap with existing domain keywords. No collision risk.

Per D-12, the patch keyword list deliberately excludes generic `"update"` / `"updates"` to avoid false-positive routing for queries like "storage update" or "update my VM size".

**Location:** Insert the patch entry AFTER arc (most specific) and BEFORE compute. Rationale: patch keywords are distinct and won't collide, but placing them early prevents any accidental match by the compute domain's broader keywords.

### 2.2 `agents/orchestrator/agent.py`

Three modifications needed:

1. **`DOMAIN_AGENT_MAP`** — Add `"patch": "patch-agent"` (currently has 6 entries; becomes 7)
2. **`RESOURCE_TYPE_TO_DOMAIN`** — Add `"microsoft.maintenance": "patch"` (maps Update Manager maintenance configuration resources)
3. **`ORCHESTRATOR_SYSTEM_PROMPT`** — Add routing rule: `"patch", "update manager", "windows update", "missing patches", "patch compliance" -> **patch-agent**`
4. **`create_orchestrator()`** — Add new `AgentTarget` registration for `"patch"` with env var `PATCH_AGENT_ID`

### 2.3 Detection Plane Domain Mapping

`services/detection-plane/classify_domain.py` currently maps resource types to domains but does NOT include `microsoft.maintenance`. This is a **potential future change** but is explicitly out of Phase 11 scope (D-13 says add to `RESOURCE_TYPE_TO_DOMAIN` in the orchestrator, not the detection plane). The detection plane change can be added if/when Update Manager alerts flow through the Fabric pipeline.

### 2.4 Integration Tests

`agents/tests/integration/test_handoff.py` validates `DOMAIN_AGENT_MAP` has all expected domains. After adding `"patch"`, the test assertion `expected_domains = {"compute", "network", "storage", "security", "sre", "arc"}` must be updated to include `"patch"`.

---

## 3. Azure Resource Graph — PatchAssessmentResources & PatchInstallationResources

### 3.1 ARG Table Schemas (Verified from MS Docs)

**`patchassessmentresources`** — Two resource types:
- `patchassessmentresults` (summary): `rebootPending`, `patchServiceUsed`, `osType`, `startDateTime`, `lastModifiedDateTime`, `startedBy`, `errorDetails`, `availablePatchCountByClassification`
- `patchassessmentresults/softwarepatches` (per-patch): `lastModifiedDateTime`, `publishedDateTime`, `classifications`, `rebootRequired`, `rebootBehavior`, `patchName`, `Kbid` (Windows), `version` (Linux)

**`patchinstallationresources`** — Two resource types:
- `patchinstallationresults` (summary): `installationActivityId`, `maintenanceWindowExceeded`, `installedPatchCount`, `failedPatchCount`, `pendingPatchCount`, `excludedPatchCount`, `notSelectedPatchCount`, `rebootStatus`, `status`, `startDateTime`, `startedBy`, `osType`, `patchServiceUsed`, `errorDetails`, `maintenanceRunId`
- `patchinstallationresults/softwarepatches` (per-patch): `installationState` (Installed/Failed/Pending/NotSelected/Excluded), `classifications`, `rebootRequired`, `patchName`, `Kbid`, `version`

**Data retention:** Assessment results available for 7 days; installation results for 30 days.

### 3.2 Key KQL Queries

**Compliance summary (all subscriptions):**
```kql
patchassessmentresources
| where type =~ "microsoft.compute/virtualmachines/patchassessmentresults"
    or type =~ "microsoft.hybridcompute/machines/patchassessmentresults"
| extend rebootPending = tobool(properties.rebootPending),
         osType = tostring(properties.osType),
         lastAssessment = todatetime(properties.lastModifiedDateTime),
         criticalCount = toint(properties.availablePatchCountByClassification.Critical),
         securityCount = toint(properties.availablePatchCountByClassification.Security)
| project id, name, resourceGroup, subscriptionId, osType, rebootPending,
          lastAssessment, criticalCount, securityCount
```

**Missing patches by classification:**
```kql
patchassessmentresources
| where type =~ "microsoft.compute/virtualmachines/patchassessmentresults/softwarepatches"
    or type =~ "microsoft.hybridcompute/machines/patchassessmentresults/softwarepatches"
| extend patchName = tostring(properties.patchName),
         classifications = tostring(properties.classifications),
         kbId = tostring(properties.Kbid),
         rebootRequired = tobool(properties.rebootRequired)
| where classifications in ("Critical", "Security")
| project id, patchName, classifications, kbId, rebootRequired
```

**Installation history (7-day window per D-04):**
```kql
patchinstallationresources
| where type =~ "microsoft.compute/virtualmachines/patchinstallationresults"
    or type =~ "microsoft.hybridcompute/machines/patchinstallationresults"
| extend startTime = todatetime(properties.startDateTime),
         status = tostring(properties.status),
         rebootStatus = tostring(properties.rebootStatus),
         installedCount = toint(properties.installedPatchCount),
         failedCount = toint(properties.failedPatchCount)
| where startTime > ago(7d)
| project id, resourceGroup, subscriptionId, startTime, status,
          rebootStatus, installedCount, failedCount
```

### 3.3 Python SDK: `azure-mgmt-resourcegraph`

- **Package:** `azure-mgmt-resourcegraph`
- **Latest version:** 8.0.1 (released 2025-11-24)
- **Python:** >= 3.9
- **Key class:** `ResourceGraphClient(credential=DefaultAzureCredential())`
- **Key method:** `client.resources(QueryRequest(subscriptions=[...], query="...", options=QueryRequestOptions(...)))`
- **Pagination:** Response includes `skip_token`; pass back via `QueryRequestOptions(skip_token=response.skip_token)`
- **Cross-subscription:** Pass list of all subscription IDs in `QueryRequest.subscriptions` — ARG natively supports cross-subscription queries

**This is a NEW dependency.** Must be added to `agents/patch/requirements.txt`. Consider also adding to `agents/requirements-base.txt` if future agents need ARG — but per D-07 decision, add to patch agent only for now.

---

## 4. Log Analytics ConfigurationData Table

### 4.1 Schema (Verified from MS Docs)

ConfigurationData is used by the Change Tracking solution. Key columns for patch inventory:

| Column | Type | Relevance |
|---|---|---|
| `Computer` | string | Machine name (join key with ARG) |
| `ConfigDataType` | string | Filter: `"Software"` for patch/software inventory |
| `SoftwareName` | string | Software/patch name |
| `CurrentVersion` | string | Installed version |
| `Publisher` | string | Software publisher |
| `SoftwareType` | string | `"Application"`, `"Package"`, `"Update"` |
| `_ResourceId` | string | ARM resource ID (join key with ARG) |
| `TimeGenerated` | datetime | Record timestamp |

### 4.2 Relevant KQL

**Software inventory for a specific machine:**
```kql
ConfigurationData
| where ConfigDataType == "Software"
| where Computer == "<machine-name>"
| project Computer, SoftwareName, CurrentVersion, Publisher, SoftwareType, TimeGenerated
| order by TimeGenerated desc
```

**Pending updates across workspace:**
```kql
ConfigurationData
| where ConfigDataType == "Software"
| where SoftwareType == "Update"
| summarize UpdateCount = count() by Computer, bin(TimeGenerated, 1d)
| order by UpdateCount desc
```

### 4.3 Workspace Targeting (D-08)

Per decision D-08, the agent queries Log Analytics workspaces **tied to the affected Arc/Azure resources**, not all accessible workspaces. This means the agent needs the workspace ID as context from the incident envelope or must resolve it from the resource's diagnostic settings.

The existing `query_log_analytics` tool in compute/arc agents already takes `workspace_id` as a parameter — the patch agent follows the same pattern. The LLM is given the workspace ID in the incident context or discovers it via Azure Monitor MCP tools.

---

## 5. KB-to-CVE Mapper Strategy

### 5.1 MSRC CVRF API (Recommended)

- **Base URL:** `https://api.msrc.microsoft.com/cvrf/v3.0/`
- **Key endpoint:** `GET /Updates('{id}')` where id is `yyyy-mmm` (e.g., `2026-Mar`)
- **Full document:** `GET /cvrf/{id}` returns CVRF XML/JSON with all vulnerability nodes
- **Authentication:** Appears open (no API key in swagger spec)
- **Rate limits:** None documented

**Mapping strategy:** The CVRF document contains `Vulnerability` nodes. Each node has a `CVE` field and `Remediations` child nodes that contain KB article numbers under `Description.Value`. By parsing the CVRF document, we can build a `KB -> List[CVE]` mapping.

### 5.2 Implementation Approach (Recommendation)

Given D-06 locks this feature and leaves strategy at Claude's discretion:

1. **Primary: MSRC API (live lookup)** — Query MSRC API for the monthly update release matching the KB's publish date. Parse the CVRF document to find KB -> CVE mappings. Cache results (monthly updates are immutable after release).
2. **Fallback: Return "unknown"** — If MSRC API is unavailable, return `{"kb": "KBxxxxxxx", "cves": [], "source": "unavailable"}` with a clear message. Non-blocking.

**Why not static lookup table:** Static tables go stale quickly as new patches are released monthly. MSRC API is the authoritative source and eliminates maintenance burden.

**Why not NVD API:** NVD indexes by CVE, not by KB. You'd need to search NVD for each CVE already — but you first need to know which CVEs a KB addresses, which is exactly what MSRC provides. NVD adds latency without new information.

### 5.3 Implementation Detail

The KB-to-CVE mapper can be implemented as an `@ai_function` tool (`lookup_kb_cves`) that:
1. Extracts the month/year from the KB's publish date (available in ARG `patchassessmentresources/softwarepatches.properties.publishedDateTime`)
2. Calls MSRC API: `GET /cvrf/{yyyy-mmm}`
3. Parses the response to find all CVEs associated with the given KB
4. Returns `{ "kb_id": str, "cves": List[str], "cve_count": int, "source": "msrc" }`

**Caching:** Use an in-memory dict (or `functools.lru_cache`) keyed by monthly release ID. Monthly CVRF documents are immutable — cache indefinitely within a session.

**New dependency:** `httpx` (already in base image via `agents/shared/runbook_tool.py` which uses it).

---

## 6. Merge Strategy: ARG + ConfigurationData

### 6.1 Join Key

Per D-09, merge by machine name / resource ID:
- ARG records contain the full ARM resource ID in the `id` field (e.g., `/subscriptions/.../providers/Microsoft.Compute/virtualMachines/vm-prod-001/patchAssessmentResults/...`)
- ConfigurationData has `_ResourceId` (ARM resource ID) and `Computer` (hostname)

**Join key priority:**
1. `_ResourceId` (exact ARM ID match) — most reliable
2. `Computer` hostname (fallback for Arc machines where `_ResourceId` may differ between ARG and LAW)

### 6.2 Handling Partial Data

- **Machine in ARG only:** Azure VM without AMA agent reporting to Log Analytics. ARG data is authoritative for compliance; ConfigurationData is "N/A — no agent reporting".
- **Machine in ConfigurationData only:** Arc machine reporting to LAW but not yet assessed by Update Manager. ConfigurationData provides software inventory; compliance state is "N/A — no AUM assessment".
- **Machine in both:** Full picture — merge ARG compliance state with ConfigurationData software inventory.

The merge is done at the tool level (within the `@ai_function`) or by the LLM correlating results from two separate tool calls. Per the established pattern, two separate tool calls is simpler and follows the compute/arc agent precedent where the LLM correlates signals.

---

## 7. Terraform & Infrastructure Changes

### 7.1 Container App Registration

The `terraform/modules/agent-apps/main.tf` uses a `local.agents` map that currently has 7 entries. Adding `"patch"` requires:

1. Add `patch = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }` to `local.agents`
2. Add `variable "patch_agent_id"` to `variables.tf` (same pattern as `arc_agent_id`)
3. Add dynamic `env` block for `PATCH_AGENT_ID` injection into the orchestrator container
4. Wire `patch_agent_id` through all environment `tfvars` files (dev, staging, prod)

### 7.2 RBAC Assignments

The RBAC module (`terraform/modules/rbac/main.tf`) needs a new block for the patch agent. Per D-07 context note, the likely roles are:

- **`Reader`** — Cross-subscription read access for ARG queries (ARG inherently respects RBAC; Reader on subscriptions grants ARG read)
- **`Azure Update Manager Reader`** — If a dedicated role exists; otherwise Reader is sufficient since ARG queries only read assessment/installation results

The RBAC pattern follows the existing `for sub_id in var.all_subscription_ids` loop (same as SRE agent). The `agent_principal_ids` map automatically includes the patch agent's principal_id from the Container App's system-assigned identity.

### 7.3 GitHub Actions: `deploy-all-images.yml`

Add a new `build-patch` job (same pattern as `build-arc`):
```yaml
build-patch:
  name: Build Patch Agent
  needs: build-agent-base
  uses: ./.github/workflows/docker-push.yml
  with:
    image_name: agents/patch
    dockerfile_path: agents/patch/Dockerfile
    build_context: agents/patch/
    image_tag: ${{ needs.build-agent-base.outputs.image_tag }}
    build_args: |
      BASE_IMAGE=${{ vars.ACR_LOGIN_SERVER }}/agents/base:${{ needs.build-agent-base.outputs.image_tag }}
```

Add `build-patch` to the `summary` job's `needs` list.

---

## 8. Spec File

Per D-22 (Phase 2 spec-gate), a spec file at `docs/agents/patch-agent.spec.md` is required BEFORE implementation. It follows the format of `docs/agents/compute-agent.spec.md`:

```
---
agent: patch
requirements: [TRIAGE-002, TRIAGE-003, TRIAGE-004, MONITOR-001, REMEDI-001]
phase: 11
---
# Patch Agent Spec
## Persona
## Goals
## Workflow
## Tool Permissions
## Safety Constraints
## Example Flows
```

---

## 9. Test Strategy

### 9.1 Unit Tests

Located at `agents/tests/shared/` or a new `agents/tests/patch/` directory:
- **Tool function tests:** Mock ARG SDK responses, verify KQL construction, verify pagination handling
- **KB-to-CVE mapper tests:** Mock MSRC API responses, verify parsing, verify cache behavior, verify graceful fallback on API failure
- **Merge logic tests:** Verify ARG + ConfigurationData merge with partial data scenarios (machine in one source only)
- **Routing tests:** Verify `classify_query_text` returns `"patch"` for patch keywords

### 9.2 Integration Tests

Located at `agents/tests/integration/`:
- **Handoff routing test:** Verify orchestrator routes patch incidents and queries to `patch-agent`
- **`DOMAIN_AGENT_MAP` completeness:** Update existing test to expect 7 domains (was 6)
- **`RESOURCE_TYPE_TO_DOMAIN` test:** Verify `microsoft.maintenance` -> `patch`

### 9.3 Test Fixtures

Mock data for ARG responses should cover:
- Assessment summary with multiple classifications (Critical, Security, UpdateRollup, etc.)
- Software patches with KB IDs and Linux version info
- Installation results with mixed statuses (Installed, Failed, Pending)
- Reboot-pending machines
- Cross-subscription results

---

## 10. Remediation Proposal Schema

Per D-16 through D-20, the patch agent proposes but never executes. Two proposal types:

### 10.1 Schedule AUM Assessment Run
```python
{
    "action_type": "schedule_aum_assessment",
    "description": "Schedule a fresh Azure Update Manager assessment scan",
    "target_resources": ["<resource_id>"],
    "estimated_impact": "No downtime — assessment scan only",
    "risk_level": "low",
    "reversible": True,
}
```

### 10.2 Schedule AUM Patch Installation
```python
{
    "action_type": "schedule_aum_patch_installation",
    "description": "Schedule patch installation for <N> <classification> patches",
    "target_resources": ["<resource_id>"],
    "estimated_impact": "Potential reboot required — maintenance window recommended",
    "risk_level": "high",  # or "medium" per D-18
    "reversible": False,
    "patch_classifications": ["Critical", "Security"],
}
```

Risk level logic per D-18:
- Critical / Security classification -> `"high"`
- All other classifications -> `"medium"`
- Assessment runs -> `"low"`

---

## 11. Requirement Traceability

Phase 11 does not introduce NEW requirements — it extends existing ones to a new domain:

| Requirement | How Phase 11 Addresses It |
|---|---|
| TRIAGE-001 | Orchestrator classifies patch incidents and routes to patch-agent |
| TRIAGE-002 | Patch agent queries Log Analytics (ConfigurationData) AND Resource Health |
| TRIAGE-003 | Patch agent checks Activity Log (2h look-back) as FIRST step |
| TRIAGE-004 | Patch agent includes confidence score (0.0-1.0) in every diagnosis |
| TRIAGE-005 | Patch agent cites top-3 runbooks via `retrieve_runbooks(domain="patch")` |
| REMEDI-001 | Patch agent proposes remediation — NEVER executes without approval |
| AUDIT-001 | `correlation_id` preserved through all handoff messages |
| AUDIT-005 | Agent attribution via `AGENT_ENTRA_ID` |
| AGENT-001 | Explicit `ALLOWED_MCP_TOOLS` list — no wildcards |
| AGENT-002 | Typed `IncidentMessage` envelope for all inter-agent messages |
| AGENT-008 | `DefaultAzureCredential` for all Azure API access |
| AGENT-009 | `.spec.md` file required before implementation |

---

## 12. Risk Assessment

### Low Risk
- **Agent scaffolding:** Identical pattern to 6 existing agents. No new patterns to invent.
- **Orchestrator routing:** Additive changes (new map entries, new keywords). No existing behavior changed.
- **Dockerfile/CI:** Copy-paste of existing agent build patterns.

### Medium Risk
- **ARG SDK pagination:** Cross-subscription queries can return large result sets. Must implement `skip_token` pagination loop. Not done in existing agents (they use MCP tools which handle pagination internally).
- **KB-to-CVE mapper:** External API dependency (MSRC). Must handle: API unavailability, missing data, parsing errors. Mitigation: non-blocking fallback.
- **RBAC scope:** Patch agent needs cross-subscription Reader for ARG. Verify `Reader` role is sufficient for ARG queries on `patchassessmentresources`.

### Low-Medium Risk
- **Terraform changes:** Adding a new agent to the for_each map is well-established. Risk is in wiring the `PATCH_AGENT_ID` env var correctly through all layers.
- **Test completeness:** Need good mock data for ARG responses. The ARG response format (nested `properties` bags) is more complex than simple ARM API responses.

---

## 13. Dependency Summary

### New Python Dependencies (patch agent only)
| Package | Version | Purpose |
|---|---|---|
| `azure-mgmt-resourcegraph` | `>=8.0.1` | Azure Resource Graph queries for PatchAssessmentResources / PatchInstallationResources |

### Already Available in Base Image
| Package | Usage |
|---|---|
| `agent-framework==1.0.0rc5` | `@ai_function`, `ChatAgent` |
| `azure-ai-agents>=1.0.0` | `AgentsClient` via `get_foundry_client()` |
| `azure-identity>=1.17.0` | `DefaultAzureCredential` |
| `azure-cosmos>=4.7.0` | Approval records |
| `azure-monitor-opentelemetry>=1.6.0` | OTel instrumentation |
| `httpx` | MSRC API calls (available via shared deps) |
| `pydantic>=2.8.0` | Data validation |

---

## 14. Files Changed Summary

### New Files
| File | Description |
|---|---|
| `agents/patch/__init__.py` | Empty package init |
| `agents/patch/agent.py` | ChatAgent factory, system prompt, entry point |
| `agents/patch/tools.py` | @ai_function tools: ARG queries, ConfigurationData, KB-to-CVE, ALLOWED_MCP_TOOLS |
| `agents/patch/Dockerfile` | Container image (FROM base, COPY, CMD) |
| `agents/patch/requirements.txt` | `azure-mgmt-resourcegraph>=8.0.1` |
| `docs/agents/patch-agent.spec.md` | Agent specification (required before implementation per D-22) |
| `agents/tests/patch/test_patch_tools.py` | Unit tests for patch agent tools |
| `agents/tests/patch/__init__.py` | Empty test package init |

### Modified Files
| File | Change |
|---|---|
| `agents/shared/routing.py` | Add `"patch"` entry to `QUERY_DOMAIN_KEYWORDS` |
| `agents/orchestrator/agent.py` | Add `"patch"` to `DOMAIN_AGENT_MAP`, `RESOURCE_TYPE_TO_DOMAIN`, system prompt, and `AgentTarget` registration |
| `agents/tests/integration/test_handoff.py` | Update `expected_domains` to include `"patch"` |
| `terraform/modules/agent-apps/main.tf` | Add `patch` to `local.agents` map, add `PATCH_AGENT_ID` env var injection |
| `terraform/modules/agent-apps/variables.tf` | Add `variable "patch_agent_id"` |
| `terraform/modules/rbac/main.tf` | Add RBAC assignments for patch agent (Reader + Monitoring Reader on all subscriptions) |
| `terraform/envs/dev/main.tf` | Wire `patch_agent_id` variable |
| `terraform/envs/staging/main.tf` | Wire `patch_agent_id` variable |
| `terraform/envs/prod/main.tf` | Wire `patch_agent_id` variable |
| `.github/workflows/deploy-all-images.yml` | Add `build-patch` job + update summary |

---

## 15. Suggested Plan Breakdown

Based on the spec-gate requirement and the dependency chain:

1. **Plan 11-01: Spec + Agent Scaffolding** — Write `patch-agent.spec.md`, create `agents/patch/` directory with all files, implement `@ai_function` tools (ARG queries, ConfigurationData query, Activity Log, Resource Health, KB-to-CVE mapper), system prompt, agent factory. Unit tests.
2. **Plan 11-02: Orchestrator Routing + Integration** — Modify routing.py keywords, orchestrator agent map/prompt/targets, update integration tests. Verify handoff routing works.
3. **Plan 11-03: Terraform + CI/CD** — Add patch agent to agent-apps module, RBAC assignments, env var wiring, deploy-all-images workflow. `terraform plan` validation.

This 3-plan structure mirrors the natural dependency chain: spec/code first, then routing integration, then infrastructure.

---

*Phase: 11-patch-domain-agent*
*Research completed: 2026-03-30*
