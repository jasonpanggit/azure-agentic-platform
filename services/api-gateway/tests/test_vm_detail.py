"""Tests for GET /api/v1/vms/{id} and GET /api/v1/vms/{id}/metrics."""
from __future__ import annotations

import base64
import os
from unittest.mock import MagicMock, patch, PropertyMock

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


# ---------------------------------------------------------------------------
# Unit tests: _is_arc_vm
# ---------------------------------------------------------------------------

def test_is_arc_vm_true():
    from services.api_gateway.vm_detail import _is_arc_vm

    arc_rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm"
    assert _is_arc_vm(arc_rid) is True


def test_is_arc_vm_false():
    from services.api_gateway.vm_detail import _is_arc_vm

    vm_rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"
    assert _is_arc_vm(vm_rid) is False


# ---------------------------------------------------------------------------
# Unit tests: _check_ama_installed
# ---------------------------------------------------------------------------

@patch("services.api_gateway.vm_detail.requests.get")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_check_ama_installed_windows_200(mock_token, mock_get):
    """AMA Windows agent found → returns True."""
    from services.api_gateway.vm_detail import _check_ama_installed

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    cred = MagicMock()
    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"
    result = _check_ama_installed(cred, rid, "Windows")

    assert result is True
    # Verify correct extension name in URL
    call_url = mock_get.call_args[0][0]
    assert "AzureMonitorWindowsAgent" in call_url


@patch("services.api_gateway.vm_detail.requests.get")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_check_ama_installed_linux_404(mock_token, mock_get):
    """AMA Linux agent not found → returns False."""
    from services.api_gateway.vm_detail import _check_ama_installed

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    cred = MagicMock()
    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"
    result = _check_ama_installed(cred, rid, "Linux")

    assert result is False
    call_url = mock_get.call_args[0][0]
    assert "AzureMonitorLinuxAgent" in call_url


# ---------------------------------------------------------------------------
# Unit tests: _list_dcr_associations
# ---------------------------------------------------------------------------

@patch("services.api_gateway.vm_detail.requests.get")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_list_dcr_associations_found(mock_token, mock_get):
    """Returns list of associations when API returns 200."""
    from services.api_gateway.vm_detail import _list_dcr_associations

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"value": [{"id": "assoc-1"}, {"id": "assoc-2"}]}
    mock_get.return_value = mock_resp

    cred = MagicMock()
    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"
    result = _list_dcr_associations(cred, rid)

    assert len(result) == 2
    assert result[0]["id"] == "assoc-1"


@patch("services.api_gateway.vm_detail.requests.get")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_list_dcr_associations_empty(mock_token, mock_get):
    """Returns empty list on non-200 response."""
    from services.api_gateway.vm_detail import _list_dcr_associations

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    cred = MagicMock()
    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"
    result = _list_dcr_associations(cred, rid)

    assert result == []


# ---------------------------------------------------------------------------
# Unit tests: _ensure_platform_dcr
# ---------------------------------------------------------------------------

@patch("services.api_gateway.vm_detail.requests.put")
@patch("services.api_gateway.vm_detail.requests.get")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_ensure_platform_dcr_success(mock_token, mock_get, mock_put):
    """Creates DCR and returns its resource ID."""
    from services.api_gateway.vm_detail import _ensure_platform_dcr

    # Mock workspace GET → returns location
    ws_resp = MagicMock()
    ws_resp.status_code = 200
    ws_resp.json.return_value = {"location": "eastus"}
    mock_get.return_value = ws_resp

    # Mock DCR PUT → success
    dcr_resp = MagicMock()
    dcr_resp.ok = True
    dcr_resp.json.return_value = {}
    mock_put.return_value = dcr_resp

    cred = MagicMock()
    ws_rid = "/subscriptions/sub1/resourceGroups/rg-la/providers/Microsoft.OperationalInsights/workspaces/ws-prod"
    dcr_id = _ensure_platform_dcr(cred, ws_rid, "sub1", "rg-la")

    assert "aap-dcr" in dcr_id
    assert "sub1" in dcr_id
    mock_put.assert_called_once()


@patch("services.api_gateway.vm_detail.requests.put")
@patch("services.api_gateway.vm_detail.requests.get")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_ensure_platform_dcr_failure(mock_token, mock_get, mock_put):
    """Raises ValueError when DCR PUT fails."""
    from services.api_gateway.vm_detail import _ensure_platform_dcr

    ws_resp = MagicMock()
    ws_resp.status_code = 200
    ws_resp.json.return_value = {"location": "eastus"}
    mock_get.return_value = ws_resp

    dcr_resp = MagicMock()
    dcr_resp.ok = False
    dcr_resp.status_code = 403
    dcr_resp.text = "Forbidden"
    mock_put.return_value = dcr_resp

    cred = MagicMock()
    ws_rid = "/subscriptions/sub1/resourceGroups/rg-la/providers/Microsoft.OperationalInsights/workspaces/ws-prod"

    with pytest.raises(ValueError, match="Failed to create DCR"):
        _ensure_platform_dcr(cred, ws_rid, "sub1", "rg-la")


# ---------------------------------------------------------------------------
# Unit tests: _create_dcr_association
# ---------------------------------------------------------------------------

@patch("services.api_gateway.vm_detail.requests.put")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_create_dcr_association_success(mock_token, mock_put):
    """Calls PUT to associate DCR with VM."""
    from services.api_gateway.vm_detail import _create_dcr_association

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_put.return_value = mock_resp

    cred = MagicMock()
    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"
    dcr_id = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Insights/dataCollectionRules/aap-dcr"

    _create_dcr_association(cred, rid, dcr_id)
    mock_put.assert_called_once()
    call_url = mock_put.call_args[0][0]
    assert "aap-dcr-assoc" in call_url


@patch("services.api_gateway.vm_detail.requests.put")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_create_dcr_association_failure(mock_token, mock_put):
    """Raises ValueError on failure."""
    from services.api_gateway.vm_detail import _create_dcr_association

    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 400
    mock_resp.text = "Bad request"
    mock_put.return_value = mock_resp

    cred = MagicMock()
    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"
    dcr_id = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Insights/dataCollectionRules/aap-dcr"

    with pytest.raises(ValueError, match="Failed to create DCR association"):
        _create_dcr_association(cred, rid, dcr_id)


# ---------------------------------------------------------------------------
# Unit tests: _install_ama_extension
# ---------------------------------------------------------------------------

@patch("services.api_gateway.vm_detail.requests.put")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_install_ama_extension_windows(mock_token, mock_put):
    """Installs Windows AMA extension."""
    from services.api_gateway.vm_detail import _install_ama_extension

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_put.return_value = mock_resp

    cred = MagicMock()
    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"

    _install_ama_extension(cred, rid, "Windows", "eastus")
    call_url = mock_put.call_args[0][0]
    assert "AzureMonitorWindowsAgent" in call_url

    body = mock_put.call_args[1]["json"]
    assert body["properties"]["type"] == "AzureMonitorWindowsAgent"


@patch("services.api_gateway.vm_detail.requests.put")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_install_ama_extension_linux(mock_token, mock_put):
    """Installs Linux AMA extension."""
    from services.api_gateway.vm_detail import _install_ama_extension

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_put.return_value = mock_resp

    cred = MagicMock()
    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"

    _install_ama_extension(cred, rid, "Linux", "westus2")
    call_url = mock_put.call_args[0][0]
    assert "AzureMonitorLinuxAgent" in call_url


@patch("services.api_gateway.vm_detail.requests.put")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_install_ama_extension_409_accepted(mock_token, mock_put):
    """409 (already exists) is not treated as an error."""
    from services.api_gateway.vm_detail import _install_ama_extension

    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 409
    mock_put.return_value = mock_resp

    cred = MagicMock()
    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"

    # Should not raise
    _install_ama_extension(cred, rid, "Linux", "eastus")


@patch("services.api_gateway.vm_detail.requests.put")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_install_ama_extension_failure(mock_token, mock_put):
    """Non-409 failure raises ValueError."""
    from services.api_gateway.vm_detail import _install_ama_extension

    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_put.return_value = mock_resp

    cred = MagicMock()
    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"

    with pytest.raises(ValueError, match="Failed to install AMA"):
        _install_ama_extension(cred, rid, "Linux", "eastus")


# ---------------------------------------------------------------------------
# Endpoint tests: GET /api/v1/vms/{id}/diagnostic-settings
# ---------------------------------------------------------------------------

@patch("services.api_gateway.vm_detail._list_dcr_associations")
@patch("services.api_gateway.vm_detail._check_ama_installed")
def test_get_diag_settings_ama_active(mock_ama, mock_dcr):
    """GET returns configured=true when AMA installed and DCR associated."""
    mock_ama.return_value = True
    mock_dcr.return_value = [{"id": "assoc-1"}]

    from services.api_gateway.main import app
    from fastapi.testclient import TestClient

    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    client = TestClient(app)

    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"
    encoded = _encode(rid)
    resp = client.get(
        f"/api/v1/vms/{encoded}/diagnostic-settings?os_type=Linux",
        headers={"Authorization": "Bearer test-token"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ama_installed"] is True
    assert data["dcr_associated"] is True
    assert data["configured"] is True


@patch("services.api_gateway.vm_detail._list_dcr_associations")
@patch("services.api_gateway.vm_detail._check_ama_installed")
def test_get_diag_settings_not_configured(mock_ama, mock_dcr):
    """GET returns configured=false when AMA not installed."""
    mock_ama.return_value = False
    mock_dcr.return_value = []

    from services.api_gateway.main import app
    from fastapi.testclient import TestClient

    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    client = TestClient(app)

    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"
    encoded = _encode(rid)
    resp = client.get(
        f"/api/v1/vms/{encoded}/diagnostic-settings",
        headers={"Authorization": "Bearer test-token"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ama_installed"] is False
    assert data["dcr_associated"] is False
    assert data["configured"] is False


def test_get_diag_settings_arc_vm_returns_false():
    """Arc VM resource IDs return configured=false without API calls."""
    from services.api_gateway.main import app
    from fastapi.testclient import TestClient

    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    client = TestClient(app)

    arc_rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-srv"
    encoded = _encode(arc_rid)
    resp = client.get(
        f"/api/v1/vms/{encoded}/diagnostic-settings",
        headers={"Authorization": "Bearer test-token"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ama_installed"] is False
    assert data["dcr_associated"] is False
    assert data["configured"] is False


# ---------------------------------------------------------------------------
# Endpoint tests: POST /api/v1/vms/{id}/diagnostic-settings
# ---------------------------------------------------------------------------

@patch("services.api_gateway.vm_detail._install_ama_extension")
@patch("services.api_gateway.vm_detail._create_dcr_association")
@patch("services.api_gateway.vm_detail._ensure_platform_dcr")
@patch("services.api_gateway.vm_detail.requests.get")
@patch("services.api_gateway.vm_detail._arm_token", return_value="fake-token")
def test_enable_diag_settings_success(mock_token, mock_req_get, mock_dcr, mock_assoc, mock_ama):
    """POST enables AMA monitoring: creates DCR, associates, installs AMA."""
    import services.api_gateway.vm_detail as vm_mod

    # Patch the module-level workspace resource ID directly (avoid reload)
    original_ws = vm_mod._LA_WORKSPACE_RESOURCE_ID
    vm_mod._LA_WORKSPACE_RESOURCE_ID = (
        "/subscriptions/sub1/resourceGroups/rg-la/providers/Microsoft.OperationalInsights/workspaces/ws-prod"
    )

    # Mock workspace location fetch
    ws_resp = MagicMock()
    ws_resp.status_code = 200
    ws_resp.json.return_value = {"location": "eastus"}
    mock_req_get.return_value = ws_resp

    mock_dcr.return_value = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Insights/dataCollectionRules/aap-dcr"

    from services.api_gateway.main import app
    from fastapi.testclient import TestClient

    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    client = TestClient(app)

    rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-001"
    encoded = _encode(rid)
    resp = client.post(
        f"/api/v1/vms/{encoded}/diagnostic-settings?os_type=Linux",
        headers={"Authorization": "Bearer test-token"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "enabled"
    assert data["ama_installed"] is True
    assert data["dcr_associated"] is True
    assert data["configured"] is True

    mock_dcr.assert_called_once()
    mock_assoc.assert_called_once()
    mock_ama.assert_called_once()

    # Clean up
    vm_mod._LA_WORKSPACE_RESOURCE_ID = original_ws


def test_enable_diag_settings_arc_vm_rejected():
    """POST returns 400 for Arc VM resource IDs."""
    import services.api_gateway.vm_detail as vm_mod

    original_ws = vm_mod._LA_WORKSPACE_RESOURCE_ID
    vm_mod._LA_WORKSPACE_RESOURCE_ID = (
        "/subscriptions/sub1/resourceGroups/rg-la/providers/Microsoft.OperationalInsights/workspaces/ws-prod"
    )

    from services.api_gateway.main import app
    from fastapi.testclient import TestClient

    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    client = TestClient(app)

    arc_rid = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-srv"
    encoded = _encode(arc_rid)
    resp = client.post(
        f"/api/v1/vms/{encoded}/diagnostic-settings?os_type=Linux",
        headers={"Authorization": "Bearer test-token"},
    )

    assert resp.status_code == 400
    assert "Arc VM" in resp.json()["detail"]

    vm_mod._LA_WORKSPACE_RESOURCE_ID = original_ws
