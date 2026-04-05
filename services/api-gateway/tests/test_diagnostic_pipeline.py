"""Tests for diagnostic_pipeline.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
import asyncio

from services.api_gateway.diagnostic_pipeline import (
    _extract_subscription_id,
    _collect_activity_log,
    _collect_resource_health,
    _collect_metrics,
    _collect_log_analytics,
    _build_evidence_summary,
    run_diagnostic_pipeline,
)

RESOURCE_ID = "/subscriptions/sub-123/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-001"


def test_extract_subscription_id():
    assert _extract_subscription_id(RESOURCE_ID) == "sub-123"


def test_extract_subscription_id_invalid():
    with pytest.raises(ValueError):
        _extract_subscription_id("/invalid/path")


@pytest.mark.asyncio
async def test_collect_activity_log_success():
    mock_event = MagicMock()
    mock_event.event_timestamp.isoformat.return_value = "2026-04-01T10:00:00Z"
    mock_event.operation_name.value = "Microsoft.Compute/virtualMachines/start/action"
    mock_event.caller = "user@example.com"
    mock_event.status.value = "Succeeded"
    mock_event.level.value = "Informational"
    mock_event.description = None

    mock_credential = MagicMock()
    mock_client = MagicMock()
    mock_client.activity_logs.list.return_value = [mock_event]
    mock_monitor_cls = MagicMock(return_value=mock_client)

    mock_monitor_module = MagicMock()
    mock_monitor_module.MonitorManagementClient = mock_monitor_cls

    with patch.dict("sys.modules", {"azure.mgmt.monitor": mock_monitor_module}):
        result = await _collect_activity_log(mock_credential, RESOURCE_ID)

    assert result["status"] == "success"
    assert len(result["entries"]) == 1
    assert result["entries"][0]["operationName"] == "Microsoft.Compute/virtualMachines/start/action"


@pytest.mark.asyncio
async def test_collect_activity_log_error():
    mock_credential = MagicMock()
    mock_monitor_module = MagicMock()
    mock_monitor_module.MonitorManagementClient = MagicMock(side_effect=Exception("Auth failed"))

    with patch.dict("sys.modules", {"azure.mgmt.monitor": mock_monitor_module}):
        result = await _collect_activity_log(mock_credential, RESOURCE_ID)

    assert result["status"] == "error"
    assert "error" in result
    assert result["entries"] == []


@pytest.mark.asyncio
async def test_collect_resource_health_success():
    mock_credential = MagicMock()
    mock_client = MagicMock()
    mock_status = MagicMock()
    mock_status.properties.availability_state.value = "Available"
    mock_status.properties.summary = "Resource is healthy"
    mock_status.properties.reason_type = None
    mock_status.properties.occurred_time = None
    mock_client.availability_statuses.get_by_resource.return_value = mock_status
    mock_health_cls = MagicMock(return_value=mock_client)

    mock_health_module = MagicMock()
    mock_health_module.ResourceHealthMgmtClient = mock_health_cls

    with patch.dict("sys.modules", {"azure.mgmt.resourcehealth": mock_health_module}):
        result = await _collect_resource_health(mock_credential, RESOURCE_ID)

    assert result["status"] == "success"
    assert result["availability_state"] == "Available"


@pytest.mark.asyncio
async def test_collect_log_analytics_skipped_when_no_workspace():
    result = await _collect_log_analytics(MagicMock(), "", RESOURCE_ID, "compute")
    assert result["status"] == "skipped"
    assert result["rows"] == []


def test_build_evidence_summary():
    activity_log = {
        "entries": [
            {
                "eventTimestamp": "2026-04-01T10:00:00Z",
                "operationName": "Microsoft.Compute/virtualMachines/restart/action",
                "caller": "user@example.com",
                "status": "Succeeded",
                "level": "Informational",
                "description": None,
            }
        ]
    }
    resource_health = {"availability_state": "Degraded", "summary": "VM is degraded"}
    metrics = {
        "metrics": [
            {
                "name": "Percentage CPU",
                "unit": "Percent",
                "timeseries": [
                    {
                        "timestamp": "2026-04-01T10:00:00Z",
                        "average": 95.0,
                        "maximum": 99.0,
                        "minimum": 90.0,
                    }
                ],
            }
        ]
    }
    log_analytics = {"rows": [{"RenderedDescription": "Error: disk full"}]}

    summary = _build_evidence_summary(activity_log, resource_health, metrics, log_analytics)

    assert summary["health_state"] == "Degraded"
    assert len(summary["recent_changes"]) == 1
    assert len(summary["metric_anomalies"]) == 1
    assert summary["metric_anomalies"][0]["metric_name"] == "Percentage CPU"
    assert summary["log_errors"]["count"] == 1


@pytest.mark.asyncio
async def test_run_diagnostic_pipeline_no_cosmos():
    """Pipeline should complete without error even when cosmos_client is None."""
    mock_credential = MagicMock()

    with patch(
        "services.api_gateway.diagnostic_pipeline._collect_activity_log",
        return_value={"status": "success", "entries": [], "duration_ms": 10},
    ), patch(
        "services.api_gateway.diagnostic_pipeline._collect_resource_health",
        return_value={"status": "success", "availability_state": "Available", "duration_ms": 10},
    ), patch(
        "services.api_gateway.diagnostic_pipeline._collect_metrics",
        return_value={"status": "success", "metrics": [], "duration_ms": 10},
    ), patch(
        "services.api_gateway.diagnostic_pipeline._collect_log_analytics",
        return_value={"status": "skipped", "rows": [], "duration_ms": 0},
    ):
        # Should not raise even with cosmos_client=None
        await run_diagnostic_pipeline(
            incident_id="inc-001",
            resource_id=RESOURCE_ID,
            domain="compute",
            credential=mock_credential,
            cosmos_client=None,
        )
