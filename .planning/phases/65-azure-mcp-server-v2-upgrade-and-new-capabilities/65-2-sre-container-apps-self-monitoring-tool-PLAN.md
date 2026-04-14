---
phase: 65
plan: 65-2
title: "SRE Container Apps Self-Monitoring Tool"
wave: 2
depends_on: ["65-1"]
files_modified:
  - agents/sre/tools.py
  - agents/sre/agent.py
  - agents/sre/requirements.txt
  - agents/tests/sre/test_sre_tools.py
autonomous: true
requirements: []
---

# Plan 65-2: SRE Container Apps Self-Monitoring Tool

## Goal

Add a `query_container_app_health` `@ai_function` tool to the SRE agent that enables platform self-monitoring. An operator can ask "why is the compute agent slow?" and the SRE agent will inspect the Container App's revision status, replica count, provisioning state, and scaling events using the `azure-mgmt-appcontainers` SDK.

The MCP `containerapps` namespace was already added to `ALLOWED_MCP_TOOLS` in Plan 65-1, but it only provides basic listing. The SDK tool provides deep revision and replica detail required for self-monitoring.

<threat_model>
## Threat Model

### Assets
- SRE agent's diagnostic capability (new Container Apps inspection tool)
- Container Apps API access via managed identity

### Threats
1. **LOW: Information disclosure via Container App inspection** — The tool returns provisioning state, replica count, revision details. This is operational data, not secrets. The SRE agent already has Reader access across all subscriptions. Mitigation: Tool returns structured summary data only — no env vars, secrets, or container images exposed. The `ContainerAppsAPIClient.container_apps.get()` API does not return secrets by default.

2. **LOW: SDK import availability** — `azure-mgmt-appcontainers` may not be installed in all environments. Mitigation: Lazy import with `try/except ImportError` pattern (established project convention). Tool returns structured error dict when SDK is unavailable — never raises.

### Verdict: No HIGH/CRITICAL threats. Proceed.
</threat_model>

## Tasks

<task id="65-2-01">
<title>Add azure-mgmt-appcontainers to SRE requirements.txt</title>
<read_first>
- agents/sre/requirements.txt
</read_first>
<action>
Append the following line to `agents/sre/requirements.txt`:

```
azure-mgmt-appcontainers>=4.0.0
```

The full file should read:
```
# SRE agent — azure-mgmt-monitor for availability metrics and performance baselines,
# azure-mgmt-resourcehealth for Service Health events,
# azure-mgmt-advisor for Advisor recommendations,
# azure-mgmt-changeanalysis for Change Analysis,
# azure-mgmt-appcontainers for Container Apps self-monitoring.
azure-mgmt-monitor>=6.0.0
azure-mgmt-resourcehealth==1.0.0b6
azure-mgmt-advisor>=9.0.0
azure-mgmt-changeanalysis>=1.0.0
azure-mgmt-appcontainers>=4.0.0
```
</action>
<acceptance_criteria>
- `agents/sre/requirements.txt` contains `azure-mgmt-appcontainers>=4.0.0`
- `agents/sre/requirements.txt` contains a comment mentioning `Container Apps self-monitoring`
</acceptance_criteria>
</task>

<task id="65-2-02">
<title>Add lazy import and SDK availability logging for ContainerAppsAPIClient</title>
<read_first>
- agents/sre/tools.py
</read_first>
<action>
In `agents/sre/tools.py`:

1. Add lazy import block after the existing `AzureChangeAnalysisManagementClient` import (after line ~43):

```python
# Lazy import — azure-mgmt-appcontainers may not be installed in all envs
try:
    from azure.mgmt.containerapp import ContainerAppsAPIClient
except ImportError:
    ContainerAppsAPIClient = None  # type: ignore[assignment,misc]
```

**IMPORTANT:** The Python import path is `azure.mgmt.containerapp` (singular), NOT `azure.mgmt.containerapps` (plural). The PyPI package is `azure-mgmt-appcontainers` but the module is `azure.mgmt.containerapp`.

2. Add the SDK availability entry in the `_log_sdk_availability()` function's `packages` dict:

```python
"azure-mgmt-appcontainers": "azure.mgmt.containerapp",
```
</action>
<acceptance_criteria>
- `agents/sre/tools.py` contains `from azure.mgmt.containerapp import ContainerAppsAPIClient`
- `agents/sre/tools.py` does NOT contain `from azure.mgmt.containerapps` (plural would be wrong)
- `agents/sre/tools.py` `_log_sdk_availability()` packages dict contains key `"azure-mgmt-appcontainers"` with value `"azure.mgmt.containerapp"`
</acceptance_criteria>
</task>

<task id="65-2-03">
<title>Implement query_container_app_health @ai_function tool</title>
<read_first>
- agents/sre/tools.py
- agents/shared/otel.py
</read_first>
<action>
**Before writing:** Read `agents/shared/otel.py` to verify the `instrument_tool_call` signature. It is a **context manager** (used with `with instrument_tool_call(...) as span:`), NOT a standalone function with `outcome=`/`duration_ms=` kwargs. Also read an existing tool (e.g., `query_availability_metrics` in `agents/sre/tools.py`) to see the exact calling convention used throughout the codebase.

The actual calling convention is:
```python
with instrument_tool_call(
    tracer=tracer,
    agent_name="sre-agent",
    agent_id=agent_id,
    tool_name="query_container_app_health",
    tool_parameters={...},
    correlation_id="",
    thread_id="",
) as span:
    # ... tool logic inside the context manager ...
```

Add the following `@ai_function` tool function at the end of `agents/sre/tools.py` (before any `if __name__` block, after the last existing tool function). Follow the established tool pattern exactly — wrapping the SDK call inside the `instrument_tool_call` context manager:

```python
@ai_function
def query_container_app_health(
    container_app_name: str,
    resource_group: str,
    subscription_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Query the health and status of an Azure Container App.

    Returns provisioning state, active revision details (name, traffic weight,
    replica count, running state), and last modified time. Use this to check
    the health of AAP agent Container Apps (e.g., ca-compute-prod, ca-sre-prod)
    or any Container App in monitored subscriptions.

    Args:
        container_app_name: Name of the Container App (e.g., "ca-compute-prod").
        resource_group: Resource group containing the Container App (e.g., "rg-aap-prod").
        subscription_id: Azure subscription ID. Defaults to AZURE_SUBSCRIPTION_ID env var.

    Returns:
        Dict with query_status, app_name, provisioning_state, active_revisions list,
        and duration_ms. Returns error dict (never raises) if SDK unavailable or API fails.
    """
    if ContainerAppsAPIClient is None:
        return {
            "query_status": "error",
            "error": "azure-mgmt-appcontainers SDK not installed",
            "duration_ms": 0.0,
        }

    sub_id = subscription_id or os.environ.get("AZURE_SUBSCRIPTION_ID", "")
    if not sub_id:
        return {
            "query_status": "error",
            "error": "subscription_id not provided and AZURE_SUBSCRIPTION_ID not set",
            "duration_ms": 0.0,
        }

    tool_params = {
        "container_app_name": container_app_name,
        "resource_group": resource_group,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="sre-agent",
        agent_id=agent_id,
        tool_name="query_container_app_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            credential = get_credential()
            client = ContainerAppsAPIClient(credential, sub_id)

            # Get Container App details
            app = client.container_apps.get(resource_group, container_app_name)

            # Get revision details
            revisions = []
            try:
                for rev in client.container_apps_revisions.list_revisions(
                    resource_group, container_app_name
                ):
                    revisions.append({
                        "name": rev.name,
                        "active": getattr(rev, "active", None),
                        "traffic_weight": getattr(rev, "traffic_weight", None),
                        "replicas": getattr(rev, "replicas", None),
                        "running_state": getattr(rev, "running_state", None),
                        "provisioning_state": getattr(rev, "provisioning_state", None),
                        "created_time": str(getattr(rev, "created_time", "")) if getattr(rev, "created_time", None) else None,
                        "last_active_time": str(getattr(rev, "last_active_time", "")) if getattr(rev, "last_active_time", None) else None,
                    })
            except Exception as rev_err:
                logger.warning(
                    "query_container_app_health: revision_list_error | app=%s error=%s",
                    container_app_name,
                    str(rev_err),
                )

            duration_ms = round((time.monotonic() - start_time) * 1000, 2)

            return {
                "query_status": "success",
                "app_name": app.name,
                "provisioning_state": getattr(app, "provisioning_state", None),
                "latest_revision_name": getattr(app, "latest_revision_name", None),
                "latest_ready_revision_name": getattr(app, "latest_ready_revision_name", None),
                "managed_environment_id": getattr(app, "managed_environment_id", None),
                "outbound_ip_addresses": getattr(app, "outbound_ip_addresses", None),
                "active_revisions": revisions,
                "revision_count": len(revisions),
                "duration_ms": duration_ms,
            }

        except Exception as exc:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            logger.error(
                "query_container_app_health: error | app=%s error=%s",
                container_app_name,
                str(exc),
            )
            return {
                "query_status": "error",
                "error": str(exc),
                "duration_ms": duration_ms,
            }
```

**Key difference from the original plan draft:** `start_time = time.monotonic()` is placed as the first line INSIDE the `with instrument_tool_call(...)` block, not before it. This matches the actual codebase pattern used in `query_availability_metrics` and all other existing SRE tools. The early-exit paths (SDK missing, subscription missing) return before entering the `with` block and use `duration_ms: 0.0` since no real work was done.

`instrument_tool_call` is used as a context manager wrapping the entire try/except block. Do NOT call it as a standalone function with `outcome=` or `duration_ms=` kwargs — those parameters do not exist on the actual function.
</action>
<acceptance_criteria>
- `agents/sre/tools.py` contains `def query_container_app_health(`
- `agents/sre/tools.py` contains `@ai_function` decorator before `query_container_app_health`
- `agents/sre/tools.py` `query_container_app_health` contains `start_time = time.monotonic()` as the first line INSIDE the `with instrument_tool_call(...)` block
- `agents/sre/tools.py` `query_container_app_health` contains `duration_ms` in both the try block and the except block
- `agents/sre/tools.py` `query_container_app_health` contains `"query_status": "error"` in error paths (never raises)
- `agents/sre/tools.py` `query_container_app_health` uses `with instrument_tool_call(` as a context manager (NOT as a standalone function call)
- `agents/sre/tools.py` `query_container_app_health` uses `ContainerAppsAPIClient` (not `ContainerAppsManagementClient`)
- Function has type annotations on all parameters and return type `Dict[str, Any]`
</acceptance_criteria>
</task>

<task id="65-2-04">
<title>Wire query_container_app_health into SRE agent</title>
<read_first>
- agents/sre/agent.py
</read_first>
<action>
**Important:** Read the full `agents/sre/agent.py` file to confirm `create_sre_agent_version()` exists before modifying it. It should be defined around line 188 — if not found, search for all function definitions and add to whichever creates an alternate version.

In `agents/sre/agent.py`:

1. Add `query_container_app_health` to the import from `sre.tools` (line 32):
```python
from sre.tools import (
    ALLOWED_MCP_TOOLS,
    correlate_cross_domain,
    propose_remediation,
    query_advisor_recommendations,
    query_availability_metrics,
    query_change_analysis,
    query_container_app_health,
    query_performance_baselines,
    query_service_health,
)
```

2. Add `query_container_app_health` to the `tools=[...]` list in `create_sre_agent()` (line ~154):
```python
tools=[
    query_availability_metrics,
    query_performance_baselines,
    query_service_health,
    query_advisor_recommendations,
    query_change_analysis,
    correlate_cross_domain,
    propose_remediation,
    query_container_app_health,
],
```

3. Add `query_container_app_health` to the `tools=[...]` list in `create_sre_agent_version()` (line ~188) — same addition.

4. Add `"query_container_app_health"` to the allowed_tools string list at the bottom of the system prompt (line ~124-132):
```python
""".format(allowed_tools="\n".join(f"- `{t}`" for t in ALLOWED_MCP_TOOLS + [
    "query_availability_metrics",
    "query_performance_baselines",
    "query_service_health",
    "query_advisor_recommendations",
    "query_change_analysis",
    "correlate_cross_domain",
    "propose_remediation",
    "query_container_app_health",
]))
```

5. Add a "Platform Self-Monitoring" section to the SRE_AGENT_SYSTEM_PROMPT, after the "Arc Fallback (Phase 2)" section and before "Safety Constraints":

```
## Platform Self-Monitoring

You can inspect AAP agent Container Apps to diagnose platform health issues:
- Call `query_container_app_health` with the Container App name and resource group
  to check provisioning state, active revisions, replica count, and running state.
- AAP agent Container Apps follow the naming convention `ca-{agent}-prod` in
  resource group `rg-aap-prod` (e.g., `ca-compute-prod`, `ca-sre-prod`,
  `ca-api-gateway-prod`, `ca-orchestrator-prod`).
- Use the `containerapps` MCP tool for listing all Container Apps in a subscription.
```
</action>
<acceptance_criteria>
- `agents/sre/agent.py` imports `query_container_app_health` from `sre.tools`
- `agents/sre/agent.py` `create_sre_agent()` tools list includes `query_container_app_health`
- `agents/sre/agent.py` `create_sre_agent_version()` tools list includes `query_container_app_health`
- `agents/sre/agent.py` `SRE_AGENT_SYSTEM_PROMPT` contains `query_container_app_health`
- `agents/sre/agent.py` `SRE_AGENT_SYSTEM_PROMPT` contains `Platform Self-Monitoring`
- `agents/sre/agent.py` `SRE_AGENT_SYSTEM_PROMPT` contains `ca-compute-prod`
- `agents/sre/agent.py` `SRE_AGENT_SYSTEM_PROMPT` contains `containerapps` MCP tool`
</acceptance_criteria>
</task>

<task id="65-2-05">
<title>Add unit tests for query_container_app_health</title>
<read_first>
- agents/tests/sre/test_sre_tools.py
- agents/sre/tools.py
</read_first>
<action>
Add the following test class to `agents/tests/sre/test_sre_tools.py`, after the existing test classes (following the same test pattern used by `TestQueryAvailabilityMetrics` and other tool test classes in the file):

```python
# ---------------------------------------------------------------------------
# query_container_app_health
# ---------------------------------------------------------------------------


class TestQueryContainerAppHealth:
    """Verify query_container_app_health returns expected structure."""

    @patch.dict("os.environ", {"AZURE_SUBSCRIPTION_ID": "sub-123"})
    @patch("agents.sre.tools.get_credential")
    @patch("agents.sre.tools.ContainerAppsAPIClient")
    def test_success_returns_app_details(self, mock_client_cls, mock_cred):
        from agents.sre.tools import query_container_app_health

        # Mock app response
        mock_app = MagicMock()
        mock_app.name = "ca-compute-prod"
        mock_app.provisioning_state = "Succeeded"
        mock_app.latest_revision_name = "ca-compute-prod--rev1"
        mock_app.latest_ready_revision_name = "ca-compute-prod--rev1"
        mock_app.managed_environment_id = "/subscriptions/sub-123/resourceGroups/rg-aap-prod/providers/Microsoft.App/managedEnvironments/cae-aap-prod"
        mock_app.outbound_ip_addresses = ["10.0.1.5"]

        # Mock revision response
        mock_rev = MagicMock()
        mock_rev.name = "ca-compute-prod--rev1"
        mock_rev.active = True
        mock_rev.traffic_weight = 100
        mock_rev.replicas = 2
        mock_rev.running_state = "Running"
        mock_rev.provisioning_state = "Provisioned"
        mock_rev.created_time = datetime(2026, 4, 14, 0, 0, tzinfo=timezone.utc)
        mock_rev.last_active_time = datetime(2026, 4, 14, 1, 0, tzinfo=timezone.utc)

        mock_client = mock_client_cls.return_value
        mock_client.container_apps.get.return_value = mock_app
        mock_client.container_apps_revisions.list_revisions.return_value = [mock_rev]

        result = query_container_app_health(
            container_app_name="ca-compute-prod",
            resource_group="rg-aap-prod",
        )

        assert result["query_status"] == "success"
        assert result["app_name"] == "ca-compute-prod"
        assert result["provisioning_state"] == "Succeeded"
        assert result["latest_revision_name"] == "ca-compute-prod--rev1"
        assert result["revision_count"] == 1
        assert len(result["active_revisions"]) == 1
        assert result["active_revisions"][0]["name"] == "ca-compute-prod--rev1"
        assert result["active_revisions"][0]["active"] is True
        assert result["active_revisions"][0]["traffic_weight"] == 100
        assert "duration_ms" in result

    @patch.dict("os.environ", {"AZURE_SUBSCRIPTION_ID": "sub-123"})
    @patch("agents.sre.tools.get_credential")
    @patch("agents.sre.tools.ContainerAppsAPIClient")
    def test_error_returns_error_dict(self, mock_client_cls, mock_cred):
        from agents.sre.tools import query_container_app_health

        mock_client = mock_client_cls.return_value
        mock_client.container_apps.get.side_effect = Exception("not found")

        result = query_container_app_health(
            container_app_name="ca-missing-prod",
            resource_group="rg-aap-prod",
        )

        assert result["query_status"] == "error"
        assert "not found" in result["error"]
        assert "duration_ms" in result

    @patch("agents.sre.tools.ContainerAppsAPIClient", None)
    def test_sdk_missing_returns_error_dict(self):
        from agents.sre.tools import query_container_app_health

        result = query_container_app_health(
            container_app_name="ca-compute-prod",
            resource_group="rg-aap-prod",
        )

        assert result["query_status"] == "error"
        assert "SDK not installed" in result["error"]
        assert "duration_ms" in result

    def test_missing_subscription_id_returns_error(self):
        from agents.sre.tools import query_container_app_health

        with patch.dict("os.environ", {}, clear=True):
            result = query_container_app_health(
                container_app_name="ca-compute-prod",
                resource_group="rg-aap-prod",
            )

        assert result["query_status"] == "error"
        assert "subscription_id" in result["error"]
```

Also add `import os` and ensure `from unittest.mock import patch` includes `patch.dict` (it should already be imported).
</action>
<acceptance_criteria>
- `agents/tests/sre/test_sre_tools.py` contains `class TestQueryContainerAppHealth`
- `agents/tests/sre/test_sre_tools.py` contains `test_success_returns_app_details`
- `agents/tests/sre/test_sre_tools.py` contains `test_error_returns_error_dict`
- `agents/tests/sre/test_sre_tools.py` contains `test_sdk_missing_returns_error_dict`
- `agents/tests/sre/test_sre_tools.py` contains `test_missing_subscription_id_returns_error`
- `pytest agents/tests/sre/test_sre_tools.py::TestQueryContainerAppHealth -v` exits 0
</acceptance_criteria>
</task>

<task id="65-2-06">
<title>Run full SRE test suite and verify zero regressions</title>
<read_first>
- agents/tests/sre/test_sre_tools.py
</read_first>
<action>
Run the complete SRE agent test suite:

```bash
# SRE tool tests (all classes)
pytest agents/tests/sre/test_sre_tools.py -v

# Full agent test suite (catch any import/wiring regressions)
pytest agents/tests/ -v --timeout=120
```

Verify:
1. All `TestQueryContainerAppHealth` tests pass (4 tests)
2. All `TestAllowedMcpTools` tests pass (including the updated count/entries from Plan 65-1)
3. All existing SRE tool tests pass (no regressions)
4. Full agent suite passes

Fix any failures before marking complete.
</action>
<acceptance_criteria>
- `pytest agents/tests/sre/test_sre_tools.py -v` exits 0
- `pytest agents/tests/sre/test_sre_tools.py -v` output shows `TestQueryContainerAppHealth` with 4 passing tests
- `pytest agents/tests/ --timeout=120` exits 0 with zero failures
</acceptance_criteria>
</task>

<task id="65-2-07">
<title>Document OperationalExcellence category in query_advisor_recommendations and SRE prompt</title>
<read_first>
- agents/sre/tools.py
- agents/sre/agent.py
</read_first>
<action>
This task fulfills the CONTEXT.md decision: "Expand `query_advisor_recommendations` to include `OperationalExcellence` as a valid category filter (currently accepted but not documented in docstring)" and "Update SRE system prompt to mention OperationalExcellence category."

1. In `agents/sre/tools.py`, find the `query_advisor_recommendations` function docstring. Update the `category` parameter documentation to explicitly list `OperationalExcellence` as a valid value. The current docstring lists categories like `Cost`, `Security`, `Reliability`, `Performance` — add `OperationalExcellence` to this list. Example:

   ```
   category: Filter by recommendation category. Valid values:
       "Cost", "Security", "Reliability", "OperationalExcellence",
       "Performance", "HighAvailability". Defaults to all categories.
   ```

2. In `agents/sre/agent.py`, in the `SRE_AGENT_SYSTEM_PROMPT`, find the section that mentions Advisor recommendations. Add a note that the `OperationalExcellence` category is available for operational best-practice recommendations. For example, after the existing advisor line, add:

   ```
   - The `advisor` MCP tool supports category filtering including `OperationalExcellence`
     for operational best-practice recommendations (resource configuration, scaling, diagnostics).
   ```

No functional code changes — this is documentation-only (the function already accepts OperationalExcellence as a category value at runtime).
</action>
<acceptance_criteria>
- `agents/sre/tools.py` `query_advisor_recommendations` docstring contains the string `OperationalExcellence`
- `agents/sre/agent.py` `SRE_AGENT_SYSTEM_PROMPT` contains the string `OperationalExcellence`
- No functional code changes to `query_advisor_recommendations` — only docstring update
</acceptance_criteria>
</task>

## Verification

```bash
# 1. SRE requirements includes appcontainers
grep -q "azure-mgmt-appcontainers" agents/sre/requirements.txt && echo "PASS: requirements" || echo "FAIL: requirements"

# 2. Tool function exists and follows pattern
python3 -c "
from agents.sre.tools import query_container_app_health
import inspect
source = inspect.getsource(query_container_app_health)
assert 'start_time = time.monotonic()' in source, 'Missing start_time pattern'
assert source.count('duration_ms') >= 2, 'duration_ms not in both try/except'
assert 'query_status' in source, 'Missing query_status'
assert 'with instrument_tool_call(' in source, 'Must use context manager pattern'
print('PASS: tool function follows pattern')
"

# 3. Tool wired into agent
python3 -c "
from agents.sre.agent import SRE_AGENT_SYSTEM_PROMPT
assert 'query_container_app_health' in SRE_AGENT_SYSTEM_PROMPT
assert 'Platform Self-Monitoring' in SRE_AGENT_SYSTEM_PROMPT
assert 'OperationalExcellence' in SRE_AGENT_SYSTEM_PROMPT
print('PASS: tool wired into system prompt')
"

# 4. Import path is correct (singular)
grep -q "azure.mgmt.containerapp" agents/sre/tools.py && echo "PASS: import path" || echo "FAIL: import path"
grep -c "azure.mgmt.containerapps" agents/sre/tools.py | grep -q "^0$" && echo "PASS: no plural import" || echo "FAIL: plural import found"

# 5. OperationalExcellence documented
grep -q "OperationalExcellence" agents/sre/tools.py && echo "PASS: docstring" || echo "FAIL: docstring"

# 6. Full test suite
pytest agents/tests/sre/test_sre_tools.py -v -q
```

## must_haves
- [ ] `azure-mgmt-appcontainers>=4.0.0` in `agents/sre/requirements.txt`
- [ ] Lazy import uses correct path `azure.mgmt.containerapp` (singular, not plural)
- [ ] `query_container_app_health` follows project tool pattern (start_time inside `with` block, duration_ms, never raises, returns error dicts)
- [ ] `query_container_app_health` uses `instrument_tool_call` as a context manager (`with instrument_tool_call(...):`), not as a standalone function call
- [ ] `query_container_app_health` wired into `create_sre_agent()` tools list
- [ ] SRE system prompt includes "Platform Self-Monitoring" section with Container App naming convention
- [ ] 4 unit tests pass: success, error, SDK-missing, missing-subscription-id
- [ ] `query_advisor_recommendations` docstring documents `OperationalExcellence` as a valid category
- [ ] SRE system prompt mentions `OperationalExcellence` category for advisor recommendations
- [ ] Full SRE test suite passes with zero regressions
