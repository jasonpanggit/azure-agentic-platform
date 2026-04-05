"""Tests for services/api-gateway/tool_executor.py — gateway-side tool executor."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


# ---------------------------------------------------------------------------
# Dispatcher tests
# ---------------------------------------------------------------------------

def test_execute_tool_call_unknown_tool():
    """Unknown tool name returns error JSON with tool_name."""
    from services.api_gateway.tool_executor import execute_tool_call

    result = json.loads(execute_tool_call("nonexistent_tool", "{}"))
    assert "error" in result
    assert "Unknown tool" in result["error"]
    assert result["tool_name"] == "nonexistent_tool"


def test_execute_tool_call_invalid_json_args():
    """Bad JSON args handled gracefully — args default to empty dict."""
    from services.api_gateway.tool_executor import execute_tool_call

    # query_resource_health with invalid JSON should not raise — returns error
    # because azure-mgmt-resourcehealth won't be installed in test env, but the
    # point is it doesn't crash on bad JSON.
    result = json.loads(execute_tool_call("query_resource_health", "not-valid-json!!!"))
    assert isinstance(result, dict)
    assert "resource_id" in result  # function ran (with empty args)


def test_execute_tool_call_dispatches_correctly():
    """Dispatcher routes to the correct function based on tool_name."""
    from services.api_gateway import tool_executor

    called_with = {}

    def fake_activity_log(args: dict) -> dict:
        called_with["fn"] = "activity_log"
        called_with["args"] = args
        return {"query_status": "success", "entries": []}

    original = tool_executor.TOOL_MAP["query_activity_log"]
    tool_executor.TOOL_MAP["query_activity_log"] = fake_activity_log
    try:
        result = json.loads(
            tool_executor.execute_tool_call(
                "query_activity_log",
                json.dumps({"resource_ids": ["/sub/123"], "timespan_hours": 1}),
            )
        )
        assert called_with["fn"] == "activity_log"
        assert called_with["args"]["resource_ids"] == ["/sub/123"]
        assert result["query_status"] == "success"
    finally:
        tool_executor.TOOL_MAP["query_activity_log"] = original


def test_execute_tool_call_dict_args():
    """Dispatcher accepts already-parsed dict args (not just str)."""
    from services.api_gateway import tool_executor

    called = {}

    def fake_fn(args: dict) -> dict:
        called["args"] = args
        return {"ok": True}

    original = tool_executor.TOOL_MAP["query_resource_health"]
    tool_executor.TOOL_MAP["query_resource_health"] = fake_fn
    try:
        result = json.loads(
            tool_executor.execute_tool_call(
                "query_resource_health",
                {"resource_id": "/sub/abc/rg/vm1"},  # dict, not str
            )
        )
        assert result["ok"] is True
        assert called["args"]["resource_id"] == "/sub/abc/rg/vm1"
    finally:
        tool_executor.TOOL_MAP["query_resource_health"] = original


# ---------------------------------------------------------------------------
# _exec_query_activity_log tests
# ---------------------------------------------------------------------------

@patch("services.api_gateway.tool_executor._get_credential")
@patch("services.api_gateway.tool_executor.MonitorManagementClient")
def test_exec_query_activity_log_success(mock_monitor_cls, mock_cred):
    """Mocked MonitorManagementClient returns entries."""
    from services.api_gateway.tool_executor import _exec_query_activity_log

    mock_cred.return_value = MagicMock()

    # Build a fake event
    event = MagicMock()
    event.event_timestamp.isoformat.return_value = "2026-04-05T10:00:00+00:00"
    event.operation_name.value = "Microsoft.Compute/virtualMachines/restart/action"
    event.caller = "user@example.com"
    event.status.value = "Succeeded"
    event.resource_id = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
    event.level.value = "Informational"
    event.description = "VM restarted"

    mock_client = MagicMock()
    mock_client.activity_logs.list.return_value = [event]
    mock_monitor_cls.return_value = mock_client

    result = _exec_query_activity_log({
        "resource_ids": ["/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"],
        "timespan_hours": 2,
    })

    assert result["query_status"] == "success"
    assert len(result["entries"]) == 1
    assert result["entries"][0]["caller"] == "user@example.com"
    assert result["entries"][0]["operationName"] == "Microsoft.Compute/virtualMachines/restart/action"


def test_exec_query_activity_log_sdk_missing():
    """MonitorManagementClient=None returns error dict."""
    from services.api_gateway import tool_executor

    original = tool_executor.MonitorManagementClient
    tool_executor.MonitorManagementClient = None
    try:
        result = tool_executor._exec_query_activity_log({
            "resource_ids": ["/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"],
            "timespan_hours": 1,
        })
        assert result["query_status"] == "error"
        assert "not installed" in result["error"]
        assert result["entries"] == []
    finally:
        tool_executor.MonitorManagementClient = original


# ---------------------------------------------------------------------------
# _exec_query_resource_health tests
# ---------------------------------------------------------------------------

@patch("services.api_gateway.tool_executor._get_credential")
@patch("services.api_gateway.tool_executor.ResourceHealthMgmtClient")
def test_exec_query_resource_health_success(mock_health_cls, mock_cred):
    """Mocked client returns Available state (plain str, not enum)."""
    from services.api_gateway.tool_executor import _exec_query_resource_health

    mock_cred.return_value = MagicMock()

    mock_status = MagicMock()
    # SDK v1.0.0b6+ returns plain str — test the hasattr guard
    mock_status.properties.availability_state = "Available"
    mock_status.properties.summary = "Resource is healthy"
    mock_status.properties.reason_type = "Unplanned"
    mock_status.properties.occurred_time = None

    mock_client = MagicMock()
    mock_client.availability_statuses.get_by_resource.return_value = mock_status
    mock_health_cls.return_value = mock_client

    result = _exec_query_resource_health({
        "resource_id": "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
    })

    assert result["query_status"] == "success"
    assert result["availability_state"] == "Available"
    assert result["summary"] == "Resource is healthy"


@patch("services.api_gateway.tool_executor._get_credential")
@patch("services.api_gateway.tool_executor.ResourceHealthMgmtClient")
def test_exec_query_resource_health_enum_state(mock_health_cls, mock_cred):
    """Mocked client returns enum with .value attribute."""
    from services.api_gateway.tool_executor import _exec_query_resource_health

    mock_cred.return_value = MagicMock()

    enum_state = MagicMock()
    enum_state.value = "Degraded"

    mock_status = MagicMock()
    mock_status.properties.availability_state = enum_state
    mock_status.properties.summary = "Degraded performance"
    mock_status.properties.reason_type = "UserInitiated"
    mock_status.properties.occurred_time = None

    mock_client = MagicMock()
    mock_client.availability_statuses.get_by_resource.return_value = mock_status
    mock_health_cls.return_value = mock_client

    result = _exec_query_resource_health({
        "resource_id": "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
    })

    assert result["query_status"] == "success"
    assert result["availability_state"] == "Degraded"


def test_exec_query_resource_health_sdk_missing():
    """ResourceHealthMgmtClient=None returns Unknown availability_state."""
    from services.api_gateway import tool_executor

    original = tool_executor.ResourceHealthMgmtClient
    tool_executor.ResourceHealthMgmtClient = None
    try:
        result = tool_executor._exec_query_resource_health({
            "resource_id": "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
        })
        assert result["query_status"] == "error"
        assert result["availability_state"] == "Unknown"
        assert "not installed" in result["error"]
    finally:
        tool_executor.ResourceHealthMgmtClient = original


# ---------------------------------------------------------------------------
# _exec_query_monitor_metrics tests
# ---------------------------------------------------------------------------

@patch("services.api_gateway.tool_executor._get_credential")
@patch("services.api_gateway.tool_executor.MonitorManagementClient")
def test_exec_query_monitor_metrics_success(mock_monitor_cls, mock_cred):
    """Mocked client returns timeseries data."""
    from services.api_gateway.tool_executor import _exec_query_monitor_metrics

    mock_cred.return_value = MagicMock()

    # Build fake metric response
    dp = MagicMock()
    dp.time_stamp.isoformat.return_value = "2026-04-05T10:00:00+00:00"
    dp.average = 45.2
    dp.maximum = 78.1
    dp.minimum = 12.3

    ts = MagicMock()
    ts.data = [dp]

    metric = MagicMock()
    metric.name.value = "Percentage CPU"
    metric.unit.value = "Percent"
    metric.timeseries = [ts]

    mock_response = MagicMock()
    mock_response.value = [metric]

    mock_client = MagicMock()
    mock_client.metrics.list.return_value = mock_response
    mock_monitor_cls.return_value = mock_client

    result = _exec_query_monitor_metrics({
        "resource_id": "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
        "metric_names": ["Percentage CPU"],
        "timespan": "PT1H",
    })

    assert result["query_status"] == "success"
    assert len(result["metrics"]) == 1
    assert result["metrics"][0]["name"] == "Percentage CPU"
    assert result["metrics"][0]["timeseries"][0]["average"] == 45.2


# ---------------------------------------------------------------------------
# _exec_query_os_version tests
# ---------------------------------------------------------------------------

@patch("services.api_gateway.tool_executor._get_credential")
@patch("services.api_gateway.tool_executor.ResourceGraphClient")
@patch("services.api_gateway.tool_executor.QueryRequest")
@patch("services.api_gateway.tool_executor.QueryRequestOptions")
def test_exec_query_os_version_success(mock_opts, mock_req, mock_arg_cls, mock_cred):
    """Mocked ARG client returns OS info."""
    from services.api_gateway.tool_executor import _exec_query_os_version

    mock_cred.return_value = MagicMock()

    vm_record = {
        "id": "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
        "name": "vm1",
        "resourceGroup": "rg",
        "subscriptionId": "sub1",
        "osName": "Ubuntu 22.04",
        "osVersion": "22.04",
        "osType": "Linux",
        "resourceType": "vm",
    }

    # First call (VM query) returns the record; second call (Arc query) returns empty
    vm_response = MagicMock()
    vm_response.data = [vm_record]
    vm_response.skip_token = None

    arc_response = MagicMock()
    arc_response.data = []
    arc_response.skip_token = None

    mock_client = MagicMock()
    mock_client.resources.side_effect = [vm_response, arc_response]
    mock_arg_cls.return_value = mock_client

    result = _exec_query_os_version({
        "resource_ids": ["/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"],
        "subscription_ids": ["sub1"],
    })

    assert result["query_status"] == "success"
    assert result["total_count"] == 1
    assert result["machines"][0]["osName"] == "Ubuntu 22.04"


# ---------------------------------------------------------------------------
# _exec_query_log_analytics tests
# ---------------------------------------------------------------------------

def test_exec_query_log_analytics_no_workspace():
    """Empty workspace_id returns skipped status."""
    from services.api_gateway.tool_executor import _exec_query_log_analytics

    result = _exec_query_log_analytics({"kql_query": "Heartbeat | take 5"})
    assert result["query_status"] == "skipped"
    assert result["rows"] == []
