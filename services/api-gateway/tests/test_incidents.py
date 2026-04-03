"""Tests for API gateway incident ingestion endpoint (DETECT-004)."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from services.api_gateway.main import app


@pytest.fixture()
def client():
    from unittest.mock import MagicMock
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = MagicMock(name="CosmosClient")
    return TestClient(app)


@pytest.fixture()
def valid_payload():
    return {
        "incident_id": "inc-001",
        "severity": "Sev1",
        "domain": "compute",
        "affected_resources": [
            {
                "resource_id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1",
                "subscription_id": "sub-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
            }
        ],
        "detection_rule": "high-cpu-alert",
        "kql_evidence": "Perf | where CounterName == '% Processor Time' | where CounterValue > 95",
    }


class TestIncidentPayloadValidation:
    """Verify payload schema validation."""

    def test_valid_payload_structure(self, valid_payload):
        """Valid payload has all required fields."""
        assert "incident_id" in valid_payload
        assert "severity" in valid_payload
        assert "domain" in valid_payload
        assert "affected_resources" in valid_payload
        assert "detection_rule" in valid_payload

    def test_invalid_severity_rejected(self, client, valid_payload):
        """Severity must match Sev0-Sev3."""
        valid_payload["severity"] = "Critical"
        response = client.post(
            "/api/v1/incidents",
            json=valid_payload,
        )
        assert response.status_code == 422

    def test_invalid_domain_rejected(self, client, valid_payload):
        """Domain must be one of compute|network|storage|security|arc|sre."""
        valid_payload["domain"] = "database"
        response = client.post(
            "/api/v1/incidents",
            json=valid_payload,
        )
        assert response.status_code == 422

    def test_empty_affected_resources_rejected(self, client, valid_payload):
        """At least one affected resource is required."""
        valid_payload["affected_resources"] = []
        response = client.post(
            "/api/v1/incidents",
            json=valid_payload,
        )
        assert response.status_code == 422


class TestIncidentIngestion:
    """Verify incident dispatch flow."""

    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    def test_valid_incident_returns_202(self, mock_dispatch, client, valid_payload):
        """Valid incident returns 202 Accepted with thread_id."""
        mock_dispatch.return_value = {
            "thread_id": "thread-abc-123",
            "run_id": "run-xyz-456",
        }
        response = client.post(
            "/api/v1/incidents",
            json=valid_payload,
        )
        assert response.status_code == 202
        data = response.json()
        assert data["thread_id"] == "thread-abc-123"
        assert data["status"] == "dispatched"

    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    def test_foundry_error_returns_503(self, mock_dispatch, client, valid_payload):
        """Foundry dispatch failure returns 503."""
        mock_dispatch.side_effect = ValueError("AZURE_PROJECT_ENDPOINT not set")
        response = client.post(
            "/api/v1/incidents",
            json=valid_payload,
        )
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# TOPO-004: Topology integration in incident handler tests
# ---------------------------------------------------------------------------


class TestIncidentHandlerTopologyIntegration:
    """Tests for blast_radius_summary pre-fetch in POST /api/v1/incidents (TOPO-004)."""

    def test_blast_radius_summary_populated_when_topology_available(self, client):
        """blast_radius_summary is populated in response when topology_client is set."""
        from unittest.mock import MagicMock, AsyncMock, patch

        mock_topology_client = MagicMock()
        mock_topology_client.get_blast_radius.return_value = {
            "resource_id": "/subscriptions/s1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1",
            "affected_resources": [
                {
                    "resource_id": "/subscriptions/s1/resourcegroups/rg/providers/microsoft.network/networkinterfaces/nic1",
                    "resource_type": "microsoft.network/networkinterfaces",
                    "resource_group": "rg",
                    "subscription_id": "s1",
                    "name": "nic1",
                    "hop_count": 1,
                }
            ],
            "hop_counts": {"/subscriptions/s1/resourcegroups/rg/providers/microsoft.network/networkinterfaces/nic1": 1},
            "total_affected": 1,
        }

        with patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock) as mock_thread, \
             patch("services.api_gateway.dedup_integration.check_dedup", return_value=None):
            mock_thread.return_value = {"thread_id": "t-topo-001"}
            # Inject topology_client onto app.state
            client.app.state.topology_client = mock_topology_client

            response = client.post(
                "/api/v1/incidents",
                json={
                    "incident_id": "inc-topo-001",
                    "severity": "Sev1",
                    "domain": "compute",
                    "affected_resources": [
                        {
                            "resource_id": "/subscriptions/s1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1",
                            "subscription_id": "s1",
                            "resource_type": "Microsoft.Compute/virtualMachines",
                        }
                    ],
                    "detection_rule": "HighCpuAlert",
                },
            )

        assert response.status_code == 202
        data = response.json()
        assert data["thread_id"] == "t-topo-001"
        # blast_radius_summary should be populated
        assert data.get("blast_radius_summary") is not None
        assert data["blast_radius_summary"]["total_affected"] == 1

        # Cleanup
        client.app.state.topology_client = None

    def test_blast_radius_summary_none_when_topology_unavailable(self, client):
        """blast_radius_summary is None when topology_client is not set."""
        from unittest.mock import AsyncMock, patch

        with patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock) as mock_thread, \
             patch("services.api_gateway.dedup_integration.check_dedup", return_value=None):
            mock_thread.return_value = {"thread_id": "t-topo-002"}
            client.app.state.topology_client = None

            response = client.post(
                "/api/v1/incidents",
                json={
                    "incident_id": "inc-topo-002",
                    "severity": "Sev2",
                    "domain": "network",
                    "affected_resources": [
                        {
                            "resource_id": "/subscriptions/s1/resourcegroups/rg/providers/microsoft.network/virtualnetworks/vnet1",
                            "subscription_id": "s1",
                            "resource_type": "Microsoft.Network/virtualNetworks",
                        }
                    ],
                    "detection_rule": "VNetAlert",
                },
            )

        assert response.status_code == 202
        data = response.json()
        assert data["thread_id"] == "t-topo-002"
        # blast_radius_summary should be None when topology unavailable
        assert data.get("blast_radius_summary") is None

    def test_incident_dispatched_even_if_topology_raises(self, client):
        """Incident is dispatched successfully even if topology blast-radius fails."""
        from unittest.mock import MagicMock, AsyncMock, patch

        mock_topology_client = MagicMock()
        mock_topology_client.get_blast_radius.side_effect = RuntimeError("Cosmos timeout")

        with patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock) as mock_thread, \
             patch("services.api_gateway.dedup_integration.check_dedup", return_value=None):
            mock_thread.return_value = {"thread_id": "t-topo-003"}
            client.app.state.topology_client = mock_topology_client

            response = client.post(
                "/api/v1/incidents",
                json={
                    "incident_id": "inc-topo-003",
                    "severity": "Sev0",
                    "domain": "sre",
                    "affected_resources": [
                        {
                            "resource_id": "/subscriptions/s1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm2",
                            "subscription_id": "s1",
                            "resource_type": "Microsoft.Compute/virtualMachines",
                        }
                    ],
                    "detection_rule": "OutageAlert",
                },
            )

        # Must still return 202 — topology failure is non-fatal
        assert response.status_code == 202
        data = response.json()
        assert data["thread_id"] == "t-topo-003"
        assert data.get("blast_radius_summary") is None

        client.app.state.topology_client = None
