"""Tests for simulation endpoints (Phase 69)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    """TestClient with simulation router mounted and dependencies overridden."""
    from fastapi import FastAPI
    from services.api_gateway.simulation_endpoints import router
    from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

    app = FastAPI()
    app.include_router(router)

    mock_credential = MagicMock(name="DefaultAzureCredential")

    app.dependency_overrides[get_credential] = lambda: mock_credential
    app.dependency_overrides[get_optional_cosmos_client] = lambda: None  # no Cosmos by default

    return TestClient(app)


@pytest.fixture()
def client_with_cosmos() -> TestClient:
    """TestClient with a mock Cosmos client wired in."""
    from fastapi import FastAPI
    from services.api_gateway.simulation_endpoints import router
    from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

    app = FastAPI()
    app.include_router(router)

    mock_credential = MagicMock(name="DefaultAzureCredential")
    mock_cosmos = _make_cosmos_mock()

    app.dependency_overrides[get_credential] = lambda: mock_credential
    app.dependency_overrides[get_optional_cosmos_client] = lambda: mock_cosmos

    return TestClient(app)


def _make_cosmos_mock() -> MagicMock:
    """Build a mock Cosmos client that returns empty query results by default."""
    mock_cosmos = MagicMock()
    mock_db = MagicMock()
    mock_container = MagicMock()
    mock_cosmos.get_database_client.return_value = mock_db
    mock_db.get_container_client.return_value = mock_container
    mock_db.create_container.return_value = None
    mock_container.upsert_item.return_value = None
    mock_container.query_items.return_value = iter([])
    return mock_cosmos


# ---------------------------------------------------------------------------
# 1. List scenarios
# ---------------------------------------------------------------------------


def test_list_scenarios_returns_all(client: TestClient) -> None:
    """GET /api/v1/simulations returns all 10 scenarios."""
    response = client.get("/api/v1/simulations")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 10
    assert len(data["scenarios"]) == 10
    assert "generated_at" in data


def test_list_scenarios_fields(client: TestClient) -> None:
    """Each scenario has the required fields."""
    response = client.get("/api/v1/simulations")
    for scenario in response.json()["scenarios"]:
        assert "id" in scenario
        assert "name" in scenario
        assert "description" in scenario
        assert "domain" in scenario
        assert "severity" in scenario
        assert "expected_agent" in scenario


# ---------------------------------------------------------------------------
# 2. Run simulation — dry_run=True
# ---------------------------------------------------------------------------


def test_run_simulation_dry_run(client: TestClient) -> None:
    """POST /api/v1/simulations/run with dry_run=True returns 'validated', no incident_id."""
    response = client.post(
        "/api/v1/simulations/run",
        json={
            "scenario_id": "vm-high-cpu",
            "subscription_id": "sub-test-001",
            "dry_run": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "validated"
    assert data["dry_run"] is True
    assert data["incident_id"] is None
    assert data["scenario_id"] == "vm-high-cpu"
    assert data["expected_agent"] == "ca-compute-prod"
    assert "run_id" in data
    assert data["run_id"].startswith("sim-")
    assert "triggered_at" in data


def test_run_simulation_dry_run_with_optional_fields(client: TestClient) -> None:
    """dry_run=True with target_resource and resource_group still validates."""
    response = client.post(
        "/api/v1/simulations/run",
        json={
            "scenario_id": "nsg-blocked-traffic",
            "subscription_id": "sub-test-001",
            "target_resource": "my-nsg-001",
            "resource_group": "rg-network",
            "dry_run": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "validated"
    assert data["scenario_id"] == "nsg-blocked-traffic"
    assert data["expected_agent"] == "ca-network-prod"


# ---------------------------------------------------------------------------
# 3. Run simulation — dry_run=False, Cosmos unavailable → still works
# ---------------------------------------------------------------------------


def test_run_simulation_no_cosmos(client: TestClient) -> None:
    """dry_run=False with no Cosmos — injection attempted, run still returns."""
    with patch("services.api_gateway.simulation_endpoints.httpx") as mock_httpx:
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_httpx.AsyncClient.return_value = mock_client

        response = client.post(
            "/api/v1/simulations/run",
            json={
                "scenario_id": "vm-disk-full",
                "subscription_id": "sub-test-001",
                "dry_run": False,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is False
    assert data["scenario_id"] == "vm-disk-full"
    assert "run_id" in data


def test_run_simulation_injection_error_still_returns(client: TestClient) -> None:
    """If httpx injection raises, run still returns with injection_failed status."""
    with patch("services.api_gateway.simulation_endpoints.httpx") as mock_httpx:
        mock_httpx.AsyncClient.side_effect = Exception("connection refused")

        response = client.post(
            "/api/v1/simulations/run",
            json={
                "scenario_id": "keyvault-access-denied",
                "subscription_id": "sub-test-001",
                "dry_run": False,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "injection_failed"
    assert data["incident_id"] is not None  # still assigned a sim-* ID


# ---------------------------------------------------------------------------
# 4. Run simulation — unknown scenario → 404
# ---------------------------------------------------------------------------


def test_run_simulation_unknown_scenario(client: TestClient) -> None:
    """Unknown scenario_id returns 404."""
    response = client.post(
        "/api/v1/simulations/run",
        json={
            "scenario_id": "does-not-exist",
            "subscription_id": "sub-test-001",
            "dry_run": True,
        },
    )
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert "does-not-exist" in data["error"]
    assert "available" in data


# ---------------------------------------------------------------------------
# 5. List run history — happy path (Cosmos returns items)
# ---------------------------------------------------------------------------


def test_list_runs_happy_path(client_with_cosmos: TestClient) -> None:
    """GET /api/v1/simulations/runs returns run history from Cosmos."""
    sample_runs = [
        {
            "run_id": "sim-abc123",
            "scenario_id": "vm-high-cpu",
            "scenario_name": "VM High CPU Alert",
            "incident_id": "sim-def456",
            "status": "triggered",
            "triggered_at": "2026-04-17T10:00:00+00:00",
            "subscription_id": "sub-001",
            "dry_run": False,
        }
    ]
    # Patch the query function so it returns our sample
    with patch(
        "services.api_gateway.simulation_endpoints._query_runs",
        new=AsyncMock(return_value=sample_runs),
    ):
        response = client_with_cosmos.get("/api/v1/simulations/runs")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["runs"][0]["run_id"] == "sim-abc123"
    assert "generated_at" in data


def test_list_runs_with_scenario_filter(client_with_cosmos: TestClient) -> None:
    """scenario_id and limit query params are forwarded to _query_runs."""
    with patch(
        "services.api_gateway.simulation_endpoints._query_runs",
        new=AsyncMock(return_value=[]),
    ) as mock_query:
        response = client_with_cosmos.get("/api/v1/simulations/runs?scenario_id=arc-agent-offline&limit=10")

    assert response.status_code == 200
    # First arg is cosmos_client (a MagicMock injected by fixture), then scenario_id, then limit
    args = mock_query.call_args[0]
    assert args[1] == "arc-agent-offline"
    assert args[2] == 10


# ---------------------------------------------------------------------------
# 6. List run history — empty
# ---------------------------------------------------------------------------


def test_list_runs_empty(client: TestClient) -> None:
    """GET /api/v1/simulations/runs returns empty list when no Cosmos client."""
    response = client.get("/api/v1/simulations/runs")
    assert response.status_code == 200
    data = response.json()
    assert data["runs"] == []
    assert data["total"] == 0


# ---------------------------------------------------------------------------
# 7. Get run by ID — found
# ---------------------------------------------------------------------------


def test_get_run_by_id_found(client: TestClient) -> None:
    """GET /api/v1/simulations/runs/{run_id} returns the run record."""
    sample_run = {
        "run_id": "sim-xyz789",
        "scenario_id": "sev0-cascade",
        "status": "triggered",
        "triggered_at": "2026-04-17T12:00:00+00:00",
    }
    with patch(
        "services.api_gateway.simulation_endpoints._get_run_by_id",
        new=AsyncMock(return_value=sample_run),
    ):
        response = client.get("/api/v1/simulations/runs/sim-xyz789")

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "sim-xyz789"
    assert data["scenario_id"] == "sev0-cascade"


# ---------------------------------------------------------------------------
# 8. Get run by ID — not found → 404
# ---------------------------------------------------------------------------


def test_get_run_by_id_not_found(client: TestClient) -> None:
    """GET /api/v1/simulations/runs/{run_id} returns 404 for unknown run."""
    with patch(
        "services.api_gateway.simulation_endpoints._get_run_by_id",
        new=AsyncMock(return_value=None),
    ):
        response = client.get("/api/v1/simulations/runs/sim-unknown")

    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert "sim-unknown" in data["error"]


# ---------------------------------------------------------------------------
# 9. Incident payload construction
# ---------------------------------------------------------------------------


def test_build_incident_payload_defaults() -> None:
    """_build_incident_payload uses sensible defaults when no resource specified."""
    from services.api_gateway.simulation_endpoints import _build_incident_payload, _SCENARIO_INDEX

    scenario = _SCENARIO_INDEX["vm-high-cpu"]
    payload = _build_incident_payload(scenario, "sub-abc", None, None)

    assert payload["incident_id"].startswith("sim-")
    assert "[SIMULATION]" in payload["title"]
    assert payload["severity"] == "Sev2"
    assert payload["domain"] == "compute"
    assert "rg-simulation" in payload["affected_resources"][0]["resource_id"]
    assert "sim-resource-compute-001" in payload["affected_resources"][0]["resource_id"]
    assert payload["affected_resources"][0]["subscription_id"] == "sub-abc"


def test_build_incident_payload_custom_resource() -> None:
    """_build_incident_payload honours explicit target_resource and resource_group."""
    from services.api_gateway.simulation_endpoints import _build_incident_payload, _SCENARIO_INDEX

    scenario = _SCENARIO_INDEX["storage-latency"]
    payload = _build_incident_payload(scenario, "sub-xyz", "my-storage-001", "rg-custom")

    assert "my-storage-001" in payload["affected_resources"][0]["resource_id"]
    assert "rg-custom" in payload["affected_resources"][0]["resource_id"]
    assert payload["domain"] == "storage"


# ---------------------------------------------------------------------------
# 10. All scenarios are valid (smoke test)
# ---------------------------------------------------------------------------


def test_all_scenario_ids_are_unique() -> None:
    """Every scenario has a unique id."""
    from services.api_gateway.simulation_endpoints import SIMULATION_SCENARIOS

    ids = [s["id"] for s in SIMULATION_SCENARIOS]
    assert len(ids) == len(set(ids))


def test_all_scenario_domains_are_valid() -> None:
    """All scenario domains are accepted by IncidentPayload validation or known extensions."""
    from services.api_gateway.simulation_endpoints import SIMULATION_SCENARIOS

    # Domains used by the platform (including finops/database which map to storage/finops)
    known_domains = {"compute", "network", "storage", "security", "arc", "sre", "patch", "eol", "messaging", "finops"}
    for s in SIMULATION_SCENARIOS:
        assert s["domain"] in known_domains, f"Unknown domain {s['domain']} for scenario {s['id']}"


def test_all_scenario_severities_are_valid() -> None:
    """All scenario severities match the Sev0-Sev3 pattern."""
    import re
    from services.api_gateway.simulation_endpoints import SIMULATION_SCENARIOS

    pattern = re.compile(r"^Sev[0-3]$")
    for s in SIMULATION_SCENARIOS:
        assert pattern.match(s["severity"]), f"Invalid severity {s['severity']} for {s['id']}"


# ---------------------------------------------------------------------------
# 11. _persist_run — Cosmos unavailable → no exception raised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_run_no_cosmos() -> None:
    """_persist_run with cosmos_client=None completes silently."""
    from services.api_gateway.simulation_endpoints import _persist_run

    run = {"run_id": "sim-test", "scenario_id": "vm-high-cpu"}
    # Should not raise
    await _persist_run(None, run)


@pytest.mark.asyncio
async def test_persist_run_cosmos_error_is_swallowed() -> None:
    """_persist_run swallows Cosmos errors and does not raise."""
    from services.api_gateway.simulation_endpoints import _persist_run

    mock_cosmos = MagicMock()
    mock_cosmos.get_database_client.side_effect = Exception("cosmos unavailable")

    run = {"run_id": "sim-test", "scenario_id": "vm-high-cpu"}
    # Should not raise
    await _persist_run(mock_cosmos, run)


# ---------------------------------------------------------------------------
# 12. _query_runs / _get_run_by_id — Cosmos errors return graceful defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_runs_cosmos_error_returns_empty() -> None:
    """_query_runs returns [] on Cosmos error."""
    from services.api_gateway.simulation_endpoints import _query_runs

    mock_cosmos = MagicMock()
    mock_cosmos.get_database_client.side_effect = Exception("cosmos error")

    result = await _query_runs(mock_cosmos, None, 50)
    assert result == []


@pytest.mark.asyncio
async def test_get_run_by_id_cosmos_error_returns_none() -> None:
    """_get_run_by_id returns None on Cosmos error."""
    from services.api_gateway.simulation_endpoints import _get_run_by_id

    mock_cosmos = MagicMock()
    mock_cosmos.get_database_client.side_effect = Exception("cosmos error")

    result = await _get_run_by_id(mock_cosmos, "sim-xyz")
    assert result is None
