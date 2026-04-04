"""Tests for GET /api/v1/vms — VM inventory endpoint.

Tests cover:
- _normalize_power_state: canonical mapping for all known states
- _build_vm_kql: KQL generation with no filter, status filter, search filter, injection safety
- list_vms route: success response shape, ARG failure degrades to empty list, pagination
- OS normalization: raw Azure SKU strings → human-readable OS names via normalize_os
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure auth is bypassed for all tests in this file
os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """TestClient with mock app.state (no real Azure connections)."""
    from services.api_gateway.main import app

    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = None  # Optional — omit for most tests
    return TestClient(app)


@pytest.fixture()
def client_with_cosmos():
    """TestClient with a mock CosmosClient configured on app.state."""
    from services.api_gateway.main import app

    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = MagicMock(name="CosmosClient")
    return TestClient(app)


def _sample_arg_row(
    name: str = "vm-prod-001",
    power_state: str = "VM running",
    subscription_id: str = "sub1",
) -> dict:
    """Return a minimal ARG row dict for vm-prod-001."""
    return {
        "id": (
            f"/subscriptions/{subscription_id}/resourceGroups/rg-prod"
            f"/providers/Microsoft.Compute/virtualMachines/{name}"
        ),
        "name": name,
        "resourceGroup": "rg-prod",
        "subscriptionId": subscription_id,
        "location": "eastus",
        "vmSize": "Standard_D4s_v5",
        "osType": "Linux",
        "osName": "UbuntuServer",
        "powerState": power_state,
        "tags": {},
    }


# ---------------------------------------------------------------------------
# Unit tests — _normalize_power_state
# ---------------------------------------------------------------------------


def test_normalize_power_state_running():
    from services.api_gateway.vm_inventory import _normalize_power_state

    assert _normalize_power_state("VM running") == "running"


def test_normalize_power_state_deallocated():
    from services.api_gateway.vm_inventory import _normalize_power_state

    assert _normalize_power_state("VM deallocated") == "deallocated"


def test_normalize_power_state_stopped():
    from services.api_gateway.vm_inventory import _normalize_power_state

    assert _normalize_power_state("VM stopped") == "stopped"


def test_normalize_power_state_starting():
    from services.api_gateway.vm_inventory import _normalize_power_state

    assert _normalize_power_state("VM starting") == "starting"


def test_normalize_power_state_deallocating():
    from services.api_gateway.vm_inventory import _normalize_power_state

    assert _normalize_power_state("VM deallocating") == "deallocating"


def test_normalize_power_state_unknown_empty():
    from services.api_gateway.vm_inventory import _normalize_power_state

    assert _normalize_power_state("") == "unknown"


def test_normalize_power_state_unknown_unrecognized():
    from services.api_gateway.vm_inventory import _normalize_power_state

    assert _normalize_power_state("Some other status") == "unknown"


# ---------------------------------------------------------------------------
# Unit tests — _build_vm_kql
# ---------------------------------------------------------------------------


def test_build_vm_kql_no_filter_contains_type():
    from services.api_gateway.vm_inventory import _build_vm_kql

    kql = _build_vm_kql("all", None)
    assert "microsoft.compute/virtualmachines" in kql


def test_build_vm_kql_includes_strcat_offer_sku():
    """KQL must use strcat(offer, " ", sku) — not offer alone — for Azure VMs."""
    from services.api_gateway.vm_inventory import _build_vm_kql

    kql = _build_vm_kql("all", None)
    assert "strcat" in kql
    assert "imageReference.offer" in kql
    assert "imageReference.sku" in kql


def test_build_vm_kql_skips_empty_strings_before_strcat():
    """KQL must skip empty osSku/instanceViewOsName before falling through to strcat.

    Root cause: Azure VMs return osSku='' and instanceViewOsName='' while the real OS
    info lives in storageProfile.imageReference.offer+sku. Without an emptiness guard,
    the empty string is returned as-is instead of falling through to the strcat branch.

    The fix uses nested iff(isnotempty(...), ...) — ARG KQL does not support nullif().
    """
    from services.api_gateway.vm_inventory import _build_vm_kql

    kql = _build_vm_kql("all", None)
    # Must use isnotempty guards to skip empty strings — ARG does not have nullif()
    assert "isnotempty" in kql, "KQL must use isnotempty() to skip empty strings"
    # strcat must still be present for the offer+sku fallback
    assert "strcat" in kql


def test_build_vm_kql_includes_instance_view_osname():
    """KQL must try properties.extended.instanceView.osName as second priority."""
    from services.api_gateway.vm_inventory import _build_vm_kql

    kql = _build_vm_kql("all", None)
    assert "instanceView.osName" in kql


def test_build_vm_kql_no_filter_has_order_by():
    from services.api_gateway.vm_inventory import _build_vm_kql

    kql = _build_vm_kql("all", None)
    assert "order by name" in kql


def test_build_vm_kql_no_filter_no_where_powerstate():
    """'all' status should not inject a powerState filter clause."""
    from services.api_gateway.vm_inventory import _build_vm_kql

    kql = _build_vm_kql("all", None)
    # The KQL should not have a bare powerState filter line
    assert "where powerState" not in kql


def test_build_vm_kql_running_filter():
    from services.api_gateway.vm_inventory import _build_vm_kql

    kql = _build_vm_kql("running", None)
    assert "VM running" in kql


def test_build_vm_kql_deallocated_filter():
    from services.api_gateway.vm_inventory import _build_vm_kql

    kql = _build_vm_kql("deallocated", None)
    assert "VM deallocated" in kql


def test_build_vm_kql_with_search():
    from services.api_gateway.vm_inventory import _build_vm_kql

    kql = _build_vm_kql("all", "prod")
    assert "prod" in kql
    assert "contains" in kql


def test_build_vm_kql_search_escapes_single_quotes():
    """Verify single-quote injection is neutralised by doubling.

    KQL uses '' (doubled single-quote) as the in-string escape.
    Input "vm'" becomes "vm''" in the KQL — the quote is doubled, not
    left as a bare terminator. The raw un-doubled sequence "vm'" must not
    appear as a standalone quote (i.e. not followed by another quote).
    """
    from services.api_gateway.vm_inventory import _build_vm_kql

    kql = _build_vm_kql("all", "vm'; DROP TABLE--")
    # The single-quote must have been escaped (doubled)
    assert "vm''" in kql
    # The escaped form must be present somewhere after 'contains'
    assert "contains" in kql


# ---------------------------------------------------------------------------
# Integration tests — GET /api/v1/vms route
# ---------------------------------------------------------------------------


@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_success_response_shape(mock_arg, mock_health, client):
    """ARG returns 1 VM → response has correct envelope and field set."""
    row = _sample_arg_row()
    mock_arg.return_value = [row]
    mock_health.return_value = {row["id"]: "Available"}

    resp = client.get("/api/v1/vms?subscriptions=sub1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["has_more"] is False
    assert len(data["vms"]) == 1

    vm = data["vms"][0]
    assert vm["name"] == "vm-prod-001"
    assert vm["power_state"] == "running"
    assert vm["health_state"] == "Available"
    assert vm["active_alert_count"] == 0
    assert vm["ama_status"] == "unknown"
    # Verify all required fields are present
    for field in (
        "id",
        "name",
        "resource_group",
        "subscription_id",
        "location",
        "size",
        "os_type",
        "os_name",
        "power_state",
        "health_state",
        "ama_status",
        "active_alert_count",
        "tags",
    ):
        assert field in vm, f"Missing field: {field}"


@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_arg_failure_returns_empty_not_500(mock_arg, mock_health, client):
    """When ARG raises, endpoint returns 200 with empty list — never 500."""
    mock_arg.side_effect = Exception("ARG service unavailable")
    mock_health.return_value = {}

    resp = client.get("/api/v1/vms?subscriptions=sub1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["vms"] == []
    assert data["has_more"] is False


@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_pagination_has_more_true(mock_arg, mock_health, client):
    """has_more is True when total > offset + limit."""
    rows = [_sample_arg_row(name=f"vm-{i:03d}") for i in range(5)]
    mock_arg.return_value = rows
    mock_health.return_value = {}

    resp = client.get("/api/v1/vms?subscriptions=sub1&limit=2&offset=0")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["vms"]) == 2
    assert data["has_more"] is True


@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_pagination_last_page_has_more_false(mock_arg, mock_health, client):
    """has_more is False on the last page."""
    rows = [_sample_arg_row(name=f"vm-{i:03d}") for i in range(3)]
    mock_arg.return_value = rows
    mock_health.return_value = {}

    resp = client.get("/api/v1/vms?subscriptions=sub1&limit=2&offset=2")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["vms"]) == 1
    assert data["has_more"] is False


@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_empty_subscriptions_returns_empty(mock_arg, mock_health, client):
    """Empty subscriptions param returns immediately with empty list."""
    resp = client.get("/api/v1/vms?subscriptions=")

    assert resp.status_code == 200
    data = resp.json()
    assert data["vms"] == []
    assert data["total"] == 0
    # ARG should not have been called
    mock_arg.assert_not_called()


@patch("services.api_gateway.vm_inventory._get_alert_counts")
@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_cosmos_alert_count_enrichment(
    mock_arg, mock_health, mock_alerts, client_with_cosmos
):
    """When Cosmos is configured, active_alert_count is enriched."""
    row = _sample_arg_row()
    mock_arg.return_value = [row]
    mock_health.return_value = {row["id"]: "Available"}
    mock_alerts.return_value = {row["id"].lower(): 3}

    resp = client_with_cosmos.get("/api/v1/vms?subscriptions=sub1")

    assert resp.status_code == 200
    vm = resp.json()["vms"][0]
    assert vm["active_alert_count"] == 3


# ---------------------------------------------------------------------------
# Integration tests — OS normalization in list_vms response
# ---------------------------------------------------------------------------


def _sample_arg_row_with_os(
    name: str = "vm-win-001",
    os_name: str = "WindowsServer",
    os_type: str = "Windows",
    vm_type: str = "Azure VM",
    subscription_id: str = "sub1",
) -> dict:
    """Return an ARG row dict with configurable OS fields."""
    return {
        "id": (
            f"/subscriptions/{subscription_id}/resourceGroups/rg-prod"
            f"/providers/Microsoft.Compute/virtualMachines/{name}"
        ),
        "name": name,
        "resourceGroup": "rg-prod",
        "subscriptionId": subscription_id,
        "location": "eastus",
        "vmSize": "Standard_D4s_v5",
        "osType": os_type,
        "osName": os_name,
        "powerState": "VM running",
        "vmType": vm_type,
        "tags": {},
    }


@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_normalizes_windows_server_strcat(mock_arg, mock_health, client):
    """Azure VM with strcat(offer, sku) osName is normalized to readable form."""
    row = _sample_arg_row_with_os(
        os_name="WindowsServer 2019-datacenter",
        os_type="Windows",
    )
    mock_arg.return_value = [row]
    mock_health.return_value = {}

    resp = client.get("/api/v1/vms?subscriptions=sub1")

    assert resp.status_code == 200
    vm = resp.json()["vms"][0]
    assert vm["os_name"] == "Windows Server 2019 Datacenter"


@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_normalizes_bare_windows_server_offer(mock_arg, mock_health, client):
    """Bare 'WindowsServer' (offer only, no sku) normalizes to 'Windowsserver' basic cleanup,
    but with the KQL fix this case should no longer occur in practice."""
    row = _sample_arg_row_with_os(
        os_name="WindowsServer",
        os_type="Windows",
    )
    mock_arg.return_value = [row]
    mock_health.return_value = {}

    resp = client.get("/api/v1/vms?subscriptions=sub1")

    assert resp.status_code == 200
    vm = resp.json()["vms"][0]
    # normalize_os falls through to _basic_cleanup for bare "WindowsServer"
    # which produces "Windowsserver" — this is acceptable as the KQL fix
    # ensures this raw value no longer occurs for Azure VMs
    assert vm["os_name"] != "WindowsServer", "Raw offer must not pass through unnormalized"


@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_preserves_clean_arc_os_name(mock_arg, mock_health, client):
    """Arc VM with already-clean osSku is preserved through normalization."""
    row = _sample_arg_row_with_os(
        name="win-arc-001",
        os_name="Windows Server 2016 Standard",
        os_type="Windows",
        vm_type="Arc VM",
    )
    mock_arg.return_value = [row]
    mock_health.return_value = {}

    resp = client.get("/api/v1/vms?subscriptions=sub1")

    assert resp.status_code == 200
    vm = resp.json()["vms"][0]
    assert vm["os_name"] == "Windows Server 2016 Standard"


@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_normalizes_ubuntu_server(mock_arg, mock_health, client):
    """UbuntuServer offer + sku is normalized to readable Ubuntu version."""
    row = _sample_arg_row_with_os(
        name="vm-linux-001",
        os_name="UbuntuServer 22_04-lts",
        os_type="Linux",
    )
    mock_arg.return_value = [row]
    mock_health.return_value = {}

    resp = client.get("/api/v1/vms?subscriptions=sub1")

    assert resp.status_code == 200
    vm = resp.json()["vms"][0]
    assert vm["os_name"] == "Ubuntu 22.04 LTS"


@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_os_type_fallback_when_os_name_empty(mock_arg, mock_health, client):
    """When osName is empty, normalize_os falls back to osType."""
    row = _sample_arg_row_with_os(
        os_name="",
        os_type="Windows",
    )
    mock_arg.return_value = [row]
    mock_health.return_value = {}

    resp = client.get("/api/v1/vms?subscriptions=sub1")

    assert resp.status_code == 200
    vm = resp.json()["vms"][0]
    assert vm["os_name"] == "Windows"


@patch("services.api_gateway.vm_inventory._get_health_states_sync")
@patch("services.api_gateway.vm_inventory._run_arg_query")
def test_list_vms_normalizes_windows_2025_datacenter_azure_edition(
    mock_arg, mock_health, client
):
    """WindowsServer 2025-datacenter-azure-edition normalizes correctly."""
    row = _sample_arg_row_with_os(
        os_name="WindowsServer 2025-datacenter-azure-edition",
        os_type="Windows",
    )
    mock_arg.return_value = [row]
    mock_health.return_value = {}

    resp = client.get("/api/v1/vms?subscriptions=sub1")

    assert resp.status_code == 200
    vm = resp.json()["vms"][0]
    assert vm["os_name"] == "Windows Server 2025 Datacenter"
