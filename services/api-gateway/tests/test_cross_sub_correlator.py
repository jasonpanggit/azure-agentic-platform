"""Tests for cross_sub_correlator.py (Phase 86).

Covers:
- _parse_iso: ISO timestamp parsing
- _recency_score: decay function
- _extract_resource_name / _group_incidents_into_correlation_groups: pattern detection
- detect_correlation_groups: full flow, error handling
- get_active_groups: happy path, error handling
- persist_groups: upsert, empty list, error handling
- get_correlation_summary: computation, error handling
"""
from __future__ import annotations

import os
import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.cross_sub_correlator import (
    CorrelationGroup,
    _group_incidents_into_correlation_groups,
    _parse_iso,
    _recency_score,
    _recommended_action,
    detect_correlation_groups,
    get_active_groups,
    get_correlation_summary,
    persist_groups,
)


# ---------------------------------------------------------------------------
# _parse_iso
# ---------------------------------------------------------------------------

class TestParseIso:
    def test_z_suffix(self):
        dt = _parse_iso("2026-04-17T10:00:00Z")
        assert dt is not None
        assert dt.year == 2026

    def test_offset(self):
        dt = _parse_iso("2026-04-17T10:00:00+00:00")
        assert dt is not None

    def test_empty_string(self):
        assert _parse_iso("") is None

    def test_invalid_string(self):
        assert _parse_iso("not-a-date") is None


# ---------------------------------------------------------------------------
# _recency_score
# ---------------------------------------------------------------------------

class TestRecencyScore:
    def test_zero_age_is_one(self):
        assert _recency_score(0) == pytest.approx(1.0)

    def test_half_life(self):
        # At exactly the half-life, score should be ~0.5
        score = _recency_score(30)
        assert score == pytest.approx(0.5, abs=0.01)

    def test_decay_monotonic(self):
        scores = [_recency_score(m) for m in [0, 10, 30, 60, 120]]
        assert scores == sorted(scores, reverse=True)

    def test_positive_result(self):
        assert _recency_score(100) > 0.0


# ---------------------------------------------------------------------------
# _group_incidents_into_correlation_groups
# ---------------------------------------------------------------------------

def _make_incident(sub_id, resource_type="Microsoft.Compute/virtualMachines", domain="compute", rg="rg-1", minutes_ago=5):
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "incident_id": f"inc-{sub_id}-{minutes_ago}",
        "resource_type": resource_type,
        "domain": domain,
        "subscription_id": sub_id,
        "resource_group": rg,
        "created_at": ts,
    }


class TestGroupIncidents:
    def test_subscription_storm_detected(self):
        now = datetime.now(timezone.utc)
        incidents = [
            _make_incident(f"sub-{i}", minutes_ago=2)
            for i in range(4)  # 4 subs, same type+domain within window
        ]
        groups = _group_incidents_into_correlation_groups(incidents, now)
        storms = [g for g in groups if g.pattern == "subscription_storm"]
        assert len(storms) >= 1
        assert storms[0].affected_count >= 3

    def test_no_storm_below_threshold(self):
        now = datetime.now(timezone.utc)
        incidents = [
            _make_incident(f"sub-{i}", minutes_ago=2)
            for i in range(2)  # only 2 subs — below threshold of 3
        ]
        groups = _group_incidents_into_correlation_groups(incidents, now)
        storms = [g for g in groups if g.pattern == "subscription_storm"]
        assert len(storms) == 0

    def test_blast_radius_detected(self):
        now = datetime.now(timezone.utc)
        incidents = [
            _make_incident("sub-1", rg=f"rg-{i}", minutes_ago=5)
            for i in range(6)  # 6 resource groups — above threshold of 5
        ]
        groups = _group_incidents_into_correlation_groups(incidents, now)
        blast = [g for g in groups if g.pattern == "blast_radius"]
        assert len(blast) >= 1
        assert blast[0].affected_count >= 5

    def test_no_blast_radius_below_threshold(self):
        now = datetime.now(timezone.utc)
        incidents = [
            _make_incident("sub-1", rg=f"rg-{i}", minutes_ago=5)
            for i in range(3)  # only 3 RGs — below threshold
        ]
        groups = _group_incidents_into_correlation_groups(incidents, now)
        blast = [g for g in groups if g.pattern == "blast_radius"]
        assert len(blast) == 0

    def test_empty_incidents(self):
        groups = _group_incidents_into_correlation_groups([], datetime.now(timezone.utc))
        assert groups == []

    def test_group_has_required_fields(self):
        now = datetime.now(timezone.utc)
        incidents = [_make_incident(f"sub-{i}", minutes_ago=1) for i in range(4)]
        groups = _group_incidents_into_correlation_groups(incidents, now)
        if groups:
            g = groups[0]
            assert g.group_id
            assert g.pattern in ("subscription_storm", "blast_radius", "cluster")
            assert g.title
            assert g.score >= 0.0
            assert g.detected_at

    def test_score_between_0_and_1(self):
        now = datetime.now(timezone.utc)
        incidents = [_make_incident(f"sub-{i}", minutes_ago=1) for i in range(5)]
        groups = _group_incidents_into_correlation_groups(incidents, now)
        for g in groups:
            assert 0.0 <= g.score <= 1.0

    def test_incident_ids_populated(self):
        now = datetime.now(timezone.utc)
        incidents = [_make_incident(f"sub-{i}", minutes_ago=1) for i in range(4)]
        groups = _group_incidents_into_correlation_groups(incidents, now)
        if groups:
            assert len(groups[0].incident_ids) > 0


# ---------------------------------------------------------------------------
# _recommended_action
# ---------------------------------------------------------------------------

class TestRecommendedAction:
    def test_subscription_storm_action(self):
        action = _recommended_action("subscription_storm", "Microsoft.Compute/virtualMachines", "compute")
        assert "shared infrastructure" in action.lower() or "subscription" in action.lower()

    def test_blast_radius_action(self):
        action = _recommended_action("blast_radius", "Microsoft.Storage/storageAccounts", "storage")
        assert "blast" in action.lower() or "scope" in action.lower()


# ---------------------------------------------------------------------------
# detect_correlation_groups
# ---------------------------------------------------------------------------

def _make_cosmos_client_for_incidents(items):
    container = MagicMock()
    container.query_items.return_value = iter(items)
    db = MagicMock()
    db.get_container_client.return_value = container
    client = MagicMock()
    client.get_database_client.return_value = db
    return client


class TestDetectCorrelationGroups:
    def test_returns_list_on_success(self):
        incidents = [_make_incident(f"sub-{i}") for i in range(4)]
        client = _make_cosmos_client_for_incidents(incidents)
        result = detect_correlation_groups(client, "aap")
        assert isinstance(result, list)

    def test_never_raises_on_cosmos_error(self):
        client = MagicMock()
        client.get_database_client.side_effect = Exception("Cosmos down")
        result = detect_correlation_groups(client, "aap")
        assert result == []

    def test_never_raises_on_none_client(self):
        result = detect_correlation_groups(None, "aap")
        assert isinstance(result, list)

    def test_empty_incidents_returns_empty(self):
        client = _make_cosmos_client_for_incidents([])
        result = detect_correlation_groups(client, "aap")
        assert result == []


# ---------------------------------------------------------------------------
# get_active_groups
# ---------------------------------------------------------------------------

def _make_group_doc(group_id="grp-1", pattern="subscription_storm"):
    return {
        "id": group_id,
        "group_id": group_id,
        "pattern": pattern,
        "title": "Test storm",
        "incident_ids": ["inc-1", "inc-2"],
        "subscription_ids": ["sub-1", "sub-2", "sub-3"],
        "resource_type": "Microsoft.Compute/virtualMachines",
        "domain": "compute",
        "time_window_start": "2026-04-17T09:00:00+00:00",
        "time_window_end": "2026-04-17T09:15:00+00:00",
        "score": 0.75,
        "affected_count": 3,
        "recommended_action": "Investigate shared infra",
        "detected_at": "2026-04-17T09:20:00+00:00",
        "ttl": 7200,
    }


class TestGetActiveGroups:
    def test_returns_groups(self):
        docs = [_make_group_doc("g1"), _make_group_doc("g2", "blast_radius")]
        container = MagicMock()
        container.query_items.return_value = iter(docs)
        db = MagicMock()
        db.create_container_if_not_exists.return_value = container
        client = MagicMock()
        client.get_database_client.return_value = db

        groups = get_active_groups(client, "aap")
        assert len(groups) == 2
        assert groups[0].group_id == "g1"
        assert groups[1].pattern == "blast_radius"

    def test_never_raises_on_error(self):
        client = MagicMock()
        client.get_database_client.side_effect = RuntimeError("boom")
        groups = get_active_groups(client, "aap")
        assert groups == []

    def test_never_raises_on_none_client(self):
        groups = get_active_groups(None, "aap")
        assert isinstance(groups, list)


# ---------------------------------------------------------------------------
# persist_groups
# ---------------------------------------------------------------------------

class TestPersistGroups:
    def _make_group(self, gid="grp-1"):
        return CorrelationGroup(
            group_id=gid,
            pattern="subscription_storm",
            title="Test",
            incident_ids=["inc-1"],
            subscription_ids=["sub-1", "sub-2", "sub-3"],
            resource_type="Microsoft.Compute/virtualMachines",
            domain="compute",
            time_window_start="2026-04-17T09:00:00+00:00",
            time_window_end="2026-04-17T09:15:00+00:00",
            score=0.8,
            affected_count=3,
            recommended_action="Investigate",
            detected_at="2026-04-17T09:20:00+00:00",
        )

    def test_upserts_each_group(self):
        container = MagicMock()
        db = MagicMock()
        db.create_container_if_not_exists.return_value = container
        client = MagicMock()
        client.get_database_client.return_value = db

        groups = [self._make_group("g1"), self._make_group("g2")]
        persist_groups(client, "aap", groups)
        assert container.upsert_item.call_count == 2

    def test_no_op_on_empty_list(self):
        client = MagicMock()
        persist_groups(client, "aap", [])
        client.get_database_client.assert_not_called()

    def test_never_raises_on_upsert_error(self):
        container = MagicMock()
        container.upsert_item.side_effect = Exception("write error")
        db = MagicMock()
        db.create_container_if_not_exists.return_value = container
        client = MagicMock()
        client.get_database_client.return_value = db

        # Should not raise
        persist_groups(client, "aap", [self._make_group()])


# ---------------------------------------------------------------------------
# get_correlation_summary
# ---------------------------------------------------------------------------

class TestGetCorrelationSummary:
    def _setup_client(self, docs):
        container = MagicMock()
        container.query_items.return_value = iter(docs)
        db = MagicMock()
        db.create_container_if_not_exists.return_value = container
        client = MagicMock()
        client.get_database_client.return_value = db
        return client

    def test_counts_storms(self):
        docs = [
            _make_group_doc("g1", "subscription_storm"),
            _make_group_doc("g2", "subscription_storm"),
            _make_group_doc("g3", "blast_radius"),
        ]
        client = self._setup_client(docs)
        summary = get_correlation_summary(client, "aap")
        assert summary["active_storms"] == 2
        assert summary["blast_radius_events"] == 1
        assert summary["total_groups"] == 3

    def test_total_correlated_incidents(self):
        docs = [_make_group_doc("g1")]  # has 2 incident_ids
        client = self._setup_client(docs)
        summary = get_correlation_summary(client, "aap")
        assert summary["total_correlated_incidents"] == 2

    def test_empty_groups(self):
        client = self._setup_client([])
        summary = get_correlation_summary(client, "aap")
        assert summary["active_storms"] == 0
        assert summary["blast_radius_events"] == 0
        assert summary["total_correlated_incidents"] == 0
        assert summary["top_affected_resource_type"] is None

    def test_never_raises_on_error(self):
        client = MagicMock()
        client.get_database_client.side_effect = RuntimeError("boom")
        summary = get_correlation_summary(client, "aap")
        assert isinstance(summary, dict)
        assert summary["active_storms"] == 0

    def test_top_affected_resource_type(self):
        docs = [
            _make_group_doc("g1"),  # Microsoft.Compute/virtualMachines
            _make_group_doc("g2"),
        ]
        client = self._setup_client(docs)
        summary = get_correlation_summary(client, "aap")
        assert summary["top_affected_resource_type"] == "Microsoft.Compute/virtualMachines"
