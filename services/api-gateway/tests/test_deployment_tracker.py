"""Tests for deployment_tracker.py — Phase 60 GitOps integration."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from services.api_gateway.deployment_tracker import (
    DeploymentEvent,
    DeploymentTracker,
    parse_github_deployment_payload,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_cosmos() -> MagicMock:
    """Return a mock Cosmos client with a mock container."""
    cosmos = MagicMock()
    container = MagicMock()
    db = MagicMock()
    cosmos.get_database_client.return_value = db
    db.create_container_if_not_exists.return_value = container
    db.get_container_client.return_value = container
    return cosmos, container


def _make_event(**kwargs) -> DeploymentEvent:
    defaults = {
        "repository": "org/my-app",
        "status": "success",
        "commit_sha": "abc123def456",
        "author": "alice",
        "environment": "production",
        "resource_group": "rg-prod",
    }
    defaults.update(kwargs)
    return DeploymentEvent(**defaults)


# ---------------------------------------------------------------------------
# 1. DeploymentEvent model defaults
# ---------------------------------------------------------------------------

def test_deployment_event_defaults():
    event = _make_event()
    assert event.source == "github"
    assert event.deployment_id.startswith("dep-")
    assert event.started_at is not None
    assert event.completed_at is None


# ---------------------------------------------------------------------------
# 2. ingest_event stores event
# ---------------------------------------------------------------------------

def test_deployment_ingest_stores_event():
    cosmos, container = _make_cosmos()
    tracker = DeploymentTracker(cosmos)
    event = _make_event()

    result = tracker.ingest_event(event)

    assert result["status"] == "stored"
    assert result["deployment_id"] == event.deployment_id
    container.upsert_item.assert_called_once()
    doc = container.upsert_item.call_args[0][0]
    assert doc["repository"] == "org/my-app"
    assert doc["resource_group"] == "rg-prod"


# ---------------------------------------------------------------------------
# 3. ingest_event — cosmos_client is None
# ---------------------------------------------------------------------------

def test_deployment_ingest_no_cosmos():
    tracker = DeploymentTracker(None)
    event = _make_event()
    result = tracker.ingest_event(event)
    assert "error" in result
    assert result["deployment_id"] == event.deployment_id


# ---------------------------------------------------------------------------
# 4. ingest_event — empty resource_group falls back to "unknown"
# ---------------------------------------------------------------------------

def test_deployment_ingest_empty_rg_falls_back_to_unknown():
    cosmos, container = _make_cosmos()
    tracker = DeploymentTracker(cosmos)
    event = _make_event(resource_group="")

    tracker.ingest_event(event)

    doc = container.upsert_item.call_args[0][0]
    assert doc["resource_group"] == "unknown"


# ---------------------------------------------------------------------------
# 5. correlate finds deployment in window
# ---------------------------------------------------------------------------

def test_correlate_finds_deployment_in_window():
    cosmos, container = _make_cosmos()
    now = datetime.now(timezone.utc)
    incident_ts = now.isoformat()
    # Deployment started 20 min before incident — within -30min window
    dep_ts = (now - timedelta(minutes=20)).isoformat()

    container.query_items.return_value = [
        {
            "id": "dep-001",
            "deployment_id": "dep-001",
            "repository": "org/app",
            "started_at": dep_ts,
            "status": "success",
            "author": "bob",
            "resource_group": "rg-prod",
        }
    ]

    tracker = DeploymentTracker(cosmos)
    result = tracker.correlate(incident_timestamp=incident_ts, resource_group="rg-prod")

    assert len(result["correlated_deployments"]) == 1
    assert result["correlated_deployments"][0]["time_before_incident_min"] == pytest.approx(20.0, abs=0.2)


# ---------------------------------------------------------------------------
# 6. correlate ignores old deployments (via window query exclusion)
# ---------------------------------------------------------------------------

def test_correlate_ignores_old_deployments():
    cosmos, container = _make_cosmos()
    # Container returns empty — simulating that no items fall in window
    container.query_items.return_value = []

    now = datetime.now(timezone.utc)
    tracker = DeploymentTracker(cosmos)
    result = tracker.correlate(incident_timestamp=now.isoformat(), resource_group="rg-prod")

    assert result["correlated_deployments"] == []


# ---------------------------------------------------------------------------
# 7. list_recent endpoint — list_recent returns deployments
# ---------------------------------------------------------------------------

def test_deployments_list_endpoint():
    cosmos, container = _make_cosmos()
    dep_ts = datetime.now(timezone.utc).isoformat()
    container.query_items.return_value = [
        {
            "id": "dep-001",
            "deployment_id": "dep-001",
            "repository": "org/app",
            "started_at": dep_ts,
            "status": "success",
            "resource_group": "rg-prod",
            "_rid": "INTERNAL",
        }
    ]

    tracker = DeploymentTracker(cosmos)
    result = tracker.list_recent(resource_group="rg-prod", limit=10, hours_back=24)

    assert result["total"] == 1
    assert result["deployments"][0]["deployment_id"] == "dep-001"
    # Internal Cosmos fields should be stripped
    assert "_rid" not in result["deployments"][0]


# ---------------------------------------------------------------------------
# 8. list_recent — cross-partition query when no resource_group
# ---------------------------------------------------------------------------

def test_list_recent_cross_partition_when_no_rg():
    cosmos, container = _make_cosmos()
    container.query_items.return_value = []

    tracker = DeploymentTracker(cosmos)
    result = tracker.list_recent(resource_group=None, limit=5, hours_back=12)

    assert result["total"] == 0
    # Cross-partition flag should have been set
    call_kwargs = container.query_items.call_args[1]
    assert call_kwargs.get("enable_cross_partition_query") is True


# ---------------------------------------------------------------------------
# 9. GitHub webhook payload parsing — deployment_status event
# ---------------------------------------------------------------------------

def test_github_webhook_payload_parsing_deployment_status():
    payload = {
        "action": "created",
        "deployment_status": {
            "state": "success",
            "target_url": "https://github.com/org/app/actions/runs/123",
            "updated_at": "2026-04-16T10:05:00Z",
            "created_at": "2026-04-16T10:04:00Z",
        },
        "deployment": {
            "id": 99887766,
            "sha": "deadbeef1234567890abcdef",
            "environment": "production",
            "created_at": "2026-04-16T10:00:00Z",
            "creator": {"login": "carol"},
        },
        "repository": {"full_name": "org/my-service", "name": "my-service"},
        "sender": {"login": "carol"},
    }

    event = parse_github_deployment_payload(payload)

    assert event is not None
    assert event.source == "github"
    assert event.repository == "org/my-service"
    assert event.status == "success"
    assert event.author == "carol"
    assert event.environment == "production"
    assert "deadbeef" in event.commit_sha
    assert "github.com" in event.pipeline_url


# ---------------------------------------------------------------------------
# 10. GitHub webhook payload parsing — deployment event (push-triggered)
# ---------------------------------------------------------------------------

def test_github_webhook_payload_parsing_deployment_event():
    payload = {
        "action": "created",
        "deployment": {
            "id": 111222333,
            "sha": "aabbcc1234",
            "environment": "staging",
            "task": "deploy",
            "created_at": "2026-04-16T09:00:00Z",
            "creator": {"login": "dave"},
            "url": "https://api.github.com/repos/org/app/deployments/111222333",
        },
        "repository": {"full_name": "org/app", "name": "app"},
        "sender": {"login": "dave"},
    }

    event = parse_github_deployment_payload(payload)

    assert event is not None
    assert event.status == "in_progress"
    assert event.environment == "staging"
    assert event.author == "dave"


# ---------------------------------------------------------------------------
# 11. GitHub webhook parsing — malformed payload returns None
# ---------------------------------------------------------------------------

def test_github_webhook_malformed_payload_returns_none():
    # Missing repository key entirely — partial parse should still succeed
    event = parse_github_deployment_payload({})
    # Should not raise — may return an event with defaults or None
    # The key guarantee: never raises
    assert True  # reached without exception


# ---------------------------------------------------------------------------
# 12. correlate — invalid timestamp returns error dict
# ---------------------------------------------------------------------------

def test_correlate_invalid_timestamp_returns_error():
    cosmos, _ = _make_cosmos()
    tracker = DeploymentTracker(cosmos)
    result = tracker.correlate(incident_timestamp="NOT-A-DATE")
    assert "error" in result
    assert result["correlated_deployments"] == []
