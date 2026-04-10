# Phase 20: Network & Security Agent Depth — Research

**Date:** 2026-04-10
**Phase:** 20-network-security-agent-depth
**Requirement:** PROD-003 — All 8 domain agent MCP tool groups registered in Foundry; each exercises domain tools in integration test

---

## 1. Current State Assessment

### 1.1 Network Agent (`agents/network/tools.py`)
- **Lines:** 207
- **Tools:** 4 stubs — `query_nsg_rules`, `query_load_balancer_health`, `query_vnet_topology`, `query_peering_status`
- **All are empty shells** — they return hardcoded empty dicts with `query_status: "success"` but make zero Azure SDK calls
- **MCP allowlist:** `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status`, `advisor.list_recommendations`
- **SDK in requirements.txt:** `azure-mgmt-network>=27.0.0` (already present)
- **No unit tests** — no `agents/tests/network/` directory exists

### 1.2 Security Agent (`agents/security/tools.py`)
- **Lines:** 166
- **Tools:** 3 stubs — `query_defender_alerts`, `query_keyvault_diagnostics`, `query_iam_changes`
- **All are empty shells** — same pattern as Network
- **MCP allowlist:** `keyvault.list_vaults`, `keyvault.get_vault`, `role.list_assignments`, `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status`
- **SDK in requirements.txt:** Empty (no additional requirements beyond base image)
- **No unit tests** — no `agents/tests/security/` directory exists

### 1.3 SRE Agent (`agents/sre/tools.py`)
- **Lines:** 183
- **Tools:** 3 — `query_availability_metrics` (stub), `query_performance_baselines` (stub), `propose_remediation` (functionally complete — no SDK needed, pure logic)
- **MCP allowlist:** `monitor.query_logs`, `monitor.query_metrics`, `applicationinsights.query`, `advisor.list_recommendations`, `resourcehealth.get_availability_status`, `resourcehealth.list_events`
- **SDK in requirements.txt:** Empty (no additional requirements beyond base image)
- **No unit tests** — no `agents/tests/sre/` directory exists

### 1.4 Reference Implementations (what "done" looks like)
- **Compute agent** (`agents/compute/tools.py`): 686 lines, 5 fully implemented tools with real SDK calls
- **Patch agent** (`agents/patch/tools.py`): 870+ lines, 7+ tools with ARG + Log Analytics + MSRC
- **Test pattern** (`agents/tests/patch/test_patch_tools.py`): 982 lines, mocks at SDK client level, covers success + error + pagination + edge cases

### 1.5 Existing Test Infrastructure
```
agents/tests/
  __init__.py
  compute/       (compute agent tools tests)
  eol/           (eol agent tools tests)
  integration/   (triage workflow integration tests — test_triage.py)
  patch/         (patch agent tools tests)
  shared/        (shared module tests)
```
Missing: `agents/tests/network/`, `agents/tests/security/`, `agents/tests/sre/`

---

## 2. Azure SDK Analysis — What Each Tool Needs

### 2.1 Network Agent — 6 Tools Total

#### Existing stubs to fill (3):

| Tool | SDK Package | Client/Method | Notes |
|------|------------|---------------|-------|
| `query_nsg_rules` | `azure-mgmt-network` | `NetworkManagementClient.network_security_groups.get(rg, nsg_name)` | Returns `.security_rules` (custom) + `.default_rules` (platform). Already in requirements. |
| `query_vnet_topology` | `azure-mgmt-network` | `NetworkManagementClient.virtual_networks.get(rg, vnet_name)` | Returns `.address_space.address_prefixes`, `.subnets`, `.virtual_network_peerings`. |
| `query_load_balancer_health` | `azure-mgmt-network` | `NetworkManagementClient.load_balancers.get(rg, lb_name, expand="frontendIPConfigurations/inboundNatRules/backendAddressPools/loadBalancingRules/probes")` | Extract health probes from `.probes`, backends from `.backend_address_pools`. |

#### New tools to add (3):

| Tool | SDK Package | Client/Method | Notes |
|------|------------|---------------|-------|
| `query_flow_logs` | `azure-mgmt-network` | `NetworkManagementClient.flow_logs.list(rg, network_watcher_name)` or Log Analytics KQL against `AzureNetworkAnalytics_CL` / `NSGFlowLogs` | Flow log config via SDK; actual flow data via Log Analytics. Consider hybrid: list configs via SDK, query data via KQL. |
| `query_expressroute_health` | `azure-mgmt-network` | `NetworkManagementClient.express_route_circuits.get(rg, circuit_name)` | Returns `.service_provider_provisioning_state`, `.circuit_provisioning_state`, `.peerings` (BGP state). |
| `check_connectivity` | `azure-mgmt-network` | `NetworkManagementClient.network_watchers.begin_check_connectivity(rg, nw_name, params)` | Long-running operation (LRO). Params: source VM, destination (address/port). Returns hops, latency, connection status. Need to handle `.result()` with timeout. |

**SDK requirement:** `azure-mgmt-network>=27.0.0` — **already in requirements.txt**, no change needed.

**Subscription ID needed:** All Network SDK calls require subscription_id for `NetworkManagementClient(credential, sub_id)`. Tools need a `subscription_id` parameter (extract from resource_id like compute agent does, or accept as explicit param).

#### `query_peering_status` Disposition
The 20-CONTEXT.md says 4 existing tools but roadmap targets 6 total. `query_peering_status` is the 4th existing stub. It overlaps with `query_vnet_topology` (which returns peerings too). **Options:**
1. Keep `query_peering_status` as a focused peering-only tool (more granular than topology) — fills it with real SDK
2. Merge into `query_vnet_topology`

**Recommendation:** Keep both. `query_peering_status` adds peering state detail (Connected/Disconnected/Initiated) that topology doesn't focus on. Total = 4 existing + 3 new = 7, but CONTEXT says 6. This means one of the "new 3" was already counted. Re-reading CONTEXT: "3 existing tools completed + 3 new tools = 6 fully implemented". The 4th tool (`query_peering_status`) is an extra beyond the roadmap — keep it, just fill it. **Final count: 7 tools** (exceeds roadmap target of 6).

### 2.2 Security Agent — 7 Tools Total

#### Existing stubs to fill (3):

| Tool | SDK Package | Client/Method | Notes |
|------|------------|---------------|-------|
| `query_defender_alerts` | `azure-mgmt-security` | `SecurityCenter.alerts.list()` or `.list_subscription_level_by_region(asc_location)` | Needs `asc_location` param (e.g., "centralus"). Filter by severity in-code. |
| `query_keyvault_diagnostics` | `azure-monitor-query` | `LogsQueryClient.query_workspace()` with KQL against `AzureDiagnostics` where `ResourceProvider == "MICROSOFT.KEYVAULT"` | Control-plane audit logs only. Needs workspace_id. |
| `query_iam_changes` | `azure-mgmt-monitor` | `MonitorManagementClient.activity_logs.list(filter=...)` | Filter for RBAC operations: `Microsoft.Authorization/roleAssignments/write`, etc. Same pattern as compute `query_activity_log`. |

#### New tools to add (4):

| Tool | SDK Package | Client/Method | Notes |
|------|------------|---------------|-------|
| `query_secure_score` | `azure-mgmt-security` | `SecurityCenter.secure_scores.get(secure_score_name="ascScore")` | Returns current score, max score, percentage. Simple GET. |
| `query_rbac_assignments` | `azure-mgmt-authorization` | `AuthorizationManagementClient.role_assignments.list_for_subscription()` or `.list_for_scope(scope)` | Filter by principal, scope. Package: `azure-mgmt-authorization>=4.0.0`. |
| `query_policy_compliance` | `azure-mgmt-policyinsights` | `PolicyInsightsClient.policy_states.list_query_results_for_subscription(policy_states_resource="latest")` | Filter by compliance state. Package: `azure-mgmt-policyinsights`. |
| `scan_public_endpoints` | `azure-mgmt-network` | `NetworkManagementClient.public_ip_addresses.list_all()` | List all public IPs + check for exposed NSG rules. Also consider `NetworkManagementClient.network_interfaces.list_all()` to find NICs with public IPs. Alternatively use ARG query for efficiency. |

**New SDK requirements for security agent:**
```
azure-mgmt-security>=5.0.0
azure-mgmt-authorization>=4.0.0
azure-mgmt-policyinsights>=1.0.0
azure-mgmt-monitor>=6.0.0
azure-monitor-query>=1.3.0
azure-mgmt-network>=27.0.0  # for scan_public_endpoints
```

**Total: 3 existing + 4 new = 7 tools** (exceeds roadmap's "6" for security).

### 2.3 SRE Agent — 7 Tools Total

#### Existing stubs to fill (2 — propose_remediation is already functional):

| Tool | SDK Package | Client/Method | Notes |
|------|------------|---------------|-------|
| `query_availability_metrics` | `azure-mgmt-monitor` | `MonitorManagementClient.metrics.list(resource_uri, metricnames="Availability", timespan, interval, aggregation)` | Same pattern as compute `query_monitor_metrics` but focused on availability. |
| `query_performance_baselines` | `azure-mgmt-monitor` | `MonitorManagementClient.metrics.list(...)` | Query metrics over baseline_period, compute stats (avg, p95, p99) in-code from time-series data. |

#### New tools to add (4):

| Tool | SDK Package | Client/Method | Notes |
|------|------------|---------------|-------|
| `query_service_health` | `azure-mgmt-resourcehealth` | `ResourceHealthMgmtClient.events.list_by_subscription_id()` | Lists Azure Service Health events (outages, maintenance, advisories). Filter by event_type and time range. |
| `query_advisor_recommendations` | `azure-mgmt-advisor` | `AdvisorManagementClient.recommendations.list()` | Subscription-wide advisor recommendations. Filter by category (HighAvailability, Security, Performance, Cost). |
| `query_change_analysis` | `azure-mgmt-changeanalysis` | `AzureChangeAnalysisManagementClient.changes.list_changes_by_resource_group(rg, start_time, end_time)` or `.list_changes_by_subscription(start_time, end_time)` | Lists detected changes. Start/end times as datetime objects. |
| `correlate_cross_domain` | Multiple / In-memory | Calls `query_service_health`, `query_advisor_recommendations`, and Monitor metrics to build a unified correlation view | **Not a direct SDK call** — this is a composite tool that aggregates signals from other SRE tools + Azure Monitor. Should use Monitor data to avoid circular agent deps (per CONTEXT D-04). |

**New SDK requirements for SRE agent:**
```
azure-mgmt-monitor>=6.0.0
azure-mgmt-resourcehealth==1.0.0b6
azure-mgmt-advisor>=9.0.0
azure-mgmt-changeanalysis>=1.0.0
```

**Total: 3 existing + 4 new = 7 tools** (exceeds roadmap's "4 new SRE tools").

---

## 3. SDK API Patterns — Critical Details

### 3.1 NetworkManagementClient Patterns

```python
from azure.mgmt.network import NetworkManagementClient
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
client = NetworkManagementClient(credential, subscription_id)

# NSG rules
nsg = client.network_security_groups.get(resource_group, nsg_name)
nsg.security_rules       # List of SecurityRule objects
nsg.default_security_rules  # List of default SecurityRule objects

# VNet + peerings
vnet = client.virtual_networks.get(resource_group, vnet_name)
vnet.address_space.address_prefixes  # List[str]
vnet.subnets                         # List of Subnet objects
vnet.virtual_network_peerings        # List of VirtualNetworkPeering objects

# Load balancer
lb = client.load_balancers.get(resource_group, lb_name)
lb.probes                    # Health probes
lb.backend_address_pools     # Backend pools
lb.load_balancing_rules      # LB rules
lb.frontend_ip_configurations

# ExpressRoute circuit
circuit = client.express_route_circuits.get(resource_group, circuit_name)
circuit.service_provider_provisioning_state  # "Provisioned"/"NotProvisioned"/"Deprovisioning"
circuit.circuit_provisioning_state           # "Enabled"/"Disabled"
circuit.peerings                             # BGP peering details

# Network Watcher connectivity check (LRO)
from azure.mgmt.network.models import (
    ConnectivityParameters,
    ConnectivitySource,
    ConnectivityDestination,
)
params = ConnectivityParameters(
    source=ConnectivitySource(resource_id=source_vm_id),
    destination=ConnectivityDestination(address=dest_address, port=dest_port),
)
poller = client.network_watchers.begin_check_connectivity(
    resource_group_name=nw_resource_group,
    network_watcher_name=network_watcher_name,
    parameters=params,
)
result = poller.result(timeout=120)  # ConnectivityInformation
result.connection_status  # "Reachable"/"Unreachable"
result.avg_latency_in_ms
result.hops               # List of ConnectivityHop
```

### 3.2 SecurityCenter Patterns

```python
from azure.mgmt.security import SecurityCenter

# SecurityCenter needs asc_location — typically "centralus" or based on subscription
client = SecurityCenter(credential, subscription_id, asc_location="centralus")

# Defender alerts
alerts = client.alerts.list()
for alert in alerts:
    alert.alert_display_name
    alert.severity          # "High"/"Medium"/"Low"/"Informational"
    alert.status            # "Active"/"Resolved"/"Dismissed"
    alert.description
    alert.compromised_entity
    alert.time_generated_utc

# Secure score
score = client.secure_scores.get(secure_score_name="ascScore")
score.current_score    # float
score.max_score        # int
score.percentage       # float 0.0-1.0
score.weight           # int
```

### 3.3 AuthorizationManagementClient Patterns

```python
from azure.mgmt.authorization import AuthorizationManagementClient

client = AuthorizationManagementClient(credential, subscription_id)

# List role assignments
assignments = client.role_assignments.list_for_subscription()
for ra in assignments:
    ra.principal_id
    ra.role_definition_id
    ra.scope
    ra.principal_type      # "User"/"ServicePrincipal"/"Group"
    ra.created_on
    ra.updated_on

# Filter by scope
scoped = client.role_assignments.list_for_scope(scope=resource_id)
```

### 3.4 PolicyInsightsClient Patterns

```python
from azure.mgmt.policyinsights import PolicyInsightsClient

client = PolicyInsightsClient(credential, subscription_id)

# List non-compliant policy states
states = client.policy_states.list_query_results_for_subscription(
    policy_states_resource="latest",
    query_options=QueryOptions(filter="complianceState eq 'NonCompliant'"),
)
for state in states:
    state.resource_id
    state.policy_assignment_id
    state.policy_definition_id
    state.compliance_state
    state.resource_type
```

### 3.5 AdvisorManagementClient Patterns

```python
from azure.mgmt.advisor import AdvisorManagementClient

client = AdvisorManagementClient(credential, subscription_id)

# List recommendations
recs = client.recommendations.list()
for rec in recs:
    rec.category           # "HighAvailability"/"Security"/"Performance"/"Cost"/"OperationalExcellence"
    rec.impact             # "High"/"Medium"/"Low"
    rec.impacted_field
    rec.impacted_value
    rec.short_description.problem
    rec.short_description.solution
    rec.resource_metadata
```

### 3.6 ResourceHealth Events Patterns

```python
from azure.mgmt.resourcehealth import ResourceHealthMgmtClient

client = ResourceHealthMgmtClient(credential, subscription_id)

# Service Health events
events = client.events.list_by_subscription_id()
for event in events:
    event.event_type         # "ServiceIssue"/"PlannedMaintenance"/"HealthAdvisory"/"SecurityAdvisory"
    event.summary
    event.status             # "Active"/"Resolved"
    event.impact_start_time
    event.last_update_time
    event.impacted_services_table  # Detailed service impact
```

### 3.7 ChangeAnalysis Patterns

```python
from azure.mgmt.changeanalysis import AzureChangeAnalysisManagementClient
from datetime import datetime, timedelta, timezone

client = AzureChangeAnalysisManagementClient(credential, subscription_id)

end_time = datetime.now(timezone.utc)
start_time = end_time - timedelta(hours=2)

# List changes by subscription
changes = client.changes.list_changes_by_subscription(
    start_time=start_time,
    end_time=end_time,
)
for change in changes:
    change.resource_id
    change.change_type         # "Add"/"Remove"/"Update"
    change.time_stamp
    change.initiated_by_list   # Who made the change
    change.property_changes    # List of property-level diffs
```

---

## 4. Subscription ID Handling

A critical design decision: how tools receive `subscription_id`.

### Current patterns in codebase:
1. **Compute agent:** `_extract_subscription_id(resource_id)` extracts from resource ID. Works when the tool operates on a specific resource.
2. **Patch agent:** Accepts `subscription_ids: List[str]` as explicit parameter for cross-subscription ARG queries.
3. **SRE agent (stubs):** Accepts `resource_id` parameter; would extract subscription.

### Recommended approach per agent:

| Agent | Pattern | Rationale |
|-------|---------|-----------|
| **Network** | `_extract_subscription_id(resource_id)` for resource-specific tools; explicit `subscription_id` for subscription-wide tools (flow logs, ExpressRoute listing) | Most network tools operate on specific named resources within a known RG |
| **Security** | Explicit `subscription_id` parameter on all tools | Security tools operate subscription-wide (Defender alerts, secure score, RBAC, policy compliance) |
| **SRE** | Hybrid — `resource_id` for metrics tools, `subscription_id` for subscription-wide tools (Service Health, Advisor, Change Analysis) | SRE does both resource-specific and cross-domain queries |

**Implement `_extract_subscription_id()` as a shared utility or copy into each tools.py** (same as compute/patch pattern — copy is the established pattern).

---

## 5. Error Handling Contract

Every tool MUST follow this pattern (from compute agent reference):

```python
@ai_function
def tool_name(params...) -> Dict[str, Any]:
    agent_id = get_agent_identity()
    tool_params = {<params>}

    with instrument_tool_call(tracer, agent_name, agent_id, tool_name, tool_params, "", ""):
        start_time = time.monotonic()
        try:
            if SdkClient is None:
                raise ImportError("package-name is not installed")

            credential = get_credential()
            client = SdkClient(credential, subscription_id)
            # ... SDK calls ...

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info("tool_name: complete | key=value duration_ms=%.0f", duration_ms)
            return {
                <result fields>,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error("tool_name: failed | error=%s duration_ms=%.0f", e, duration_ms, exc_info=True)
            return {
                <default fields>,
                "query_status": "error",
                "error": str(e),
            }
```

Key rules:
- **Never raise** — always return structured error dict
- **`start_time = time.monotonic()`** at entry (inside the `with` block)
- **`duration_ms`** recorded in BOTH try and except
- **Structured logging** with `tool_name: status | key=value` format
- **`instrument_tool_call`** wraps the entire tool body

---

## 6. Module-Level SDK Scaffold

Each tools.py MUST have this at the top (from compute agent pattern):

```python
# Lazy import — package may not be installed in all envs
try:
    from azure.mgmt.xxx import XxxClient
except ImportError:
    XxxClient = None  # type: ignore[assignment,misc]

def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {"package-name": "module.path", ...}
    for pkg, module in packages.items():
        try:
            __import__(module)
            logger.info("agent_tools: sdk_available | package=%s", pkg)
        except ImportError:
            logger.warning("agent_tools: sdk_missing | package=%s — tool will return error", pkg)

_log_sdk_availability()
```

---

## 7. Test Strategy

### 7.1 New test directories to create

```
agents/tests/network/__init__.py
agents/tests/network/test_network_tools.py

agents/tests/security/__init__.py
agents/tests/security/test_security_tools.py

agents/tests/sre/__init__.py
agents/tests/sre/test_sre_tools.py
```

### 7.2 Mock patterns (from test_patch_tools.py)

```python
@patch("agents.network.tools.instrument_tool_call")
@patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
@patch("agents.network.tools.get_credential", return_value=MagicMock())
@patch("agents.network.tools.NetworkManagementClient")
def test_query_nsg_rules_returns_expected_structure(
    self, mock_client_cls, mock_cred, mock_identity, mock_instrument
):
    mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

    # Setup mock NSG response
    mock_nsg = MagicMock()
    mock_nsg.security_rules = [...]
    mock_nsg.default_security_rules = [...]
    mock_client_cls.return_value.network_security_groups.get.return_value = mock_nsg

    result = query_nsg_rules(resource_group="rg-1", nsg_name="nsg-1", subscription_id="sub-1")

    assert result["query_status"] == "success"
    assert "security_rules" in result
```

### 7.3 Test coverage targets

| Test File | Min Tests | Coverage Target |
|-----------|-----------|-----------------|
| `test_network_tools.py` | ~25-30 (3-4 per tool x 7 tools + MCP + wiring) | >=80% on `agents/network/tools.py` |
| `test_security_tools.py` | ~25-30 (3-4 per tool x 7 tools + MCP + wiring) | >=80% on `agents/security/tools.py` |
| `test_sre_tools.py` | ~25-30 (3-4 per tool x 7 tools + MCP + wiring) | >=80% on `agents/sre/tools.py` |

### 7.4 Per-tool test cases (minimum)

For each tool:
1. **Success path** — mock SDK returns valid data, verify structured output
2. **Error path** — mock SDK raises Exception, verify error dict returned (never raises)
3. **SDK missing path** — verify tool handles `SdkClient is None` gracefully
4. **Edge case** — empty results, pagination (if applicable), specific filters

### 7.5 Integration tests

Extend `agents/tests/integration/test_triage.py` with:
- Network triage flow scenario (NSG rule change detected)
- Security triage flow scenario (Defender alert with RBAC drift)
- SRE service health flow scenario (Service Health event correlation)

---

## 8. Agent System Prompt Updates

Each agent's `agent.py` must update:

1. **System prompt** — Add new tools to the triage workflow steps and allowed tools list
2. **`ChatAgent(tools=[...])`** — Register new tool functions
3. **Tool imports** — Import from updated tools.py

### 8.1 Network Agent prompt changes
- Add flow logs, ExpressRoute, and connectivity check to workflow steps
- Step 4 after NSG: "If ExpressRoute involved, call `query_expressroute_health`"
- Step 5: "For connectivity issues, call `check_connectivity` with Network Watcher"
- Update allowed tools list

### 8.2 Security Agent prompt changes
- Add secure score, RBAC, policy, public endpoint scan to workflow steps
- Step 5: "Call `query_secure_score` for security posture overview"
- Step 6: "Call `query_rbac_assignments` to audit RBAC drift on affected resources"
- Step 7: "Call `query_policy_compliance` for non-compliant policies on affected resources"
- Step 8: "Call `scan_public_endpoints` if public-facing exposure is suspected"
- Update allowed tools list

### 8.3 SRE Agent prompt changes
- Add Service Health, Advisor, Change Analysis, and cross-domain correlation to workflow
- Step 3: "Call `query_service_health` to check for active Azure platform events (MONITOR-003)"
- Step 4: "Call `query_advisor_recommendations` for affected resources"
- Step 5: "Call `query_change_analysis` for detected infrastructure changes"
- Step 6: "Call `correlate_cross_domain` to build cross-domain correlation view"
- Update allowed tools list

---

## 9. ALLOWED_MCP_TOOLS Expansion

Per D-07, expand MCP allowlists:

### Network Agent
```python
ALLOWED_MCP_TOOLS = [
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
    "advisor.list_recommendations",
    "compute.list_vms",          # NEW: VM NIC inspection
]
```

### Security Agent
```python
ALLOWED_MCP_TOOLS = [
    "keyvault.list_vaults",
    "keyvault.get_vault",
    "role.list_assignments",
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
    "advisor.list_recommendations",  # NEW: security recommendations
]
```

### SRE Agent (already has most; add if any new ones identified)
```python
ALLOWED_MCP_TOOLS = [
    "monitor.query_logs",
    "monitor.query_metrics",
    "applicationinsights.query",
    "advisor.list_recommendations",
    "resourcehealth.get_availability_status",
    "resourcehealth.list_events",
]
# Already comprehensive — no changes needed
```

---

## 10. Long-Running Operations (LRO) — Network Watcher

`check_connectivity` is the only LRO tool in this phase. Pattern:

```python
poller = client.network_watchers.begin_check_connectivity(
    resource_group_name=nw_rg,
    network_watcher_name=nw_name,
    parameters=params,
)
# Synchronous wait with timeout
try:
    result = poller.result(timeout=120)  # 2-minute timeout
except Exception as e:
    # Handle timeout or operation failure
```

**Risks:**
- Network Watcher must exist in the same region as the source VM
- Long-running (can take 30-90 seconds)
- Requires Network Watcher + source VM with Network Watcher agent extension
- If Network Watcher doesn't exist in the region, graceful error

**Mitigation:** Add `network_watcher_resource_group` and `network_watcher_name` as required params (LLM can discover these via MCP `monitor.query_logs` or the user provides them).

---

## 11. Dependencies & Requirements Files

### New packages needed:

| Agent | Package | Version | Purpose |
|-------|---------|---------|---------|
| Network | (none) | — | `azure-mgmt-network>=27.0.0` already in requirements.txt |
| Security | `azure-mgmt-security` | `>=5.0.0` | Defender alerts, secure score |
| Security | `azure-mgmt-authorization` | `>=4.0.0` | RBAC role assignments |
| Security | `azure-mgmt-policyinsights` | `>=1.0.0` | Policy compliance |
| Security | `azure-mgmt-monitor` | `>=6.0.0` | Activity log (IAM changes) |
| Security | `azure-monitor-query` | `>=1.3.0` | KQL (Key Vault diagnostics) |
| Security | `azure-mgmt-network` | `>=27.0.0` | Public endpoint scan |
| SRE | `azure-mgmt-monitor` | `>=6.0.0` | Metrics (availability, baselines) |
| SRE | `azure-mgmt-resourcehealth` | `==1.0.0b6` | Service Health events |
| SRE | `azure-mgmt-advisor` | `>=9.0.0` | Advisor recommendations |
| SRE | `azure-mgmt-changeanalysis` | `>=1.0.0` | Change Analysis |

**Note:** `azure-mgmt-monitor`, `azure-monitor-query`, and `azure-mgmt-resourcehealth` are already in the base Dockerfile's compute agent requirements. They may need to be added per-agent since each agent has its own requirements.txt. Check if base image includes them — base image only includes `requirements-base.txt` which does NOT include these SDK packages. They must go in per-agent requirements.txt.

---

## 12. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `azure-mgmt-security` SecurityCenter needs `asc_location` param | Medium — wrong location returns empty results | Default to "centralus"; accept as optional param; log warning if empty results |
| Network Watcher `check_connectivity` LRO can be slow (30-90s) | Medium — agent timeout | Set 120s timeout; return partial result if timed out with `query_status: "timeout"` |
| `azure-mgmt-changeanalysis` may have limited availability in some regions | Low | Graceful degradation — return empty with warning if service unavailable |
| Policy compliance queries can return large result sets | Low — memory pressure in agent | Limit to top 100 non-compliant resources; paginate |
| Adding 6 new SDK packages to security agent increases image size | Low | SDK packages are lightweight; total size increase ~5-10MB |
| `scan_public_endpoints` could be slow for large subscriptions | Medium | Use ARG for efficiency: `resources | where type == "microsoft.network/publicipaddresses" | project id, name, properties.ipAddress, properties.ipConfiguration.id` |

---

## 13. File Change Summary

### Files to modify:
| File | Change Type | Estimated Lines |
|------|------------|-----------------|
| `agents/network/tools.py` | Heavy rewrite — fill 4 stubs + add 3 new tools | ~600-800 lines |
| `agents/network/agent.py` | Update system prompt + tools list + imports | ~30 lines changed |
| `agents/network/requirements.txt` | No change (already has azure-mgmt-network) | — |
| `agents/security/tools.py` | Heavy rewrite — fill 3 stubs + add 4 new tools | ~700-900 lines |
| `agents/security/agent.py` | Update system prompt + tools list + imports | ~40 lines changed |
| `agents/security/requirements.txt` | Add 6 new SDK packages | ~8 lines |
| `agents/sre/tools.py` | Moderate rewrite — fill 2 stubs + add 4 new tools (propose_remediation untouched) | ~600-800 lines |
| `agents/sre/agent.py` | Update system prompt + tools list + imports | ~40 lines changed |
| `agents/sre/requirements.txt` | Add 4 new SDK packages | ~6 lines |

### Files to create:
| File | Purpose | Estimated Lines |
|------|---------|-----------------|
| `agents/tests/network/__init__.py` | Package init | 0 |
| `agents/tests/network/test_network_tools.py` | Network tool unit tests | ~500-700 |
| `agents/tests/security/__init__.py` | Package init | 0 |
| `agents/tests/security/test_security_tools.py` | Security tool unit tests | ~500-700 |
| `agents/tests/sre/__init__.py` | Package init | 0 |
| `agents/tests/sre/test_sre_tools.py` | SRE tool unit tests | ~500-700 |

### Files to extend:
| File | Change | Lines |
|------|--------|-------|
| `agents/tests/integration/test_triage.py` | Add network/security/SRE triage scenarios | ~60-100 |

### Total estimated scope:
- **~3,500-5,000 lines of new/modified code** across tools + tests
- **~21 tools total** (7 network + 7 security + 7 SRE) — all with real SDK calls
- **~75-90 new unit tests** across 3 test files
- **3-5 new integration tests**

---

## 14. Implementation Order Recommendation

### Wave 1: Network Agent (fewest new dependencies)
1. Fill 4 existing stubs with real `azure-mgmt-network` SDK calls
2. Add 3 new tools (flow logs, ExpressRoute, connectivity check)
3. Update agent.py (prompt + tool registration)
4. Write test_network_tools.py
5. Run tests, verify >=80% coverage

### Wave 2: Security Agent (most new dependencies)
1. Update requirements.txt with 6 new SDK packages
2. Fill 3 existing stubs with real SDK calls
3. Add 4 new tools (secure score, RBAC, policy, public endpoints)
4. Update agent.py (prompt + tool registration)
5. Write test_security_tools.py
6. Run tests, verify >=80% coverage

### Wave 3: SRE Agent
1. Update requirements.txt with 4 new SDK packages
2. Fill 2 existing stubs with real SDK calls
3. Add 4 new tools (Service Health, Advisor, Change Analysis, cross-domain correlation)
4. Update agent.py (prompt + tool registration)
5. Write test_sre_tools.py
6. Run tests, verify >=80% coverage

### Wave 4: Integration & Validation
1. Extend integration tests
2. Verify all tests pass together (no import conflicts)
3. Verify system prompt coherence

**Rationale for order:** Network has zero new dependencies (azure-mgmt-network already in requirements), so it's the lowest-risk starting point. Security has the most new packages, so it benefits from patterns established in Network. SRE depends on patterns from both.

---

## 15. Constraints Reminder

From the CONTEXT and REQUIREMENTS:
- **TRIAGE-002:** Must query Log Analytics AND Resource Health before diagnosis
- **TRIAGE-003:** Must check Activity Log (prior 2h) as FIRST RCA step
- **TRIAGE-004:** Must include confidence score (0.0-1.0) in every diagnosis
- **REMEDI-001:** Must NOT execute remediation without human approval
- **D-01:** All tools get full real SDK implementations (not stubs)
- **D-02:** Follow established tool pattern (start_time, duration_ms, structured error)
- **D-03:** Wrap SDK calls with `instrument_tool_call()`
- **D-09:** Update system prompts to reference new tools
- **D-10:** Maintain existing TRIAGE/REMEDI constraints in system prompts
- **D-11:** Dedicated per-agent test files
- **D-12:** Extend integration tests
- **D-13:** >=80% coverage on tools.py per agent

---

*Phase: 20-network-security-agent-depth*
*Research completed: 2026-04-10*
