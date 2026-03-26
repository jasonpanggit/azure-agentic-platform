"""Tests for API gateway health endpoint."""
import pytest
from fastapi.testclient import TestClient

from services.api_gateway.main import app


@pytest.fixture()
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "ok"

    def test_health_returns_version(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["version"] == "1.0.0"
