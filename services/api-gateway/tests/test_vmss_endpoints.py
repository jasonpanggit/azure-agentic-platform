from __future__ import annotations
"""Tests for VMSS endpoints — vmss_endpoints.py.

Tests cover:
- _extract_os_image_version: marketplace, gallery, empty fallback
- _get_vmss_instance_counts: ARG VM instance count query
- _get_vmss_health_states: Resource Health API enrichment
- list_vmss: health enrichment preserves ARG-derived state when Resource Health
  returns "Unknown", instance count enrichment from ARG VM query
- _enum_value: Azure SDK enum extraction
"""
import os

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VMSS_RID = (
    "/subscriptions/sub-1/resourceGroups/rg-aks"
    "/providers/Microsoft.Compute/virtualMachineScaleSets/aks-system-12345-vmss"
)
_VMSS_RID_2 = (
    "/subscriptions/sub-1/resourceGroups/rg-aks"
    "/providers/Microsoft.Compute/virtualMachineScaleSets/aks-workload-12345-vmss"
)


@pytest.fixture()
def client():
    """TestClient with mock app.state."""
    from services.api_gateway.main import app

    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = None
    return TestClient(app)


def _sample_arg_row(
    name: str = "aks-system-12345-vmss",
    instance_count: int = 0,
    health_state: str = "available",
    resource_id: str = _VMSS_RID,
) -> dict:
    """Return a minimal ARG row dict for a VMSS."""
    return {
        "id": resource_id,
        "name": name,
        "resourceGroup": "rg-aks",
        "subscriptionId": "sub-1",
        "location": "eastus",
        "sku": "Standard_D4s_v3",
        "instance_count": instance_count,
        "os_type": "Linux",
        "os_image_offer": "",
        "os_image_sku": "",
        "os_image_gallery_id": "/subscriptions/sub-1/providers/Microsoft.Compute/galleries/gal/images/img/versions/202603.12.1",
        "power_state": "running",
        "health_state": health_state,
        "autoscale_raw": "false",
        "active_alert_count": 0,
    }


# ---------------------------------------------------------------------------
# Unit tests — _extract_os_image_version
# ---------------------------------------------------------------------------


def test_extract_os_image_version_marketplace():
    from services.api_gateway.vmss_endpoints import _extract_os_image_version

    assert _extract_os_image_version("UbuntuServer", "18.04-LTS", "") == "UbuntuServer 18.04-LTS"


def test_extract_os_image_version_offer_only():
    from services.api_gateway.vmss_endpoints import _extract_os_image_version

    assert _extract_os_image_version("UbuntuServer", "", "") == "UbuntuServer"


def test_extract_os_image_version_gallery():
    from services.api_gateway.vmss_endpoints import _extract_os_image_version

    gallery_id = "/subscriptions/sub/providers/Microsoft.Compute/galleries/g/images/i/versions/202603.12.1"
    assert _extract_os_image_version("", "", gallery_id) == "202603.12.1"


def test_extract_os_image_version_empty():
    from services.api_gateway.vmss_endpoints import _extract_os_image_version

    assert _extract_os_image_version("", "", "") == ""


# ---------------------------------------------------------------------------
# Unit tests — _enum_value
# ---------------------------------------------------------------------------


def test_enum_value_none():
    from services.api_gateway.vmss_endpoints import _enum_value

    assert _enum_value(None, "fallback") == "fallback"


def test_enum_value_with_value_attr():
    from services.api_gateway.vmss_endpoints import _enum_value

    mock_enum = MagicMock()
    mock_enum.value = "Linux"
    assert _enum_value(mock_enum, "") == "Linux"


def test_enum_value_plain_string():
    from services.api_gateway.vmss_endpoints import _enum_value

    assert _enum_value("Windows", "") == "Windows"


# ---------------------------------------------------------------------------
# Unit tests — _get_vmss_health_states
# ---------------------------------------------------------------------------


def test_get_vmss_health_states_no_sdk():
    """Returns empty dict when Resource Health SDK unavailable."""
    from services.api_gateway import vmss_endpoints

    original = vmss_endpoints._RHClient
    vmss_endpoints._RHClient = None
    try:
        result = vmss_endpoints._get_vmss_health_states([_VMSS_RID], MagicMock())
        assert result == {}
    finally:
        vmss_endpoints._RHClient = original


def test_get_vmss_health_states_available():
    """Returns 'Available' when Resource Health reports it."""
    from services.api_gateway import vmss_endpoints

    mock_rh = MagicMock()
    mock_status = MagicMock()
    mock_status.properties.availability_state = "Available"
    mock_rh.return_value.availability_statuses.get_by_resource.return_value = mock_status

    original = vmss_endpoints._RHClient
    vmss_endpoints._RHClient = mock_rh
    try:
        result = vmss_endpoints._get_vmss_health_states([_VMSS_RID], MagicMock())
        assert result[_VMSS_RID.lower()] == "Available"
    finally:
        vmss_endpoints._RHClient = original


def test_get_vmss_health_states_exception_returns_unknown():
    """Returns 'Unknown' when Resource Health API throws."""
    from services.api_gateway import vmss_endpoints

    mock_rh = MagicMock()
    mock_rh.return_value.availability_statuses.get_by_resource.side_effect = Exception("API error")

    original = vmss_endpoints._RHClient
    vmss_endpoints._RHClient = mock_rh
    try:
        result = vmss_endpoints._get_vmss_health_states([_VMSS_RID], MagicMock())
        assert result[_VMSS_RID.lower()] == "Unknown"
    finally:
        vmss_endpoints._RHClient = original


def test_get_vmss_health_states_invalid_resource_id():
    """Returns 'Unknown' for resource IDs without subscription segment."""
    from services.api_gateway import vmss_endpoints

    original = vmss_endpoints._RHClient
    vmss_endpoints._RHClient = MagicMock()
    try:
        result = vmss_endpoints._get_vmss_health_states(["/invalid/path"], MagicMock())
        assert result["/invalid/path"] == "Unknown"
    finally:
        vmss_endpoints._RHClient = original


# ---------------------------------------------------------------------------
# Unit tests — _get_vmss_instance_counts
# ---------------------------------------------------------------------------


def test_get_vmss_instance_counts_returns_counts():
    """Returns instance counts from ARG VM query."""
    from services.api_gateway import vmss_endpoints

    mock_response = MagicMock()
    mock_response.data = [
        {"vmssId": _VMSS_RID.lower(), "instance_count": 3},
        {"vmssId": _VMSS_RID_2.lower(), "instance_count": 5},
    ]

    with patch.object(vmss_endpoints, "_ARG_AVAILABLE", True):
        mock_client_cls = MagicMock()
        mock_client_cls.return_value.resources.return_value = mock_response
        with patch.object(vmss_endpoints, "ResourceGraphClient", mock_client_cls, create=True), \
             patch.object(vmss_endpoints, "QueryRequest", MagicMock(), create=True):
            result = vmss_endpoints._get_vmss_instance_counts(["sub-1"], MagicMock())
            assert result[_VMSS_RID.lower()] == 3
            assert result[_VMSS_RID_2.lower()] == 5


def test_get_vmss_instance_counts_arg_unavailable():
    """Returns empty dict when ARG SDK unavailable."""
    from services.api_gateway import vmss_endpoints

    with patch.object(vmss_endpoints, "_ARG_AVAILABLE", False):
        result = vmss_endpoints._get_vmss_instance_counts(["sub-1"], MagicMock())
        assert result == {}


def test_get_vmss_instance_counts_exception_returns_empty():
    """Returns empty dict when ARG query throws."""
    from services.api_gateway import vmss_endpoints

    with patch.object(vmss_endpoints, "_ARG_AVAILABLE", True):
        mock_client_cls = MagicMock()
        mock_client_cls.return_value.resources.side_effect = Exception("ARG error")
        with patch.object(vmss_endpoints, "ResourceGraphClient", mock_client_cls, create=True), \
             patch.object(vmss_endpoints, "QueryRequest", MagicMock(), create=True):
            result = vmss_endpoints._get_vmss_instance_counts(["sub-1"], MagicMock())
            assert result == {}


# ---------------------------------------------------------------------------
# Integration tests — list_vmss endpoint
# ---------------------------------------------------------------------------


@patch("services.api_gateway.vmss_endpoints._get_vmss_health_states")
@patch("services.api_gateway.vmss_endpoints._get_vmss_instance_counts")
@patch("services.api_gateway.vmss_endpoints.QueryRequest", create=True)
@patch("services.api_gateway.vmss_endpoints.ResourceGraphClient", create=True)
@patch("azure.identity.DefaultAzureCredential")
def test_list_vmss_preserves_arg_health_when_resource_health_unknown(
    mock_cred_cls,
    mock_arg_cls,
    mock_qr_cls,
    mock_instance_counts,
    mock_health_states,
    client,
):
    """When Resource Health returns 'Unknown', the ARG-derived health_state
    ('available' from provisioningState=Succeeded) is preserved — not
    overwritten with 'unknown'."""
    # ARG returns provisioningState=Succeeded → health_state='available'
    mock_response = MagicMock()
    mock_response.data = [_sample_arg_row(instance_count=0, health_state="available")]
    mock_arg_cls.return_value.resources.return_value = mock_response

    # Instance count enrichment: 3 real instances
    mock_instance_counts.return_value = {_VMSS_RID.lower(): 3}

    # Resource Health returns Unknown (AKS-managed VMSS)
    mock_health_states.return_value = {_VMSS_RID.lower(): "Unknown"}

    with patch("services.api_gateway.vmss_endpoints._ARG_AVAILABLE", True):
        resp = client.get("/api/v1/vmss", params={"subscriptions": "sub-1"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["vmss"]) == 1
    vmss = data["vmss"][0]

    # Health should be preserved from ARG (not overwritten to "unknown")
    assert vmss["health_state"] == "available"
    # Instance count should be enriched from ARG VM query
    assert vmss["instance_count"] == 3
    assert vmss["healthy_instance_count"] == 3


@patch("services.api_gateway.vmss_endpoints._get_vmss_health_states")
@patch("services.api_gateway.vmss_endpoints._get_vmss_instance_counts")
@patch("services.api_gateway.vmss_endpoints.QueryRequest", create=True)
@patch("services.api_gateway.vmss_endpoints.ResourceGraphClient", create=True)
@patch("azure.identity.DefaultAzureCredential")
def test_list_vmss_uses_resource_health_when_definitive(
    mock_cred_cls,
    mock_arg_cls,
    mock_qr_cls,
    mock_instance_counts,
    mock_health_states,
    client,
):
    """When Resource Health returns a definitive state ('Unavailable'),
    it overwrites the ARG-derived health_state."""
    mock_response = MagicMock()
    mock_response.data = [_sample_arg_row(instance_count=2, health_state="available")]
    mock_arg_cls.return_value.resources.return_value = mock_response

    mock_instance_counts.return_value = {}
    # Resource Health says unavailable (definitive — overrides ARG)
    mock_health_states.return_value = {_VMSS_RID.lower(): "Unavailable"}

    with patch("services.api_gateway.vmss_endpoints._ARG_AVAILABLE", True):
        resp = client.get("/api/v1/vmss", params={"subscriptions": "sub-1"})

    assert resp.status_code == 200
    data = resp.json()
    vmss = data["vmss"][0]
    assert vmss["health_state"] == "unavailable"
    assert vmss["power_state"] == "Unavailable"


@patch("services.api_gateway.vmss_endpoints._get_vmss_health_states")
@patch("services.api_gateway.vmss_endpoints._get_vmss_instance_counts")
@patch("services.api_gateway.vmss_endpoints.QueryRequest", create=True)
@patch("services.api_gateway.vmss_endpoints.ResourceGraphClient", create=True)
@patch("azure.identity.DefaultAzureCredential")
def test_list_vmss_instance_count_not_overwritten_when_sku_capacity_nonzero(
    mock_cred_cls,
    mock_arg_cls,
    mock_qr_cls,
    mock_instance_counts,
    mock_health_states,
    client,
):
    """When sku.capacity is already nonzero, the ARG VM instance count
    enrichment does not overwrite it."""
    mock_response = MagicMock()
    mock_response.data = [_sample_arg_row(instance_count=5, health_state="available")]
    mock_arg_cls.return_value.resources.return_value = mock_response

    # ARG VM query says 3 instances, but sku.capacity says 5
    mock_instance_counts.return_value = {_VMSS_RID.lower(): 3}
    mock_health_states.return_value = {}

    with patch("services.api_gateway.vmss_endpoints._ARG_AVAILABLE", True):
        resp = client.get("/api/v1/vmss", params={"subscriptions": "sub-1"})

    assert resp.status_code == 200
    vmss = resp.json()["vmss"][0]
    # sku.capacity was 5 (nonzero), so it should NOT be overwritten by 3
    assert vmss["instance_count"] == 5


@patch("services.api_gateway.vmss_endpoints._get_vmss_health_states")
@patch("services.api_gateway.vmss_endpoints._get_vmss_instance_counts")
@patch("services.api_gateway.vmss_endpoints.QueryRequest", create=True)
@patch("services.api_gateway.vmss_endpoints.ResourceGraphClient", create=True)
@patch("azure.identity.DefaultAzureCredential")
def test_list_vmss_resource_health_available_sets_power_running(
    mock_cred_cls,
    mock_arg_cls,
    mock_qr_cls,
    mock_instance_counts,
    mock_health_states,
    client,
):
    """When Resource Health returns 'Available', power_state is set to 'Running'."""
    mock_response = MagicMock()
    mock_response.data = [_sample_arg_row(instance_count=2, health_state="available")]
    mock_arg_cls.return_value.resources.return_value = mock_response

    mock_instance_counts.return_value = {}
    mock_health_states.return_value = {_VMSS_RID.lower(): "Available"}

    with patch("services.api_gateway.vmss_endpoints._ARG_AVAILABLE", True):
        resp = client.get("/api/v1/vmss", params={"subscriptions": "sub-1"})

    assert resp.status_code == 200
    vmss = resp.json()["vmss"][0]
    assert vmss["health_state"] == "available"
    assert vmss["power_state"] == "Running"


def test_list_vmss_sdk_unavailable(client):
    """Returns empty list when ARG SDK unavailable."""
    from services.api_gateway import vmss_endpoints

    with patch.object(vmss_endpoints, "_ARG_AVAILABLE", False):
        resp = client.get("/api/v1/vmss", params={"subscriptions": "sub-1"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["vmss"] == []
    assert data["total"] == 0


# ---------------------------------------------------------------------------
# Unit tests — vmss_detail: _derive_instance_fields via the detail endpoint
# ---------------------------------------------------------------------------

import base64 as _b64


def _encode_resource_id(rid: str) -> str:
    return _b64.urlsafe_b64encode(rid.encode()).decode().rstrip("=")


def _make_mock_instance(
    instance_id: str = "10",
    name: str = "vmss_10",
    provisioning_state: str = "Succeeded",
    status_codes: list[str] | None = None,
    vm_health_code: str | None = None,
) -> MagicMock:
    """Build a MagicMock resembling an azure-mgmt-compute VirtualMachineScaleSetVM."""
    inst = MagicMock()
    inst.instance_id = instance_id
    inst.name = name
    inst.provisioning_state = provisioning_state

    if status_codes is None:
        status_codes = ["ProvisioningState/succeeded", "PowerState/running"]

    statuses = []
    for code in status_codes:
        s = MagicMock()
        s.code = code
        if code.lower().startswith("powerstate/"):
            s.display_status = "VM " + code.split("/")[1]
        else:
            s.display_status = "Provisioning " + code.split("/")[1]
        statuses.append(s)

    inst.instance_view = MagicMock()
    inst.instance_view.statuses = statuses

    if vm_health_code is not None:
        vh = MagicMock()
        vh.status = MagicMock()
        vh.status.code = vm_health_code
        inst.instance_view.vm_health = vh
    else:
        inst.instance_view.vm_health = None

    return inst


def _make_mock_vmss(sku_capacity: int = 2) -> MagicMock:
    vmss = MagicMock()
    vmss.sku = MagicMock()
    vmss.sku.capacity = sku_capacity
    vmss.id = _VMSS_RID
    vmss.name = "aks-system-12345-vmss"
    return vmss


import sys as _sys
import contextlib as _contextlib


@_contextlib.contextmanager
def _inject_compute_sdk(mock_compute_instance: MagicMock):
    """Inject mock azure.mgmt.compute and azure.identity into sys.modules so that
    inline `from azure.mgmt.compute import ComputeManagementClient` inside
    vmss_detail resolves to a MagicMock class that returns mock_compute_instance.
    """
    from services.api_gateway import vmss_endpoints

    mock_cmc_cls = MagicMock(return_value=mock_compute_instance)
    mock_compute_mod = MagicMock()
    mock_compute_mod.ComputeManagementClient = mock_cmc_cls

    mock_identity_mod = MagicMock()
    mock_identity_mod.DefaultAzureCredential = MagicMock(return_value=MagicMock())

    saved = {
        "azure.mgmt.compute": _sys.modules.get("azure.mgmt.compute"),
        "azure.identity": _sys.modules.get("azure.identity"),
    }
    _sys.modules["azure.mgmt.compute"] = mock_compute_mod
    _sys.modules["azure.identity"] = mock_identity_mod

    original_arg = vmss_endpoints._ARG_AVAILABLE
    vmss_endpoints._ARG_AVAILABLE = True
    try:
        yield
    finally:
        vmss_endpoints._ARG_AVAILABLE = original_arg
        for key, val in saved.items():
            if val is None:
                _sys.modules.pop(key, None)
            else:
                _sys.modules[key] = val


@patch("services.api_gateway.vmss_endpoints._get_vmss_health_states")
def test_vmss_detail_instance_running_provisioned_becomes_healthy(
    mock_health_states, client
):
    """Instance with PowerState/running + ProvisioningState/succeeded → health_state='healthy'."""
    mock_health_states.return_value = {}
    encoded = _encode_resource_id(_VMSS_RID)

    mock_compute = MagicMock()
    mock_compute.virtual_machine_scale_sets.get.return_value = _make_mock_vmss(sku_capacity=2)
    mock_compute.virtual_machine_scale_set_vms.list.return_value = iter([
        _make_mock_instance(
            instance_id="10",
            name="aks-system-12345-vmss_10",
            status_codes=["ProvisioningState/succeeded", "PowerState/running"],
        )
    ])

    with _inject_compute_sdk(mock_compute):
        resp = client.get(f"/api/v1/vmss/{encoded}")

    assert resp.status_code == 200
    data = resp.json()
    instances = data.get("instances", [])
    assert len(instances) == 1
    assert instances[0]["health_state"] == "healthy"
    assert "running" in instances[0]["power_state"].lower()


@patch("services.api_gateway.vmss_endpoints._get_vmss_health_states")
def test_vmss_detail_instance_failed_provisioning_becomes_degraded(
    mock_health_states, client
):
    """Instance with ProvisioningState/failed → health_state='degraded'."""
    mock_health_states.return_value = {}
    encoded = _encode_resource_id(_VMSS_RID)

    mock_compute = MagicMock()
    mock_compute.virtual_machine_scale_sets.get.return_value = _make_mock_vmss(sku_capacity=1)
    mock_compute.virtual_machine_scale_set_vms.list.return_value = iter([
        _make_mock_instance(
            instance_id="0",
            name="aks-system-12345-vmss_0",
            provisioning_state="Failed",
            status_codes=["ProvisioningState/failed"],
        )
    ])

    with _inject_compute_sdk(mock_compute):
        resp = client.get(f"/api/v1/vmss/{encoded}")

    assert resp.status_code == 200
    instances = resp.json().get("instances", [])
    assert len(instances) == 1
    assert instances[0]["health_state"] == "degraded"


@patch("services.api_gateway.vmss_endpoints._get_vmss_health_states")
def test_vmss_detail_instance_vm_health_extension_takes_priority(
    mock_health_states, client
):
    """When vmHealth extension is present its code takes priority over derived state."""
    mock_health_states.return_value = {}
    encoded = _encode_resource_id(_VMSS_RID)

    mock_compute = MagicMock()
    mock_compute.virtual_machine_scale_sets.get.return_value = _make_mock_vmss(sku_capacity=1)
    mock_compute.virtual_machine_scale_set_vms.list.return_value = iter([
        _make_mock_instance(
            instance_id="0",
            name="aks-system-12345-vmss_0",
            status_codes=["ProvisioningState/succeeded", "PowerState/running"],
            vm_health_code="HealthState/unhealthy",
        )
    ])

    with _inject_compute_sdk(mock_compute):
        resp = client.get(f"/api/v1/vmss/{encoded}")

    assert resp.status_code == 200
    instances = resp.json().get("instances", [])
    assert len(instances) == 1
    assert instances[0]["health_state"] == "unhealthy"


@patch("services.api_gateway.vmss_endpoints._get_vmss_health_states")
def test_vmss_detail_power_state_read_explicitly_not_last_status(
    mock_health_states, client
):
    """power_state is read from PowerState/* status code, not assumed to be statuses[-1]."""
    mock_health_states.return_value = {}
    encoded = _encode_resource_id(_VMSS_RID)

    mock_compute = MagicMock()
    mock_compute.virtual_machine_scale_sets.get.return_value = _make_mock_vmss(sku_capacity=1)
    # Put PowerState first, ProvisioningState second — opposite of typical Azure order
    mock_compute.virtual_machine_scale_set_vms.list.return_value = iter([
        _make_mock_instance(
            instance_id="0",
            name="aks-system-12345-vmss_0",
            status_codes=["PowerState/running", "ProvisioningState/succeeded"],
        )
    ])

    with _inject_compute_sdk(mock_compute):
        resp = client.get(f"/api/v1/vmss/{encoded}")

    assert resp.status_code == 200
    instances = resp.json().get("instances", [])
    assert len(instances) == 1
    # Regardless of status order, power_state must reflect the PowerState/* code
    assert "running" in instances[0]["power_state"].lower()
    assert instances[0]["health_state"] == "healthy"
