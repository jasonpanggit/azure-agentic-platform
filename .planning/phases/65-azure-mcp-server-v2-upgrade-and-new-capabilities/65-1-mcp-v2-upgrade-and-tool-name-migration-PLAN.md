---
phase: 65
plan: 65-1
title: "MCP v2 Upgrade + Tool Name Migration (All Agents)"
wave: 1
depends_on: []
files_modified:
  - services/azure-mcp-server/Dockerfile
  - agents/sre/tools.py
  - agents/compute/tools.py
  - agents/network/tools.py
  - agents/storage/tools.py
  - agents/security/tools.py
  - agents/eol/tools.py
  - agents/patch/tools.py
  - agents/arc/tools.py
  - agents/sre/agent.py
  - agents/compute/agent.py
  - agents/network/agent.py
  - agents/storage/agent.py
  - agents/security/agent.py
  - agents/eol/agent.py
  - agents/patch/agent.py
  - agents/arc/agent.py
  - agents/tests/sre/test_sre_tools.py
  - agents/tests/compute/test_compute_tools.py
  - agents/tests/network/test_network_tools.py
  - agents/tests/patch/test_patch_tools.py
  - agents/tests/security/test_security_tools.py
  - agents/tests/eol/test_eol_tools.py
  - agents/tests/integration/test_mcp_tools.py
  - agents/tests/test_mcp_v2_migration.py
  - CLAUDE.md
autonomous: true
requirements: []
---

# Plan 65-1: MCP v2 Upgrade + Tool Name Migration (All Agents)

## Goal

Upgrade the Azure MCP Server from `2.0.0-beta.34` to `2.0.0` GA and migrate all 8 agent ALLOWED_MCP_TOOLS lists from v1 dotted names to v2 namespace names. This is a mandatory atomic change — the MCP server is shared infrastructure and all consumers must be updated simultaneously.

## Context

MCP v2 changed from granular dotted tool names (e.g., `monitor.query_logs`) to intent-based namespace tools (e.g., `monitor` with an `intent` parameter). The MCP `tools/list` response now returns 61 namespace-level tools instead of 131+ individual tools. All existing dotted tool names in ALLOWED_MCP_TOOLS are **invalid** in v2.

<threat_model>
## Threat Model

### Assets
- Azure MCP Server container (shared infrastructure for all agents)
- Agent ALLOWED_MCP_TOOLS allowlists (security boundary for tool access)
- CLAUDE.md (developer reference documentation)

### Threats
1. **MEDIUM: Overly permissive namespace allowlist** — v2 namespace names are broader than v1 dotted names (e.g., `monitor` grants access to all monitor subcommands vs. `monitor.query_logs` which was a single operation). Mitigation: This is an architectural change in the MCP server — the intent-based model is by design. Agents still only call tools through Foundry and the LLM, which constrains usage to the agent's system prompt instructions. No sensitive write operations are exposed through monitor/resourcehealth/advisor namespaces (all are read-only). Acceptable risk.

2. **LOW: Stale dotted names in system prompts** — If system prompts still reference `monitor.query_logs` after migration, the LLM may attempt to call non-existent tools. Mitigation: All system prompts updated in this plan; cross-agent validation test catches remaining references.

3. **LOW: Dockerfile version pinning** — Upgrading from beta.34 to 2.0.0 GA. Mitigation: Pin to exact version `2.0.0` (not `latest` or range). v3.0.0-beta.1 exists on npm — must NOT be used.

### Verdict: No HIGH/CRITICAL threats. Proceed.
</threat_model>

## Tasks

<task id="65-1-01">
<title>Update Dockerfile ARG to 2.0.0</title>
<read_first>
- services/azure-mcp-server/Dockerfile
</read_first>
<action>
In `services/azure-mcp-server/Dockerfile`, change line 13:
```
ARG AZURE_MCP_VERSION=2.0.0-beta.34
```
to:
```
ARG AZURE_MCP_VERSION=2.0.0
```
No other changes to the Dockerfile. The CMD, proxy.js, transport, and auth patterns are unchanged in v2.
</action>
<acceptance_criteria>
- `services/azure-mcp-server/Dockerfile` contains `ARG AZURE_MCP_VERSION=2.0.0`
- `services/azure-mcp-server/Dockerfile` does NOT contain the string `beta`
- `services/azure-mcp-server/Dockerfile` does NOT contain the string `3.0.0`
</acceptance_criteria>
</task>

<task id="65-1-02">
<title>Migrate SRE agent ALLOWED_MCP_TOOLS to v2 namespace names</title>
<read_first>
- agents/sre/tools.py
</read_first>
<action>
In `agents/sre/tools.py`, replace the ALLOWED_MCP_TOOLS list (lines 49-56) and the module docstring (lines 1-7):

Replace the module docstring:
```python
"""SRE Agent tool functions — cross-domain monitoring and remediation proposal wrappers.

Allowed MCP tools (explicit allowlist — v2 namespace names, no wildcards):
    monitor, applicationinsights, advisor, resourcehealth, containerapps
"""
```

Replace the ALLOWED_MCP_TOOLS list:
```python
# Explicit MCP tool allowlist — v2 namespace names (no dotted names, no wildcards).
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor",
    "applicationinsights",
    "advisor",
    "resourcehealth",
    "containerapps",
]
```

Note: `containerapps` is added here for the new self-monitoring capability (wired in Plan 65-2).

**CONTEXT.md override:** The `65-CONTEXT.md` decisions section originally said "advisor.list_recommendations already in ALLOWED_MCP_TOOLS — keep it". This is a stale v1 decision. Research during planning revealed that `advisor.list_recommendations` is a v1 dotted name that no longer exists in v2's intent-based tool name architecture. This plan correctly follows the research finding (Option A: update all agents to v2 namespace names) — `advisor.list_recommendations` is replaced by the namespace name `advisor`. The CONTEXT.md "keep" decision is overridden.
</action>
<acceptance_criteria>
- `agents/sre/tools.py` contains `ALLOWED_MCP_TOOLS` with exactly 5 entries: `"monitor"`, `"applicationinsights"`, `"advisor"`, `"resourcehealth"`, `"containerapps"`
- `agents/sre/tools.py` does NOT contain the string `monitor.query_logs`
- `agents/sre/tools.py` does NOT contain the string `monitor.query_metrics`
- `agents/sre/tools.py` does NOT contain the string `advisor.list_recommendations`
- `agents/sre/tools.py` does NOT contain the string `applicationinsights.query`
- `agents/sre/tools.py` does NOT contain the string `resourcehealth.get_availability_status` in the ALLOWED_MCP_TOOLS list (may still appear in system prompt references)
- No entry in ALLOWED_MCP_TOOLS contains a `.` character
</acceptance_criteria>
</task>

<task id="65-1-03">
<title>Migrate Compute agent ALLOWED_MCP_TOOLS to v2 namespace names</title>
<read_first>
- agents/compute/tools.py
</read_first>
<action>
In `agents/compute/tools.py`, replace the ALLOWED_MCP_TOOLS list (lines 142-152):

```python
# Explicit MCP tool allowlist — v2 namespace names (no dotted names, no wildcards).
ALLOWED_MCP_TOOLS: List[str] = [
    "compute",
    "monitor",
    "resourcehealth",
    "advisor",
    "appservice",
]
```

This collapses:
- `compute.list_vms`, `compute.get_vm`, `compute.list_disks` → `compute`
- `monitor.query_logs`, `monitor.query_metrics` → `monitor`
- `resourcehealth.get_availability_status` → `resourcehealth`
- `advisor.list_recommendations` → `advisor`
- `appservice.list_apps`, `appservice.get_app` → `appservice`

Also update the module docstring if it references specific dotted tool names — replace any dotted MCP tool names with namespace names.
</action>
<acceptance_criteria>
- `agents/compute/tools.py` `ALLOWED_MCP_TOOLS` list contains exactly 5 entries: `"compute"`, `"monitor"`, `"resourcehealth"`, `"advisor"`, `"appservice"`
- No entry in `agents/compute/tools.py` `ALLOWED_MCP_TOOLS` contains a `.` character
- `agents/compute/tools.py` does NOT contain `compute.list_vms` in ALLOWED_MCP_TOOLS
</acceptance_criteria>
</task>

<task id="65-1-04">
<title>Migrate Network agent ALLOWED_MCP_TOOLS to v2 namespace names</title>
<read_first>
- agents/network/tools.py
</read_first>
<action>
In `agents/network/tools.py`, replace the ALLOWED_MCP_TOOLS list (lines 50-56):

```python
# Explicit MCP tool allowlist — v2 namespace names (no dotted names, no wildcards).
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor",
    "resourcehealth",
    "advisor",
    "compute",
]
```

This collapses:
- `monitor.query_logs`, `monitor.query_metrics` → `monitor`
- `resourcehealth.get_availability_status` → `resourcehealth`
- `advisor.list_recommendations` → `advisor`
- `compute.list_vms` → `compute`

Also update the module docstring if it references specific dotted tool names.
</action>
<acceptance_criteria>
- `agents/network/tools.py` `ALLOWED_MCP_TOOLS` list contains exactly 4 entries: `"monitor"`, `"resourcehealth"`, `"advisor"`, `"compute"`
- No entry in `agents/network/tools.py` `ALLOWED_MCP_TOOLS` contains a `.` character
</acceptance_criteria>
</task>

<task id="65-1-05">
<title>Migrate Storage agent ALLOWED_MCP_TOOLS to v2 namespace names</title>
<read_first>
- agents/storage/tools.py
</read_first>
<action>
In `agents/storage/tools.py`, replace the ALLOWED_MCP_TOOLS list (lines 20-27):

```python
# Explicit MCP tool allowlist — v2 namespace names (no dotted names, no wildcards).
ALLOWED_MCP_TOOLS: List[str] = [
    "storage",
    "fileshares",
    "monitor",
    "resourcehealth",
]
```

This collapses:
- `storage.list_accounts`, `storage.get_account` → `storage`
- `fileshares.list` → `fileshares`
- `monitor.query_logs`, `monitor.query_metrics` → `monitor`
- `resourcehealth.get_availability_status` → `resourcehealth`
</action>
<acceptance_criteria>
- `agents/storage/tools.py` `ALLOWED_MCP_TOOLS` list contains exactly 4 entries: `"storage"`, `"fileshares"`, `"monitor"`, `"resourcehealth"`
- No entry in `agents/storage/tools.py` `ALLOWED_MCP_TOOLS` contains a `.` character
</acceptance_criteria>
</task>

<task id="65-1-06">
<title>Migrate Security agent ALLOWED_MCP_TOOLS to v2 namespace names</title>
<read_first>
- agents/security/tools.py
</read_first>
<action>
In `agents/security/tools.py`, replace the ALLOWED_MCP_TOOLS list (lines 63-71):

```python
# Explicit MCP tool allowlist — v2 namespace names (no dotted names, no wildcards).
ALLOWED_MCP_TOOLS: List[str] = [
    "keyvault",
    "role",
    "monitor",
    "resourcehealth",
    "advisor",
]
```

This collapses:
- `keyvault.list_vaults`, `keyvault.get_vault` → `keyvault`
- `role.list_assignments` → `role`
- `monitor.query_logs`, `monitor.query_metrics` → `monitor`
- `resourcehealth.get_availability_status` → `resourcehealth`
- `advisor.list_recommendations` → `advisor`
</action>
<acceptance_criteria>
- `agents/security/tools.py` `ALLOWED_MCP_TOOLS` list contains exactly 5 entries: `"keyvault"`, `"role"`, `"monitor"`, `"resourcehealth"`, `"advisor"`
- No entry in `agents/security/tools.py` `ALLOWED_MCP_TOOLS` contains a `.` character
</acceptance_criteria>
</task>

<task id="65-1-07">
<title>Migrate EOL agent ALLOWED_MCP_TOOLS to v2 namespace names</title>
<read_first>
- agents/eol/tools.py
</read_first>
<action>
In `agents/eol/tools.py`, replace the ALLOWED_MCP_TOOLS list (lines 71-75):

```python
# Explicit MCP tool allowlist — v2 namespace names (no dotted names, no wildcards).
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor",
    "resourcehealth",
]
```

This collapses:
- `monitor.query_logs`, `monitor.query_metrics` → `monitor`
- `resourcehealth.get_availability_status` → `resourcehealth`
</action>
<acceptance_criteria>
- `agents/eol/tools.py` `ALLOWED_MCP_TOOLS` list contains exactly 2 entries: `"monitor"`, `"resourcehealth"`
- No entry in `agents/eol/tools.py` `ALLOWED_MCP_TOOLS` contains a `.` character
</acceptance_criteria>
</task>

<task id="65-1-08">
<title>Migrate Patch agent ALLOWED_MCP_TOOLS to v2 namespace names</title>
<read_first>
- agents/patch/tools.py
</read_first>
<action>
In `agents/patch/tools.py`, replace the ALLOWED_MCP_TOOLS list (lines 64-68):

```python
# Explicit MCP tool allowlist — v2 namespace names (no dotted names, no wildcards).
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor",
    "resourcehealth",
]
```

This collapses:
- `monitor.query_logs`, `monitor.query_metrics` → `monitor`
- `resourcehealth.get_availability_status` → `resourcehealth`
</action>
<acceptance_criteria>
- `agents/patch/tools.py` `ALLOWED_MCP_TOOLS` list contains exactly 2 entries: `"monitor"`, `"resourcehealth"`
- No entry in `agents/patch/tools.py` `ALLOWED_MCP_TOOLS` contains a `.` character
</acceptance_criteria>
</task>

<task id="65-1-09">
<title>Migrate Arc agent ALLOWED_MCP_TOOLS Azure MCP entries to v2 namespace names</title>
<read_first>
- agents/arc/tools.py
</read_first>
<action>
In `agents/arc/tools.py`, replace the ALLOWED_MCP_TOOLS list (lines 67-82). The Arc MCP Server tool names (custom server, not Azure MCP) are unchanged. Only the Azure MCP Server dotted names change:

```python
# Explicit MCP tool allowlist — replaces the Phase 2 empty list (AGENT-005)
ALLOWED_MCP_TOOLS: List[str] = [
    # Arc MCP Server tools (Phase 3 — custom FastMCP server, names unchanged)
    "arc_servers_list",
    "arc_servers_get",
    "arc_extensions_list",
    "arc_k8s_list",
    "arc_k8s_get",
    "arc_k8s_gitops_status",
    "arc_data_sql_mi_list",
    "arc_data_sql_mi_get",
    "arc_data_postgresql_list",
    # Azure MCP Server tools — v2 namespace names
    "monitor",
    "resourcehealth",
]
```

Also update the module docstring (lines 10-15) to replace:
```
  Azure MCP Server tools: monitor.query_logs, monitor.query_metrics,
    resourcehealth.get_availability_status
```
with:
```
  Azure MCP Server tools (v2 namespace names): monitor, resourcehealth
```
</action>
<acceptance_criteria>
- `agents/arc/tools.py` `ALLOWED_MCP_TOOLS` list contains exactly 11 entries: 9 Arc MCP tools + `"monitor"` + `"resourcehealth"`
- `agents/arc/tools.py` does NOT contain `monitor.query_logs` in ALLOWED_MCP_TOOLS
- `agents/arc/tools.py` does NOT contain `monitor.query_metrics` in ALLOWED_MCP_TOOLS
- `agents/arc/tools.py` does NOT contain `resourcehealth.get_availability_status` in ALLOWED_MCP_TOOLS
- Arc MCP tool names (`arc_servers_list`, `arc_servers_get`, etc.) are unchanged
- No Azure MCP entry in ALLOWED_MCP_TOOLS contains a `.` character (Arc tools use `_` not `.`)
</acceptance_criteria>
</task>

<task id="65-1-10">
<title>Update SRE agent system prompt MCP tool references</title>
<read_first>
- agents/sre/agent.py
</read_first>
<action>
In `agents/sre/agent.py`, update the `SRE_AGENT_SYSTEM_PROMPT` string to replace v1 dotted MCP tool name references with v2 namespace names:

1. Line 65: Replace `Use \`monitor.query_logs\` to query the Activity Log` with `Use the \`monitor\` MCP tool to query the Activity Log`
2. Line 69: Replace `Use \`monitor.query_logs\` for cross-workspace KQL queries` with `Use the \`monitor\` MCP tool for cross-workspace KQL queries`
3. Line 73: Replace `Use \`resourcehealth.get_availability_status\`` with `Use the \`resourcehealth\` MCP tool`
4. Line 73: Replace `\`resourcehealth.list_events\` for Azure Service Health platform` with `for Azure Service Health platform`
5. Line 79: Replace `Also use \`advisor.list_recommendations\`\n   via MCP for additional coverage.` with `Also use the \`advisor\` MCP tool for additional coverage.`

The dynamically-generated allowed tools list at the bottom (line 124) already uses `ALLOWED_MCP_TOOLS` and will automatically reflect the new namespace names — no change needed there.
</action>
<acceptance_criteria>
- `agents/sre/agent.py` `SRE_AGENT_SYSTEM_PROMPT` does NOT contain `monitor.query_logs`
- `agents/sre/agent.py` `SRE_AGENT_SYSTEM_PROMPT` does NOT contain `resourcehealth.get_availability_status`
- `agents/sre/agent.py` `SRE_AGENT_SYSTEM_PROMPT` does NOT contain `resourcehealth.list_events`
- `agents/sre/agent.py` `SRE_AGENT_SYSTEM_PROMPT` does NOT contain `advisor.list_recommendations`
- `agents/sre/agent.py` `SRE_AGENT_SYSTEM_PROMPT` contains the string `monitor` MCP tool`
- `agents/sre/agent.py` `SRE_AGENT_SYSTEM_PROMPT` contains the string `resourcehealth` MCP tool`
</acceptance_criteria>
</task>

<task id="65-1-11">
<title>Update Compute, Network, Storage, Security, EOL, Patch, Arc agent system prompts</title>
<read_first>
- agents/compute/agent.py
- agents/network/agent.py
- agents/storage/agent.py
- agents/security/agent.py
- agents/eol/agent.py
- agents/patch/agent.py
- agents/arc/agent.py
</read_first>
<action>
In each of the 7 agent.py files, search the system prompt string for any v1 dotted MCP tool name references and replace with v2 namespace names. The pattern is the same across all agents:

- `monitor.query_logs` → `monitor` MCP tool (for log queries)
- `monitor.query_metrics` → `monitor` MCP tool (for metric queries)
- `resourcehealth.get_availability_status` → `resourcehealth` MCP tool
- `resourcehealth.list_events` → `resourcehealth` MCP tool (for service health events)
- `advisor.list_recommendations` → `advisor` MCP tool
- `compute.list_vms` → `compute` MCP tool
- `storage.list_accounts` / `storage.get_account` → `storage` MCP tool
- `fileshares.list` → `fileshares` MCP tool
- `keyvault.list_vaults` / `keyvault.get_vault` → `keyvault` MCP tool
- `role.list_assignments` → `role` MCP tool
- `appservice.list_apps` / `appservice.get_app` → `appservice` MCP tool
- `applicationinsights.query` → `applicationinsights` MCP tool

For the Arc agent (`agents/arc/agent.py`): only update Azure MCP tool name references. Arc MCP tool names (`arc_servers_list`, etc.) are UNCHANGED — they come from the custom Arc MCP Server, not the Azure MCP Server.

The dynamically-generated allowed tools section at the bottom of each prompt already uses `ALLOWED_MCP_TOOLS` and will automatically reflect the new namespace names.
</action>
<acceptance_criteria>
- None of these 7 files contain any of these v1 dotted strings in their system prompts: `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status`, `advisor.list_recommendations`, `compute.list_vms`, `storage.list_accounts`, `storage.get_account`, `fileshares.list`, `keyvault.list_vaults`, `keyvault.get_vault`, `role.list_assignments`, `appservice.list_apps`, `appservice.get_app`, `applicationinsights.query`
- Arc agent system prompt still references `arc_servers_list`, `arc_k8s_list`, etc. (custom Arc MCP names unchanged)
</acceptance_criteria>
</task>

<task id="65-1-12">
<title>Update SRE ALLOWED_MCP_TOOLS tests</title>
<read_first>
- agents/tests/sre/test_sre_tools.py
</read_first>
<action>
In `agents/tests/sre/test_sre_tools.py`, update the `TestAllowedMcpTools` class (lines 27-53):

```python
class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_mcp_tools_has_exactly_five_entries(self):
        from agents.sre.tools import ALLOWED_MCP_TOOLS

        assert len(ALLOWED_MCP_TOOLS) == 5

    def test_allowed_mcp_tools_contains_expected_entries(self):
        from agents.sre.tools import ALLOWED_MCP_TOOLS

        expected = [
            "monitor",
            "applicationinsights",
            "advisor",
            "resourcehealth",
            "containerapps",
        ]
        for tool in expected:
            assert tool in ALLOWED_MCP_TOOLS, f"Missing: {tool}"

    def test_allowed_mcp_tools_no_wildcards(self):
        from agents.sre.tools import ALLOWED_MCP_TOOLS

        for tool in ALLOWED_MCP_TOOLS:
            assert "*" not in tool, f"Wildcard found in tool: {tool}"

    def test_allowed_mcp_tools_no_dotted_names(self):
        """v2 uses namespace names, not dotted names."""
        from agents.sre.tools import ALLOWED_MCP_TOOLS

        for tool in ALLOWED_MCP_TOOLS:
            assert "." not in tool, (
                f"Dotted tool name '{tool}' found — must use v2 namespace name"
            )
```
</action>
<acceptance_criteria>
- `agents/tests/sre/test_sre_tools.py` has `test_allowed_mcp_tools_has_exactly_five_entries` asserting `len(ALLOWED_MCP_TOOLS) == 5`
- `agents/tests/sre/test_sre_tools.py` expected list contains `"monitor"`, `"applicationinsights"`, `"advisor"`, `"resourcehealth"`, `"containerapps"`
- `agents/tests/sre/test_sre_tools.py` has `test_allowed_mcp_tools_no_dotted_names` test
- `agents/tests/sre/test_sre_tools.py` does NOT contain `monitor.query_logs` in expected entries
- `pytest agents/tests/sre/test_sre_tools.py::TestAllowedMcpTools -v` exits 0
</acceptance_criteria>
</task>

<task id="65-1-13">
<title>Update Compute, Network, Patch, Security, EOL ALLOWED_MCP_TOOLS tests</title>
<read_first>
- agents/tests/compute/test_compute_tools.py
- agents/tests/network/test_network_tools.py
- agents/tests/patch/test_patch_tools.py
- agents/tests/security/test_security_tools.py
- agents/tests/eol/test_eol_tools.py
</read_first>
<action>
Update the `TestAllowedMcpTools` class in each test file. Replace dotted name assertions with v2 namespace name assertions. Add a `test_allowed_mcp_tools_no_dotted_names` test to each.

**Note:** Read `agents/tests/network/test_network_tools.py` first to verify the actual test method name before renaming. The plan assumes `test_allowed_mcp_tools_has_exactly_five_entries` exists — confirm the exact name from the file before editing.

**Compute** (`agents/tests/compute/test_compute_tools.py`):
- `test_allowed_tools_contains_expected_entries`: assert `"compute"`, `"monitor"`, `"resourcehealth"` (replace `compute.list_vms`, `monitor.query_logs`, `resourcehealth.get_availability_status`)
- Add `test_allowed_mcp_tools_no_dotted_names`

**Network** (`agents/tests/network/test_network_tools.py`):
- `test_allowed_mcp_tools_has_exactly_five_entries` → rename to `test_allowed_mcp_tools_has_exactly_four_entries` with `assert len(ALLOWED_MCP_TOOLS) == 4`
- Expected entries: `"monitor"`, `"resourcehealth"`, `"advisor"`, `"compute"`
- Add `test_allowed_mcp_tools_no_dotted_names`

**Patch** (`agents/tests/patch/test_patch_tools.py`):
- `test_allowed_mcp_tools_has_exactly_three_entries` → rename to `test_allowed_mcp_tools_has_exactly_two_entries` with `assert len(ALLOWED_MCP_TOOLS) == 2`
- Expected entries: `"monitor"`, `"resourcehealth"`
- Add `test_allowed_mcp_tools_no_dotted_names`

**Security** (`agents/tests/security/test_security_tools.py`):
- `test_allowed_mcp_tools_has_exactly_seven_entries` → rename to `test_allowed_mcp_tools_has_exactly_five_entries` with `assert len(ALLOWED_MCP_TOOLS) == 5`
- Expected entries: `"keyvault"`, `"role"`, `"monitor"`, `"resourcehealth"`, `"advisor"`
- Add `test_allowed_mcp_tools_no_dotted_names`

**EOL** (`agents/tests/eol/test_eol_tools.py`):
- `test_allowed_tools_contains_monitor_query_logs`: rename to `test_allowed_tools_contains_monitor` and assert `"monitor" in ALLOWED_MCP_TOOLS`
- Add `test_allowed_mcp_tools_no_dotted_names`
</action>
<acceptance_criteria>
- `agents/tests/compute/test_compute_tools.py` expected entries include `"compute"`, `"monitor"`, `"resourcehealth"` (not dotted names)
- `agents/tests/network/test_network_tools.py` asserts `len(ALLOWED_MCP_TOOLS) == 4`
- `agents/tests/patch/test_patch_tools.py` asserts `len(ALLOWED_MCP_TOOLS) == 2`
- `agents/tests/security/test_security_tools.py` asserts `len(ALLOWED_MCP_TOOLS) == 5`
- `agents/tests/eol/test_eol_tools.py` asserts `"monitor" in ALLOWED_MCP_TOOLS` (not `monitor.query_logs`)
- All 5 test files contain `test_allowed_mcp_tools_no_dotted_names` or equivalent
- None of the 5 test files contain any dotted MCP tool name string (e.g., `monitor.query_logs`, `compute.list_vms`, etc.) in expected entries
</acceptance_criteria>
</task>

<task id="65-1-14">
<title>Update integration test MCP tool assertions</title>
<read_first>
- agents/tests/integration/test_mcp_tools.py
</read_first>
<action>
In `agents/tests/integration/test_mcp_tools.py`, update all ALLOWED_MCP_TOOLS assertion strings from dotted names to v2 namespace names:

- Line 27: `assert "compute.list_vms" in ALLOWED_MCP_TOOLS` → `assert "compute" in ALLOWED_MCP_TOOLS`
- Line 30: `assert "monitor.query_logs" in ALLOWED_MCP_TOOLS` → `assert "monitor" in ALLOWED_MCP_TOOLS`
- Line 33: `assert "resourcehealth.get_availability_status" in ALLOWED_MCP_TOOLS` → `assert "resourcehealth" in ALLOWED_MCP_TOOLS`
- Line 52: `assert "storage.list_accounts" in store_tools` → `assert "storage" in store_tools`
- Line 58: `assert "keyvault.list_vaults" in sec_tools` → `assert "keyvault" in sec_tools`
- Line 64: `assert "monitor.query_logs" in sre_tools` → `assert "monitor" in sre_tools`

**Important:** Only update dotted names used in ALLOWED_MCP_TOOLS assertion strings. The `TestOtelSpanRecording` class uses `compute.list_vms` as a `tool_name` parameter value for OTel span tests — those are NOT allowlist entries and must be **preserved as-is**. They test OTel span recording with an example tool name string, not the ALLOWED_MCP_TOOLS list.

Add a new test:
```python
def test_no_dotted_names_across_all_agents(self):
    """v2 MCP uses namespace names, not dotted names."""
    from agents.compute.tools import ALLOWED_MCP_TOOLS as compute_tools
    from agents.network.tools import ALLOWED_MCP_TOOLS as net_tools
    from agents.storage.tools import ALLOWED_MCP_TOOLS as store_tools
    from agents.security.tools import ALLOWED_MCP_TOOLS as sec_tools
    from agents.sre.tools import ALLOWED_MCP_TOOLS as sre_tools
    from agents.eol.tools import ALLOWED_MCP_TOOLS as eol_tools
    from agents.patch.tools import ALLOWED_MCP_TOOLS as patch_tools
    from agents.arc.tools import ALLOWED_MCP_TOOLS as arc_tools

    all_lists = {
        "compute": compute_tools,
        "network": net_tools,
        "storage": store_tools,
        "security": sec_tools,
        "sre": sre_tools,
        "eol": eol_tools,
        "patch": patch_tools,
        "arc": arc_tools,
    }
    for agent_name, tools in all_lists.items():
        for tool in tools:
            # Arc MCP tools use underscores (arc_servers_list) — not dotted
            assert "." not in tool, (
                f"{agent_name}: dotted tool name '{tool}' — "
                f"must use v2 namespace name"
            )
```
</action>
<acceptance_criteria>
- `agents/tests/integration/test_mcp_tools.py` does NOT contain `compute.list_vms`, `monitor.query_logs`, `resourcehealth.get_availability_status`, `storage.list_accounts`, `keyvault.list_vaults` in **ALLOWED_MCP_TOOLS assertion strings** (i.e., lines asserting `"xxx" in ALLOWED_MCP_TOOLS` or `"xxx" in *_tools`)
- `agents/tests/integration/test_mcp_tools.py` `TestOtelSpanRecording` references to `compute.list_vms` as span `tool_name` argument values are intentionally **preserved** — these are OTel test fixtures, not allowlist entries
- `agents/tests/integration/test_mcp_tools.py` contains `test_no_dotted_names_across_all_agents` method
</acceptance_criteria>
</task>

<task id="65-1-15">
<title>Create cross-agent MCP v2 migration validation test</title>
<read_first>
- agents/tests/integration/test_mcp_tools.py (for pattern reference)
</read_first>
<action>
Create `agents/tests/test_mcp_v2_migration.py` with the following tests.

**Path anchoring:** Use `Path(__file__).parents[2]` to resolve repo-root-relative file paths. This makes tests CI-safe regardless of working directory. The test file lives at `agents/tests/test_mcp_v2_migration.py`, so `Path(__file__).parents[2]` resolves to the repo root.

```python
"""Cross-agent validation tests for MCP v2 tool name migration.

Ensures all agents use v2 namespace names and no v1 dotted names remain
in ALLOWED_MCP_TOOLS lists or system prompts.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

# Repo root — resolved from this file's location (agents/tests/test_mcp_v2_migration.py)
_REPO_ROOT = Path(__file__).parents[2]

# v1 dotted tool names that must NOT appear anywhere
V1_DOTTED_NAMES = [
    "monitor.query_logs",
    "monitor.query_metrics",
    "advisor.list_recommendations",
    "resourcehealth.get_availability_status",
    "resourcehealth.list_events",
    "applicationinsights.query",
    "storage.list_accounts",
    "storage.get_account",
    "compute.list_vms",
    "compute.get_vm",
    "compute.list_disks",
    "keyvault.list_vaults",
    "keyvault.get_vault",
    "role.list_assignments",
    "fileshares.list",
    "appservice.list_apps",
    "appservice.get_app",
]

AGENT_TOOLS_MODULES = [
    "agents.sre.tools",
    "agents.compute.tools",
    "agents.network.tools",
    "agents.storage.tools",
    "agents.security.tools",
    "agents.eol.tools",
    "agents.patch.tools",
    "agents.arc.tools",
]


class TestMcpV2Migration:
    """Verify all agents have migrated to v2 namespace tool names."""

    @pytest.mark.parametrize("mod_path", AGENT_TOOLS_MODULES)
    def test_no_dotted_mcp_tool_names(self, mod_path: str):
        """ALLOWED_MCP_TOOLS must not contain v1 dotted names."""
        mod = importlib.import_module(mod_path)
        tools = getattr(mod, "ALLOWED_MCP_TOOLS")
        for tool in tools:
            assert "." not in tool, (
                f"{mod_path}: dotted tool name '{tool}' found — "
                f"must use v2 namespace name (e.g., 'monitor' not 'monitor.query_logs')"
            )

    def test_dockerfile_mcp_version(self):
        """Dockerfile must pin to 2.0.0 (not beta, not 3.x)."""
        dockerfile = _REPO_ROOT / "services/azure-mcp-server/Dockerfile"
        content = dockerfile.read_text()
        assert "ARG AZURE_MCP_VERSION=2.0.0" in content
        version_line = [
            l for l in content.splitlines()
            if "AZURE_MCP_VERSION=" in l
        ][0]
        assert "beta" not in version_line
        assert "3.0.0" not in version_line

    def test_claude_md_references_new_repo(self):
        """CLAUDE.md must reference microsoft/mcp repo."""
        claude_md = _REPO_ROOT / "CLAUDE.md"
        content = claude_md.read_text()
        assert "microsoft/mcp" in content
```
</action>
<acceptance_criteria>
- `agents/tests/test_mcp_v2_migration.py` exists
- `agents/tests/test_mcp_v2_migration.py` contains `class TestMcpV2Migration`
- `agents/tests/test_mcp_v2_migration.py` contains `test_no_dotted_mcp_tool_names` parametrized across 8 agent modules
- `agents/tests/test_mcp_v2_migration.py` contains `test_dockerfile_mcp_version`
- `agents/tests/test_mcp_v2_migration.py` contains `test_claude_md_references_new_repo`
- `agents/tests/test_mcp_v2_migration.py` imports `Path` from `pathlib` and uses `Path(__file__).parents[2]` for repo-root anchoring
- `pytest agents/tests/test_mcp_v2_migration.py -v` exits 0
</acceptance_criteria>
</task>

<task id="65-1-16">
<title>Update CLAUDE.md Azure MCP Server section</title>
<read_first>
- CLAUDE.md
</read_first>
<action>
In `CLAUDE.md`, update the Azure MCP Server sections:

1. In the "Azure MCP Server (GA)" table:
   - **Package**: Change `@azure/mcp` description to note it's from `microsoft/mcp` repo
   - Add note: `Repository moved from Azure/azure-mcp (archived) to microsoft/mcp`
   - **Distribution**: Update to note platform-specific native binaries in v2
   - Add a note about v2 intent-based tool architecture: "v2 uses namespace-level intent tools (e.g., `monitor` with `intent` parameter) instead of v1 dotted names (e.g., `monitor.query_logs`)"

2. In the "Covered Services" table:
   - Add row: `| Container Apps | \`containerapps\` (list) |`
   - Add row: `| Azure Policy | \`policy\` |`

3. In the Summary table:
   - Update Azure MCP Server row: version to `2.0.0`

4. In the "MCP Surfaces" section under Architecture:
   - Add note about v2 namespace-level tool architecture

5. Do NOT change the package name — it remains `@azure/mcp` on npm.
</action>
<acceptance_criteria>
- `CLAUDE.md` contains the string `microsoft/mcp`
- `CLAUDE.md` contains the string `2.0.0` in reference to Azure MCP Server version
- `CLAUDE.md` contains `containerapps` in the covered services section
- `CLAUDE.md` contains reference to intent-based or namespace-level tools
- `CLAUDE.md` does NOT reference `2.0.0-beta` as the current version
</acceptance_criteria>
</task>

<task id="65-1-17">
<title>Run full agent test suite and verify zero regressions</title>
<read_first>
- agents/tests/test_mcp_v2_migration.py (newly created)
</read_first>
<action>
Run the complete agent test suite to verify all changes are correct:

```bash
# Cross-agent migration validation
pytest agents/tests/test_mcp_v2_migration.py -v

# Per-agent MCP tool tests
pytest agents/tests/sre/test_sre_tools.py::TestAllowedMcpTools -v
pytest agents/tests/compute/test_compute_tools.py::TestAllowedMcpTools -v
pytest agents/tests/network/test_network_tools.py::TestAllowedMcpTools -v
pytest agents/tests/patch/test_patch_tools.py::TestAllowedMcpTools -v
pytest agents/tests/security/test_security_tools.py::TestAllowedMcpTools -v
pytest agents/tests/eol/test_eol_tools.py::TestAllowedMcpTools -v

# Integration tests
pytest agents/tests/integration/test_mcp_tools.py -v

# Full suite (ensure no regressions)
pytest agents/tests/ -v --timeout=120
```

Fix any failures before marking complete.
</action>
<acceptance_criteria>
- `pytest agents/tests/test_mcp_v2_migration.py -v` exits 0
- `pytest agents/tests/sre/test_sre_tools.py -v` exits 0
- `pytest agents/tests/compute/test_compute_tools.py -v` exits 0
- `pytest agents/tests/network/test_network_tools.py -v` exits 0
- `pytest agents/tests/patch/test_patch_tools.py -v` exits 0
- `pytest agents/tests/security/test_security_tools.py -v` exits 0
- `pytest agents/tests/eol/test_eol_tools.py -v` exits 0
- `pytest agents/tests/integration/test_mcp_tools.py -v` exits 0
- `pytest agents/tests/ --timeout=120` exits 0 with zero failures
</acceptance_criteria>
</task>

## Verification

```bash
# 1. Dockerfile version is correct
grep -q "ARG AZURE_MCP_VERSION=2.0.0" services/azure-mcp-server/Dockerfile && echo "PASS: Dockerfile" || echo "FAIL: Dockerfile"
grep -c "beta" services/azure-mcp-server/Dockerfile | grep -q "^0$" && echo "PASS: No beta" || echo "FAIL: Beta found"

# 2. No dotted MCP tool names in any ALLOWED_MCP_TOOLS list
for f in agents/sre/tools.py agents/compute/tools.py agents/network/tools.py agents/storage/tools.py agents/security/tools.py agents/eol/tools.py agents/patch/tools.py agents/arc/tools.py; do
  python3 -c "
import ast, sys
with open('$f') as fh:
    tree = ast.parse(fh.read())
for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == 'ALLOWED_MCP_TOOLS':
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and '.' in elt.value:
                        print(f'FAIL: {\"$f\"}: dotted name {elt.value}')
                        sys.exit(1)
print(f'PASS: $f')
"
done

# 3. CLAUDE.md references updated
grep -q "microsoft/mcp" CLAUDE.md && echo "PASS: CLAUDE.md repo" || echo "FAIL: CLAUDE.md repo"

# 4. Full test suite
pytest agents/tests/ --timeout=120 -q
```

## must_haves
- [ ] Dockerfile pins to `AZURE_MCP_VERSION=2.0.0` (not beta, not 3.x)
- [ ] All 8 agent ALLOWED_MCP_TOOLS lists use v2 namespace names (no dots in Azure MCP entries)
- [ ] All 8 agent system prompts reference v2 namespace names (no v1 dotted names)
- [ ] SRE ALLOWED_MCP_TOOLS includes `containerapps` (for Plan 65-2)
- [ ] All existing MCP tool tests updated with v2 names and pass
- [ ] Cross-agent migration validation test exists and passes
- [ ] CLAUDE.md references `microsoft/mcp` repo and v2.0.0
- [ ] Full agent test suite passes with zero regressions
