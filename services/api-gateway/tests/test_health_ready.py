"""Tests for GET /health/ready readiness endpoint (CONCERNS 5.1)."""
import os
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch


class TestHealthReady:
    """Tests for /health/ready readiness probe."""

    def _make_client(self, env_overrides: dict) -> TestClient:
        """Build a test client with specific env vars patched and module reloaded."""
        with patch.dict(os.environ, env_overrides, clear=False):
            import services.api_gateway.health as health_module
            importlib.reload(health_module)
            app = FastAPI()
            app.include_router(health_module.router)
            return TestClient(app)

    def test_returns_503_when_orchestrator_agent_id_missing(self):
        env = {
            "COSMOS_ENDPOINT": "https://cosmos.example.com",
            "AZURE_PROJECT_ENDPOINT": "https://foundry.example.com",
        }
        with patch.dict(os.environ, env):
            os.environ.pop("ORCHESTRATOR_AGENT_ID", None)
            import services.api_gateway.health as health_module
            importlib.reload(health_module)
            app = FastAPI()
            app.include_router(health_module.router)
            client = TestClient(app)
            response = client.get("/health/ready")
            assert response.status_code == 503
            body = response.json()
            assert body["status"] == "not_ready"
            assert body["checks"]["orchestrator_agent_id"] is False

    def test_returns_503_when_cosmos_endpoint_missing(self):
        with patch.dict(os.environ, {
            "ORCHESTRATOR_AGENT_ID": "asst_test123",
            "AZURE_PROJECT_ENDPOINT": "https://foundry.example.com",
        }):
            os.environ.pop("COSMOS_ENDPOINT", None)
            import services.api_gateway.health as health_module
            importlib.reload(health_module)
            app = FastAPI()
            app.include_router(health_module.router)
            client = TestClient(app)
            response = client.get("/health/ready")
            assert response.status_code == 503
            body = response.json()
            assert body["checks"]["cosmos"] is False

    def test_returns_503_when_foundry_endpoint_missing(self):
        with patch.dict(os.environ, {
            "ORCHESTRATOR_AGENT_ID": "asst_test123",
            "COSMOS_ENDPOINT": "https://cosmos.example.com",
        }):
            os.environ.pop("AZURE_PROJECT_ENDPOINT", None)
            os.environ.pop("FOUNDRY_ACCOUNT_ENDPOINT", None)
            import services.api_gateway.health as health_module
            importlib.reload(health_module)
            app = FastAPI()
            app.include_router(health_module.router)
            client = TestClient(app)
            response = client.get("/health/ready")
            assert response.status_code == 503
            body = response.json()
            assert body["checks"]["foundry"] is False

    def test_returns_200_when_all_deps_configured(self):
        with patch.dict(os.environ, {
            "ORCHESTRATOR_AGENT_ID": "asst_test123",
            "COSMOS_ENDPOINT": "https://cosmos.example.com",
            "AZURE_PROJECT_ENDPOINT": "https://foundry.example.com",
        }):
            import services.api_gateway.health as health_module
            importlib.reload(health_module)
            app = FastAPI()
            app.include_router(health_module.router)
            client = TestClient(app)
            response = client.get("/health/ready")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "ready"
            assert body["checks"]["orchestrator_agent_id"] is True
            assert body["checks"]["cosmos"] is True
            assert body["checks"]["foundry"] is True

    def test_foundry_endpoint_fallback_to_foundry_account_endpoint(self):
        """FOUNDRY_ACCOUNT_ENDPOINT is accepted as a fallback for AZURE_PROJECT_ENDPOINT."""
        with patch.dict(os.environ, {
            "ORCHESTRATOR_AGENT_ID": "asst_test123",
            "COSMOS_ENDPOINT": "https://cosmos.example.com",
            "FOUNDRY_ACCOUNT_ENDPOINT": "https://foundry-fallback.example.com",
        }):
            os.environ.pop("AZURE_PROJECT_ENDPOINT", None)
            import services.api_gateway.health as health_module
            importlib.reload(health_module)
            app = FastAPI()
            app.include_router(health_module.router)
            client = TestClient(app)
            response = client.get("/health/ready")
            assert response.status_code == 200
            body = response.json()
            assert body["checks"]["foundry"] is True

    def test_existing_liveness_health_unaffected(self):
        """GET /health (liveness) must still return 200 regardless of readiness."""
        from services.api_gateway.main import app
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
