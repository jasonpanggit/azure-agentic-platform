# Plan 02-04 Summary — Agent Implementations

**Wave:** 4
**Depends on:** 02-02 (shared infra — COMPLETE), 02-03 (API gateway — COMPLETE)
**Status:** COMPLETE
**Commit:** `feat(agents): implement all 7 domain agents and CI matrix build (plan 02-04)`

---

## What Was Done

### Files Created (35 total)

#### Task 04.01 — Orchestrator Agent
- `agents/orchestrator/__init__.py` — package docstring
- `agents/orchestrator/agent.py` — `HandoffOrchestrator` with `classify_incident_domain` @ai_function; `DOMAIN_AGENT_MAP`; `RESOURCE_TYPE_TO_DOMAIN` mapping for 11 resource type prefixes; `create_orchestrator()` registering 6 `AgentTarget` instances via env vars; entry point
- `agents/orchestrator/Dockerfile` — ARG BASE_IMAGE pattern; CMD ["python", "-m", "orchestrator.agent"]
- `agents/orchestrator/requirements.txt` — empty (comment only)

#### Task 04.02 — Shared Triage Infrastructure
- `agents/shared/triage.py` — `TriageDiagnosis` dataclass with `confidence_score` validation (0.0–1.0, raises ValueError), `to_dict()`, `to_envelope()` returning `IncidentMessage(message_type="diagnosis_complete")`; `RemediationProposal` with `risk_level` validation (`{"low","medium","high","critical"}`), `to_dict()` with `"requires_approval": True` (REMEDI-001); requirement refs TRIAGE-002, TRIAGE-003, TRIAGE-004 in docstrings

#### Task 04.03 — Compute Agent
- `agents/compute/__init__.py`
- `agents/compute/tools.py` — `ALLOWED_MCP_TOOLS` (9 tools, no wildcards); `@ai_function`: `query_activity_log`, `query_log_analytics`, `query_resource_health`, `query_monitor_metrics`; each uses `instrument_tool_call`
- `agents/compute/agent.py` — `ChatAgent` with `COMPUTE_AGENT_SYSTEM_PROMPT` enforcing TRIAGE-002/003/004/REMEDI-001; "without human approval"; Activity Log; `create_compute_agent()`; entry point
- `agents/compute/Dockerfile`, `agents/compute/requirements.txt`

#### Task 04.04 — Network, Storage, Security, SRE Agents

**Network** (`agents/network/`):
- `tools.py` — `ALLOWED_MCP_TOOLS` (4 MCP tools); note on azure-mgmt-network SDK gap; `@ai_function`: `query_nsg_rules`, `query_load_balancer_health`, `query_vnet_topology`, `query_peering_status`
- `agent.py` — `NETWORK_AGENT_SYSTEM_PROMPT` with VNet/NSG/LB/DNS/ExpressRoute scope, Activity Log, TRIAGE-003, confidence score, REMEDI-001 "without human approval", MCP gap note; `create_network_agent()`
- `requirements.txt` — `azure-mgmt-network>=27.0.0`

**Storage** (`agents/storage/`):
- `tools.py` — `ALLOWED_MCP_TOOLS` (6 tools); `@ai_function`: `query_storage_metrics`, `query_blob_diagnostics`, `query_file_sync_health`
- `agent.py` — `STORAGE_AGENT_SYSTEM_PROMPT` with Blob/Files/Tables/Queues/ADLS Gen2 scope, Activity Log, TRIAGE-003, confidence score, REMEDI-001 "without human approval", MUST NOT delete; `create_storage_agent()`
- `requirements.txt` — empty (comment only)

**Security** (`agents/security/`):
- `tools.py` — `ALLOWED_MCP_TOOLS` (6 tools); `@ai_function`: `query_defender_alerts`, `query_keyvault_diagnostics`, `query_iam_changes`
- `agent.py` — `SECURITY_AGENT_SYSTEM_PROMPT` with Defender/Key Vault/RBAC drift scope, Activity Log, TRIAGE-003, confidence score, REMEDI-001 "without human approval", immediate escalation for credential exposure; `create_security_agent()`
- `requirements.txt` — empty (comment only)

**SRE** (`agents/sre/`):
- `tools.py` — `ALLOWED_MCP_TOOLS` (6 tools including `resourcehealth.list_events`); `@ai_function`: `query_availability_metrics`, `query_performance_baselines`, `propose_remediation` (returns `"requires_approval": True` — REMEDI-001)
- `agent.py` — `SRE_AGENT_SYSTEM_PROMPT` with cross-domain monitoring, SLA tracking, Arc fallback, Activity Log, TRIAGE-003, confidence score, REMEDI-001 "without human approval", MUST NOT modify; `create_sre_agent()`
- `requirements.txt` — empty (comment only)

#### Task 04.05 — Arc Agent (stub)
- `agents/arc/__init__.py` — docstring documenting Phase 2 stub status and Phase 3 dependency on custom Arc MCP Server
- `agents/arc/agent.py` — `ALLOWED_MCP_TOOLS: list[str] = []` (empty); `@ai_function handle_arc_incident` returns `"status": "pending_phase3"`, `"message": "Arc-specific capabilities are pending Phase 3 implementation..."`, `"recommendation": "Escalate to SRE agent"`, `"timestamp"`, `"needs_cross_domain": True`, `"suspected_domain": "sre"`; `create_arc_agent()`; entry point
- `agents/arc/Dockerfile` — ARG BASE_IMAGE pattern; CMD ["python", "-m", "arc.agent"]
- `agents/arc/requirements.txt` — documents Phase 3 SDK packages: azure-mgmt-hybridcompute, azure-mgmt-connectedk8s, azure-mgmt-azurearcdata

#### Task 04.06 — CI Matrix Build
- `.github/workflows/agent-images.yml` — `dorny/paths-filter@v3` change detection matrix; 7 per-agent jobs (build-orchestrator, build-compute, build-network, build-storage, build-security, build-sre, build-arc); each uses `docker-push.yml` reusable workflow with per-agent `image_name`, `dockerfile_path`, `build_context: agents/`

---

## Verification Results

All 12 acceptance criteria checks PASSED:

| Check | Result |
|---|---|
| All 7 agent directories exist with required files | ✅ OK |
| tools.py exists for compute/network/storage/security/sre | ✅ OK (5/5) |
| No wildcard in ALLOWED_MCP_TOOLS | ✅ OK |
| Arc returns pending_phase3 | ✅ OK |
| Arc has empty ALLOWED_MCP_TOOLS | ✅ OK |
| All 7 agents import from shared.auth | ✅ OK (7/7) |
| All 7 agents import from shared.otel | ✅ OK (7/7) |
| "without human approval" in all 5 domain agents | ✅ OK (5/5) |
| "Activity Log" in all 5 non-Arc agent prompts | ✅ OK (5/5) |
| triage.py: TriageDiagnosis class | ✅ OK |
| triage.py: RemediationProposal class | ✅ OK |
| triage.py: `"requires_approval": True` | ✅ OK |
| CI workflow name: "Build Agent Images" | ✅ OK |
| CI workflow uses dorny/paths-filter | ✅ OK |
| CI workflow has 7 build job references | ✅ OK (7) |

---

## Notable Implementation Decisions

1. **Orchestrator uses resource type prefix matching** — `classify_incident_domain` implements a deterministic first-pass classification by extracting resource type from resource IDs (e.g., `/providers/Microsoft.Compute/` → compute), then falls back to detection rule keyword matching, then defaults to `sre`. This avoids unnecessary LLM calls for unambiguous classifications.

2. **Network agent uses `azure-mgmt-network` SDK** — The Azure MCP Server does not cover direct VNet/NSG/LB operations (confirmed gap). Network tools are implemented as `@ai_function` wrappers with `azure-mgmt-network>=27.0.0` in requirements.txt. The system prompt explicitly documents this gap.

3. **instrument_tool_call with empty correlation_id/thread_id** — The tool functions receive empty strings for `correlation_id` and `thread_id` since these are resolved at runtime from the incoming IncidentMessage envelope. This keeps tool function signatures clean (no thread context threading) while maintaining OTEL attribution.

4. **Arc agent ALLOWED_MCP_TOOLS typed as `list[str]`** — Uses `list[str]` (not `List[str]`) to match the spec exactly. The Phase 3 SDK packages are documented as comments in requirements.txt.

5. **System prompts embed ALLOWED_MCP_TOOLS at class definition time** — Format strings populate tool allowlists into prompts at module import, ensuring prompts stay in sync with the tool lists defined in tools.py.

6. **SRE `propose_remediation` returns `requires_approval: True`** — The SRE agent is the only domain agent with a tool that produces a remediation proposal struct (other agents embed proposals in their diagnosis output). This makes the approval gate explicit and machine-readable for the Teams approval flow (Phase 3).
