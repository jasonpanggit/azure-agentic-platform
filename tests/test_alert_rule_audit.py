"""Unit tests for alert_rule_audit_service.py (Phase 90).

Covers:
- scan_alert_coverage: happy path, ARG failure, no gaps (all covered), empty subscriptions
- persist_gaps: happy path, empty list, exception
- get_gaps: happy path, subscription filter, severity filter, exception
- get_alert_coverage_summary: empty, all critical, mixed, exception
- AlertCoverageGap.to_dict: structure validation
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.alert_rule_audit_service import (
    AlertCoverageGap,
    get_alert_coverage_summary,
    get_gaps,
    persist_gaps,
    scan_alert_coverage,
    CRITICAL_RESOURCE_TYPES,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_metric_alert(sub: str, rtype: str) -> Dict[str, Any]:
    return {
        "rule_id": f"/sub/{sub}/alert1",
        "rule_name": "alert1",
        "subscription_id": sub,
        "resource_group": "rg1",
        "severity": 2,
        "enabled": True,
        "target_resource_type": rtype.lower(),
        "description": "Test alert",
    }


def _make_resource_row(sub: str, rtype: str, count: int = 3) -> Dict[str, Any]:
    return {
        "type": rtype.lower(),
        "subscription_id": sub,
        "resource_count": count,
    }


# ---------------------------------------------------------------------------
# AlertCoverageGap.to_dict (2)
# ---------------------------------------------------------------------------

def test_gap_to_dict_has_required_keys():
    gap = AlertCoverageGap(
        gap_id="gid1", subscription_id="sub1", resource_type="Virtual Machines",
        resource_count=5, alert_rule_count=0, severity="critical",
        recommendation="Add CPU alerts.", scanned_at="2026-01-01T00:00:00Z",
    )
    d = gap.to_dict()
    assert d["id"] == "gid1"
    assert d["gap_id"] == "gid1"
    assert d["resource_type"] == "Virtual Machines"
    assert d["ttl"] == 86400


def test_gap_to_dict_stable_id():
    gap1 = AlertCoverageGap(
        gap_id="gid1", subscription_id="sub1", resource_type="VMs",
        resource_count=2, alert_rule_count=0, severity="high",
        recommendation="x", scanned_at="2026-01-01T00:00:00Z",
    )
    gap2 = AlertCoverageGap(
        gap_id="gid1", subscription_id="sub1", resource_type="VMs",
        resource_count=2, alert_rule_count=0, severity="high",
        recommendation="x", scanned_at="2026-01-02T00:00:00Z",
    )
    assert gap1.to_dict()["id"] == gap2.to_dict()["id"]


# ---------------------------------------------------------------------------
# scan_alert_coverage tests (8)
# ---------------------------------------------------------------------------

def test_scan_alert_coverage_gap_found():
    credential = MagicMock()
    metric_alerts: list = []
    activity_alerts: list = []
    resource_rows = [_make_resource_row("sub1", "microsoft.compute/virtualmachines")]
    with patch(
        "services.api_gateway.alert_rule_audit_service.run_arg_query",
        side_effect=[metric_alerts, activity_alerts, resource_rows],
    ):
        gaps = scan_alert_coverage(credential, ["sub1"])
    assert len(gaps) == 1
    assert gaps[0].severity == "critical"
    assert gaps[0].resource_type == "Virtual Machines"


def test_scan_alert_coverage_no_gap_when_covered():
    credential = MagicMock()
    metric_alerts = [_make_metric_alert("sub1", "microsoft.compute/virtualmachines")]
    activity_alerts: list = []
    resource_rows = [_make_resource_row("sub1", "microsoft.compute/virtualmachines")]
    with patch(
        "services.api_gateway.alert_rule_audit_service.run_arg_query",
        side_effect=[metric_alerts, activity_alerts, resource_rows],
    ):
        gaps = scan_alert_coverage(credential, ["sub1"])
    assert gaps == []


def test_scan_alert_coverage_multiple_resource_types():
    credential = MagicMock()
    metric_alerts: list = []
    activity_alerts: list = []
    resource_rows = [
        _make_resource_row("sub1", "microsoft.compute/virtualmachines"),
        _make_resource_row("sub1", "microsoft.keyvault/vaults"),
        _make_resource_row("sub1", "microsoft.web/sites"),
    ]
    with patch(
        "services.api_gateway.alert_rule_audit_service.run_arg_query",
        side_effect=[metric_alerts, activity_alerts, resource_rows],
    ):
        gaps = scan_alert_coverage(credential, ["sub1"])
    assert len(gaps) == 3


def test_scan_alert_coverage_arg_failure_returns_empty():
    credential = MagicMock()
    with patch(
        "services.api_gateway.alert_rule_audit_service.run_arg_query",
        side_effect=Exception("ARG error"),
    ):
        gaps = scan_alert_coverage(credential, ["sub1"])
    assert gaps == []


def test_scan_alert_coverage_unknown_resource_type_skipped():
    credential = MagicMock()
    metric_alerts: list = []
    activity_alerts: list = []
    resource_rows = [_make_resource_row("sub1", "microsoft.unknown/widgets")]
    with patch(
        "services.api_gateway.alert_rule_audit_service.run_arg_query",
        side_effect=[metric_alerts, activity_alerts, resource_rows],
    ):
        gaps = scan_alert_coverage(credential, ["sub1"])
    assert gaps == []


def test_scan_alert_coverage_stable_gap_id():
    credential = MagicMock()
    metric_alerts: list = []
    activity_alerts: list = []
    resource_rows = [_make_resource_row("sub1", "microsoft.compute/virtualmachines")]
    with patch(
        "services.api_gateway.alert_rule_audit_service.run_arg_query",
        side_effect=[metric_alerts, activity_alerts, resource_rows],
    ):
        g1 = scan_alert_coverage(credential, ["sub1"])
    with patch(
        "services.api_gateway.alert_rule_audit_service.run_arg_query",
        side_effect=[metric_alerts, activity_alerts, resource_rows],
    ):
        g2 = scan_alert_coverage(credential, ["sub1"])
    assert g1[0].gap_id == g2[0].gap_id


def test_scan_alert_coverage_high_severity_resource():
    credential = MagicMock()
    metric_alerts: list = []
    activity_alerts: list = []
    resource_rows = [_make_resource_row("sub1", "microsoft.network/networksecuritygroups")]
    with patch(
        "services.api_gateway.alert_rule_audit_service.run_arg_query",
        side_effect=[metric_alerts, activity_alerts, resource_rows],
    ):
        gaps = scan_alert_coverage(credential, ["sub1"])
    assert gaps[0].severity == "high"


def test_scan_alert_coverage_medium_severity_resource():
    credential = MagicMock()
    metric_alerts: list = []
    activity_alerts: list = []
    resource_rows = [_make_resource_row("sub1", "microsoft.web/sites")]
    with patch(
        "services.api_gateway.alert_rule_audit_service.run_arg_query",
        side_effect=[metric_alerts, activity_alerts, resource_rows],
    ):
        gaps = scan_alert_coverage(credential, ["sub1"])
    assert gaps[0].severity == "medium"


# ---------------------------------------------------------------------------
# persist_gaps tests (3)
# ---------------------------------------------------------------------------

def test_persist_gaps_upserts_all():
    cosmos = MagicMock()
    container = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    gaps = [
        AlertCoverageGap(
            gap_id="gid1", subscription_id="sub1", resource_type="Virtual Machines",
            resource_count=3, alert_rule_count=0, severity="critical",
            recommendation="Add CPU alerts.", scanned_at="2026-01-01T00:00:00Z",
        )
    ]
    persist_gaps(cosmos, "aap", gaps)
    container.upsert_item.assert_called_once()


def test_persist_gaps_empty_list_no_call():
    cosmos = MagicMock()
    persist_gaps(cosmos, "aap", [])
    cosmos.get_database_client.assert_not_called()


def test_persist_gaps_exception_does_not_raise():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("cosmos error")
    gaps = [
        AlertCoverageGap(
            gap_id="gid2", subscription_id="sub1", resource_type="Key Vaults",
            resource_count=1, alert_rule_count=0, severity="critical",
            recommendation="Add availability alerts.", scanned_at="2026-01-01T00:00:00Z",
        )
    ]
    # Must not raise
    persist_gaps(cosmos, "aap", gaps)


# ---------------------------------------------------------------------------
# get_gaps tests (3)
# ---------------------------------------------------------------------------

def test_get_gaps_returns_items():
    cosmos = MagicMock()
    expected = [{"gap_id": "g1", "severity": "critical"}]
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter(expected)
    result = get_gaps(cosmos, "aap")
    assert result == expected


def test_get_gaps_with_filters():
    cosmos = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter([])
    result = get_gaps(cosmos, "aap", subscription_ids=["sub1"], severity="high")
    assert result == []


def test_get_gaps_exception_returns_empty():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("db error")
    result = get_gaps(cosmos, "aap")
    assert result == []


# ---------------------------------------------------------------------------
# get_alert_coverage_summary tests (5)
# ---------------------------------------------------------------------------

def test_get_alert_coverage_summary_empty():
    cosmos = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter([])
    result = get_alert_coverage_summary(cosmos, "aap")
    assert result["total_gaps"] == 0
    assert "overall_coverage_pct" in result


def test_get_alert_coverage_summary_all_critical():
    cosmos = MagicMock()
    items = [
        {"severity": "critical", "subscription_id": "sub1"},
        {"severity": "critical", "subscription_id": "sub1"},
    ]
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter(items)
    result = get_alert_coverage_summary(cosmos, "aap")
    assert result["critical_gaps"] == 2
    assert result["subscriptions_with_gaps"] == 1


def test_get_alert_coverage_summary_mixed():
    cosmos = MagicMock()
    items = [
        {"severity": "critical", "subscription_id": "sub1"},
        {"severity": "high", "subscription_id": "sub2"},
        {"severity": "medium", "subscription_id": "sub2"},
    ]
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter(items)
    result = get_alert_coverage_summary(cosmos, "aap")
    assert result["total_gaps"] == 3
    assert result["high_gaps"] == 1
    assert result["medium_gaps"] == 1
    assert result["subscriptions_with_gaps"] == 2


def test_get_alert_coverage_summary_coverage_pct_non_negative():
    cosmos = MagicMock()
    items = [{"severity": "critical", "subscription_id": "sub1"} for _ in range(20)]
    cosmos.get_database_client.return_value.get_container_client.return_value.query_items.return_value = iter(items)
    result = get_alert_coverage_summary(cosmos, "aap")
    assert result["overall_coverage_pct"] >= 0.0


def test_get_alert_coverage_summary_exception_returns_defaults():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("db error")
    result = get_alert_coverage_summary(cosmos, "aap")
    assert result["total_gaps"] == 0
    assert result["critical_gaps"] == 0
