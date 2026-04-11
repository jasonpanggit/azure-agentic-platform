"""Tests for GET /api/v1/vms/cost-summary.

Includes a regression test ensuring the /cost-summary route is not
swallowed by the vm_detail wildcard /{resource_id_base64} route.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


def _setup_app_state():
    """Set app.state fields that lifespan normally initializes."""
    from services.api_gateway.main import app

    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    return app


# ---------------------------------------------------------------------------
# Route collision regression test
# ---------------------------------------------------------------------------


def test_cost_summary_route_not_swallowed_by_vm_detail_wildcard():
    """Verify GET /api/v1/vms/cost-summary hits the cost router, NOT the
    vm_detail router's /{resource_id_base64} wildcard.

    Regression test for: cost-tab-base64url-gzip-decode-error
    Before the fix, FastAPI matched "cost-summary" as a base64url-encoded
    resource ID and returned a 400 with:
      "Invalid base64url resource ID: 'utf-8' codec can't decode byte 0x8b
       in position 1: invalid start byte"
    """
    from fastapi.testclient import TestClient

    app = _setup_app_state()
    client = TestClient(app, raise_server_exceptions=False)

    # Mock the Advisor SDK to avoid real Azure calls
    with patch("services.api_gateway.vm_cost.AdvisorManagementClient") as mock_advisor:
        mock_client = MagicMock()
        mock_client.recommendations.list.return_value = []
        mock_advisor.return_value = mock_client

        res = client.get(
            "/api/v1/vms/cost-summary",
            params={"subscription_id": "00000000-0000-0000-0000-000000000001"},
        )

    # Must NOT be a 400 with base64url error
    assert res.status_code == 200, f"Expected 200 but got {res.status_code}: {res.text}"
    data = res.json()
    # Should have the cost-summary response shape, not a vm_detail error
    assert "vms" in data
    assert "base64url" not in res.text.lower()


# ---------------------------------------------------------------------------
# Unit tests: cost-summary endpoint
# ---------------------------------------------------------------------------


def test_cost_summary_returns_empty_when_no_recommendations():
    """Verify empty response when Advisor returns no Cost recommendations."""
    from fastapi.testclient import TestClient

    app = _setup_app_state()
    client = TestClient(app, raise_server_exceptions=False)

    with patch("services.api_gateway.vm_cost.AdvisorManagementClient") as mock_advisor:
        mock_client = MagicMock()
        mock_client.recommendations.list.return_value = []
        mock_advisor.return_value = mock_client

        res = client.get(
            "/api/v1/vms/cost-summary",
            params={"subscription_id": "sub-123"},
        )

    assert res.status_code == 200
    data = res.json()
    assert data["vms"] == []
    assert data["total_recommendations"] == 0
    assert data["subscription_id"] == "sub-123"


def test_cost_summary_returns_error_when_sdk_missing():
    """Verify graceful degradation when azure-mgmt-advisor is not installed."""
    from fastapi.testclient import TestClient

    app = _setup_app_state()
    client = TestClient(app, raise_server_exceptions=False)

    with patch("services.api_gateway.vm_cost.AdvisorManagementClient", None):
        res = client.get(
            "/api/v1/vms/cost-summary",
            params={"subscription_id": "sub-123"},
        )

    assert res.status_code == 200
    data = res.json()
    assert "error" in data
    assert data["vms"] == []


def test_cost_summary_requires_subscription_id():
    """Verify 422 when subscription_id query param is missing."""
    from fastapi.testclient import TestClient

    app = _setup_app_state()
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/v1/vms/cost-summary")

    assert res.status_code == 422


def test_cost_summary_filters_vm_recommendations():
    """Verify that only Cost+VM recommendations are returned."""
    from fastapi.testclient import TestClient

    app = _setup_app_state()
    client = TestClient(app, raise_server_exceptions=False)

    # Build mock recommendations: 1 Cost/VM, 1 Cost/non-VM, 1 non-Cost
    cost_vm_rec = MagicMock()
    cost_vm_rec.category = "Cost"
    cost_vm_rec.impacted_field = "Microsoft.Compute/virtualMachines"
    cost_vm_rec.impacted_value = "vm-expensive"
    cost_vm_rec.impact = "High"
    cost_vm_rec.extended_properties = {
        "currentSku": "Standard_D4s_v3",
        "recommendedSkuName": "Standard_D2s_v3",
        "savingsAmount": "150.00",
        "annualSavingsAmount": "1800.00",
        "savingsCurrency": "USD",
    }
    cost_vm_rec.resource_metadata = MagicMock()
    cost_vm_rec.resource_metadata.resource_id = (
        "/subscriptions/sub-1/resourceGroups/rg-prod/providers/"
        "Microsoft.Compute/virtualMachines/vm-expensive"
    )
    cost_vm_rec.short_description = MagicMock()
    cost_vm_rec.short_description.solution = "Right-size your VM"
    cost_vm_rec.last_updated = None

    cost_storage_rec = MagicMock()
    cost_storage_rec.category = "Cost"
    cost_storage_rec.impacted_field = "Microsoft.Storage/storageAccounts"

    perf_vm_rec = MagicMock()
    perf_vm_rec.category = "Performance"
    perf_vm_rec.impacted_field = "Microsoft.Compute/virtualMachines"

    with patch("services.api_gateway.vm_cost.AdvisorManagementClient") as mock_advisor:
        mock_client = MagicMock()
        mock_client.recommendations.list.return_value = [
            cost_vm_rec,
            cost_storage_rec,
            perf_vm_rec,
        ]
        mock_advisor.return_value = mock_client

        res = client.get(
            "/api/v1/vms/cost-summary",
            params={"subscription_id": "sub-1"},
        )

    assert res.status_code == 200
    data = res.json()
    assert data["total_recommendations"] == 1
    assert len(data["vms"]) == 1
    assert data["vms"][0]["vm_name"] == "vm-expensive"
    assert data["vms"][0]["estimated_monthly_savings"] == 150.0
    assert data["vms"][0]["current_sku"] == "Standard_D4s_v3"
