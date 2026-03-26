"""Tests for API gateway incident ingestion endpoint (DETECT-004)."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from services.api_gateway.main import app


@pytest.fixture()
def client():
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
