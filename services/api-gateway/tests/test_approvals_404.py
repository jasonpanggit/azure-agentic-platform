import os
"""Tests for approvals endpoints returning 404 on missing records (CONCERNS 5.7)."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


def _make_not_found_error() -> CosmosResourceNotFoundError:
    """Construct a CosmosResourceNotFoundError that matches the real SDK signature."""
    response_mock = MagicMock()
    response_mock.status_code = 404
    response_mock.headers = {}
    response_mock.text = "Not Found"
    return CosmosResourceNotFoundError(
        message="Resource Not Found",
        response=response_mock,
    )


class TestApprovals404:
    """Approval endpoints must return 404, not 500, when record not found."""

    @pytest.fixture
    def client(self):
        from services.api_gateway.main import app
        from unittest.mock import MagicMock
        app.state.credential = MagicMock(name="DefaultAzureCredential")
        app.state.cosmos_client = MagicMock(name="CosmosClient")
        return TestClient(app, raise_server_exceptions=False)

    @pytest.fixture
    def mock_cosmos_not_found(self):
        """Mock the approvals container to raise CosmosResourceNotFoundError."""
        mock_container = MagicMock()
        mock_container.read_item.side_effect = _make_not_found_error()
        return mock_container

    def test_approve_nonexistent_returns_404(self, client, mock_cosmos_not_found):
        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_not_found,
        ):
            resp = client.post(
                "/api/v1/approvals/nonexistent-id/approve",
                json={"decided_by": "operator@example.com", "thread_id": "th_123"},
                headers={"Authorization": "Bearer test"},
            )
            assert resp.status_code == 404
            body = resp.json()
            assert "not found" in body["detail"].lower()

    def test_reject_nonexistent_returns_404(self, client, mock_cosmos_not_found):
        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_not_found,
        ):
            resp = client.post(
                "/api/v1/approvals/nonexistent-id/reject",
                json={"decided_by": "operator@example.com", "thread_id": "th_123"},
                headers={"Authorization": "Bearer test"},
            )
            assert resp.status_code == 404

    def test_approve_existing_record_still_works(self, client):
        """Confirm that a found record continues to flow through normally."""
        from datetime import datetime, timezone, timedelta

        mock_container = MagicMock()
        future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        mock_record = {
            "id": "approval-123",
            "thread_id": "th_abc",
            "status": "pending",
            "expires_at": future,
            "proposal": {"target_resources": []},
            "_etag": "etag_1",
        }
        mock_container.read_item.return_value = mock_record
        mock_container.replace_item.return_value = {**mock_record, "status": "approved"}

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_container,
        ), patch(
            "services.api_gateway.approvals._resume_foundry_thread",
            new=AsyncMock(),
        ), patch(
            "services.api_gateway.approvals.log_remediation_event",
            new=AsyncMock(),
        ):
            resp = client.post(
                "/api/v1/approvals/approval-123/approve",
                json={
                    "decided_by": "operator@example.com",
                    "thread_id": "th_abc",
                },
                headers={"Authorization": "Bearer test"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "approved"

    def test_get_approval_status_nonexistent_returns_404(self, client, mock_cosmos_not_found):
        """GET /api/v1/approvals/{id} must also return 404, not 500, when record not found."""
        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_not_found,
        ):
            resp = client.get(
                "/api/v1/approvals/nonexistent-id",
                params={"thread_id": "th_123"},
                headers={"Authorization": "Bearer test"},
            )
            assert resp.status_code == 404
            body = resp.json()
            assert "not found" in body["detail"].lower()
