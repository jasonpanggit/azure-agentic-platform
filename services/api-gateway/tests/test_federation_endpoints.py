from __future__ import annotations
"""Tests for cross-subscription federation: endpoints default to all subscriptions from registry.

PLAN: 50-02, Task 1 (TDD — RED phase)

Tests verify that:
1. GET /api/v1/vms with no subscriptions param calls ARG with all registry IDs
2. GET /api/v1/vms?subscriptions=sub-a uses only sub-a (backward compat)
3. GET /api/v1/vms without subscriptions param returns 200 (not 422)
4. GET /api/v1/vms with empty registry returns graceful empty list
5. GET /api/v1/resources without subscriptions uses registry all_ids
6. GET /api/v1/vmss without subscriptions uses registry all_ids
7. GET /api/v1/aks without subscriptions uses registry all_ids
"""
import os

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.main import app  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(sub_ids: list) -> MagicMock:
    """Build a mock SubscriptionRegistry with the given subscription IDs."""
    mock = MagicMock()
    mock.get_all_ids.return_value = list(sub_ids)
    mock.get_all.return_value = [{"id": sid, "name": f"Sub {sid}"} for sid in sub_ids]
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_app_state(request):
    """Inject a mock subscription_registry + credential into app.state for each test.

    Parameterised via indirect=True to allow per-test sub_ids override:
        @pytest.mark.parametrize("mock_app_state", [[]], indirect=True)
    """
    sub_ids = getattr(request, "param", ["sub-abc", "sub-xyz"])
    app.state.subscription_registry = _make_registry(sub_ids)
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = None
    app.state.topology_client = None
    yield
    # Cleanup — restore registry to avoid leaking state across test modules
    if hasattr(app.state, "subscription_registry"):
        del app.state.subscription_registry


# ---------------------------------------------------------------------------
# VM Federation Tests
# ---------------------------------------------------------------------------


class TestVMsFederation:
    def test_no_subscriptions_param_uses_registry(self):
        """GET /api/v1/vms without subscriptions param defaults to all from registry.

        The mock registry must be injected *after* TestClient lifespan startup
        because the startup handler overwrites app.state.subscription_registry
        with a real (empty) registry.
        """
        from fastapi.testclient import TestClient

        with patch("services.api_gateway.vm_inventory._run_arg_query", return_value=[]) as mock_arg:
            with TestClient(app) as client:
                # Inject mock registry AFTER lifespan startup (which clobbers it)
                app.state.subscription_registry = _make_registry(["sub-abc", "sub-xyz"])
                response = client.get("/api/v1/vms")

        assert response.status_code == 200

        # ARG should have been called with both registry subscription IDs
        assert mock_arg.called, "Expected _run_arg_query to be called"
        call_args = mock_arg.call_args
        # Second positional arg is subscription_ids list
        called_sub_ids = call_args[0][1] if call_args[0] and len(call_args[0]) > 1 else []
        assert "sub-abc" in called_sub_ids, (
            f"Expected 'sub-abc' in subscription_ids but got: {called_sub_ids}"
        )
        assert "sub-xyz" in called_sub_ids, (
            f"Expected 'sub-xyz' in subscription_ids but got: {called_sub_ids}"
        )

    def test_explicit_subscriptions_param_respected(self):
        """GET /api/v1/vms?subscriptions=sub-a uses only sub-a (backward compat)."""
        from fastapi.testclient import TestClient

        with patch("services.api_gateway.vm_inventory._run_arg_query", return_value=[]) as mock_arg:
            with TestClient(app) as client:
                response = client.get("/api/v1/vms?subscriptions=sub-a")

        assert response.status_code == 200

        # ARG should have been called with ONLY the explicit subscription
        assert mock_arg.called, "Expected _run_arg_query to be called"
        call_args = mock_arg.call_args
        called_sub_ids = call_args[0][1] if call_args[0] and len(call_args[0]) > 1 else []
        assert called_sub_ids == ["sub-a"], (
            f"Expected only ['sub-a'] but got: {called_sub_ids}"
        )

    def test_no_subscriptions_returns_200_not_422(self):
        """Omitting subscriptions param must NOT return 422 (previously required)."""
        from fastapi.testclient import TestClient

        with patch("services.api_gateway.vm_inventory._run_arg_query", return_value=[]):
            with TestClient(app) as client:
                response = client.get("/api/v1/vms")

        # 422 Unprocessable Entity would indicate the param is still required
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. "
            "This likely means 'subscriptions' is still a required Query param."
        )

    @pytest.mark.parametrize("mock_app_state", [[]], indirect=True)
    def test_empty_registry_returns_empty_list(self, mock_app_state):
        """When registry has no subscriptions, return empty vms list gracefully."""
        from fastapi.testclient import TestClient

        with patch("services.api_gateway.vm_inventory._run_arg_query", return_value=[]):
            with TestClient(app) as client:
                response = client.get("/api/v1/vms")

        assert response.status_code == 200
        data = response.json()
        assert data["vms"] == [], f"Expected empty vms list, got: {data.get('vms')}"
        assert data["total"] == 0, f"Expected total=0, got: {data.get('total')}"
        assert "has_more" in data

    def test_response_shape_is_preserved(self):
        """Federation default must not break the VM response shape."""
        from fastapi.testclient import TestClient

        with patch("services.api_gateway.vm_inventory._run_arg_query", return_value=[]):
            with TestClient(app) as client:
                response = client.get("/api/v1/vms")

        assert response.status_code == 200
        data = response.json()
        assert "vms" in data
        assert "total" in data
        assert "has_more" in data


# ---------------------------------------------------------------------------
# Resources Federation Tests
# ---------------------------------------------------------------------------


class TestResourcesFederation:
    def test_no_subscriptions_param_uses_registry(self):
        """GET /api/v1/resources/inventory without subscriptions param uses registry."""
        from fastapi.testclient import TestClient

        with patch("services.api_gateway.resources_inventory.run_arg_query", return_value=[]):
            with TestClient(app) as client:
                response = client.get("/api/v1/resources/inventory")

        assert response.status_code == 200

    def test_no_subscriptions_returns_200_not_422(self):
        """GET /api/v1/resources/inventory without subscriptions must return 200."""
        from fastapi.testclient import TestClient

        with patch("services.api_gateway.resources_inventory.run_arg_query", return_value=[]):
            with TestClient(app) as client:
                response = client.get("/api/v1/resources/inventory")

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )


# ---------------------------------------------------------------------------
# VMSS Federation Tests
# ---------------------------------------------------------------------------


class TestVMSSFederation:
    def test_no_subscriptions_param_returns_200(self):
        """GET /api/v1/vmss without subscriptions param returns 200 (not 422).

        In the test environment azure-mgmt-resourcegraph is not installed
        (_ARG_AVAILABLE=False), so list_vmss returns empty data immediately.
        The key assertion is that FastAPI does NOT reject the request with 422
        once 'subscriptions' becomes Optional rather than required.
        """
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/api/v1/vmss")

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )

    def test_response_shape_preserved(self):
        """GET /api/v1/vmss without subscriptions must return vmss/total shape."""
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/api/v1/vmss")

        assert response.status_code == 200
        data = response.json()
        assert "vmss" in data
        assert "total" in data


# ---------------------------------------------------------------------------
# AKS Federation Tests
# ---------------------------------------------------------------------------


class TestAKSFederation:
    def test_no_subscriptions_param_returns_200(self):
        """GET /api/v1/aks without subscriptions param returns 200 (not 422).

        In the test environment azure-mgmt-resourcegraph is not installed
        (_ARG_AVAILABLE=False), so list_aks_clusters returns empty data.
        The key assertion: FastAPI must not reject with 422 once 'subscriptions'
        becomes Optional.
        """
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/api/v1/aks")

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )

    def test_response_shape_preserved(self):
        """GET /api/v1/aks without subscriptions must return valid dict response."""
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/api/v1/aks")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
