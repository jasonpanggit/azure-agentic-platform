"""Tests for POST /api/v1/vms/{id}/chat — resource-scoped compute agent chat."""
from __future__ import annotations

import base64
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


def _encode(resource_id: str) -> str:
    return base64.urlsafe_b64encode(resource_id.encode()).decode().rstrip("=")


RID = "/subscriptions/sub1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-001"


# ---------------------------------------------------------------------------
# Unit tests: _decode_resource_id
# ---------------------------------------------------------------------------

def test_decode_resource_id():
    from services.api_gateway.vm_chat import _decode_resource_id
    assert _decode_resource_id(_encode(RID)) == RID


def test_decode_resource_id_invalid():
    from services.api_gateway.vm_chat import _decode_resource_id
    with pytest.raises(ValueError):
        _decode_resource_id("!!!bad-base64!!!")


# ---------------------------------------------------------------------------
# Unit tests: _build_evidence_context
# ---------------------------------------------------------------------------

def test_build_evidence_context_no_evidence():
    from services.api_gateway.vm_chat import _build_evidence_context
    ctx = _build_evidence_context(RID, None)
    assert "vm-prod-001" in ctx
    assert "No pre-fetched evidence" in ctx


def test_build_evidence_context_with_evidence():
    from services.api_gateway.vm_chat import _build_evidence_context
    evidence = {
        "collected_at": "2026-04-02T10:00:00Z",
        "evidence_summary": {
            "health_state": "Degraded",
            "recent_changes": [
                {
                    "timestamp": "2026-04-02T09:50:00Z",
                    "operation": "Microsoft.Compute/virtualMachines/restart/action",
                    "caller": "user@example.com",
                    "status": "Succeeded",
                }
            ],
            "metric_anomalies": [
                {"metric_name": "Percentage CPU", "current_value": 98.5, "threshold": 90, "unit": "%"}
            ],
            "log_errors": {"count": 3, "sample": ["Error: disk timeout"]},
        }
    }
    ctx = _build_evidence_context(RID, evidence)
    assert "Degraded" in ctx
    assert "Percentage CPU" in ctx
    assert "98.5%" in ctx
    assert "restart/action" in ctx
    assert "disk timeout" in ctx


def test_build_evidence_context_no_anomalies():
    from services.api_gateway.vm_chat import _build_evidence_context
    evidence = {
        "collected_at": "2026-04-02T10:00:00Z",
        "evidence_summary": {
            "health_state": "Available",
            "recent_changes": [],
            "metric_anomalies": [],
            "log_errors": {"count": 0, "sample": []},
        }
    }
    ctx = _build_evidence_context(RID, evidence)
    assert "Available" in ctx
    assert "No activity log events" in ctx


def test_build_evidence_context_truncates_long_change_list():
    """More than 5 recent_changes should show a '... and N more' line."""
    from services.api_gateway.vm_chat import _build_evidence_context
    changes = [
        {
            "timestamp": f"2026-04-02T09:5{i}:00Z",
            "operation": f"op-{i}",
            "caller": "user@example.com",
            "status": "Succeeded",
        }
        for i in range(8)
    ]
    evidence = {
        "collected_at": "2026-04-02T10:00:00Z",
        "evidence_summary": {
            "health_state": "Available",
            "recent_changes": changes,
            "metric_anomalies": [],
            "log_errors": {"count": 0},
        }
    }
    ctx = _build_evidence_context(RID, evidence)
    assert "and 3 more events" in ctx


# ---------------------------------------------------------------------------
# Integration tests: POST /api/v1/vms/{id}/chat
# ---------------------------------------------------------------------------

@patch("services.api_gateway.vm_chat.verify_token", return_value={"sub": "test"})
@patch("services.api_gateway.vm_chat._dispatch_vm_chat", new_callable=AsyncMock)
def test_start_vm_chat_success(mock_create, mock_auth):
    mock_create.return_value = {"thread_id": "thread-123", "run_id": "run-456", "status": "completed"}

    from services.api_gateway.main import app
    from fastapi.testclient import TestClient
    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    client = TestClient(app)

    encoded = _encode(RID)
    resp = client.post(
        f"/api/v1/vms/{encoded}/chat",
        json={"message": "What is wrong with this VM?"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["thread_id"] == "thread-123"
    assert data["run_id"] == "run-456"
    assert data["status"] == "created"


@patch("services.api_gateway.vm_chat.verify_token", return_value={"sub": "test"})
@patch("services.api_gateway.vm_chat._dispatch_vm_chat", new_callable=AsyncMock)
def test_start_vm_chat_continue_thread(mock_create, mock_auth):
    mock_create.return_value = {"thread_id": "thread-123", "run_id": "run-789", "status": "completed"}

    from services.api_gateway.main import app
    from fastapi.testclient import TestClient
    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    client = TestClient(app)

    encoded = _encode(RID)
    resp = client.post(
        f"/api/v1/vms/{encoded}/chat",
        json={"message": "Now restart the VM", "thread_id": "thread-123"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "continued"


@patch("services.api_gateway.vm_chat.verify_token", return_value={"sub": "test"})
@patch("services.api_gateway.vm_chat._dispatch_vm_chat", new_callable=AsyncMock)
def test_start_vm_chat_503_when_no_compute_agent(mock_create, mock_auth):
    mock_create.side_effect = ValueError("COMPUTE_AGENT_ID environment variable is required")

    from services.api_gateway.main import app
    from fastapi.testclient import TestClient
    app.state.credential = MagicMock()
    app.state.cosmos_client = None
    client = TestClient(app)

    encoded = _encode(RID)
    resp = client.post(
        f"/api/v1/vms/{encoded}/chat",
        json={"message": "investigate"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 503


def test_start_vm_chat_400_bad_encoding():
    from services.api_gateway.main import app
    from fastapi.testclient import TestClient
    with patch("services.api_gateway.vm_chat.verify_token", return_value={"sub": "test"}):
        app.state.credential = MagicMock()
        app.state.cosmos_client = None
        client = TestClient(app)
        resp = client.post(
            "/api/v1/vms/!!!bad!!!/chat",
            json={"message": "test"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 400
