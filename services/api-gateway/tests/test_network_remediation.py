"""Tests for network_remediation.py — Phase 108-3.

Covers:
  - _fix_firewall_threatintel: happy path + SDK error
  - _fix_pe_approve: happy path + SDK error
  - execute_network_remediation: routing (safe, unsafe, unknown)
  - POST /api/v1/network-topology/remediate: executed, approval_pending, 404, require_approval
  - Integration: cache invalidation + WAL write
  - Integration: HITL path for non-safe issue type
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_firewall_issue(issue_id: str = "fw001") -> dict:
    return {
        "id": issue_id,
        "type": "firewall_threatintel_off",
        "severity": "high",
        "title": "Firewall Threat Intelligence Disabled",
        "affected_resource_id": (
            "/subscriptions/sub-1/resourceGroups/rg-net/providers/"
            "Microsoft.Network/azureFirewalls/fw-prod"
        ),
        "affected_resource_name": "fw-prod",
        "auto_fix_available": True,
        "auto_fix_label": "Enable ThreatIntel Alert",
        "related_resource_ids": [],
        "remediation_steps": [],
        "portal_link": "",
        "explanation": "",
        "impact": "",
    }


def _make_pe_issue(issue_id: str = "pe001") -> dict:
    return {
        "id": issue_id,
        "type": "pe_not_approved",
        "severity": "critical",
        "title": "Private Endpoint Not Approved",
        "affected_resource_id": (
            "/subscriptions/sub-1/resourceGroups/rg-net/providers/"
            "Microsoft.Network/privateEndpoints/pe-storage"
        ),
        "affected_resource_name": "pe-storage",
        "auto_fix_available": True,
        "auto_fix_label": "Approve connection",
        "related_resource_ids": [],
        "remediation_steps": [],
        "portal_link": "",
        "explanation": "",
        "impact": "",
    }


def _make_subnet_issue(issue_id: str = "sn001") -> dict:
    return {
        "id": issue_id,
        "type": "subnet_no_nsg",
        "severity": "high",
        "title": "Subnet Without NSG",
        "affected_resource_id": (
            "/subscriptions/sub-1/resourceGroups/rg-net/providers/"
            "Microsoft.Network/virtualNetworks/vnet-1/subnets/subnet-1"
        ),
        "affected_resource_name": "subnet-1",
        "auto_fix_available": False,
        "auto_fix_label": None,
        "related_resource_ids": [],
        "remediation_steps": [],
        "portal_link": "",
        "explanation": "",
        "impact": "",
    }


# ---------------------------------------------------------------------------
# Unit tests: _fix_firewall_threatintel
# ---------------------------------------------------------------------------

class TestFixFirewallThreatintel:
    def test_happy_path(self):
        """SDK call succeeds → returns executed status."""
        from services.api_gateway.network_remediation import _fix_firewall_threatintel

        mock_fw = MagicMock()
        mock_fw.threat_intel_mode = "Off"

        mock_poller = MagicMock()
        mock_poller.result.return_value = None

        mock_client = MagicMock()
        mock_client.azure_firewalls.get.return_value = mock_fw
        mock_client.azure_firewalls.begin_create_or_update.return_value = mock_poller

        issue = _make_firewall_issue()

        with patch(
            "services.api_gateway.network_remediation.NetworkManagementClient",
            return_value=mock_client,
        ):
            result = asyncio.get_event_loop().run_until_complete(
                _fix_firewall_threatintel(issue, "sub-1", MagicMock())
            )

        assert result["status"] == "executed"
        assert "execution_id" in result
        assert "fw-prod" in result["message"]
        mock_client.azure_firewalls.begin_create_or_update.assert_called_once()
        assert mock_fw.threat_intel_mode == "Alert"

    def test_sdk_error_returns_error_dict(self):
        """SDK raises → structured error dict returned, no raise."""
        from services.api_gateway.network_remediation import _fix_firewall_threatintel

        mock_client = MagicMock()
        mock_client.azure_firewalls.get.side_effect = Exception("ResourceNotFound")

        issue = _make_firewall_issue()

        with patch(
            "services.api_gateway.network_remediation.NetworkManagementClient",
            return_value=mock_client,
        ):
            result = asyncio.get_event_loop().run_until_complete(
                _fix_firewall_threatintel(issue, "sub-1", MagicMock())
            )

        assert result["status"] == "error"
        assert "ResourceNotFound" in result["message"]
        assert "execution_id" in result

    def test_bad_resource_id_returns_error(self):
        """Unparseable resource ID → error dict, no raise."""
        from services.api_gateway.network_remediation import _fix_firewall_threatintel

        issue = {**_make_firewall_issue(), "affected_resource_id": "/bad/path"}
        result = asyncio.get_event_loop().run_until_complete(
            _fix_firewall_threatintel(issue, "sub-1", MagicMock())
        )

        assert result["status"] == "error"
        assert "execution_id" in result


# ---------------------------------------------------------------------------
# Unit tests: _fix_pe_approve
# ---------------------------------------------------------------------------

class TestFixPeApprove:
    def test_happy_path_with_pending_connection(self):
        """PE has pending connection → it gets approved."""
        from services.api_gateway.network_remediation import _fix_pe_approve

        mock_conn = MagicMock()
        mock_conn.name = "pe-storage-connection"
        mock_conn.private_link_service_connection_state = MagicMock(status="Pending")

        mock_client = MagicMock()
        mock_client.private_endpoint_connections = MagicMock()
        mock_client.private_endpoint_connections.list.return_value = [mock_conn]
        mock_client.private_endpoint_connections.update.return_value = MagicMock()

        issue = _make_pe_issue()

        with patch(
            "services.api_gateway.network_remediation.NetworkManagementClient",
            return_value=mock_client,
        ):
            result = asyncio.get_event_loop().run_until_complete(
                _fix_pe_approve(issue, "sub-1", MagicMock())
            )

        assert result["status"] == "executed"
        assert "execution_id" in result
        assert "pe-storage" in result["message"]

    def test_sdk_error_returns_error_dict(self):
        """SDK raises → error dict, no raise."""
        from services.api_gateway.network_remediation import _fix_pe_approve

        mock_client = MagicMock()
        mock_client.private_endpoint_connections = MagicMock()
        mock_client.private_endpoint_connections.list.side_effect = Exception("Not found")

        issue = _make_pe_issue()

        with patch(
            "services.api_gateway.network_remediation.NetworkManagementClient",
            return_value=mock_client,
        ):
            result = asyncio.get_event_loop().run_until_complete(
                _fix_pe_approve(issue, "sub-1", MagicMock())
            )

        assert result["status"] == "error"
        assert "execution_id" in result


# ---------------------------------------------------------------------------
# Unit tests: execute_network_remediation routing
# ---------------------------------------------------------------------------

class TestExecuteNetworkRemediation:
    def test_safe_type_calls_fix_function(self):
        """firewall_threatintel_off → calls the mapped fix function."""
        import services.api_gateway.network_remediation as rem_mod
        from services.api_gateway.network_remediation import execute_network_remediation

        issue = _make_firewall_issue()
        mock_result = {"status": "executed", "execution_id": "x", "message": "done", "duration_ms": 100.0}
        mock_fix = AsyncMock(return_value=mock_result)

        original = rem_mod.SAFE_NETWORK_ACTIONS.copy()
        rem_mod.SAFE_NETWORK_ACTIONS["firewall_threatintel_off"] = mock_fix
        try:
            result = asyncio.get_event_loop().run_until_complete(
                execute_network_remediation(issue, "sub-1", MagicMock())
            )
        finally:
            rem_mod.SAFE_NETWORK_ACTIONS.update(original)

        assert result["status"] == "executed"
        mock_fix.assert_called_once()

    def test_unsafe_type_returns_requires_approval(self):
        """subnet_no_nsg → returns requires_approval without calling any fix."""
        from services.api_gateway.network_remediation import execute_network_remediation

        issue = _make_subnet_issue()
        result = asyncio.get_event_loop().run_until_complete(
            execute_network_remediation(issue, "sub-1", MagicMock())
        )

        assert result["status"] == "requires_approval"
        assert result["issue_type"] == "subnet_no_nsg"

    def test_unknown_type_returns_requires_approval(self):
        """Completely unknown issue type → requires_approval."""
        from services.api_gateway.network_remediation import execute_network_remediation

        issue = {**_make_subnet_issue(), "type": "totally_unknown_type"}
        result = asyncio.get_event_loop().run_until_complete(
            execute_network_remediation(issue, "sub-1", MagicMock())
        )

        assert result["status"] == "requires_approval"


# ---------------------------------------------------------------------------
# Endpoint tests via TestClient
# ---------------------------------------------------------------------------

def _build_app(issues: list[dict]):
    """Build a test FastAPI app with dependency overrides and mocked service calls."""
    from fastapi import FastAPI
    from services.api_gateway.network_topology_endpoints import router
    from services.api_gateway.auth import verify_token
    from services.api_gateway.dependencies import get_credential_for_subscriptions

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_token] = lambda: {"sub": "test"}
    app.dependency_overrides[get_credential_for_subscriptions] = lambda: MagicMock()
    return app


@pytest.fixture()
def client_with_fw_issue():
    """TestClient with a firewall issue pre-seeded in the topology."""
    issue = _make_firewall_issue("fw001")
    mock_cache = MagicMock()

    with (
        patch("services.api_gateway.network_topology_endpoints.resolve_subscription_ids", return_value=["sub-1"]),
        patch(
            "services.api_gateway.network_topology_endpoints.fetch_network_topology",
            return_value={"nodes": [], "edges": [], "issues": [issue]},
        ),
        patch(
            "services.api_gateway.network_topology_endpoints.execute_network_remediation",
            new_callable=AsyncMock,
            return_value={"status": "executed", "execution_id": "exec-001", "message": "Fix applied"},
        ),
        patch("services.api_gateway.network_topology_endpoints.arg_cache", mock_cache),
        patch(
            "services.api_gateway.network_topology_endpoints.create_approval",
            new_callable=AsyncMock,
            return_value={"id": "appr-001"},
        ),
    ):
        app = _build_app([issue])
        yield TestClient(app), mock_cache


@pytest.fixture()
def client_with_subnet_issue():
    """TestClient with a non-auto-fixable (subnet_no_nsg) issue."""
    issue = _make_subnet_issue("sn001")
    mock_approval = AsyncMock(return_value={"id": "appr-002"})

    with (
        patch("services.api_gateway.network_topology_endpoints.resolve_subscription_ids", return_value=["sub-1"]),
        patch(
            "services.api_gateway.network_topology_endpoints.fetch_network_topology",
            return_value={"nodes": [], "edges": [], "issues": [issue]},
        ),
        patch(
            "services.api_gateway.network_topology_endpoints.execute_network_remediation",
            new_callable=AsyncMock,
            return_value={"status": "requires_approval"},
        ),
        patch("services.api_gateway.network_topology_endpoints.arg_cache"),
        patch(
            "services.api_gateway.network_topology_endpoints.create_approval",
            mock_approval,
        ),
    ):
        app = _build_app([issue])
        yield TestClient(app), mock_approval


class TestRemediateEndpoint:
    def test_safe_issue_returns_executed(self, client_with_fw_issue):
        client, mock_cache = client_with_fw_issue
        resp = client.post(
            "/api/v1/network-topology/remediate",
            json={"issue_id": "fw001", "require_approval": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "executed"
        assert data["execution_id"] == "exec-001"

    def test_safe_issue_invalidates_cache(self, client_with_fw_issue):
        client, mock_cache = client_with_fw_issue
        client.post(
            "/api/v1/network-topology/remediate",
            json={"issue_id": "fw001", "require_approval": False},
        )
        mock_cache.invalidate.assert_called_once_with("network_topology")

    def test_unsafe_issue_returns_approval_pending(self, client_with_subnet_issue):
        client, mock_approval = client_with_subnet_issue
        resp = client.post(
            "/api/v1/network-topology/remediate",
            json={"issue_id": "sn001", "require_approval": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approval_pending"
        assert data["approval_id"] == "appr-002"
        mock_approval.assert_called_once()

    def test_unknown_issue_id_returns_404(self, client_with_fw_issue):
        client, _ = client_with_fw_issue
        resp = client.post(
            "/api/v1/network-topology/remediate",
            json={"issue_id": "does-not-exist", "require_approval": False},
        )
        assert resp.status_code == 404

    def test_require_approval_true_on_safe_issue_routes_to_approval(self, client_with_fw_issue):
        """Even a safe issue should go to HITL when require_approval=True."""
        client, mock_cache = client_with_fw_issue

        with patch(
            "services.api_gateway.network_topology_endpoints.create_approval",
            new_callable=AsyncMock,
            return_value={"id": "appr-forced"},
        ) as mock_approval:
            resp = client.post(
                "/api/v1/network-topology/remediate",
                json={"issue_id": "fw001", "require_approval": True},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approval_pending"
        mock_approval.assert_called_once()
        # Cache should NOT be invalidated — no fix was executed
        mock_cache.invalidate.assert_not_called()
