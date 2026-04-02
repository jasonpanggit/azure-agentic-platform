"""Tests for GET /api/v1/vms/{id} and GET /api/v1/vms/{id}/metrics."""
from __future__ import annotations

import base64
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


def _encode(resource_id: str) -> str:
    """Encode an ARM resource ID as base64url without padding."""
    return base64.urlsafe_b64encode(resource_id.encode()).decode().rstrip("=")


# ---------------------------------------------------------------------------
# Unit tests: _decode_resource_id
# ---------------------------------------------------------------------------

def test_decode_resource_id_valid():
    from services.api_gateway.vm_detail import _decode_resource_id

    rid = "/subscriptions/sub1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-001"
    encoded = _encode(rid)
    assert _decode_resource_id(encoded) == rid


def test_decode_resource_id_with_padding():
    """Accepts base64url strings that already have = padding."""
    from services.api_gateway.vm_detail import _decode_resource_id

    rid = "/subscriptions/abc/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"
    encoded = base64.urlsafe_b64encode(rid.encode()).decode()  # includes padding
    assert _decode_resource_id(encoded) == rid


def test_decode_resource_id_invalid():
    from services.api_gateway.vm_detail import _decode_resource_id

    with pytest.raises(ValueError):
        _decode_resource_id("!!!not-base64!!!")


# ---------------------------------------------------------------------------
# Unit tests: _extract_subscription_id
# ---------------------------------------------------------------------------

def test_extract_subscription_id():
    from services.api_gateway.vm_detail import _extract_subscription_id

    rid = "/subscriptions/abc-123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"
    assert _extract_subscription_id(rid) == "abc-123"


def test_extract_subscription_id_missing():
    from services.api_gateway.vm_detail import _extract_subscription_id

    with pytest.raises(ValueError):
        _extract_subscription_id("/invalid/path")


# ---------------------------------------------------------------------------
# Unit tests: _normalize_power_state
# ---------------------------------------------------------------------------

def test_normalize_power_state():
    from services.api_gateway.vm_detail import _normalize_power_state

    assert _normalize_power_state("VM running") == "running"
    assert _normalize_power_state("VM deallocated") == "deallocated"
    assert _normalize_power_state("VM stopped") == "stopped"
    assert _normalize_power_state("") == "unknown"
    assert _normalize_power_state("RUNNING") == "running"


# ---------------------------------------------------------------------------
# Integration tests: GET /api/v1/vms/{id}
# ---------------------------------------------------------------------------

@patch("services.api_gateway.vm_detail._get_resource_health")
@patch("services.api_gateway.vm_detail._get_vm_details_from_arg")
def test_get_vm_detail_success(mock_arg, mock_health):
    rid = "/subscriptions/sub1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-001"
    mock_arg.return_value = {
        "id": rid,
        "name": "vm-prod-001",
        "resourceGroup": "rg-prod",
        "subscriptionId": "sub1",
        "location": "eastus",
        "vmSize": "Standard_D4s_v5",
        "osType": "Linux",
        "osName": "UbuntuServer",
        "powerState": "VM running",
        "tags": {},
    }
    mock_health.return_value = {"health_state": "Available", "summary": None, "reason_type": None}

    from services.api_gateway.main import app
    from fastapi.testclient import TestClient

    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    client = TestClient(app)

    encoded = _encode(rid)
    resp = client.get(f"/api/v1/vms/{encoded}", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "vm-prod-001"
    assert data["power_state"] == "running"
    assert data["health_state"] == "Available"
    assert data["size"] == "Standard_D4s_v5"
    assert data["os_type"] == "Linux"
    assert data["active_incidents"] == []


@patch("services.api_gateway.vm_detail._get_resource_health")
@patch("services.api_gateway.vm_detail._get_vm_details_from_arg")
def test_get_vm_detail_not_found(mock_arg, mock_health):
    mock_arg.return_value = None
    mock_health.return_value = {"health_state": "Unknown", "summary": None, "reason_type": None}

    from services.api_gateway.main import app
    from fastapi.testclient import TestClient

    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    client = TestClient(app)

    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/missing-vm"
    encoded = _encode(rid)
    resp = client.get(f"/api/v1/vms/{encoded}", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 404


def test_get_vm_detail_bad_encoding():
    from services.api_gateway.main import app
    from fastapi.testclient import TestClient

    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    client = TestClient(app)

    resp = client.get("/api/v1/vms/!!!invalid!!!", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 400
