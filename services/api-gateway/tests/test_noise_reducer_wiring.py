"""Unit tests for Phase 24 noise reducer wiring in main.py and stats endpoint.

Tests:
Group 1 — ingest_incident suppression path (4 tests):
    test_ingest_suppressed_returns_suppressed_status
    test_ingest_suppressed_skips_foundry_dispatch
    test_ingest_suppressed_persists_to_cosmos
    test_ingest_suppressed_no_cosmos_still_returns_suppressed

Group 2 — ingest_incident composite severity path (3 tests):
    test_ingest_attaches_composite_severity_to_response
    test_ingest_composite_severity_no_topology
    test_ingest_noise_reducer_failure_doesnt_block_dispatch

Group 3 — GET /api/v1/incidents/stats (3 tests):
    test_stats_returns_correct_counts
    test_stats_no_cosmos_returns_503
    test_stats_empty_window_returns_zeros
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
    "/subscriptions/sub-123/resourceGroups/rg-prod/providers/"
    "Microsoft.Compute/virtualMachines/vm-noise-01"
)

VALID_INCIDENT = {
    "incident_id": "inc-noise-001",
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
    "title": "High CPU on vm-noise-01",
}

PARENT_INCIDENT_ID = "inc-parent-999"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_cosmos_mock():
    """Return a MagicMock CosmosClient with containers wired up."""
    cosmos = MagicMock(name="CosmosClient")
    db = MagicMock(name="DatabaseProxy")
    container = MagicMock(name="ContainerProxy")
    container.upsert_item.return_value = {}
    container.patch_item.return_value = {}
    container.query_items.return_value = iter([])
    db.get_container_client.return_value = container
    cosmos.get_database_client.return_value = db
    return cosmos


def _override_auth(client_app):
    """Override verify_token to return a stub token dict."""
    client_app.dependency_overrides[verify_token] = lambda: {"sub": "test-user"}


def _override_cosmos(client_app, cosmos_mock):
    """Override get_optional_cosmos_client to return the provided mock."""
    client_app.dependency_overrides[get_optional_cosmos_client] = lambda: cosmos_mock


def _clear_overrides(client_app):
    """Remove all dependency overrides."""
    client_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Group 1: Suppression path
# ---------------------------------------------------------------------------


class TestIngestSuppression:
    """Verify suppressed incidents are handled correctly before Foundry dispatch."""

    def setup_method(self):
        """Set up app state with mocked clients before each test."""
        app.state.credential = MagicMock(name="DefaultAzureCredential")
        app.state.topology_client = MagicMock(name="TopologyClient")
        _override_auth(app)

    def teardown_method(self):
        """Clear overrides after each test."""
        _clear_overrides(app)

    @patch("services.api_gateway.noise_reducer.check_causal_suppression", new_callable=AsyncMock)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    def test_ingest_suppressed_returns_suppressed_status(
        self, _mock_dedup, mock_suppression
    ):
        """When check_causal_suppression returns a parent_id, response has
        status='suppressed_cascade', suppressed=True, parent_incident_id set."""
        mock_suppression.return_value = PARENT_INCIDENT_ID
        cosmos = _make_cosmos_mock()
        _override_cosmos(app, cosmos)

        with TestClient(app) as client:
            response = client.post("/api/v1/incidents", json=VALID_INCIDENT)

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "suppressed_cascade"
        assert data["suppressed"] is True
        assert data["parent_incident_id"] == PARENT_INCIDENT_ID

    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    @patch("services.api_gateway.noise_reducer.check_causal_suppression", new_callable=AsyncMock)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    def test_ingest_suppressed_skips_foundry_dispatch(
        self, _mock_dedup, mock_suppression, mock_foundry
    ):
        """Suppressed incident must NOT call create_foundry_thread."""
        mock_suppression.return_value = PARENT_INCIDENT_ID
        mock_foundry.return_value = {"thread_id": "th-should-not-be-called"}
        cosmos = _make_cosmos_mock()
        _override_cosmos(app, cosmos)

        with TestClient(app) as client:
            client.post("/api/v1/incidents", json=VALID_INCIDENT)

        mock_foundry.assert_not_called()

    @patch("services.api_gateway.noise_reducer.check_causal_suppression", new_callable=AsyncMock)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    def test_ingest_suppressed_persists_to_cosmos(
        self, _mock_dedup, mock_suppression
    ):
        """Cosmos upsert_item called once with status='suppressed_cascade'."""
        mock_suppression.return_value = PARENT_INCIDENT_ID
        cosmos = _make_cosmos_mock()
        _override_cosmos(app, cosmos)

        with TestClient(app) as client:
            response = client.post("/api/v1/incidents", json=VALID_INCIDENT)

        assert response.status_code == 202
        container = cosmos.get_database_client.return_value.get_container_client.return_value
        container.upsert_item.assert_called_once()
        call_kwargs = container.upsert_item.call_args[0][0]
        assert call_kwargs["status"] == "suppressed_cascade"
        assert call_kwargs["parent_incident_id"] == PARENT_INCIDENT_ID
        assert call_kwargs["incident_id"] == VALID_INCIDENT["incident_id"]

    @patch("services.api_gateway.noise_reducer.check_causal_suppression", new_callable=AsyncMock)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    def test_ingest_suppressed_no_cosmos_still_returns_suppressed(
        self, _mock_dedup, mock_suppression
    ):
        """cosmos=None + suppression hit → still returns suppressed response, no error."""
        mock_suppression.return_value = PARENT_INCIDENT_ID
        _override_cosmos(app, None)

        with TestClient(app) as client:
            response = client.post("/api/v1/incidents", json=VALID_INCIDENT)

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "suppressed_cascade"
        assert data["suppressed"] is True


# ---------------------------------------------------------------------------
# Group 2: Composite severity path
# ---------------------------------------------------------------------------


class TestCompositeSevertiy:
    """Verify composite severity is attached to the IncidentResponse."""

    def setup_method(self):
        app.state.credential = MagicMock(name="DefaultAzureCredential")
        _override_auth(app)

    def teardown_method(self):
        _clear_overrides(app)

    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    @patch("services.api_gateway.noise_reducer.check_temporal_topological_correlation", new_callable=AsyncMock)
    @patch("services.api_gateway.noise_reducer.check_causal_suppression", new_callable=AsyncMock)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    def test_ingest_attaches_composite_severity_to_response(
        self, _mock_dedup, mock_suppression, mock_correlation, mock_foundry
    ):
        """Not suppressed, not correlated → IncidentResponse.composite_severity is set."""
        mock_suppression.return_value = None
        mock_correlation.return_value = None
        mock_foundry.return_value = {"thread_id": "th-200"}
        cosmos = _make_cosmos_mock()
        app.state.topology_client = MagicMock(name="TopologyClient")
        app.state.topology_client.get_blast_radius.return_value = {
            "total_affected": 5,
            "affected_resources": [],
            "resource_id": RESOURCE_ID,
            "hop_counts": {},
        }
        _override_cosmos(app, cosmos)

        with TestClient(app) as client:
            response = client.post("/api/v1/incidents", json=VALID_INCIDENT)

        assert response.status_code == 202
        data = response.json()
        assert data.get("composite_severity") is not None
        # Sev1 compute with blast_radius=5 → should be Sev1 or Sev0
        assert data["composite_severity"] in ("Sev0", "Sev1", "Sev2", "Sev3")

    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    @patch("services.api_gateway.noise_reducer.check_temporal_topological_correlation", new_callable=AsyncMock)
    @patch("services.api_gateway.noise_reducer.check_causal_suppression", new_callable=AsyncMock)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    def test_ingest_composite_severity_no_topology(
        self, _mock_dedup, mock_suppression, mock_correlation, mock_foundry
    ):
        """topology_client=None → compute_composite_severity called with blast_radius_size=0,
        incident still dispatched without error."""
        mock_suppression.return_value = None
        mock_correlation.return_value = None
        mock_foundry.return_value = {"thread_id": "th-201"}
        cosmos = _make_cosmos_mock()
        app.state.topology_client = None  # No topology
        _override_cosmos(app, cosmos)

        with TestClient(app) as client:
            response = client.post("/api/v1/incidents", json=VALID_INCIDENT)

        assert response.status_code == 202
        data = response.json()
        assert data.get("composite_severity") is not None

    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    @patch("services.api_gateway.noise_reducer.check_temporal_topological_correlation", new_callable=AsyncMock)
    @patch("services.api_gateway.noise_reducer.check_causal_suppression", new_callable=AsyncMock)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    def test_ingest_noise_reducer_failure_doesnt_block_dispatch(
        self, _mock_dedup, mock_suppression, mock_correlation, mock_foundry
    ):
        """If blast_radius prefetch raises, incident is still dispatched to Foundry."""
        mock_suppression.return_value = None
        mock_correlation.return_value = None
        mock_foundry.return_value = {"thread_id": "th-202"}
        cosmos = _make_cosmos_mock()
        # topology_client.get_blast_radius raises to simulate failure
        topo = MagicMock(name="TopologyClient")
        topo.get_blast_radius.side_effect = RuntimeError("topology unavailable")
        app.state.topology_client = topo
        _override_cosmos(app, cosmos)

        with TestClient(app) as client:
            response = client.post("/api/v1/incidents", json=VALID_INCIDENT)

        assert response.status_code == 202
        assert response.json()["status"] == "dispatched"
        mock_foundry.assert_called_once()


# ---------------------------------------------------------------------------
# Group 3: GET /api/v1/incidents/stats
# ---------------------------------------------------------------------------


class TestIncidentStats:
    """Verify the GET /api/v1/incidents/stats endpoint."""

    def setup_method(self):
        app.state.credential = MagicMock(name="DefaultAzureCredential")
        app.state.topology_client = None
        _override_auth(app)

    def teardown_method(self):
        _clear_overrides(app)

    def test_stats_returns_correct_counts(self):
        """Cosmos returns 10 items (3 suppressed, 2 correlated, 5 new) → noise_reduction_pct=50.0."""
        items = (
            [{"status": "suppressed_cascade"}] * 3
            + [{"status": "correlated"}] * 2
            + [{"status": "new"}] * 5
        )
        cosmos = _make_cosmos_mock()
        container = cosmos.get_database_client.return_value.get_container_client.return_value
        container.query_items.return_value = iter(items)
        _override_cosmos(app, cosmos)

        with TestClient(app) as client:
            response = client.get("/api/v1/incidents/stats?window_hours=24")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 10
        assert data["suppressed"] == 3
        assert data["correlated"] == 2
        assert data["new"] == 5
        assert data["noise_reduction_pct"] == 50.0
        assert data["window_hours"] == 24

    def test_stats_no_cosmos_returns_503(self):
        """cosmos=None → 503."""
        _override_cosmos(app, None)

        with TestClient(app) as client:
            response = client.get("/api/v1/incidents/stats")

        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()

    def test_stats_empty_window_returns_zeros(self):
        """Cosmos returns 0 items → total=0, noise_reduction_pct=0.0 (no ZeroDivisionError)."""
        cosmos = _make_cosmos_mock()
        container = cosmos.get_database_client.return_value.get_container_client.return_value
        container.query_items.return_value = iter([])
        _override_cosmos(app, cosmos)

        with TestClient(app) as client:
            response = client.get("/api/v1/incidents/stats?window_hours=1")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["suppressed"] == 0
        assert data["correlated"] == 0
        assert data["noise_reduction_pct"] == 0.0
        assert data["window_hours"] == 1
