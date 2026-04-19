"""Tests for database_health_service — Phase 105."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.api_gateway.database_health_service import _classify, scan_database_health


# ---------------------------------------------------------------------------
# _classify tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state,expected_status", [
    ("Succeeded", "healthy"),
    ("Ready", "healthy"),
    ("Online", "healthy"),
    ("Creating", "provisioning"),
    ("Updating", "provisioning"),
    ("Deleting", "stopped"),
    ("Disabled", "stopped"),
    ("Stopped", "stopped"),
    ("Failed", "failed"),
])
def test_classify_states(state: str, expected_status: str) -> None:
    row = {"state": state, "db_type": "cosmos", "name": "test-account"}
    status, findings = _classify(row)
    assert status == expected_status


def test_classify_healthy_has_no_findings() -> None:
    row = {"state": "Succeeded", "db_type": "postgresql", "name": "pg-server"}
    status, findings = _classify(row)
    assert status == "healthy"
    assert findings == []


def test_classify_stopped_has_finding() -> None:
    row = {"state": "Stopped", "db_type": "sql", "name": "sql-db"}
    status, findings = _classify(row)
    assert status == "stopped"
    assert len(findings) == 1
    assert "stopped" in findings[0].lower() or "traffic" in findings[0].lower()


# ---------------------------------------------------------------------------
# scan_database_health tests
# ---------------------------------------------------------------------------

def test_scan_returns_list_of_records() -> None:
    mock_rows = [
        {
            "resource_id": "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.DocumentDB/databaseAccounts/cosmos1",
            "name": "cosmos1",
            "db_type": "cosmos",
            "resource_group": "rg",
            "subscription_id": "sub1",
            "location": "eastus",
            "state": "Succeeded",
            "sku_name": "",
            "version": "",
            "tags": {},
        }
    ]
    with patch("azure.identity.DefaultAzureCredential"), \
         patch("services.api_gateway.arg_helper.run_arg_query", return_value=mock_rows):
        results = scan_database_health(["sub1"])

    assert len(results) == 1
    assert results[0]["name"] == "cosmos1"
    assert results[0]["health_status"] == "healthy"
    assert "findings" in results[0]
    assert "scanned_at" in results[0]


def test_scan_never_raises_on_arg_error() -> None:
    with patch("azure.identity.DefaultAzureCredential"), \
         patch("services.api_gateway.arg_helper.run_arg_query", side_effect=Exception("ARG down")):
        results = scan_database_health(["sub1"])
    assert results == []


def test_scan_returns_empty_on_no_results() -> None:
    with patch("azure.identity.DefaultAzureCredential"), \
         patch("services.api_gateway.arg_helper.run_arg_query", return_value=[]):
        results = scan_database_health(["sub1"])
    assert results == []
