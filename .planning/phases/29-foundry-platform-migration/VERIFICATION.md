---
status: passed
phase: 29
verified_at: "2026-04-11"
verified_by: "goal-backward verification"
tests_run: 38
tests_passed: 38
full_suite_passing: 1161
full_suite_failing: 8
full_suite_failures_are_pre_existing: true
---

# Phase 29 Verification — Foundry Platform Migration

## Goal

Migrate all 9 agents from `azure-ai-projects` 1.x / `AgentsClient` thread-run patterns to
`azure-ai-projects` 2.0.x `PromptAgentDefinition` / Responses API patterns, making every
agent version-tracked and visible in the Foundry portal, with A2A orchestrator topology
and OTel tracing wired to App Insights.

---

## Must-Have Checks

### 1. `agents/shared/telemetry.py` — PASSED

| Check | Result |
|---|---|
| File exists | ✅ `agents/shared/telemetry.py` |
| `setup_foundry_tracing()` function present | ✅ Line 30 |
| Calls `configure_azure_monitor(connection_string=...)` | ✅ Line 44 |
| Calls `AIProjectInstrumentor().instrument()` | ✅ Lines 46–47 |
| `get_tracer()` function present | ✅ Line 50 |
| `try/except ImportError` guard for `AIProjectInstrumentor` | ✅ Lines 24–27 |
| `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true` auto-set | ✅ Line 21 |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` auto-set | ✅ Line 22 |

### 2. All 8 Domain Agents — `create_version()` Functions — PASSED

| Agent file | Function | Line |
|---|---|---|
| `agents/compute/agent.py` | `create_compute_agent_version()` | 141 |
| `agents/network/agent.py` | `create_network_agent_version()` | 162 |
| `agents/storage/agent.py` | `create_storage_agent_version()` | 133 |
| `agents/security/agent.py` | `create_security_agent_version()` | 167 |
| `agents/arc/agent.py` | `create_arc_agent_version()` | 185 |
| `agents/sre/agent.py` | `create_sre_agent_version()` | 168 |
| `agents/patch/agent.py` | `create_patch_agent_version()` | 215 |
| `agents/eol/agent.py` | `create_eol_agent_version()` | 224 |

All functions take `project: AIProjectClient` and return an `AgentVersion` via
`project.agents.create_version(agent_name="aap-{domain}-agent", definition=PromptAgentDefinition(...))`.

Each uses consistent `aap-{domain}-agent` naming (verified by smoke test
`test_all_domain_agents_have_consistent_registration_pattern`).

### 3. Orchestrator — `create_orchestrator_agent_version()` with `A2APreviewTool` — PASSED

| Check | Result |
|---|---|
| `agents/orchestrator/agent.py` has `create_orchestrator_agent_version()` | ✅ Line 285 |
| `A2APreviewTool` imported with `ImportError` guard | ✅ Lines 34, 37 |
| `_A2A_DOMAINS` list of 8 domains | ✅ Lines 279–283 |
| `A2APreviewTool(project_connection_id=conn.id)` per domain | ✅ Line 306 |
| `project.connections.get()` called for each domain | ✅ Verified by `test_fetches_connection_for_each_domain` (count=8) |
| `agent_name="aap-orchestrator"` | ✅ Verified by `test_calls_create_version_with_orchestrator_name` |

### 4. `services/api-gateway/foundry.py` — Responses API — PASSED

| Check | Result |
|---|---|
| `dispatch_to_orchestrator()` function exists | ✅ Line 115 |
| Uses `openai.responses.create()` (not threads/runs) | ✅ Line 142 |
| `AIProjectClient` used for new dispatch path | ✅ Lines 69, 87 |
| `_get_openai_client()` helper present | ✅ Line 90 |
| `build_incident_message()` envelope builder present | ✅ Line 97 |
| Returns `{"response_id": ..., "status": ...}` | ✅ Line 163 |
| `extra_body["agent_reference"]` passed to `responses.create` | ✅ Lines 144–149 |
| OTel span attributes: `incident.id`, `incident.domain`, `agent.name` | ✅ Lines 152–154 |
| Backward-compat `_get_foundry_client()` (AgentsClient) preserved | ✅ Lines 34–55 |
| Backward-compat `create_foundry_thread()` alias preserved | ✅ Lines 172–184 |

Note: `AgentsClient` kept at module level for `chat.py`, `vm_chat.py`, `approvals.py`
compatibility — noted as intentional in SUMMARY.md technical decisions.

### 5. `scripts/register_agents.py` — PASSED

| Check | Result |
|---|---|
| File exists | ✅ `scripts/register_agents.py` |
| Imports all 9 `create_*_agent_version` functions | ✅ Lines 20–28 |
| `register_all_agents()` calls all 9 functions | ✅ Lines 47–68 |
| Domain agents registered before orchestrator | ✅ Orchestrator registered last (line 66) |
| Returns `dict[agent_name → AgentVersion]` | ✅ Line 33 |
| `__main__` block with `AZURE_PROJECT_ENDPOINT` guard | ✅ Lines 73–92 |

### 6. Terraform — GenAI Tracing + A2A Connections — PASSED

| Check | Result |
|---|---|
| `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true` on agent Container Apps | ✅ `main.tf` line 265, `for_each = contains(keys(local.agents), each.key)` |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` on agents | ✅ `main.tf` line 272 |
| `ORCHESTRATOR_AGENT_NAME=aap-orchestrator` on orchestrator + api-gateway | ✅ `main.tf` line 280 |
| 8 `azapi_resource` A2A connections (`RemoteA2A` category) | ✅ `main.tf` line 491 — single `for_each = local.a2a_domains` resource (8 iterations) |
| 8 domain endpoint variables in `variables.tf` | ✅ Lines 233–275: `compute_agent_endpoint`, `arc_agent_endpoint`, `eol_agent_endpoint`, `network_agent_endpoint`, `patch_agent_endpoint`, `security_agent_endpoint`, `sre_agent_endpoint`, `storage_agent_endpoint` |
| `foundry_project_id` variable | ✅ `variables.tf` line 41 |

Implementation note: Terraform uses `for_each = local.a2a_domains` (a map of domain→endpoint)
rather than 8 separate resources — functionally equivalent, more idiomatic Terraform.

### 7. Tests — 38 New Tests — PASSED

| Test File | Count | Result |
|---|---|---|
| `agents/tests/shared/test_telemetry.py` | 5 | ✅ All pass |
| `agents/tests/shared/test_agent_registration.py` | 10 | ✅ All pass |
| `agents/tests/shared/test_orchestrator_a2a.py` | 3 | ✅ All pass |
| `agents/tests/integration/test_phase29_smoke.py` | 9 | ✅ All pass |
| `scripts/tests/test_register_agents.py` | 3 | ✅ All pass |
| `services/api-gateway/tests/test_foundry_v2.py` | 5 | ✅ All pass |
| `services/api-gateway/tests/test_foundry_spans.py` | 3 | ✅ All pass |
| **Total** | **38** | **✅ 38/38** |

---

## Regression Check

Full suite (excluding `arc-mcp-server` and `detection-plane` which have pre-existing
`ImportPathMismatchError` collection errors unrelated to Phase 29):

```
1161 passed, 8 failed, 2 skipped
```

The 8 failures are all **pre-existing** (documented in SUMMARY.md):
- `agents/tests/eol/test_eol_agent.py` — 5 failures (eol agent stub tests)
- `agents/tests/patch/test_patch_agent.py` — 1 failure (patch tool count)
- `services/api-gateway/tests/test_approval_lifecycle.py` — 2 failures (approval lifecycle)

**Zero regressions introduced by Phase 29.**

---

## Gaps Found

None. All must-have checks pass.

### Minor Notes (non-blocking)

1. **`description` removed from `PromptAgentDefinition`**: SDK 2.0.1 doesn't accept a
   `description` kwarg — removed to match actual API. This is the correct behavior.
   
2. **Terraform uses `for_each` pattern**: Instead of 8 separate `azapi_resource` blocks,
   a single resource with `for_each = local.a2a_domains` achieves the same result with
   less repetition. This is more idiomatic Terraform, not a gap.

3. **`add_incident_span_attributes()` function**: The plan mentioned this as a named
   helper but the implementation inlines `span.set_attribute()` calls directly in
   `dispatch_to_orchestrator()`. The span attributes (`incident.id`, `incident.domain`,
   `agent.name`) are set correctly — no functional gap, just no standalone helper function.

---

## Verdict

**Status: PASSED**

Phase 29 fully delivers on its goal:
- All 9 agents are version-tracked via `PromptAgentDefinition` / `create_version()`
- Orchestrator topology is visible in Foundry portal via `A2APreviewTool` (8 domain connections)
- API gateway dispatches incidents via Responses API (`openai.responses.create()`)
- OTel traces with `incident.id`, `incident.domain`, `agent.name` span attributes
- Shared telemetry module wires `AIProjectInstrumentor` + App Insights
- Terraform enables GenAI tracing on all agent Container Apps
- 38 new tests, zero regressions
