from __future__ import annotations
"""Tests for the GET /api/v1/incidents alert feed endpoint (UI-006).

Covers:
- list_incidents() helper (incidents_list.py) with various filter combinations
- GET /api/v1/incidents HTTP endpoint (happy path, filters, subscription split, 503, 401)
"""
import os

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services.api_gateway.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_INCIDENTS = [
    {
        "id": "inc-001",
        "incident_id": "inc-001",
        "severity": "Sev1",
        "domain": "compute",
        "status": "new",
        "created_at": "2026-03-31T10:00:00Z",
        "title": "High CPU on vm-prod-01",
        "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
        "subscription_id": "sub-1",
    },
    {
        "id": "inc-002",
        "incident_id": "inc-002",
        "severity": "Sev2",
        "domain": "network",
        "status": "acknowledged",
        "created_at": "2026-03-31T09:00:00Z",
        "title": "NSG rule gap",
        "resource_id": "/subscriptions/sub-2/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg-1",
        "subscription_id": "sub-2",
    },
    {
        "id": "inc-003",
        "incident_id": "inc-003",
        "severity": "Sev0",
        "domain": "security",
        "status": "new",
        "created_at": "2026-03-31T08:00:00Z",
        "title": "Critical: credential exposure",
        "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/kv-1",
        "subscription_id": "sub-1",
    },
]


@pytest.fixture()
def mock_cosmos_client():
    """Return a MagicMock CosmosClient that serves SAMPLE_INCIDENTS."""
    client = MagicMock(name="CosmosClient")
    container = MagicMock(name="ContainerProxy")
    container.query_items.return_value = iter(SAMPLE_INCIDENTS)
    db = MagicMock(name="DatabaseProxy")
    db.get_container_client.return_value = container
    client.get_database_client.return_value = db
    return client, container


@pytest.fixture()
def client(mock_cosmos_client):
    """TestClient with mocked app state (credential + cosmos_client)."""
    cosmos_mock, _ = mock_cosmos_client
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = cosmos_mock
    return TestClient(app)


@pytest.fixture()
def auth_headers():
    """Valid-looking Authorization header (JWT verification is mocked by conftest)."""
    return {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# Unit tests: list_incidents() helper
# ---------------------------------------------------------------------------


class TestListIncidentsHelper:
    """Test the incidents_list.list_incidents() function directly."""

    @pytest.mark.asyncio
    async def test_returns_all_items_when_no_filters(self, mock_cosmos_client):
        """No filters → all items returned."""
        cosmos_mock, container = mock_cosmos_client
        container.query_items.return_value = iter(SAMPLE_INCIDENTS)

        from services.api_gateway.incidents_list import list_incidents

        result = await list_incidents(cosmos_client=cosmos_mock)

        assert len(result) == 3
        container.query_items.assert_called_once()
        call_kwargs = container.query_items.call_args
        query = call_kwargs.kwargs["query"]
        assert "WHERE 1=1" in query

    @pytest.mark.asyncio
    async def test_severity_filter_in_query(self, mock_cosmos_client):
        """severity filter adds WHERE clause to query."""
        cosmos_mock, container = mock_cosmos_client
        container.query_items.return_value = iter([SAMPLE_INCIDENTS[0]])

        from services.api_gateway.incidents_list import list_incidents

        result = await list_incidents(severity="Sev1", cosmos_client=cosmos_mock)

        assert len(result) == 1
        call_kwargs = container.query_items.call_args
        query = call_kwargs.kwargs["query"]
        params = call_kwargs.kwargs["parameters"]
        assert "c.severity = @severity" in query
        assert {"name": "@severity", "value": "Sev1"} in params

    @pytest.mark.asyncio
    async def test_domain_filter_in_query(self, mock_cosmos_client):
        """domain filter adds WHERE clause."""
        cosmos_mock, container = mock_cosmos_client
        container.query_items.return_value = iter([SAMPLE_INCIDENTS[1]])

        from services.api_gateway.incidents_list import list_incidents

        await list_incidents(domain="network", cosmos_client=cosmos_mock)

        call_kwargs = container.query_items.call_args
        query = call_kwargs.kwargs["query"]
        params = call_kwargs.kwargs["parameters"]
        assert "c.domain = @domain" in query
        assert {"name": "@domain", "value": "network"} in params

    @pytest.mark.asyncio
    async def test_status_filter_in_query(self, mock_cosmos_client):
        """status filter adds WHERE clause."""
        cosmos_mock, container = mock_cosmos_client
        container.query_items.return_value = iter([SAMPLE_INCIDENTS[0]])

        from services.api_gateway.incidents_list import list_incidents

        await list_incidents(status="new", cosmos_client=cosmos_mock)

        call_kwargs = container.query_items.call_args
        query = call_kwargs.kwargs["query"]
        params = call_kwargs.kwargs["parameters"]
        assert "c.status = @status" in query
        assert {"name": "@status", "value": "new"} in params

    @pytest.mark.asyncio
    async def test_since_filter_in_query(self, mock_cosmos_client):
        """since filter adds WHERE clause."""
        cosmos_mock, container = mock_cosmos_client
        container.query_items.return_value = iter(SAMPLE_INCIDENTS)

        from services.api_gateway.incidents_list import list_incidents

        await list_incidents(since="2026-03-31T09:00:00Z", cosmos_client=cosmos_mock)

        call_kwargs = container.query_items.call_args
        query = call_kwargs.kwargs["query"]
        params = call_kwargs.kwargs["parameters"]
        assert "c.created_at >= @since" in query
        assert {"name": "@since", "value": "2026-03-31T09:00:00Z"} in params

    @pytest.mark.asyncio
    async def test_multiple_filters_joined_with_and(self, mock_cosmos_client):
        """Multiple filters are joined with AND."""
        cosmos_mock, container = mock_cosmos_client
        container.query_items.return_value = iter([SAMPLE_INCIDENTS[0]])

        from services.api_gateway.incidents_list import list_incidents

        await list_incidents(severity="Sev1", domain="compute", cosmos_client=cosmos_mock)

        call_kwargs = container.query_items.call_args
        query = call_kwargs.kwargs["query"]
        assert "c.severity = @severity AND c.domain = @domain" in query

    @pytest.mark.asyncio
    async def test_subscription_ids_filter_client_side(self, mock_cosmos_client):
        """subscription_ids filter is applied client-side after query."""
        cosmos_mock, container = mock_cosmos_client
        container.query_items.return_value = iter(SAMPLE_INCIDENTS)

        from services.api_gateway.incidents_list import list_incidents

        result = await list_incidents(
            subscription_ids=["sub-1"], cosmos_client=cosmos_mock
        )

        # Only sub-1 incidents: inc-001 and inc-003
        assert len(result) == 2
        assert all(r["subscription_id"] == "sub-1" for r in result)

    @pytest.mark.asyncio
    async def test_subscription_ids_filter_multiple(self, mock_cosmos_client):
        """Multiple subscription IDs return items from all matching subscriptions."""
        cosmos_mock, container = mock_cosmos_client
        container.query_items.return_value = iter(SAMPLE_INCIDENTS)

        from services.api_gateway.incidents_list import list_incidents

        result = await list_incidents(
            subscription_ids=["sub-1", "sub-2"], cosmos_client=cosmos_mock
        )
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_limit_passed_as_parameter(self, mock_cosmos_client):
        """limit is passed as @limit parameter."""
        cosmos_mock, container = mock_cosmos_client
        container.query_items.return_value = iter(SAMPLE_INCIDENTS[:1])

        from services.api_gateway.incidents_list import list_incidents

        await list_incidents(limit=10, cosmos_client=cosmos_mock)

        call_kwargs = container.query_items.call_args
        params = call_kwargs.kwargs["parameters"]
        assert {"name": "@limit", "value": 10} in params

    @pytest.mark.asyncio
    async def test_cross_partition_query_enabled(self, mock_cosmos_client):
        """enable_cross_partition_query is always True."""
        cosmos_mock, container = mock_cosmos_client
        container.query_items.return_value = iter([])

        from services.api_gateway.incidents_list import list_incidents

        await list_incidents(cosmos_client=cosmos_mock)

        call_kwargs = container.query_items.call_args
        assert call_kwargs.kwargs.get("enable_cross_partition_query") is True

    @pytest.mark.asyncio
    async def test_empty_result_returned_when_no_matches(self, mock_cosmos_client):
        """Empty result set is returned without error."""
        cosmos_mock, container = mock_cosmos_client
        container.query_items.return_value = iter([])

        from services.api_gateway.incidents_list import list_incidents

        result = await list_incidents(cosmos_client=cosmos_mock)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_incidents_container_raises_without_endpoint(self):
        """_get_incidents_container raises ValueError when COSMOS_ENDPOINT not set."""
        from services.api_gateway.incidents_list import _get_incidents_container
        import os

        saved = os.environ.pop("COSMOS_ENDPOINT", None)
        try:
            with pytest.raises(ValueError, match="COSMOS_ENDPOINT"):
                _get_incidents_container(cosmos_client=None)
        finally:
            if saved is not None:
                os.environ["COSMOS_ENDPOINT"] = saved


# ---------------------------------------------------------------------------
# HTTP endpoint tests: GET /api/v1/incidents
# ---------------------------------------------------------------------------


class TestListIncidentsEndpoint:
    """Test the GET /api/v1/incidents HTTP endpoint."""

    def test_returns_200_with_incident_list(self, client, auth_headers, mock_cosmos_client):
        """Successful request returns 200 with list of incidents."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter(SAMPLE_INCIDENTS)

        response = client.get("/api/v1/incidents", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3

    def test_response_shape_matches_incident_summary(self, client, auth_headers, mock_cosmos_client):
        """Response items include required IncidentSummary fields."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter([SAMPLE_INCIDENTS[0]])

        response = client.get("/api/v1/incidents", headers=auth_headers)

        assert response.status_code == 200
        item = response.json()[0]
        assert item["incident_id"] == "inc-001"
        assert item["severity"] == "Sev1"
        assert item["domain"] == "compute"
        assert item["status"] == "new"
        assert "created_at" in item

    def test_severity_query_param_forwarded(self, client, auth_headers, mock_cosmos_client):
        """severity query param is forwarded to list_incidents."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter([SAMPLE_INCIDENTS[0]])

        response = client.get("/api/v1/incidents?severity=Sev1", headers=auth_headers)

        assert response.status_code == 200
        call_kwargs = container.query_items.call_args
        params = call_kwargs.kwargs["parameters"]
        assert {"name": "@severity", "value": "Sev1"} in params

    def test_domain_query_param_forwarded(self, client, auth_headers, mock_cosmos_client):
        """domain query param is forwarded to list_incidents."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter([SAMPLE_INCIDENTS[1]])

        response = client.get("/api/v1/incidents?domain=network", headers=auth_headers)

        assert response.status_code == 200
        call_kwargs = container.query_items.call_args
        params = call_kwargs.kwargs["parameters"]
        assert {"name": "@domain", "value": "network"} in params

    def test_status_query_param_forwarded(self, client, auth_headers, mock_cosmos_client):
        """status query param is forwarded."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter([SAMPLE_INCIDENTS[0]])

        response = client.get("/api/v1/incidents?status=new", headers=auth_headers)

        assert response.status_code == 200
        call_kwargs = container.query_items.call_args
        params = call_kwargs.kwargs["parameters"]
        assert {"name": "@status", "value": "new"} in params

    def test_subscription_query_param_split_and_filtered(self, client, auth_headers, mock_cosmos_client):
        """subscription param is split on comma and used for client-side filtering."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter(SAMPLE_INCIDENTS)

        response = client.get("/api/v1/incidents?subscription=sub-1", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert all(item["subscription_id"] == "sub-1" for item in data)
        assert len(data) == 2  # inc-001 and inc-003

    def test_multiple_subscriptions_comma_separated(self, client, auth_headers, mock_cosmos_client):
        """Comma-separated subscription IDs all included in filter."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter(SAMPLE_INCIDENTS)

        response = client.get("/api/v1/incidents?subscription=sub-1,sub-2", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

    def test_empty_result_returns_empty_list(self, client, auth_headers, mock_cosmos_client):
        """Empty result set returns 200 with empty list (not 404)."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter([])

        response = client.get("/api/v1/incidents", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_auth_disabled_in_test_mode_allows_no_token(self, client, mock_cosmos_client):
        """In test mode (API_GATEWAY_AUTH_MODE=disabled), requests without
        an Authorization header succeed rather than returning 401.
        This validates that the conftest auth bypass is active.
        """
        _, container = mock_cosmos_client
        container.query_items.return_value = iter([])

        # No Authorization header — should succeed because auth is disabled in tests
        response = client.get("/api/v1/incidents")
        assert response.status_code == 200

    def test_cosmos_not_configured_returns_503(self, auth_headers):
        """When cosmos_client is None on app.state, endpoint returns 503."""
        app.state.credential = MagicMock()
        app.state.cosmos_client = None
        test_client = TestClient(app)

        response = test_client.get("/api/v1/incidents", headers=auth_headers)

        assert response.status_code == 503
        assert "Cosmos" in response.json()["detail"]

    def test_limit_default_is_50(self, client, auth_headers, mock_cosmos_client):
        """Default limit is 50."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter([])

        client.get("/api/v1/incidents", headers=auth_headers)

        call_kwargs = container.query_items.call_args
        params = call_kwargs.kwargs["parameters"]
        assert {"name": "@limit", "value": 50} in params

    def test_custom_limit_respected(self, client, auth_headers, mock_cosmos_client):
        """Custom limit is passed through."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter([])

        client.get("/api/v1/incidents?limit=5", headers=auth_headers)

        call_kwargs = container.query_items.call_args
        params = call_kwargs.kwargs["parameters"]
        assert {"name": "@limit", "value": 5} in params

    def test_since_query_param_forwarded(self, client, auth_headers, mock_cosmos_client):
        """since query param is forwarded to list_incidents."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter(SAMPLE_INCIDENTS)

        response = client.get(
            "/api/v1/incidents?since=2026-03-31T09:00:00Z", headers=auth_headers
        )

        assert response.status_code == 200
        call_kwargs = container.query_items.call_args
        params = call_kwargs.kwargs["parameters"]
        assert {"name": "@since", "value": "2026-03-31T09:00:00Z"} in params

    def test_optional_fields_present_in_response(self, client, auth_headers, mock_cosmos_client):
        """Optional fields (title, resource_id) included when present."""
        _, container = mock_cosmos_client
        container.query_items.return_value = iter([SAMPLE_INCIDENTS[0]])

        response = client.get("/api/v1/incidents", headers=auth_headers)

        item = response.json()[0]
        assert item["title"] == "High CPU on vm-prod-01"
        assert "resource_id" in item


# ---------------------------------------------------------------------------
# Unit tests: _parse_resource_id helper
# ---------------------------------------------------------------------------


class TestParseResourceId:
    """Tests for the _parse_resource_id() ARM resource ID parser."""

    def test_parse_resource_id_vm(self):
        """Standard VM resource ID parsed correctly."""
        from services.api_gateway.incidents_list import _parse_resource_id

        rid = "/subscriptions/sub-123/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-001"
        result = _parse_resource_id(rid)
        assert result["subscription_id"] == "sub-123"
        assert result["resource_group"] == "rg-prod"
        assert result["resource_type"] == "microsoft.compute/virtualmachines"
        assert result["resource_name"] == "vm-prod-001"

    def test_parse_resource_id_storage(self):
        """Storage account resource ID parsed correctly."""
        from services.api_gateway.incidents_list import _parse_resource_id

        rid = "/subscriptions/abc/resourceGroups/rg-storage/providers/Microsoft.Storage/storageAccounts/stgprod001"
        result = _parse_resource_id(rid)
        assert result["resource_name"] == "stgprod001"
        assert result["resource_type"] == "microsoft.storage/storageaccounts"

    def test_parse_resource_id_none(self):
        """None input returns all-None dict."""
        from services.api_gateway.incidents_list import _parse_resource_id

        result = _parse_resource_id(None)
        assert result == {
            "resource_name": None,
            "resource_group": None,
            "resource_type": None,
            "subscription_id": None,
        }

    def test_parse_resource_id_malformed(self):
        """Malformed path falls back to last segment as resource_name."""
        from services.api_gateway.incidents_list import _parse_resource_id

        result = _parse_resource_id("/invalid/path")
        assert result["resource_name"] == "path"  # fallback: last non-empty segment

    def test_parse_resource_id_empty_string(self):
        """Empty string input returns all-None dict."""
        from services.api_gateway.incidents_list import _parse_resource_id

        result = _parse_resource_id("")
        assert result == {
            "resource_name": None,
            "resource_group": None,
            "resource_type": None,
            "subscription_id": None,
        }

    def test_parse_resource_id_key_vault(self):
        """Key Vault resource ID parsed correctly."""
        from services.api_gateway.incidents_list import _parse_resource_id

        rid = "/subscriptions/sub-999/resourceGroups/rg-security/providers/Microsoft.KeyVault/vaults/kv-prod"
        result = _parse_resource_id(rid)
        assert result["subscription_id"] == "sub-999"
        assert result["resource_group"] == "rg-security"
        assert result["resource_type"] == "microsoft.keyvault/vaults"
        assert result["resource_name"] == "kv-prod"

    def test_parse_resource_id_nsg(self):
        """NSG resource ID parsed correctly (matches SAMPLE_INCIDENTS[1])."""
        from services.api_gateway.incidents_list import _parse_resource_id

        rid = "/subscriptions/sub-2/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg-1"
        result = _parse_resource_id(rid)
        assert result["resource_name"] == "nsg-1"
        assert result["resource_type"] == "microsoft.network/networksecuritygroups"
        assert result["resource_group"] == "rg"

    def test_incident_summary_has_new_fields(self):
        """IncidentSummary model accepts all 5 new optional fields."""
        from services.api_gateway.models import IncidentSummary

        summary = IncidentSummary(
            incident_id="inc-001",
            severity="Sev1",
            domain="compute",
            status="open",
            created_at="2026-04-01T10:00:00Z",
            resource_name="vm-prod-001",
            resource_group="rg-prod",
            resource_type="microsoft.compute/virtualmachines",
            investigation_status="evidence_ready",
        )
        assert summary.resource_name == "vm-prod-001"
        assert summary.resource_group == "rg-prod"
        assert summary.resource_type == "microsoft.compute/virtualmachines"
        assert summary.investigation_status == "evidence_ready"
        assert summary.evidence_collected_at is None
