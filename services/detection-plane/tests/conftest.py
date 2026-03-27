"""Shared fixtures for detection-plane tests.

Provides mock Cosmos DB clients, mock Azure Monitor clients,
mock Event Hub clients, and sample data factories.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_cosmos_container() -> MagicMock:
    """Mock Cosmos DB ContainerProxy for unit tests."""
    container = MagicMock()
    container.query_items.return_value = iter([])
    return container


@pytest.fixture
def mock_credential() -> MagicMock:
    """Mock DefaultAzureCredential."""
    return MagicMock()


@pytest.fixture
def sample_incident_record() -> dict[str, Any]:
    """A complete incident record matching the D-13 schema."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": "inc-test-001",
        "resource_id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1",
        "incident_id": "inc-test-001",
        "severity": "Sev1",
        "domain": "compute",
        "detection_rule": "HighCPU",
        "kql_evidence": "Alert: HighCPU on vm-1 (Sev1) at 2026-03-26T12:00:00Z",
        "status": "new",
        "status_history": [
            {"status": "new", "actor": "system", "timestamp": now}
        ],
        "thread_id": "thread-abc-123",
        "correlated_alerts": [],
        "affected_resources": [
            {
                "resource_id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1",
                "subscription_id": "sub-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
            }
        ],
        "title": "HighCPU on vm-1",
        "description": "CPU utilization exceeded 90% for 5 minutes",
        "duplicate_count": 0,
        "created_at": now,
        "updated_at": now,
        "_etag": "etag-initial-001",
    }


@pytest.fixture
def sample_detection_result() -> dict[str, Any]:
    """A sample DetectionResults row from Eventhouse."""
    return {
        "alert_id": "alert-test-001",
        "severity": "Sev1",
        "domain": "compute",
        "fired_at": "2026-03-26T12:00:00Z",
        "resource_id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "subscription_id": "sub-1",
        "resource_name": "vm-1",
        "alert_rule": "HighCPU",
        "description": "CPU above 90%",
        "kql_evidence": "Alert: HighCPU | Resource: vm-1 | Severity: Sev1",
        "classified_at": "2026-03-26T12:00:05Z",
    }


@pytest.fixture
def sample_raw_alert_payload() -> dict[str, Any]:
    """A sample Common Alert Schema payload (as received from Event Hub)."""
    return {
        "schemaId": "azureMonitorCommonAlertSchema",
        "data": {
            "essentials": {
                "alertId": "/subscriptions/sub-1/providers/Microsoft.AlertsManagement/alerts/alert-test-001",
                "alertRule": "HighCPU",
                "severity": "Sev1",
                "signalType": "Metric",
                "monitorCondition": "Fired",
                "monitoringService": "Platform",
                "alertTargetIDs": [
                    "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1"
                ],
                "configurationItems": ["vm-1"],
                "originAlertId": "alert-test-001",
                "firedDateTime": "2026-03-26T12:00:00.0000000Z",
                "description": "CPU utilization exceeded 90%",
            },
            "alertContext": {},
        },
    }
