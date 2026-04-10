# Phase 32 — VM Domain Depth Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the VM domain (Azure VM, Arc VM, VMSS, AKS) and Patch/EOL agents to world-class depth by fixing 5 triage stubs and adding 17+ new tools covering diagnostics, HITL remediation proposals, VMSS scaling, AKS cluster health, and Arc guest configuration.

**Architecture:** All new tools follow the existing `agents/compute/tools.py` pattern: lazy SDK imports, `@ai_function` decorator, `instrument_tool_call` span, `try/except` returning structured error dicts (never raise). All `propose_*` tools call only `approval_manager.create_approval_record()` — zero ARM mutations. Stub fixes are identical to the Compute agent's existing `query_activity_log` / `query_resource_health` implementations.

**Tech Stack:** `agent_framework.ai_function`, `azure-mgmt-compute`, `azure-mgmt-containerservice`, `azure-mgmt-hybridcompute`, `azure-mgmt-guestconfiguration`, `azure-mgmt-monitor`, `azure-mgmt-resourcehealth`, `asyncpg` (approval records), Python pytest

**Spec:** `docs/superpowers/specs/2026-04-11-world-class-aiops-phases-29-34-design.md` §6

**Prerequisite:** Phase 30 (sop_notify tool pattern established, approval_manager.py exists).

---

## Chunk 1: Stub Fixes — Patch and EOL Agents

### Task 1: Write failing tests for Patch stub fixes

**Files:**
- Create: `agents/tests/patch/test_patch_stub_fixes.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for Patch agent stub fixes — query_activity_log and query_resource_health (Phase 32)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_instrument_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestPatchQueryActivityLog:
    """Verify query_activity_log is a real SDK call, not a stub."""

    @patch("agents.patch.tools.instrument_tool_call")
    @patch("agents.patch.tools.get_agent_identity", return_value="entra-id-test")
    @patch("agents.patch.tools.MonitorManagementClient")
    @patch("agents.patch.tools.get_credential")
    def test_calls_monitor_management_client_activity_logs(
        self, mock_cred, mock_monitor_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_monitor = MagicMock()
        mock_monitor_cls.return_value = mock_monitor
        mock_monitor.activity_logs.list.return_value = iter([])

        from agents.patch.tools import query_activity_log

        result = query_activity_log(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            subscription_id="sub-123",
            thread_id="thread-1",
        )

        mock_monitor.activity_logs.list.assert_called_once()
        assert "entries" in result

    @patch("agents.patch.tools.instrument_tool_call")
    @patch("agents.patch.tools.get_agent_identity", return_value="entra-id-test")
    @patch("agents.patch.tools.MonitorManagementClient", None)
    @patch("agents.patch.tools.get_credential")
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        from agents.patch.tools import query_activity_log

        result = query_activity_log(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            subscription_id="sub-123",
            thread_id="thread-1",
        )

        assert "error" in result or "unavailable" in str(result).lower()


class TestPatchQueryResourceHealth:
    """Verify query_resource_health is a real SDK call, not a stub."""

    @patch("agents.patch.tools.instrument_tool_call")
    @patch("agents.patch.tools.get_agent_identity", return_value="entra-id-test")
    @patch("agents.patch.tools.MicrosoftResourceHealth")
    @patch("agents.patch.tools.get_credential")
    def test_calls_availability_statuses(
        self, mock_cred, mock_rh_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_rh = MagicMock()
        mock_rh_cls.return_value = mock_rh
        mock_status = MagicMock()
        mock_status.properties.availability_state = "Available"
        mock_status.properties.summary = "The resource is available"
        mock_rh.availability_statuses.get_by_resource.return_value = mock_status

        from agents.patch.tools import query_resource_health

        result = query_resource_health(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            subscription_id="sub-123",
            thread_id="thread-1",
        )

        mock_rh.availability_statuses.get_by_resource.assert_called_once()
        assert result.get("availability_state") == "Available"
```

- [ ] **Step 2: Run test — expect failures (stubs return placeholder data)**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/patch/test_patch_stub_fixes.py -v 2>&1 | head -20
```

### Task 2: Fix Patch agent stubs

**Files:**
- Modify: `agents/patch/tools.py`

- [ ] **Step 1: Read the current patch/tools.py stub implementations**

```bash
grep -n "stub\|TODO\|not implemented\|placeholder" agents/patch/tools.py -i
```

- [ ] **Step 2: Fix `query_activity_log` in patch/tools.py**

Replace any stub implementation with the real SDK call mirroring `agents/compute/tools.py`:

```python
# Ensure lazy imports are at the top of patch/tools.py:
try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

@ai_function
def query_activity_log(
    resource_id: str,
    subscription_id: str,
    thread_id: str,
    hours: int = 2,
) -> dict:
    """Query Azure Activity Log for recent operations on a resource.

    TRIAGE-003: Must be called as the FIRST step before metric queries.

    Args:
        resource_id: Full ARM resource ID of the target resource.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID for audit tracing.
        hours: Look-back window in hours (default: 2).

    Returns:
        Dict with 'entries' list (each entry has operationName, status,
        caller, eventTimestamp) and 'count'.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="patch-agent",
        agent_id=agent_id,
        tool_name="query_activity_log",
        tool_parameters={"resource_id": resource_id, "hours": hours},
        correlation_id=resource_id,
        thread_id=thread_id,
    ):
        if MonitorManagementClient is None:
            return {
                "error": "azure-mgmt-monitor not installed",
                "entries": [],
                "count": 0,
            }

        credential = get_credential()
        client = MonitorManagementClient(credential, subscription_id)

        end_time = datetime.now(timezone.utc)
        start_time_dt = end_time - timedelta(hours=hours)
        filter_str = (
            f"eventTimestamp ge '{start_time_dt.isoformat()}' "
            f"and resourceUri eq '{resource_id}'"
        )

        entries = []
        try:
            for event in client.activity_logs.list(filter=filter_str):
                entries.append({
                    "operationName": getattr(event.operation_name, "value", str(event.operation_name)),
                    "status": getattr(event.status, "value", str(event.status)),
                    "caller": event.caller or "unknown",
                    "eventTimestamp": event.event_timestamp.isoformat() if event.event_timestamp else None,
                    "description": event.description or "",
                })
        except Exception as exc:
            logger.warning("query_activity_log: error fetching events: %s", exc)
            return {"error": str(exc), "entries": [], "count": 0}

        return {"entries": entries, "count": len(entries), "resource_id": resource_id}
```

- [ ] **Step 3: Fix `query_resource_health` in patch/tools.py**

```python
try:
    from azure.mgmt.resourcehealth import MicrosoftResourceHealth
except ImportError:
    MicrosoftResourceHealth = None  # type: ignore[assignment,misc]

@ai_function
def query_resource_health(
    resource_id: str,
    subscription_id: str,
    thread_id: str,
) -> dict:
    """Query Azure Resource Health for a resource's availability status.

    TRIAGE-002: Must be called before finalising diagnosis.

    Returns:
        Dict with availability_state, summary, reason_type, occurred_time.
    """
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="patch-agent",
        agent_id=agent_id,
        tool_name="query_resource_health",
        tool_parameters={"resource_id": resource_id},
        correlation_id=resource_id,
        thread_id=thread_id,
    ):
        if MicrosoftResourceHealth is None:
            return {"error": "azure-mgmt-resourcehealth not installed", "availability_state": "Unknown"}

        credential = get_credential()
        client = MicrosoftResourceHealth(credential, subscription_id)

        try:
            status = client.availability_statuses.get_by_resource(
                resource_uri=resource_id
            )
            props = status.properties
            return {
                "availability_state": props.availability_state,
                "summary": props.summary or "",
                "reason_type": props.reason_type or "",
                "occurred_time": props.occurred_time.isoformat() if props.occurred_time else None,
                "resource_id": resource_id,
            }
        except Exception as exc:
            logger.warning("query_resource_health: error: %s", exc)
            return {"error": str(exc), "availability_state": "Unknown"}
```

- [ ] **Step 4: Run Patch stub fix tests — expect PASS**

```bash
python -m pytest agents/tests/patch/test_patch_stub_fixes.py -v
```

- [ ] **Step 5: Apply identical fixes to `agents/eol/tools.py`**

The EOL agent has the same two stubs. Apply the same `query_activity_log` and `query_resource_health` fixes.

Also fix `query_software_inventory` in EOL agent — activate the KQL query already in comments:

```python
@ai_function
async def query_software_inventory(
    workspace_id: str,
    resource_id: str,
    thread_id: str,
) -> dict:
    """Query Log Analytics ConfigurationData for installed software inventory.

    Returns installed Python, Node.js, .NET, and database runtime versions
    for EOL detection.
    """
    # ... use LogsQueryClient with ConfigurationData KQL (already in comments)
    KQL = """
    ConfigurationData
    | where TimeGenerated > ago(7d)
    | where SoftwareType in ("Application", "Middleware")
    | where Publisher in ("Python", "Microsoft", "Node.js Foundation", "Oracle")
    | project SoftwareName, CurrentVersion, Publisher, Computer
    | summarize by SoftwareName, CurrentVersion, Publisher
    """
    # ... execute via LogsQueryClient
```

- [ ] **Step 6: Commit stub fixes**

```bash
git add agents/patch/tools.py agents/eol/tools.py \
        agents/tests/patch/test_patch_stub_fixes.py
git commit -m "fix(phase-32): replace Patch + EOL agent stubs with real SDK calls"
```

---

## Chunk 2: New Compute Agent Tools — Azure VM

### Task 3: Write failing tests for new Azure VM tools

**Files:**
- Create: `agents/tests/compute/test_compute_new_tools.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for new Azure VM tools (Phase 32): extensions, boot diagnostics, disk health, SKU options, propose_*."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _instrument_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestQueryVmExtensions:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_extensions_list(self, mock_cred, mock_compute_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        ext = MagicMock()
        ext.name = "MicrosoftMonitoringAgent"
        ext.properties.provisioning_state = "Succeeded"
        ext.properties.type_handler_version = "1.0"
        mock_compute.virtual_machine_extensions.list.return_value = [ext]

        from agents.compute.tools import query_vm_extensions

        result = query_vm_extensions(
            resource_group="rg1",
            vm_name="vm1",
            subscription_id="sub",
            thread_id="thread-1",
        )

        assert "extensions" in result
        assert len(result["extensions"]) == 1

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient", None)
    @patch("agents.compute.tools.get_credential")
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_vm_extensions

        result = query_vm_extensions("rg1", "vm1", "sub", "thread-1")
        assert "error" in result


class TestQueryBootDiagnostics:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_screenshot_uri(self, mock_cred, mock_compute_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        diag_result = MagicMock()
        diag_result.console_screenshot_blob_uri = "https://storage/screenshot.png"
        diag_result.serial_console_log_blob_uri = "https://storage/serial.txt"
        mock_compute.virtual_machines.retrieve_boot_diagnostics_data.return_value = diag_result

        from agents.compute.tools import query_boot_diagnostics

        result = query_boot_diagnostics("rg1", "vm1", "sub", "thread-1")
        assert "screenshot_uri" in result
        assert result["screenshot_uri"] == "https://storage/screenshot.png"


class TestQueryVmSkuOptions:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_sku_list(self, mock_cred, mock_compute_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        sku = MagicMock()
        sku.name = "Standard_D4s_v3"
        sku.tier = "Standard"
        mock_compute.resource_skus.list.return_value = iter([sku])

        from agents.compute.tools import query_vm_sku_options

        result = query_vm_sku_options(
            subscription_id="sub",
            location="eastus",
            sku_family="Standard_D",
            thread_id="thread-1",
        )
        assert "skus" in result
        assert len(result["skus"]) >= 1


class TestProposeVmRestart:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record")
    def test_creates_approval_record(self, mock_create_approval, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_create_approval.return_value = {"id": "appr_123", "status": "pending"}

        from agents.compute.tools import propose_vm_restart

        result = propose_vm_restart(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_group="rg",
            vm_name="vm1",
            subscription_id="sub",
            incident_id="inc-001",
            thread_id="thread-1",
            reason="High CPU post-deployment",
        )

        mock_create_approval.assert_called_once()
        assert result.get("status") == "pending_approval" or "approval_id" in result

    def test_propose_vm_restart_does_not_call_arm_directly(self):
        """propose_vm_restart must NOT import or use ComputeManagementClient.virtual_machines.restart."""
        import inspect

        from agents.compute import tools as compute_tools

        src = inspect.getsource(compute_tools.propose_vm_restart)
        assert "virtual_machines.restart" not in src
        assert "virtual_machines.begin_restart" not in src


class TestProposeVmResize:
    def test_propose_vm_resize_does_not_call_arm_directly(self):
        import inspect

        from agents.compute import tools as compute_tools

        src = inspect.getsource(compute_tools.propose_vm_resize)
        assert "virtual_machines.update" not in src
        assert "begin_update" not in src

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record")
    def test_creates_approval_record_with_target_sku(
        self, mock_create_approval, mock_identity, mock_instr
    ):
        mock_instr.return_value = _instrument_mock()
        mock_create_approval.return_value = {"id": "appr_resize", "status": "pending"}

        from agents.compute.tools import propose_vm_resize

        result = propose_vm_resize(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_group="rg",
            vm_name="vm1",
            subscription_id="sub",
            current_sku="Standard_D2s_v3",
            target_sku="Standard_D4s_v3",
            incident_id="inc-001",
            thread_id="thread-1",
            reason="CPU saturation",
        )

        mock_create_approval.assert_called_once()
        call_kwargs = mock_create_approval.call_args
        proposal = call_kwargs.kwargs.get("proposal") or call_kwargs.args[3]
        assert "Standard_D4s_v3" in str(proposal)
```

- [ ] **Step 2: Run test — expect ImportError / AttributeError**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/compute/test_compute_new_tools.py -v 2>&1 | head -20
```

### Task 4: Add new Azure VM tools to `agents/compute/tools.py`

**Files:**
- Modify: `agents/compute/tools.py`

- [ ] **Step 1: Add lazy imports at the top of compute/tools.py**

```python
try:
    from azure.mgmt.compute import ComputeManagementClient
except ImportError:
    ComputeManagementClient = None  # type: ignore[assignment,misc]
```

- [ ] **Step 2: Add `query_vm_extensions` tool**

```python
@ai_function
def query_vm_extensions(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    thread_id: str,
) -> dict:
    """List extensions installed on an Azure VM with provisioning state and version.

    Args:
        resource_group: Resource group name.
        vm_name: Virtual machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID for tracing.

    Returns:
        Dict with 'extensions' list (name, type, provisioning_state, version).
    """
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_vm_extensions",
        tool_parameters={"resource_group": resource_group, "vm_name": vm_name},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        if ComputeManagementClient is None:
            return {"error": "azure-mgmt-compute not installed", "extensions": []}

        credential = get_credential()
        client = ComputeManagementClient(credential, subscription_id)

        try:
            raw = client.virtual_machine_extensions.list(resource_group, vm_name)
            extensions = []
            for ext in (raw.value or []):
                extensions.append({
                    "name": ext.name,
                    "type": getattr(ext, "type_properties_type", ext.type) or "",
                    "provisioning_state": getattr(ext.properties, "provisioning_state", "Unknown"),
                    "type_handler_version": getattr(ext.properties, "type_handler_version", ""),
                    "auto_upgrade_minor_version": getattr(
                        ext.properties, "auto_upgrade_minor_version", None
                    ),
                })
            return {"extensions": extensions, "vm_name": vm_name}
        except Exception as exc:
            logger.warning("query_vm_extensions error: %s", exc)
            return {"error": str(exc), "extensions": []}
```

- [ ] **Step 3: Add `query_boot_diagnostics` tool**

```python
@ai_function
def query_boot_diagnostics(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    thread_id: str,
) -> dict:
    """Retrieve boot diagnostics data for an Azure VM (screenshot URI + serial log URI).

    Args:
        resource_group: Resource group name.
        vm_name: Virtual machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with 'screenshot_uri' and 'serial_log_uri'.
    """
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_boot_diagnostics",
        tool_parameters={"resource_group": resource_group, "vm_name": vm_name},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        if ComputeManagementClient is None:
            return {"error": "azure-mgmt-compute not installed"}

        credential = get_credential()
        client = ComputeManagementClient(credential, subscription_id)

        try:
            result = client.virtual_machines.retrieve_boot_diagnostics_data(
                resource_group, vm_name
            )
            return {
                "screenshot_uri": result.console_screenshot_blob_uri or "",
                "serial_log_uri": result.serial_console_log_blob_uri or "",
                "vm_name": vm_name,
            }
        except Exception as exc:
            logger.warning("query_boot_diagnostics error: %s", exc)
            return {"error": str(exc), "screenshot_uri": "", "serial_log_uri": ""}
```

- [ ] **Step 4: Add `query_vm_sku_options` tool (diagnostic read only)**

```python
@ai_function
def query_vm_sku_options(
    subscription_id: str,
    location: str,
    sku_family: str,
    thread_id: str,
) -> dict:
    """List available VM SKUs in a region for rightsizing recommendations.

    Call this BEFORE propose_vm_resize to identify valid target SKUs.
    This is a diagnostic read — no changes are made.

    Args:
        subscription_id: Azure subscription ID.
        location: Azure region (e.g. "eastus").
        sku_family: SKU family prefix to filter (e.g. "Standard_D").
        thread_id: Foundry thread ID.

    Returns:
        Dict with 'skus' list (name, tier, vcpus, memory_gb).
    """
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_vm_sku_options",
        tool_parameters={"location": location, "sku_family": sku_family},
        correlation_id=subscription_id,
        thread_id=thread_id,
    ):
        if ComputeManagementClient is None:
            return {"error": "azure-mgmt-compute not installed", "skus": []}

        credential = get_credential()
        client = ComputeManagementClient(credential, subscription_id)

        try:
            skus = []
            for sku in client.resource_skus.list(filter=f"location eq '{location}'"):
                if sku.resource_type != "virtualMachines":
                    continue
                if sku_family and not sku.name.startswith(sku_family):
                    continue
                capabilities = {c.name: c.value for c in (sku.capabilities or [])}
                skus.append({
                    "name": sku.name,
                    "tier": sku.tier or "",
                    "vcpus": capabilities.get("vCPUs", ""),
                    "memory_gb": capabilities.get("MemoryGB", ""),
                })
            return {"skus": skus[:20], "location": location, "sku_family": sku_family}
        except Exception as exc:
            logger.warning("query_vm_sku_options error: %s", exc)
            return {"error": str(exc), "skus": []}
```

- [ ] **Step 5: Add `query_disk_health` tool**

```python
@ai_function
def query_disk_health(
    resource_group: str,
    disk_name: str,
    subscription_id: str,
    thread_id: str,
) -> dict:
    """Query disk state, IOPS, throughput, and encryption status.

    Args:
        resource_group: Resource group name.
        disk_name: Managed disk name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with disk_state, disk_size_gb, iops, throughput_mbps, encryption_type.
    """
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_disk_health",
        tool_parameters={"resource_group": resource_group, "disk_name": disk_name},
        correlation_id=disk_name,
        thread_id=thread_id,
    ):
        if ComputeManagementClient is None:
            return {"error": "azure-mgmt-compute not installed"}

        credential = get_credential()
        client = ComputeManagementClient(credential, subscription_id)

        try:
            disk = client.disks.get(resource_group, disk_name)
            return {
                "disk_name": disk_name,
                "disk_state": disk.disk_state or "Unknown",
                "disk_size_gb": disk.disk_size_gb,
                "provisioning_state": disk.provisioning_state or "Unknown",
                "iops_read_write": disk.disk_iops_read_write,
                "throughput_mbps": disk.disk_m_bps_read_write,
                "encryption_type": getattr(
                    getattr(disk, "encryption", None), "type", "Unknown"
                ),
            }
        except Exception as exc:
            logger.warning("query_disk_health error: %s", exc)
            return {"error": str(exc)}
```

- [ ] **Step 6: Add `propose_vm_restart`, `propose_vm_resize`, `propose_vm_redeploy` tools**

```python
from shared.approval_manager import create_approval_record

@ai_function
def propose_vm_restart(
    resource_id: str,
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> dict:
    """Propose a VM restart — creates HITL ApprovalRecord (no ARM call).

    REMEDI-001: This tool ONLY creates an approval record. The restart
    is executed by RemediationExecutor AFTER human approval.

    Returns:
        Dict with approval_id and status="pending_approval".
    """
    proposal = {
        "action": "vm_restart",
        "resource_id": resource_id,
        "resource_group": resource_group,
        "vm_name": vm_name,
        "subscription_id": subscription_id,
        "reason": reason,
        "description": f"Restart VM '{vm_name}' to resolve: {reason}",
        "target_resources": [resource_id],
        "estimated_impact": "~2-5 min downtime",
        "reversible": True,
    }

    record = create_approval_record(
        container=None,   # injected at runtime via dependency
        thread_id=thread_id,
        incident_id=incident_id,
        agent_name="compute-agent",
        proposal=proposal,
        resource_snapshot={"vm_name": vm_name, "resource_id": resource_id},
        risk_level="medium",
    )

    return {
        "status": "pending_approval",
        "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
        "message": f"VM restart proposal created for '{vm_name}'. Awaiting human approval.",
    }


@ai_function
def propose_vm_resize(
    resource_id: str,
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    current_sku: str,
    target_sku: str,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> dict:
    """Propose a VM resize — creates HITL ApprovalRecord (no ARM call).

    Call query_vm_sku_options FIRST to identify a valid target_sku.
    This tool does NOT validate the SKU — pass the SKU returned by
    query_vm_sku_options.

    REMEDI-001: No ARM call. Approval required before execution.
    """
    proposal = {
        "action": "vm_resize",
        "resource_id": resource_id,
        "resource_group": resource_group,
        "vm_name": vm_name,
        "subscription_id": subscription_id,
        "current_sku": current_sku,
        "target_sku": target_sku,
        "reason": reason,
        "description": f"Resize VM '{vm_name}' from {current_sku} to {target_sku}: {reason}",
        "target_resources": [resource_id],
        "estimated_impact": "~5-10 min downtime (deallocate/resize/start)",
        "reversible": True,
    }

    record = create_approval_record(
        container=None,
        thread_id=thread_id,
        incident_id=incident_id,
        agent_name="compute-agent",
        proposal=proposal,
        resource_snapshot={"vm_name": vm_name, "current_sku": current_sku, "target_sku": target_sku},
        risk_level="high",
    )

    return {
        "status": "pending_approval",
        "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
        "message": f"VM resize proposal created for '{vm_name}' ({current_sku} → {target_sku}). Awaiting approval.",
    }


@ai_function
def propose_vm_redeploy(
    resource_id: str,
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> dict:
    """Propose a VM redeploy to a different host — creates HITL ApprovalRecord.

    Use when host-level issues are suspected. Redeploy is irreversible
    (new host allocation; IP/disk are preserved).

    REMEDI-001: No ARM call. Approval required before execution.
    """
    proposal = {
        "action": "vm_redeploy",
        "resource_id": resource_id,
        "resource_group": resource_group,
        "vm_name": vm_name,
        "subscription_id": subscription_id,
        "reason": reason,
        "description": f"Redeploy VM '{vm_name}' to new host: {reason}",
        "target_resources": [resource_id],
        "estimated_impact": "~10 min downtime",
        "reversible": False,
    }

    record = create_approval_record(
        container=None,
        thread_id=thread_id,
        incident_id=incident_id,
        agent_name="compute-agent",
        proposal=proposal,
        resource_snapshot={"vm_name": vm_name, "resource_id": resource_id},
        risk_level="high",
    )

    return {
        "status": "pending_approval",
        "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
        "message": f"VM redeploy proposal created for '{vm_name}'. Awaiting approval.",
    }
```

- [ ] **Step 7: Update ALLOWED_MCP_TOOLS list in compute/tools.py**

```python
ALLOWED_MCP_TOOLS: List[str] = [
    "compute.list_vms",
    "compute.get_vm",
    "compute.list_disks",
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
    "advisor.list_recommendations",
    "appservice.list_apps",
    "appservice.get_app",
    "aks.list_clusters",          # new
    "aks.get_cluster",            # new
]
```

- [ ] **Step 8: Update `create_compute_agent()` tools list to include new tools**

```python
agent = ChatAgent(
    name="compute-agent",
    tools=[
        query_activity_log,
        query_log_analytics,
        query_resource_health,
        query_monitor_metrics,
        query_os_version,
        # New Phase 32 tools:
        query_vm_extensions,
        query_boot_diagnostics,
        query_vm_sku_options,
        query_disk_health,
        propose_vm_restart,
        propose_vm_resize,
        propose_vm_redeploy,
    ],
)
```

- [ ] **Step 9: Run new tools tests — expect PASS**

```bash
python -m pytest agents/tests/compute/test_compute_new_tools.py -v
```

- [ ] **Step 10: Commit**

```bash
git add agents/compute/tools.py agents/compute/agent.py \
        agents/tests/compute/test_compute_new_tools.py
git commit -m "feat(phase-32): add 7 new Azure VM tools (extensions, boot-diag, SKU, disk, propose_*)"
```

---

## Chunk 3: VMSS Tools

### Task 5: Write failing tests for VMSS tools

**Files:**
- Create: `agents/tests/compute/test_vmss_tools.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for VMSS tools added to compute agent (Phase 32)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _instr_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestQueryVmssInstances:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_instances_list(self, mock_cred, mock_compute_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        inst = MagicMock()
        inst.instance_id = "0"
        inst.properties.provisioning_state = "Succeeded"
        inst.properties.power_state = "running"
        mock_compute.virtual_machine_scale_set_vms.list.return_value = [inst]

        from agents.compute.tools import query_vmss_instances

        result = query_vmss_instances(
            resource_group="rg",
            vmss_name="vmss1",
            subscription_id="sub",
            thread_id="t1",
        )
        assert "instances" in result


class TestQueryVmssAutoscale:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.MonitorManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_autoscale_settings(self, mock_cred, mock_monitor_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_monitor = MagicMock()
        mock_monitor_cls.return_value = mock_monitor
        setting = MagicMock()
        setting.name = "autoscale-vmss1"
        mock_monitor.autoscale_settings.list_by_resource_group.return_value = [setting]

        from agents.compute.tools import query_vmss_autoscale

        result = query_vmss_autoscale(
            resource_group="rg",
            vmss_name="vmss1",
            subscription_id="sub",
            thread_id="t1",
        )
        assert "autoscale_settings" in result


class TestProposeVmssScale:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.create_approval_record")
    def test_creates_approval_record(self, mock_create, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_create.return_value = {"id": "appr_vmss", "status": "pending"}

        from agents.compute.tools import propose_vmss_scale

        result = propose_vmss_scale(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachineScaleSets/vmss1",
            resource_group="rg",
            vmss_name="vmss1",
            subscription_id="sub",
            current_capacity=2,
            target_capacity=4,
            incident_id="inc-001",
            thread_id="t1",
            reason="Scale out due to load",
        )
        mock_create.assert_called_once()
        assert result["status"] == "pending_approval"
```

- [ ] **Step 2: Run test — expect failures**

```bash
python -m pytest agents/tests/compute/test_vmss_tools.py -v 2>&1 | head -10
```

### Task 6: Add VMSS tools to `agents/compute/tools.py`

**Files:**
- Modify: `agents/compute/tools.py`

- [ ] **Step 1: Add `query_vmss_instances` tool**

```python
@ai_function
def query_vmss_instances(
    resource_group: str,
    vmss_name: str,
    subscription_id: str,
    thread_id: str,
) -> dict:
    """List VMSS instances with health state, power state, and provisioning status."""
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer, agent_name="compute-agent", agent_id=agent_id,
        tool_name="query_vmss_instances",
        tool_parameters={"resource_group": resource_group, "vmss_name": vmss_name},
        correlation_id=vmss_name, thread_id=thread_id,
    ):
        if ComputeManagementClient is None:
            return {"error": "azure-mgmt-compute not installed", "instances": []}

        credential = get_credential()
        client = ComputeManagementClient(credential, subscription_id)

        try:
            instances = []
            for inst in client.virtual_machine_scale_set_vms.list(resource_group, vmss_name):
                instances.append({
                    "instance_id": inst.instance_id,
                    "provisioning_state": getattr(inst.properties, "provisioning_state", "Unknown"),
                    "power_state": str(getattr(inst.properties, "power_state", "Unknown")),
                    "vm_id": inst.vm_id or "",
                })
            return {"instances": instances, "vmss_name": vmss_name, "count": len(instances)}
        except Exception as exc:
            logger.warning("query_vmss_instances error: %s", exc)
            return {"error": str(exc), "instances": []}
```

- [ ] **Step 2: Add `query_vmss_autoscale` tool**

```python
@ai_function
def query_vmss_autoscale(
    resource_group: str,
    vmss_name: str,
    subscription_id: str,
    thread_id: str,
) -> dict:
    """Query current autoscale settings and recent scale events for a VMSS."""
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer, agent_name="compute-agent", agent_id=agent_id,
        tool_name="query_vmss_autoscale",
        tool_parameters={"resource_group": resource_group, "vmss_name": vmss_name},
        correlation_id=vmss_name, thread_id=thread_id,
    ):
        if MonitorManagementClient is None:
            return {"error": "azure-mgmt-monitor not installed", "autoscale_settings": []}

        credential = get_credential()
        client = MonitorManagementClient(credential, subscription_id)

        try:
            settings = []
            for s in client.autoscale_settings.list_by_resource_group(resource_group):
                if vmss_name.lower() not in (s.name or "").lower() and \
                   vmss_name.lower() not in str(getattr(s, "target_resource_uri", "")).lower():
                    continue
                profiles = []
                for p in (s.profiles or []):
                    profiles.append({
                        "name": p.name,
                        "min_count": getattr(getattr(p.capacity, "minimum", None), "__str__", lambda: "")(),
                        "max_count": getattr(getattr(p.capacity, "maximum", None), "__str__", lambda: "")(),
                        "default_count": getattr(getattr(p.capacity, "default", None), "__str__", lambda: "")(),
                    })
                settings.append({"name": s.name, "enabled": s.enabled, "profiles": profiles})
            return {"autoscale_settings": settings, "vmss_name": vmss_name}
        except Exception as exc:
            logger.warning("query_vmss_autoscale error: %s", exc)
            return {"error": str(exc), "autoscale_settings": []}
```

- [ ] **Step 3: Add `query_vmss_rolling_upgrade` tool**

```python
@ai_function
def query_vmss_rolling_upgrade(
    resource_group: str,
    vmss_name: str,
    subscription_id: str,
    thread_id: str,
) -> dict:
    """Query rolling upgrade status for a VMSS — policy, progress, and failed instances."""
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer, agent_name="compute-agent", agent_id=agent_id,
        tool_name="query_vmss_rolling_upgrade",
        tool_parameters={"resource_group": resource_group, "vmss_name": vmss_name},
        correlation_id=vmss_name, thread_id=thread_id,
    ):
        if ComputeManagementClient is None:
            return {"error": "azure-mgmt-compute not installed"}

        credential = get_credential()
        client = ComputeManagementClient(credential, subscription_id)

        try:
            upgrade = client.virtual_machine_scale_set_rolling_upgrades.get_latest(
                resource_group, vmss_name
            )
            progress = upgrade.progress
            return {
                "running_instance_count": getattr(progress, "successful_instance_count", 0),
                "failed_instance_count": getattr(progress, "failed_instance_count", 0),
                "pending_instance_count": getattr(progress, "pending_instance_count", 0),
                "provisioning_state": upgrade.provisioning_state or "Unknown",
            }
        except Exception as exc:
            logger.warning("query_vmss_rolling_upgrade error: %s", exc)
            return {"error": str(exc)}
```

- [ ] **Step 4: Add `propose_vmss_scale` tool**

```python
@ai_function
def propose_vmss_scale(
    resource_id: str,
    resource_group: str,
    vmss_name: str,
    subscription_id: str,
    current_capacity: int,
    target_capacity: int,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> dict:
    """Propose manual VMSS scale-out or scale-in — HITL ApprovalRecord only."""
    proposal = {
        "action": "vmss_scale",
        "resource_id": resource_id,
        "vmss_name": vmss_name,
        "current_capacity": current_capacity,
        "target_capacity": target_capacity,
        "reason": reason,
        "description": f"Scale VMSS '{vmss_name}' from {current_capacity} to {target_capacity}: {reason}",
        "target_resources": [resource_id],
        "estimated_impact": "New instances take ~5 min to become healthy",
        "reversible": True,
    }

    record = create_approval_record(
        container=None,
        thread_id=thread_id,
        incident_id=incident_id,
        agent_name="compute-agent",
        proposal=proposal,
        resource_snapshot={"vmss_name": vmss_name, "current_capacity": current_capacity},
        risk_level="medium",
    )

    return {
        "status": "pending_approval",
        "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
        "message": f"VMSS scale proposal: {vmss_name} {current_capacity}→{target_capacity}. Awaiting approval.",
    }
```

- [ ] **Step 5: Run VMSS tool tests — expect PASS**

```bash
python -m pytest agents/tests/compute/test_vmss_tools.py -v
```

- [ ] **Step 6: Commit**

```bash
git add agents/compute/tools.py agents/tests/compute/test_vmss_tools.py
git commit -m "feat(phase-32): add 4 VMSS tools (instances, autoscale, rolling-upgrade, propose_vmss_scale)"
```

---

## Chunk 4: AKS Tools

### Task 7: Write failing tests for AKS tools

**Files:**
- Create: `agents/tests/compute/test_aks_tools.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for AKS tools (Phase 32)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _instr_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestQueryAksClusterHealth:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.ContainerServiceClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_cluster_state(self, mock_cred, mock_aks_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_aks = MagicMock()
        mock_aks_cls.return_value = mock_aks
        cluster = MagicMock()
        cluster.properties.provisioning_state = "Succeeded"
        cluster.properties.kubernetes_version = "1.29.0"
        cluster.properties.power_state.code = "Running"
        mock_aks.managed_clusters.get.return_value = cluster

        from agents.compute.tools import query_aks_cluster_health

        result = query_aks_cluster_health("rg", "aks1", "sub", "t1")
        assert result["provisioning_state"] == "Succeeded"
        assert result["kubernetes_version"] == "1.29.0"


class TestQueryAksNodePools:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id")
    @patch("agents.compute.tools.ContainerServiceClient")
    @patch("agents.compute.tools.get_credential")
    def test_returns_node_pools(self, mock_cred, mock_aks_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_aks = MagicMock()
        mock_aks_cls.return_value = mock_aks
        np = MagicMock()
        np.name = "nodepool1"
        np.properties.count = 3
        np.properties.vm_size = "Standard_D4s_v3"
        np.properties.provisioning_state = "Succeeded"
        mock_aks.agent_pools.list.return_value = [np]

        from agents.compute.tools import query_aks_node_pools

        result = query_aks_node_pools("rg", "aks1", "sub", "t1")
        assert "node_pools" in result
        assert len(result["node_pools"]) == 1
```

- [ ] **Step 2: Run test — expect failures**

```bash
python -m pytest agents/tests/compute/test_aks_tools.py -v 2>&1 | head -10
```

### Task 8: Add AKS tools to `agents/compute/tools.py`

**Files:**
- Modify: `agents/compute/tools.py`

- [ ] **Step 1: Add ContainerServiceClient lazy import**

```python
try:
    from azure.mgmt.containerservice import ContainerServiceClient
except ImportError:
    ContainerServiceClient = None  # type: ignore[assignment,misc]
```

- [ ] **Step 2: Add `query_aks_cluster_health` tool**

```python
@ai_function
def query_aks_cluster_health(
    resource_group: str,
    cluster_name: str,
    subscription_id: str,
    thread_id: str,
) -> dict:
    """Query AKS cluster health — API server status, provisioning state, Kubernetes version."""
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer, agent_name="compute-agent", agent_id=agent_id,
        tool_name="query_aks_cluster_health",
        tool_parameters={"resource_group": resource_group, "cluster_name": cluster_name},
        correlation_id=cluster_name, thread_id=thread_id,
    ):
        if ContainerServiceClient is None:
            return {"error": "azure-mgmt-containerservice not installed"}

        credential = get_credential()
        client = ContainerServiceClient(credential, subscription_id)

        try:
            cluster = client.managed_clusters.get(resource_group, cluster_name)
            props = cluster.properties
            return {
                "cluster_name": cluster_name,
                "provisioning_state": props.provisioning_state or "Unknown",
                "kubernetes_version": props.kubernetes_version or "Unknown",
                "power_state": getattr(getattr(props, "power_state", None), "code", "Unknown"),
                "fqdn": props.fqdn or "",
                "enable_rbac": getattr(props, "enable_rbac", None),
            }
        except Exception as exc:
            logger.warning("query_aks_cluster_health error: %s", exc)
            return {"error": str(exc)}
```

- [ ] **Step 3: Add `query_aks_node_pools`, `query_aks_diagnostics`, `query_aks_upgrade_profile`, `propose_aks_node_pool_scale`**

Follow the same pattern for each:
- `query_aks_node_pools` → `client.agent_pools.list(resource_group, cluster_name)`
- `query_aks_diagnostics` → `LogsQueryClient` with AKS KQL (kube-apiserver errors, pod OOMs)
- `query_aks_upgrade_profile` → `client.managed_clusters.get_upgrade_profile(resource_group, cluster_name)`
- `propose_aks_node_pool_scale` → `create_approval_record()` only (no ARM call)

- [ ] **Step 4: Run AKS tool tests — expect PASS**

```bash
python -m pytest agents/tests/compute/test_aks_tools.py -v
```

- [ ] **Step 5: Commit**

```bash
git add agents/compute/tools.py agents/tests/compute/test_aks_tools.py
git commit -m "feat(phase-32): add 5 AKS tools (cluster-health, node-pools, diagnostics, upgrade, propose_scale)"
```

---

## Chunk 5: Arc Agent Enhancements

### Task 9: Write failing tests for Arc tools

**Files:**
- Create: `agents/tests/arc/test_arc_new_tools.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for new Arc agent tools (Phase 32)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _instr_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestQueryArcExtensionHealth:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.HybridComputeManagementClient")
    @patch("agents.arc.tools.get_credential")
    def test_returns_extension_list(self, mock_cred, mock_hc_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_hc = MagicMock()
        mock_hc_cls.return_value = mock_hc
        ext = MagicMock()
        ext.name = "MicrosoftMonitoringAgent"
        ext.properties.provisioning_state = "Failed"
        ext.properties.type_handler_version = "1.0.0"
        mock_hc.machine_extensions.list.return_value = [ext]

        from agents.arc.tools import query_arc_extension_health

        result = query_arc_extension_health("rg", "arc-vm1", "sub", "t1")
        assert "extensions" in result
        assert len(result["extensions"]) == 1


class TestQueryArcGuestConfig:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.GuestConfigurationClient")
    @patch("agents.arc.tools.get_credential")
    def test_returns_compliance_list(self, mock_cred, mock_gc_cls, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_gc = MagicMock()
        mock_gc_cls.return_value = mock_gc
        report = MagicMock()
        report.name = "WindowsBaseline"
        report.properties.compliance_status = "Compliant"
        mock_gc.guest_configuration_assignment_reports.list.return_value = [report]

        from agents.arc.tools import query_arc_guest_config

        result = query_arc_guest_config("rg", "arc-vm1", "sub", "t1")
        assert "assignments" in result

    def test_uses_guest_configuration_client_not_run_commands(self):
        """Confirm correct SDK: GuestConfigurationClient, NOT machine_run_commands."""
        import inspect

        from agents.arc import tools as arc_tools

        src = inspect.getsource(arc_tools.query_arc_guest_config)
        assert "GuestConfigurationClient" in src
        assert "machine_run_commands" not in src


class TestProposeArcAssessment:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.create_approval_record")
    def test_creates_approval_record(self, mock_create, mock_id, mock_instr):
        mock_instr.return_value = _instr_mock()
        mock_create.return_value = {"id": "appr_arc", "status": "pending"}

        from agents.arc.tools import propose_arc_assessment

        result = propose_arc_assessment(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1",
            machine_name="arc-vm1",
            subscription_id="sub",
            incident_id="inc-001",
            thread_id="t1",
            reason="Refresh patch compliance data",
        )
        mock_create.assert_called_once()
        assert result["status"] == "pending_approval"
```

- [ ] **Step 2: Run test — expect failures**

```bash
python -m pytest agents/tests/arc/test_arc_new_tools.py -v 2>&1 | head -10
```

### Task 10: Add new Arc tools to `agents/arc/tools.py`

**Files:**
- Modify: `agents/arc/tools.py`

- [ ] **Step 1: Add lazy imports**

```python
try:
    from azure.mgmt.hybridcompute import HybridComputeManagementClient
except ImportError:
    HybridComputeManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.guestconfiguration import GuestConfigurationClient
except ImportError:
    GuestConfigurationClient = None  # type: ignore[assignment,misc]
```

- [ ] **Step 2: Add `query_arc_extension_health` tool**

```python
@ai_function
def query_arc_extension_health(
    resource_group: str,
    machine_name: str,
    subscription_id: str,
    thread_id: str,
) -> dict:
    """List Arc extensions with provisioning state and error details."""
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer, agent_name="arc-agent", agent_id=agent_id,
        tool_name="query_arc_extension_health",
        tool_parameters={"machine_name": machine_name},
        correlation_id=machine_name, thread_id=thread_id,
    ):
        if HybridComputeManagementClient is None:
            return {"error": "azure-mgmt-hybridcompute not installed", "extensions": []}

        credential = get_credential()
        client = HybridComputeManagementClient(credential, subscription_id)

        try:
            extensions = []
            for ext in client.machine_extensions.list(resource_group, machine_name):
                extensions.append({
                    "name": ext.name,
                    "provisioning_state": getattr(ext.properties, "provisioning_state", "Unknown"),
                    "type_handler_version": getattr(ext.properties, "type_handler_version", ""),
                    "instance_view": str(getattr(ext.properties, "instance_view", "")),
                })
            return {"extensions": extensions, "machine_name": machine_name}
        except Exception as exc:
            logger.warning("query_arc_extension_health error: %s", exc)
            return {"error": str(exc), "extensions": []}
```

- [ ] **Step 3: Add `query_arc_guest_config` tool**

```python
@ai_function
def query_arc_guest_config(
    resource_group: str,
    machine_name: str,
    subscription_id: str,
    thread_id: str,
) -> dict:
    """Query guest configuration assignment compliance state for an Arc machine.

    Uses azure-mgmt-guestconfiguration (GuestConfigurationClient) —
    NOT machine_run_commands. Returns compliance assignments and status.
    """
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer, agent_name="arc-agent", agent_id=agent_id,
        tool_name="query_arc_guest_config",
        tool_parameters={"machine_name": machine_name},
        correlation_id=machine_name, thread_id=thread_id,
    ):
        if GuestConfigurationClient is None:
            return {"error": "azure-mgmt-guestconfiguration not installed", "assignments": []}

        credential = get_credential()
        client = GuestConfigurationClient(credential, subscription_id)

        try:
            assignments = []
            for report in client.guest_configuration_assignment_reports.list(
                resource_group, machine_name
            ):
                assignments.append({
                    "name": report.name,
                    "compliance_status": getattr(report.properties, "compliance_status", "Unknown"),
                    "last_compliance_time": str(
                        getattr(report.properties, "last_compliance_status_checked", "")
                    ),
                })
            return {"assignments": assignments, "machine_name": machine_name}
        except Exception as exc:
            logger.warning("query_arc_guest_config error: %s", exc)
            return {"error": str(exc), "assignments": []}
```

- [ ] **Step 4: Add `query_arc_connectivity` and `propose_arc_assessment` tools**

```python
@ai_function
def query_arc_connectivity(
    resource_group: str,
    machine_name: str,
    subscription_id: str,
    thread_id: str,
) -> dict:
    """Query Arc machine connectivity status and last heartbeat."""
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer, agent_name="arc-agent", agent_id=agent_id,
        tool_name="query_arc_connectivity",
        tool_parameters={"machine_name": machine_name},
        correlation_id=machine_name, thread_id=thread_id,
    ):
        if HybridComputeManagementClient is None:
            return {"error": "azure-mgmt-hybridcompute not installed"}

        credential = get_credential()
        client = HybridComputeManagementClient(credential, subscription_id)

        try:
            machine = client.machines.get(resource_group, machine_name)
            props = machine.properties
            return {
                "machine_name": machine_name,
                "status": getattr(props, "status", "Unknown"),
                "last_status_change": str(getattr(props, "last_status_change", "")),
                "agent_version": getattr(props, "agent_version", "Unknown"),
                "os_type": getattr(props, "os_type", "Unknown"),
                "os_name": getattr(props, "os_name", "Unknown"),
            }
        except Exception as exc:
            logger.warning("query_arc_connectivity error: %s", exc)
            return {"error": str(exc)}


@ai_function
def propose_arc_assessment(
    resource_id: str,
    machine_name: str,
    subscription_id: str,
    incident_id: str,
    thread_id: str,
    reason: str,
) -> dict:
    """Propose triggering a patch assessment on an Arc VM — HITL ApprovalRecord only."""
    proposal = {
        "action": "arc_patch_assessment",
        "resource_id": resource_id,
        "machine_name": machine_name,
        "subscription_id": subscription_id,
        "reason": reason,
        "description": f"Trigger patch assessment on Arc VM '{machine_name}': {reason}",
        "target_resources": [resource_id],
        "estimated_impact": "Read-only — triggers assessment scan, no changes",
        "reversible": True,
    }

    record = create_approval_record(
        container=None,
        thread_id=thread_id,
        incident_id=incident_id,
        agent_name="arc-agent",
        proposal=proposal,
        resource_snapshot={"machine_name": machine_name},
        risk_level="low",
    )

    return {
        "status": "pending_approval",
        "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
        "message": f"Arc assessment proposal created for '{machine_name}'. Awaiting approval.",
    }
```

- [ ] **Step 5: Run Arc tool tests — expect PASS**

```bash
python -m pytest agents/tests/arc/test_arc_new_tools.py -v
```

- [ ] **Step 6: Commit**

```bash
git add agents/arc/tools.py agents/tests/arc/test_arc_new_tools.py
git commit -m "feat(phase-32): add 4 Arc tools (extension-health, guest-config, connectivity, propose_assessment)"
```

---

## Chunk 6: Final Verification

### Task 11: Phase 32 smoke test

**Files:**
- Create: `agents/tests/integration/test_phase32_smoke.py`

- [ ] **Step 1: Create smoke test**

```python
"""Phase 32 smoke tests — all new tool functions importable and callable."""
from __future__ import annotations

import pytest


class TestPhase32Smoke:
    def test_all_new_compute_tools_importable(self):
        from agents.compute.tools import (
            propose_vm_redeploy,
            propose_vm_resize,
            propose_vm_restart,
            propose_vmss_scale,
            query_aks_cluster_health,
            query_aks_node_pools,
            query_aks_upgrade_profile,
            query_boot_diagnostics,
            query_disk_health,
            query_vm_extensions,
            query_vm_sku_options,
            query_vmss_autoscale,
            query_vmss_instances,
            query_vmss_rolling_upgrade,
        )
        assert all([
            query_vm_extensions, query_boot_diagnostics, query_vm_sku_options, query_disk_health,
            propose_vm_restart, propose_vm_resize, propose_vm_redeploy,
            query_vmss_instances, query_vmss_autoscale, query_vmss_rolling_upgrade, propose_vmss_scale,
            query_aks_cluster_health, query_aks_node_pools, query_aks_upgrade_profile,
        ])

    def test_all_new_arc_tools_importable(self):
        from agents.arc.tools import (
            propose_arc_assessment,
            query_arc_connectivity,
            query_arc_extension_health,
            query_arc_guest_config,
        )
        assert all([
            query_arc_extension_health, query_arc_guest_config,
            query_arc_connectivity, propose_arc_assessment,
        ])

    def test_patch_stubs_fixed(self):
        from agents.patch.tools import query_activity_log, query_resource_health
        import inspect

        src_al = inspect.getsource(query_activity_log)
        src_rh = inspect.getsource(query_resource_health)
        # Real implementations reference the Azure SDK, not "stub" or "not implemented"
        assert "MonitorManagementClient" in src_al or "activity_logs" in src_al
        assert "MicrosoftResourceHealth" in src_rh or "availability_statuses" in src_rh

    def test_propose_tools_no_arm_calls(self):
        from agents.compute import tools as t
        import inspect

        for fn_name in ["propose_vm_restart", "propose_vm_resize", "propose_vm_redeploy"]:
            src = inspect.getsource(getattr(t, fn_name))
            assert "begin_restart" not in src
            assert "begin_update" not in src
            assert "begin_redeploy" not in src
```

- [ ] **Step 2: Run smoke test**

```bash
python -m pytest agents/tests/integration/test_phase32_smoke.py -v
```

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest agents/ services/api-gateway/tests/ -v --tb=short 2>&1 | tail -30
```

- [ ] **Step 4: Final commit**

```bash
git add agents/tests/integration/test_phase32_smoke.py
git commit -m "test(phase-32): add Phase 32 domain depth smoke tests"
```

---

## Phase 32 Done Checklist

- [ ] Patch agent: `query_activity_log` fixed (real SDK call)
- [ ] Patch agent: `query_resource_health` fixed (real SDK call)
- [ ] EOL agent: `query_activity_log` and `query_resource_health` fixed
- [ ] EOL agent: `query_software_inventory` KQL activated
- [ ] 7 new Azure VM tools added to compute agent
- [ ] 4 VMSS tools added to compute agent
- [ ] 5 AKS tools added to compute agent
- [ ] 4 Arc tools added to arc agent
- [ ] All `propose_*` tools verified to not make ARM calls directly
- [ ] Arc `query_arc_guest_config` uses `GuestConfigurationClient` (not `machine_run_commands`)
- [ ] Phase 32 smoke tests pass
- [ ] Total new tools ≥ 17 (spec target met)
