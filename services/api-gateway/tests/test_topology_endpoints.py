from __future__ import annotations
"""Unit tests for topology API endpoints (topology_endpoints.py).

Tests cover all four endpoints with mocked TopologyClient:
- GET /api/v1/topology/blast-radius
- GET /api/v1/topology/path
- GET /api/v1/topology/snapshot
- POST /api/v1/topology/bootstrap

Uses FastAPI TestClient with app.state.topology_client overridden to a mock.
verify_token is patched to return a dummy claims dict.
"""
import os

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.topology_endpoints import router


# ---------------------------------------------------------------------------
# Test app fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_topology_client():
    """Create a minimal FastAPI app with the topology router and a mock TopologyClient."""
    test_app = FastAPI()
    test_app.include_router(router)

    mock_client = MagicMock()
    test_app.state.topology_client = mock_client

    return test_app, mock_client


@pytest.fixture()
def client_with_mock(app_with_topology_client):
    test_app, mock_topology_client = app_with_topology_client
    with patch("services.api_gateway.topology_endpoints.verify_token", return_value={"sub": "test-user"}):
        with TestClient(test_app) as c:
            yield c, mock_topology_client


@pytest.fixture()
def client_no_topology():
    """TestClient with topology_client=None to test 503 responses."""
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.topology_client = None
    with patch("services.api_gateway.topology_endpoints.verify_token", return_value={"sub": "test-user"}):
        with TestClient(test_app) as c:
            yield c


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_ORIGIN_ID = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1"
_NIC_ID = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1"

_BLAST_RADIUS_RESULT = {
    "resource_id": _ORIGIN_ID,
    "affected_resources": [
        {
            "resource_id": _NIC_ID,
            "resource_type": "microsoft.network/networkinterfaces",
            "resource_group": "rg1",
            "subscription_id": "s1",
            "name": "nic1",
            "hop_count": 1,
        }
    ],
    "hop_counts": {_NIC_ID: 1},
    "total_affected": 1,
}

_PATH_RESULT = {
    "source": _ORIGIN_ID,
    "target": _NIC_ID,
    "path": [_ORIGIN_ID, _NIC_ID],
    "hops": 1,
    "found": True,
}

_SNAPSHOT_DOC = {
    "id": _ORIGIN_ID,
    "resource_id": _ORIGIN_ID,
    "resource_type": "microsoft.compute/virtualmachines",
    "resource_group": "rg1",
    "subscription_id": "s1",
    "name": "vm1",
    "tags": {"env": "prod"},
    "relationships": [
        {"target_id": _NIC_ID, "rel_type": "nic_of", "direction": "outbound"}
    ],
    "last_synced_at": "2026-04-03T10:00:00+00:00",
}


# ---------------------------------------------------------------------------
# GET /blast-radius tests
# ---------------------------------------------------------------------------


class TestBlastRadiusEndpoint:
    def test_returns_200_with_affected_resources(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_blast_radius.return_value = _BLAST_RADIUS_RESULT

        resp = http_client.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID, "max_depth": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resource_id"] == _ORIGIN_ID
        assert data["total_affected"] == 1
        assert len(data["affected_resources"]) == 1
        assert data["affected_resources"][0]["resource_id"] == _NIC_ID
        assert "query_duration_ms" in data

    def test_passes_max_depth_to_client(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_blast_radius.return_value = {
            "resource_id": _ORIGIN_ID,
            "affected_resources": [],
            "hop_counts": {},
            "total_affected": 0,
        }

        http_client.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID, "max_depth": 2},
        )
        call_args = mock_topology_client.get_blast_radius.call_args
        assert call_args[0][1] == 2  # max_depth positional arg

    def test_missing_resource_id_returns_422(self, client_with_mock):
        http_client, _ = client_with_mock
        resp = http_client.get("/api/v1/topology/blast-radius")
        assert resp.status_code == 422

    def test_max_depth_above_6_returns_422(self, client_with_mock):
        http_client, _ = client_with_mock
        resp = http_client.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID, "max_depth": 10},
        )
        assert resp.status_code == 422

    def test_max_depth_below_1_returns_422(self, client_with_mock):
        http_client, _ = client_with_mock
        resp = http_client.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID, "max_depth": 0},
        )
        assert resp.status_code == 422

    def test_returns_503_when_client_unavailable(self, client_no_topology):
        resp = client_no_topology.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID},
        )
        assert resp.status_code == 503

    def test_returns_500_when_client_raises(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_blast_radius.side_effect = RuntimeError("Cosmos timeout")

        resp = http_client.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID},
        )
        assert resp.status_code == 500

    def test_default_max_depth_is_3(self, client_with_mock):
        """max_depth should default to 3 when not specified."""
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_blast_radius.return_value = {
            "resource_id": _ORIGIN_ID,
            "affected_resources": [],
            "hop_counts": {},
            "total_affected": 0,
        }

        http_client.get(
            "/api/v1/topology/blast-radius",
            params={"resource_id": _ORIGIN_ID},
        )
        call_args = mock_topology_client.get_blast_radius.call_args
        assert call_args[0][1] == 3  # default max_depth


# ---------------------------------------------------------------------------
# GET /path tests
# ---------------------------------------------------------------------------


class TestPathEndpoint:
    def test_returns_200_with_path(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_path.return_value = _PATH_RESULT

        resp = http_client.get(
            "/api/v1/topology/path",
            params={"source": _ORIGIN_ID, "target": _NIC_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert data["hops"] == 1
        assert len(data["path"]) == 2
        assert "query_duration_ms" in data

    def test_returns_found_false_when_no_path(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        missing_vm = "/subscriptions/s1/resourcegroups/rg2/providers/microsoft.compute/virtualmachines/vm99"
        mock_topology_client.get_path.return_value = {
            "source": _ORIGIN_ID,
            "target": missing_vm,
            "path": [],
            "hops": -1,
            "found": False,
        }

        resp = http_client.get(
            "/api/v1/topology/path",
            params={"source": _ORIGIN_ID, "target": missing_vm},
        )
        assert resp.status_code == 200
        assert resp.json()["found"] is False
        assert resp.json()["hops"] == -1

    def test_missing_source_returns_422(self, client_with_mock):
        http_client, _ = client_with_mock
        resp = http_client.get("/api/v1/topology/path", params={"target": _NIC_ID})
        assert resp.status_code == 422

    def test_missing_target_returns_422(self, client_with_mock):
        http_client, _ = client_with_mock
        resp = http_client.get("/api/v1/topology/path", params={"source": _ORIGIN_ID})
        assert resp.status_code == 422

    def test_returns_503_when_client_unavailable(self, client_no_topology):
        resp = client_no_topology.get(
            "/api/v1/topology/path",
            params={"source": _ORIGIN_ID, "target": _NIC_ID},
        )
        assert resp.status_code == 503

    def test_returns_500_when_client_raises(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_path.side_effect = RuntimeError("BFS timeout")

        resp = http_client.get(
            "/api/v1/topology/path",
            params={"source": _ORIGIN_ID, "target": _NIC_ID},
        )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /snapshot tests
# ---------------------------------------------------------------------------


class TestSnapshotEndpoint:
    def test_returns_200_with_document(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_snapshot.return_value = _SNAPSHOT_DOC

        resp = http_client.get(
            "/api/v1/topology/snapshot",
            params={"resource_id": _ORIGIN_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resource_id"] == _ORIGIN_ID
        assert data["resource_type"] == "microsoft.compute/virtualmachines"
        assert data["name"] == "vm1"
        assert len(data["relationships"]) == 1

    def test_returns_404_when_not_found(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_snapshot.return_value = None

        resp = http_client.get(
            "/api/v1/topology/snapshot",
            params={"resource_id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/missing"},
        )
        assert resp.status_code == 404

    def test_missing_resource_id_returns_422(self, client_with_mock):
        http_client, _ = client_with_mock
        resp = http_client.get("/api/v1/topology/snapshot")
        assert resp.status_code == 422

    def test_returns_503_when_client_unavailable(self, client_no_topology):
        resp = client_no_topology.get(
            "/api/v1/topology/snapshot",
            params={"resource_id": _ORIGIN_ID},
        )
        assert resp.status_code == 503

    def test_returns_500_when_client_raises(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock
        mock_topology_client.get_snapshot.side_effect = RuntimeError("Cosmos unavailable")

        resp = http_client.get(
            "/api/v1/topology/snapshot",
            params={"resource_id": _ORIGIN_ID},
        )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /bootstrap tests
# ---------------------------------------------------------------------------


class TestBootstrapEndpoint:
    def test_returns_202_and_starts_background(self, client_with_mock):
        http_client, mock_topology_client = client_with_mock

        with patch("services.api_gateway.topology_endpoints.asyncio.create_task") as mock_task:
            resp = http_client.post("/api/v1/topology/bootstrap")
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "started"
        assert "background" in data["message"].lower()

    def test_returns_unavailable_when_no_client(self, client_no_topology):
        resp = client_no_topology.post("/api/v1/topology/bootstrap")
        # 202 is returned but with status=unavailable
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "unavailable"

    def test_bootstrap_message_mentions_logs(self, client_with_mock):
        http_client, _ = client_with_mock
        with patch("services.api_gateway.topology_endpoints.asyncio.create_task"):
            resp = http_client.post("/api/v1/topology/bootstrap")
        assert resp.status_code == 202
        assert "logs" in resp.json()["message"].lower()
