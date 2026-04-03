"""Integration tests for Phase 25 wiring in main.py.

Tests:
- POST /api/v1/incidents queues _attach_historical_matches BackgroundTask
- SLO escalation: composite_severity elevated to Sev0 when domain has burn-rate alert
- POST /api/v1/incidents/{id}/resolve → stores memory, updates Cosmos
- GET /api/v1/slos → list SLOs
- POST /api/v1/slos → create SLO
- GET /api/v1/slos/{slo_id}/health → health snapshot
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
    "incident_id": "inc-001",
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
    "title": "High CPU on vm-01",
    "kql_evidence": "Perf | where CounterValue > 95",
}

# Low-risk payload: arc domain + Sev3 → composite_severity=Sev2, not Sev0.
# This is used for SLO escalation tests to ensure the escalation path is exercised
# without the noise reducer independently computing Sev0.
LOW_RISK_INCIDENT_PAYLOAD = {
    "incident_id": "inc-low-001",
    "severity": "Sev3",
    "domain": "arc",
    "affected_resources": [
        {
            "resource_id": RESOURCE_ID,
            "subscription_id": "sub-123",
            "resource_type": "Microsoft.HybridCompute/machines",
        }
    ],
    "detection_rule": "arc-health-check",
    "title": "Arc agent heartbeat missed",
}

SAMPLE_SLO_RESPONSE = {
    "id": "slo-uuid-1",
    "name": "Compute API Availability",
    "domain": "compute",
    "metric": "availability",
    "target_pct": 99.9,
    "window_hours": 24,
    "status": "healthy",
    "current_value": None,
    "error_budget_pct": None,
    "burn_rate_1h": None,
    "burn_rate_15min": None,
    "created_at": "2026-04-03T00:00:00+00:00",
    "updated_at": "2026-04-03T00:00:00+00:00",
}

SAMPLE_SLO_HEALTH = {
    "slo_id": "slo-uuid-1",
    "status": "healthy",
    "error_budget_pct": 95.0,
    "burn_rate_1h": 0.5,
    "burn_rate_15min": 0.3,
    "alert": False,
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
        "id": "inc-001",
        "incident_id": "inc-001",
        "domain": "compute",
        "severity": "Sev1",
        "title": "High CPU on vm-01",
    }
    db.get_container_client.return_value = container
    cosmos.get_database_client.return_value = db
    return cosmos


@pytest.fixture()
def client(mock_cosmos):
    """TestClient with mocked Cosmos, auth, and topology dependencies."""
    app.state.credential = MagicMock()
    app.state.cosmos_client = mock_cosmos
    app.state.topology_client = None
    return TestClient(app)


@pytest.fixture()
def client_no_cosmos():
    """TestClient where cosmos_client is None."""
    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    app.state.topology_client = None
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test class 1: Historical memory BackgroundTask wiring
# ---------------------------------------------------------------------------


class TestHistoricalMemoryWiring:
    """Verify _attach_historical_matches is queued as a BackgroundTask on ingest."""

    @patch("services.api_gateway.main.check_domain_burn_rate_alert", new_callable=AsyncMock, return_value=False)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    def test_ingest_queues_attach_historical_matches(
        self, mock_foundry, _mock_dedup, _mock_br, client
    ):
        """POST /api/v1/incidents with affected_resources queues _attach_historical_matches."""
        from services.api_gateway.main import _attach_historical_matches

        mock_foundry.return_value = {"thread_id": "th-001"}

        with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
            response = client.post("/api/v1/incidents", json=VALID_INCIDENT_PAYLOAD)

        assert response.status_code == 202
        called_funcs = [call.args[0] for call in mock_add_task.call_args_list]
        assert _attach_historical_matches in called_funcs, (
            f"_attach_historical_matches not in BackgroundTasks.add_task calls: {called_funcs}"
        )

    @patch("services.api_gateway.main.check_domain_burn_rate_alert", new_callable=AsyncMock, return_value=False)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    def test_attach_historical_matches_not_queued_without_affected_resources(
        self, mock_foundry, _mock_dedup, _mock_br, client
    ):
        """Pydantic rejects empty affected_resources → 422, no BackgroundTask queued."""
        from services.api_gateway.main import _attach_historical_matches

        mock_foundry.return_value = {"thread_id": "th-002"}
        bad_payload = dict(VALID_INCIDENT_PAYLOAD, affected_resources=[])

        with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
            response = client.post("/api/v1/incidents", json=bad_payload)

        assert response.status_code == 422
        called_funcs = [call.args[0] for call in mock_add_task.call_args_list]
        assert _attach_historical_matches not in called_funcs


# ---------------------------------------------------------------------------
# Test class 2: SLO escalation
# ---------------------------------------------------------------------------


class TestSLOEscalation:
    """Verify SLO-aware severity escalation in ingest_incident."""

    @patch("services.api_gateway.main.check_domain_burn_rate_alert", new_callable=AsyncMock, return_value=False)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    def test_no_escalation_when_no_slo_alert(
        self, mock_foundry, _mock_dedup, mock_br, client
    ):
        """check_domain_burn_rate_alert returns False → composite_severity unchanged (not Sev0).

        Uses LOW_RISK_INCIDENT_PAYLOAD (arc/Sev3) which the noise reducer scores as Sev2,
        confirming SLO escalation is not applied when check_domain_burn_rate_alert is False.
        """
        mock_foundry.return_value = {"thread_id": "th-003"}

        response = client.post("/api/v1/incidents", json=LOW_RISK_INCIDENT_PAYLOAD)

        assert response.status_code == 202
        data = response.json()
        # composite_severity should not be escalated to Sev0 when no burn-rate alert
        assert data.get("composite_severity") != "Sev0", (
            f"Expected non-Sev0 composite, got: {data.get('composite_severity')}"
        )
        mock_br.assert_called_once_with("arc")

    @patch("services.api_gateway.main.check_domain_burn_rate_alert", new_callable=AsyncMock, return_value=True)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    def test_escalates_to_sev0_when_domain_in_burn_rate_alert(
        self, mock_foundry, _mock_dedup, _mock_br, client
    ):
        """check_domain_burn_rate_alert returns True → composite_severity escalated to Sev0.

        Uses LOW_RISK_INCIDENT_PAYLOAD (arc/Sev3) which would otherwise be Sev2,
        confirming the SLO escalation path overrides the noise reducer result.
        """
        mock_foundry.return_value = {"thread_id": "th-004"}

        response = client.post("/api/v1/incidents", json=LOW_RISK_INCIDENT_PAYLOAD)

        assert response.status_code == 202
        data = response.json()
        assert data["composite_severity"] == "Sev0", (
            f"Expected Sev0 escalation, got: {data.get('composite_severity')}"
        )

    @patch("services.api_gateway.main.check_domain_burn_rate_alert", new_callable=AsyncMock)
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    def test_no_double_escalation_when_already_sev0(
        self, mock_foundry, _mock_dedup, mock_br, client
    ):
        """When _composite_severity already Sev0, check_domain_burn_rate_alert not called."""
        mock_foundry.return_value = {"thread_id": "th-005"}
        sev0_payload = dict(VALID_INCIDENT_PAYLOAD, severity="Sev0")

        response = client.post("/api/v1/incidents", json=sev0_payload)

        assert response.status_code == 202
        # Since severity starts at Sev0, composite should also be Sev0 without escalation check
        data = response.json()
        assert data["composite_severity"] == "Sev0"
        # burn-rate check must NOT be called when composite is already Sev0
        mock_br.assert_not_called()

    @patch("services.api_gateway.main.check_domain_burn_rate_alert", new_callable=AsyncMock, side_effect=RuntimeError("DB down"))
    @patch("services.api_gateway.dedup_integration.check_dedup", return_value=None)
    @patch("services.api_gateway.main.create_foundry_thread", new_callable=AsyncMock)
    def test_slo_check_failure_does_not_block_ingestion(
        self, mock_foundry, _mock_dedup, _mock_br, client
    ):
        """check_domain_burn_rate_alert raises exception → incident still dispatched (202).

        Uses LOW_RISK_INCIDENT_PAYLOAD (arc/Sev3) so the SLO check is actually attempted
        (composite_severity is not already Sev0).
        """
        mock_foundry.return_value = {"thread_id": "th-006"}

        response = client.post("/api/v1/incidents", json=LOW_RISK_INCIDENT_PAYLOAD)

        assert response.status_code == 202


# ---------------------------------------------------------------------------
# Test class 3: Resolve endpoint
# ---------------------------------------------------------------------------


class TestResolveEndpoint:
    """Verify POST /api/v1/incidents/{incident_id}/resolve behavior."""

    @patch("services.api_gateway.main.store_incident_memory", new_callable=AsyncMock, return_value="inc-001")
    def test_resolve_returns_200_with_memory_id(self, mock_store, client):
        """POST resolve → 200 with incident_id, memory_id, resolved_at."""
        response = client.post(
            "/api/v1/incidents/inc-001/resolve",
            json={
                "summary": "CPU spike caused by runaway process",
                "resolution": "Restarted service X",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["incident_id"] == "inc-001"
        assert data["memory_id"] == "inc-001"
        assert "resolved_at" in data

    def test_resolve_404_for_unknown_incident(self, client, mock_cosmos):
        """Cosmos read_item raises '404 Not Found' → HTTP 404."""
        container = mock_cosmos.get_database_client.return_value.get_container_client.return_value
        container.read_item.side_effect = Exception("404 Not Found")

        response = client.post(
            "/api/v1/incidents/unknown-inc/resolve",
            json={"summary": "summary text", "resolution": "fix text"},
        )

        assert response.status_code == 404
        assert "unknown-inc" in response.json()["detail"]

    def test_resolve_503_when_cosmos_not_configured(self, client_no_cosmos):
        """cosmos=None → HTTP 503."""
        response = client_no_cosmos.post(
            "/api/v1/incidents/inc-001/resolve",
            json={"summary": "summary text", "resolution": "fix text"},
        )

        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()

    @patch(
        "services.api_gateway.main.store_incident_memory",
        new_callable=AsyncMock,
    )
    def test_resolve_503_when_memory_store_unavailable(self, mock_store, client):
        """store_incident_memory raises IncidentMemoryUnavailableError → HTTP 503."""
        from services.api_gateway.incident_memory import IncidentMemoryUnavailableError

        mock_store.side_effect = IncidentMemoryUnavailableError("postgres down")

        response = client.post(
            "/api/v1/incidents/inc-001/resolve",
            json={"summary": "summary text", "resolution": "fix text"},
        )

        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test class 4: SLO routes
# ---------------------------------------------------------------------------


class TestSLORoutes:
    """Verify POST /api/v1/slos, GET /api/v1/slos, GET /api/v1/slos/{id}/health."""

    @patch("services.api_gateway.main.create_slo", new_callable=AsyncMock)
    def test_create_slo_returns_201(self, mock_create, client):
        """POST /api/v1/slos with valid body → 201 with SLODefinition."""
        mock_create.return_value = SAMPLE_SLO_RESPONSE.copy()

        response = client.post(
            "/api/v1/slos",
            json={
                "name": "Compute API Availability",
                "domain": "compute",
                "metric": "availability",
                "target_pct": 99.9,
                "window_hours": 24,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "slo-uuid-1"
        assert data["name"] == "Compute API Availability"
        assert data["domain"] == "compute"

    @patch("services.api_gateway.main.list_slos", new_callable=AsyncMock)
    def test_list_slos_returns_200(self, mock_list, client):
        """GET /api/v1/slos → 200 with list (may be empty)."""
        mock_list.return_value = [SAMPLE_SLO_RESPONSE.copy()]

        response = client.get("/api/v1/slos")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "slo-uuid-1"

    @patch("services.api_gateway.main.list_slos", new_callable=AsyncMock)
    def test_list_slos_domain_filter_passed_through(self, mock_list, client):
        """GET /api/v1/slos?domain=compute → list_slos(domain='compute') called."""
        mock_list.return_value = []

        response = client.get("/api/v1/slos?domain=compute")

        assert response.status_code == 200
        mock_list.assert_called_once_with(domain="compute")

    @patch("services.api_gateway.main.get_slo_health", new_callable=AsyncMock)
    def test_get_slo_health_returns_200(self, mock_health, client):
        """GET /api/v1/slos/{slo_id}/health → 200 with SLOHealth body."""
        mock_health.return_value = SAMPLE_SLO_HEALTH.copy()

        response = client.get("/api/v1/slos/slo-uuid-1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["slo_id"] == "slo-uuid-1"
        assert data["status"] == "healthy"
        assert data["alert"] is False

    @patch("services.api_gateway.main.get_slo_health", new_callable=AsyncMock)
    def test_get_slo_health_404_for_unknown(self, mock_health, client):
        """get_slo_health raises KeyError → HTTP 404."""
        mock_health.side_effect = KeyError("slo-not-found")

        response = client.get("/api/v1/slos/slo-not-found/health")

        assert response.status_code == 404
        assert "slo-not-found" in response.json()["detail"]
