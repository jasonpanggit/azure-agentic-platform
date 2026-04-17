from __future__ import annotations
"""Unit tests for forecast API endpoints (INTEL-005).

Tests cover:
- GET /api/v1/forecasts?resource_id= (tests 1–6)
- GET /api/v1/forecasts/imminent (tests 7–9)
- _docs_to_forecast_result helper (test 10)
"""
import os

import os
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.auth import verify_token
from services.api_gateway.forecast_endpoints import (
    _docs_to_forecast_result,
    _group_docs_by_resource,
    router,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_baseline_doc(**overrides) -> dict:
    """Return a minimal Cosmos baseline doc dict for testing."""
    base = {
        "id": "/sub/rg/vm1:Percentage CPU",
        "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/microsoft.compute/virtualmachines/vm1",
        "resource_type": "microsoft.compute/virtualmachines",
        "metric_name": "Percentage CPU",
        "level": 72.5,
        "trend": 1.2,
        "threshold": 90.0,
        "invert": False,
        "time_to_breach_minutes": 73.0,
        "confidence": "medium",
        "mape": 18.5,
        "last_updated": "2026-04-03T10:00:00Z",
    }
    base.update(overrides)
    return base


_VM1_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/microsoft.compute/virtualmachines/vm1"
_VM2_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/microsoft.compute/virtualmachines/vm2"


def _mock_token():
    return {"sub": "test-user"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_forecaster():
    """ForecasterClient mock with controllable return values."""
    client = MagicMock()
    client.get_forecasts.return_value = []
    client.get_all_imminent.return_value = []
    return client


@pytest.fixture()
def test_app(mock_forecaster):
    """FastAPI test app with forecast router, mocked state, and no-op auth."""
    app = FastAPI()
    app.include_router(router)
    app.state.forecaster_client = mock_forecaster
    app.dependency_overrides[verify_token] = _mock_token
    return app


@pytest.fixture()
def client(test_app, mock_forecaster):
    """TestClient backed by test_app."""
    with TestClient(test_app) as c:
        yield c, mock_forecaster


@pytest.fixture()
def client_no_forecaster():
    """TestClient with forecaster_client=None to test 503 responses."""
    app = FastAPI()
    app.include_router(router)
    app.state.forecaster_client = None
    app.dependency_overrides[verify_token] = _mock_token
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/forecasts?resource_id=
# ---------------------------------------------------------------------------


def test_get_resource_forecasts_503_when_forecaster_none(client_no_forecaster):
    """503 is returned when app.state.forecaster_client is None."""
    resp = client_no_forecaster.get(
        "/api/v1/forecasts", params={"resource_id": _VM1_ID}
    )
    assert resp.status_code == 503
    assert "not available" in resp.json()["detail"].lower()


def test_get_resource_forecasts_404_when_no_baselines(client):
    """404 is returned when forecaster returns an empty list for the resource."""
    http_client, mock_fc = client
    mock_fc.get_forecasts.return_value = []

    resp = http_client.get(
        "/api/v1/forecasts", params={"resource_id": _VM1_ID}
    )
    assert resp.status_code == 404
    assert "No forecast baselines" in resp.json()["detail"]
    mock_fc.get_forecasts.assert_called_once_with(_VM1_ID)


def test_get_resource_forecasts_200_single_metric(client):
    """200 with a valid ForecastResult when one baseline doc is returned."""
    http_client, mock_fc = client
    doc = _make_baseline_doc()
    mock_fc.get_forecasts.return_value = [doc]

    resp = http_client.get(
        "/api/v1/forecasts", params={"resource_id": _VM1_ID}
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["resource_id"] == _VM1_ID
    assert body["resource_type"] == "microsoft.compute/virtualmachines"
    assert len(body["forecasts"]) == 1

    forecast = body["forecasts"][0]
    assert forecast["metric_name"] == "Percentage CPU"
    assert forecast["current_value"] == 72.5
    assert forecast["trend_per_interval"] == 1.2
    assert forecast["threshold"] == 90.0
    assert forecast["confidence"] == "medium"
    assert forecast["mape"] == 18.5
    assert forecast["last_updated"] == "2026-04-03T10:00:00Z"


def test_get_resource_forecasts_200_multiple_metrics(client):
    """200 with three MetricForecast entries when three docs are returned."""
    http_client, mock_fc = client
    docs = [
        _make_baseline_doc(metric_name="Percentage CPU", level=72.5),
        _make_baseline_doc(
            metric_name="Available Memory Bytes", level=0.5, trend=-0.01,
            threshold=0.1, invert=True, time_to_breach_minutes=200.0
        ),
        _make_baseline_doc(
            metric_name="OS Disk Queue Depth", level=3.0, trend=0.1,
            threshold=10.0, time_to_breach_minutes=350.0
        ),
    ]
    mock_fc.get_forecasts.return_value = docs

    resp = http_client.get(
        "/api/v1/forecasts", params={"resource_id": _VM1_ID}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["forecasts"]) == 3
    metric_names = {f["metric_name"] for f in body["forecasts"]}
    assert metric_names == {"Percentage CPU", "Available Memory Bytes", "OS Disk Queue Depth"}


def test_get_resource_forecasts_breach_imminent_true(client):
    """breach_imminent=True and has_imminent_breach=True when ttb < 60 minutes."""
    http_client, mock_fc = client
    doc = _make_baseline_doc(time_to_breach_minutes=30.0)
    mock_fc.get_forecasts.return_value = [doc]

    resp = http_client.get(
        "/api/v1/forecasts", params={"resource_id": _VM1_ID}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_imminent_breach"] is True
    assert body["forecasts"][0]["breach_imminent"] is True


def test_get_resource_forecasts_breach_imminent_false(client):
    """breach_imminent=False and has_imminent_breach=False when ttb is None."""
    http_client, mock_fc = client
    doc = _make_baseline_doc(time_to_breach_minutes=None)
    mock_fc.get_forecasts.return_value = [doc]

    resp = http_client.get(
        "/api/v1/forecasts", params={"resource_id": _VM1_ID}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_imminent_breach"] is False
    assert body["forecasts"][0]["breach_imminent"] is False


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/forecasts/imminent
# ---------------------------------------------------------------------------


def test_get_imminent_forecasts_503_when_forecaster_none(client_no_forecaster):
    """503 is returned for /imminent when app.state.forecaster_client is None."""
    resp = client_no_forecaster.get("/api/v1/forecasts/imminent")
    assert resp.status_code == 503
    assert "not available" in resp.json()["detail"].lower()


def test_get_imminent_forecasts_empty_list(client):
    """200 with empty list when get_all_imminent returns no docs."""
    http_client, mock_fc = client
    mock_fc.get_all_imminent.return_value = []

    resp = http_client.get("/api/v1/forecasts/imminent")
    assert resp.status_code == 200
    assert resp.json() == []
    mock_fc.get_all_imminent.assert_called_once()


def test_get_imminent_forecasts_groups_by_resource(client):
    """Two ForecastResult objects returned when docs span two resource_ids."""
    http_client, mock_fc = client
    docs = [
        _make_baseline_doc(
            resource_id=_VM1_ID, metric_name="Percentage CPU",
            time_to_breach_minutes=30.0
        ),
        _make_baseline_doc(
            resource_id=_VM1_ID, metric_name="OS Disk Queue Depth",
            time_to_breach_minutes=45.0
        ),
        _make_baseline_doc(
            resource_id=_VM2_ID, metric_name="Percentage CPU",
            time_to_breach_minutes=55.0
        ),
    ]
    mock_fc.get_all_imminent.return_value = docs

    resp = http_client.get("/api/v1/forecasts/imminent")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2

    resource_ids = {r["resource_id"] for r in body}
    assert resource_ids == {_VM1_ID, _VM2_ID}

    # VM1 should have two metric forecasts
    vm1 = next(r for r in body if r["resource_id"] == _VM1_ID)
    assert len(vm1["forecasts"]) == 2
    assert vm1["has_imminent_breach"] is True


# ---------------------------------------------------------------------------
# Tests: _docs_to_forecast_result helper
# ---------------------------------------------------------------------------


def test_docs_to_forecast_result_correct_fields():
    """_docs_to_forecast_result maps level→current_value, trend→trend_per_interval."""
    doc = _make_baseline_doc(
        level=88.0,
        trend=2.5,
        threshold=90.0,
        time_to_breach_minutes=4.0,
        confidence="high",
        mape=5.0,
        metric_name="Percentage CPU",
        last_updated="2026-04-03T12:00:00Z",
    )
    result = _docs_to_forecast_result([doc])

    assert result.resource_id == _VM1_ID
    assert result.resource_type == "microsoft.compute/virtualmachines"
    assert len(result.forecasts) == 1

    f = result.forecasts[0]
    assert f.current_value == 88.0          # level → current_value
    assert f.trend_per_interval == 2.5      # trend → trend_per_interval
    assert f.threshold == 90.0
    assert f.time_to_breach_minutes == 4.0
    assert f.confidence == "high"
    assert f.mape == 5.0
    assert f.last_updated == "2026-04-03T12:00:00Z"
    assert f.breach_imminent is True        # 4.0 < 60
    assert result.has_imminent_breach is True


def test_docs_to_forecast_result_raises_on_empty():
    """_docs_to_forecast_result raises ValueError when given an empty list."""
    with pytest.raises(ValueError, match="No docs"):
        _docs_to_forecast_result([])


def test_group_docs_by_resource_single_resource():
    """_group_docs_by_resource returns one ForecastResult for a single resource."""
    docs = [
        _make_baseline_doc(metric_name="Percentage CPU"),
        _make_baseline_doc(metric_name="OS Disk Queue Depth", level=5.0, trend=0.1),
    ]
    results = _group_docs_by_resource(docs)
    assert len(results) == 1
    assert results[0].resource_id == _VM1_ID
    assert len(results[0].forecasts) == 2
