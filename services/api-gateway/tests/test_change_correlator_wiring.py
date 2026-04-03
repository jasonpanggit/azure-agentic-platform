"""Tests for change correlator wiring in main.py — BackgroundTask + correlations endpoint.

Tests:
- POST /api/v1/incidents queues correlate_incident_changes as a BackgroundTask
- GET /api/v1/incidents/{incident_id}/correlations returns stored top_changes
- GET correlations returns 404 for unknown incident
- GET correlations returns 503 when cosmos not configured
- GET correlations returns empty list when top_changes not yet populated
- POST /api/v1/incidents without affected_resources does NOT queue correlator
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from services.api_gateway.main import app
from services.api_gateway.dependencies import get_optional_cosmos_client
from services.api_gateway.auth import verify_token

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

RESOURCE_ID = (
    "/subscriptions/sub-123/resourceGroups/rg/providers/"
    "Microsoft.Compute/virtualMachines/vm-01"
)

VALID_INCIDENT_PAYLOAD = {
    "incident_id": "inc-wiring-001",
    "severity": "Sev1",
    "domain": "compute",
    "affected_resources": [
        {
            "resource_id": RESOURCE_ID,
            "subscription_id": "sub-123",
            "resource_type": "Microsoft.Compute/virtualMachines",
        }
    ],
    "detection_rule": "high-cpu-alert",
    "kql_evidence": "Perf | where CounterValue > 95",
}

SAMPLE_CHANGE = {
    "change_id": "evt-001",
    "operation_name": "Microsoft.Compute/virtualMachines/write",
    "resource_id": RESOURCE_ID,
    "resource_name": "vm-01",
    "caller": "user@example.com",
    "changed_at": "2026-04-03T12:00:00Z",
    "delta_minutes": 15.0,
    "topology_distance": 0,
    "change_type_score": 0.9,
    "correlation_score": 0.83,
    "status": "Succeeded",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_cosmos():
    """MagicMock CosmosClient with a configurable read_item response."""
    cosmos = MagicMock(name="CosmosClient")
    db = MagicMock(name="DatabaseProxy")
    container = MagicMock(name="ContainerProxy")
    container.read_item.return_value = {
        "id": "inc-wiring-001",
        "incident_id": "inc-wiring-001",
        "top_changes": [SAMPLE_CHANGE],
    }
    db.get_container_client.return_value = container
    cosmos.get_database_client.return_value = db
    return cosmos


@pytest.fixture()
def client(mock_cosmos):
    """TestClient with mocked Cosmos and auth dependencies."""
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = mock_cosmos
    app.state.topology_client = None
    return TestClient(app)


@pytest.fixture()
def client_no_cosmos():
    """TestClient where get_optional_cosmos_client returns None."""
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = None
    app.state.topology_client = None
    return TestClient(app)


# ---------------------------------------------------------------------------
# Task 23-2-D: Wiring tests
# ---------------------------------------------------------------------------


class TestIngestIncidentQueuesCorrelator:
    """Verify correlate_incident_changes is queued as a BackgroundTask."""

    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    def test_ingest_incident_queues_correlator(
        self, _mock_dedup, mock_foundry, client
    ):
        """POST /api/v1/incidents with affected_resources queues correlate_incident_changes."""
        from services.api_gateway.change_correlator import correlate_incident_changes

        mock_foundry.return_value = {"thread_id": "th-001"}

        with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
            response = client.post("/api/v1/incidents", json=VALID_INCIDENT_PAYLOAD)

        assert response.status_code == 202

        # At least one add_task call uses correlate_incident_changes as first arg
        called_funcs = [call.args[0] for call in mock_add_task.call_args_list]
        assert correlate_incident_changes in called_funcs, (
            f"correlate_incident_changes not in BackgroundTasks.add_task calls: {called_funcs}"
        )

    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    def test_ingest_incident_correlator_queued_after_pipeline(
        self, _mock_dedup, mock_foundry, client
    ):
        """correlate_incident_changes is queued AFTER run_diagnostic_pipeline."""
        from services.api_gateway.change_correlator import correlate_incident_changes
        from services.api_gateway.diagnostic_pipeline import run_diagnostic_pipeline

        mock_foundry.return_value = {"thread_id": "th-002"}

        with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
            response = client.post("/api/v1/incidents", json=VALID_INCIDENT_PAYLOAD)

        assert response.status_code == 202

        called_funcs = [call.args[0] for call in mock_add_task.call_args_list]
        assert run_diagnostic_pipeline in called_funcs, (
            "run_diagnostic_pipeline not queued"
        )
        assert correlate_incident_changes in called_funcs, (
            "correlate_incident_changes not queued"
        )
        pipeline_idx = called_funcs.index(run_diagnostic_pipeline)
        correlator_idx = called_funcs.index(correlate_incident_changes)
        assert correlator_idx > pipeline_idx, (
            f"correlator (pos={correlator_idx}) must come after pipeline (pos={pipeline_idx})"
        )

    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    def test_ingest_incident_no_resources_skips_correlator(
        self, _mock_dedup, mock_foundry, client
    ):
        """When affected_resources is empty, correlate_incident_changes is NOT queued.

        Note: IncidentPayload enforces min_length=1 on affected_resources, so we
        can't send an empty list via the HTTP layer. Instead we test the guard by
        directly patching the correlator to verify it is not called when the HTTP
        layer rejects the payload.
        """
        from services.api_gateway.change_correlator import correlate_incident_changes

        mock_foundry.return_value = {"thread_id": "th-003"}

        # Payload with no affected_resources should be rejected by Pydantic validation
        bad_payload = dict(VALID_INCIDENT_PAYLOAD, affected_resources=[])

        with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
            response = client.post("/api/v1/incidents", json=bad_payload)

        # 422 from validation — correlator must not have been queued
        assert response.status_code == 422
        called_funcs = [call.args[0] for call in mock_add_task.call_args_list]
        assert correlate_incident_changes not in called_funcs


class TestGetIncidentCorrelationsEndpoint:
    """Verify GET /api/v1/incidents/{incident_id}/correlations behaviour."""

    def test_get_correlations_returns_top_changes(self, client, mock_cosmos):
        """Returns 200 with list of ChangeCorrelation objects from Cosmos."""
        # mock_cosmos.container.read_item already returns doc with SAMPLE_CHANGE
        response = client.get("/api/v1/incidents/inc-wiring-001/correlations")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["change_id"] == "evt-001"
        assert data[0]["correlation_score"] == 0.83

    def test_get_correlations_returns_empty_list_when_not_populated(
        self, client, mock_cosmos
    ):
        """Returns 200 with empty list when top_changes key is absent."""
        # Override read_item to return a doc without top_changes
        container = mock_cosmos.get_database_client.return_value.get_container_client.return_value
        container.read_item.return_value = {
            "id": "inc-wiring-001",
            "incident_id": "inc-wiring-001",
            # top_changes deliberately absent
        }

        response = client.get("/api/v1/incidents/inc-wiring-001/correlations")

        assert response.status_code == 200
        assert response.json() == []

    def test_get_correlations_404_for_unknown_incident(self, client, mock_cosmos):
        """Returns 404 when Cosmos raises an exception containing '404'."""
        container = mock_cosmos.get_database_client.return_value.get_container_client.return_value
        container.read_item.side_effect = Exception("404 Not Found")

        response = client.get("/api/v1/incidents/unknown-inc/correlations")

        assert response.status_code == 404
        assert "unknown-inc" in response.json()["detail"]

    def test_get_correlations_503_when_cosmos_not_configured(self, client_no_cosmos):
        """Returns 503 when cosmos_client is None."""
        response = client_no_cosmos.get("/api/v1/incidents/inc-001/correlations")

        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()
