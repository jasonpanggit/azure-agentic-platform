"""Tests for vm_chat_tools.py — live Azure SDK tool functions."""
from __future__ import annotations

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


RID = "/subscriptions/sub-abc/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm1"
CREDENTIAL = MagicMock()


# ---------------------------------------------------------------------------
# Helpers: inject fake SDK modules so lazy imports inside tool functions work
# ---------------------------------------------------------------------------

def _inject_monitor(mock_client_instance):
    """Inject azure.mgmt.monitor with a mock MonitorManagementClient."""
    mod = ModuleType("azure.mgmt.monitor")
    mod.MonitorManagementClient = MagicMock(return_value=mock_client_instance)
    sys.modules["azure.mgmt.monitor"] = mod
    return mod


def _inject_resourcehealth(mock_client_instance):
    mod = ModuleType("azure.mgmt.resourcehealth")
    mod.ResourceHealthMgmtClient = MagicMock(return_value=mock_client_instance)
    sys.modules["azure.mgmt.resourcehealth"] = mod
    return mod


def _inject_resourcegraph(mock_client_instance):
    mod = ModuleType("azure.mgmt.resourcegraph")
    models_mod = ModuleType("azure.mgmt.resourcegraph.models")
    models_mod.QueryRequest = MagicMock(return_value=MagicMock())
    mod.ResourceGraphClient = MagicMock(return_value=mock_client_instance)
    sys.modules["azure.mgmt.resourcegraph"] = mod
    sys.modules["azure.mgmt.resourcegraph.models"] = models_mod
    return mod


# ---------------------------------------------------------------------------
# _extract_subscription_id
# ---------------------------------------------------------------------------

def test_extract_subscription_id():
    from services.api_gateway.vm_chat_tools import _extract_subscription_id
    assert _extract_subscription_id(RID) == "sub-abc"


# ---------------------------------------------------------------------------
# get_vm_metrics
# ---------------------------------------------------------------------------

def _make_mock_metrics_client():
    dp = MagicMock()
    dp.time_stamp = MagicMock()
    dp.time_stamp.isoformat.return_value = "2026-04-17T00:00:00+00:00"
    dp.average = 42.5
    dp.maximum = 80.0
    dp.minimum = 10.0

    ts = MagicMock()
    ts.data = [dp]

    metric = MagicMock()
    metric.name = "Percentage CPU"
    metric.unit = "Percent"
    metric.timeseries = [ts]

    response = MagicMock()
    response.value = [metric]

    client = MagicMock()
    client.metrics.list.return_value = response
    return client


def test_get_vm_metrics_success():
    from services.api_gateway.vm_chat_tools import get_vm_metrics
    _inject_monitor(_make_mock_metrics_client())

    result = get_vm_metrics(RID, CREDENTIAL, metric_names=["Percentage CPU"])

    assert result["query_status"] == "success"
    assert "Percentage CPU" in result["metrics"]
    assert result["metrics"]["Percentage CPU"]["datapoints"][0]["average"] == 42.5


def test_get_vm_metrics_error_returns_structured():
    from services.api_gateway.vm_chat_tools import get_vm_metrics

    mod = ModuleType("azure.mgmt.monitor")
    mod.MonitorManagementClient = MagicMock(side_effect=Exception("Subscription not found"))
    sys.modules["azure.mgmt.monitor"] = mod

    result = get_vm_metrics(RID, CREDENTIAL)
    assert result["query_status"] == "error"
    assert "Subscription not found" in result["error"]


# ---------------------------------------------------------------------------
# get_activity_logs
# ---------------------------------------------------------------------------

def _make_mock_activity_client():
    event = MagicMock()
    event.event_timestamp = MagicMock()
    event.event_timestamp.isoformat.return_value = "2026-04-17T00:00:00+00:00"
    event.operation_name = "Microsoft.Compute/virtualMachines/restart/action"
    event.caller = "user@example.com"
    event.status = "Succeeded"
    event.level = "Informational"
    event.description = None

    client = MagicMock()
    client.activity_logs.list.return_value = [event]
    return client


def test_get_activity_logs_success():
    from services.api_gateway.vm_chat_tools import get_activity_logs
    _inject_monitor(_make_mock_activity_client())

    result = get_activity_logs(RID, CREDENTIAL)

    assert result["query_status"] == "success"
    assert result["event_count"] == 1
    assert result["events"][0]["caller"] == "user@example.com"


def test_get_activity_logs_error_returns_structured():
    from services.api_gateway.vm_chat_tools import get_activity_logs

    mod = ModuleType("azure.mgmt.monitor")
    mod.MonitorManagementClient = MagicMock(side_effect=Exception("Auth failed"))
    sys.modules["azure.mgmt.monitor"] = mod

    result = get_activity_logs(RID, CREDENTIAL)
    assert result["query_status"] == "error"
    assert "Auth failed" in result["error"]


# ---------------------------------------------------------------------------
# get_resource_health
# ---------------------------------------------------------------------------

def _make_mock_health_client(state_str="Available"):
    props = MagicMock()
    props.availability_state = state_str
    props.summary = "The VM is available."
    props.reason_type = None
    props.occurred_time = None

    status = MagicMock()
    status.properties = props

    client = MagicMock()
    client.availability_statuses.get_by_resource.return_value = status
    return client


def test_get_resource_health_success():
    from services.api_gateway.vm_chat_tools import get_resource_health
    _inject_resourcehealth(_make_mock_health_client("Available"))

    result = get_resource_health(RID, CREDENTIAL)

    assert result["query_status"] == "success"
    assert result["health_state"] == "Available"


def test_get_resource_health_error_returns_structured():
    from services.api_gateway.vm_chat_tools import get_resource_health

    mod = ModuleType("azure.mgmt.resourcehealth")
    mod.ResourceHealthMgmtClient = MagicMock(side_effect=Exception("Not found"))
    sys.modules["azure.mgmt.resourcehealth"] = mod

    result = get_resource_health(RID, CREDENTIAL)
    assert result["query_status"] == "error"


# ---------------------------------------------------------------------------
# get_vm_power_state
# ---------------------------------------------------------------------------

def _make_mock_arg_client(power_state="VM running"):
    row = {
        "name": "vm1",
        "location": "eastus2",
        "vmSize": "Standard_D2s_v3",
        "osType": "Windows",
        "powerState": power_state,
    }
    resp = MagicMock()
    resp.data = [row]

    client = MagicMock()
    client.resources.return_value = resp
    return client


def test_get_vm_power_state_running():
    from services.api_gateway.vm_chat_tools import get_vm_power_state
    _inject_resourcegraph(_make_mock_arg_client("VM running"))

    result = get_vm_power_state(RID, CREDENTIAL)
    assert result["query_status"] == "success"
    assert result["power_state"] == "running"


def test_get_vm_power_state_deallocated():
    from services.api_gateway.vm_chat_tools import get_vm_power_state
    _inject_resourcegraph(_make_mock_arg_client("VM deallocated"))

    result = get_vm_power_state(RID, CREDENTIAL)
    assert result["power_state"] == "deallocated"


def test_get_vm_power_state_not_found():
    from services.api_gateway.vm_chat_tools import get_vm_power_state

    resp = MagicMock()
    resp.data = []
    client = MagicMock()
    client.resources.return_value = resp
    _inject_resourcegraph(client)

    result = get_vm_power_state(RID, CREDENTIAL)
    assert result["query_status"] == "not_found"


def test_get_vm_power_state_error_returns_structured():
    from services.api_gateway.vm_chat_tools import get_vm_power_state

    mod = ModuleType("azure.mgmt.resourcegraph")
    mod.ResourceGraphClient = MagicMock(side_effect=Exception("Permission denied"))
    models_mod = ModuleType("azure.mgmt.resourcegraph.models")
    models_mod.QueryRequest = MagicMock()
    sys.modules["azure.mgmt.resourcegraph"] = mod
    sys.modules["azure.mgmt.resourcegraph.models"] = models_mod

    result = get_vm_power_state(RID, CREDENTIAL)
    assert result["query_status"] == "error"


# ---------------------------------------------------------------------------
# dispatch_tool_call
# ---------------------------------------------------------------------------

def test_dispatch_tool_call_unknown_tool():
    from services.api_gateway.vm_chat_tools import dispatch_tool_call

    result_json = dispatch_tool_call("nonexistent_tool", {}, RID, CREDENTIAL)
    result = json.loads(result_json)
    assert result["query_status"] == "error"
    assert "Unknown tool" in result["error"]


def test_dispatch_tool_call_routes_to_power_state():
    from services.api_gateway.vm_chat_tools import dispatch_tool_call

    with patch("services.api_gateway.vm_chat_tools.get_vm_power_state",
               return_value={"query_status": "success", "power_state": "running"}) as mock_fn:
        result_json = dispatch_tool_call("get_vm_power_state", {}, RID, CREDENTIAL)
        mock_fn.assert_called_once_with(resource_id=RID, credential=CREDENTIAL)

    result = json.loads(result_json)
    assert result["power_state"] == "running"


# ---------------------------------------------------------------------------
# Tool schemas — structure validation
# ---------------------------------------------------------------------------

def test_tool_schemas_have_required_fields():
    from services.api_gateway.vm_chat_tools import VM_CHAT_TOOL_SCHEMAS

    assert len(VM_CHAT_TOOL_SCHEMAS) == 4
    names = {t["function"]["name"] for t in VM_CHAT_TOOL_SCHEMAS}
    assert names == {"get_vm_metrics", "get_activity_logs", "get_resource_health", "get_vm_power_state"}

    for tool in VM_CHAT_TOOL_SCHEMAS:
        assert tool["type"] == "function"
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]
