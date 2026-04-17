from __future__ import annotations
"""Tests for disk_audit_service.py — Phase 100."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.disk_audit_service import (
    _build_disk_finding,
    _build_snapshot_finding,
    _days_old_from_created_at,
    _disk_severity,
    _estimate_disk_cost,
    _estimate_snapshot_cost,
    _snapshot_severity,
    get_disk_findings,
    get_disk_summary,
    persist_disk_findings,
    scan_orphaned_disks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCANNED_AT = datetime.now(timezone.utc).isoformat()
_OLD_DATE = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
_VERY_OLD_DATE = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()


def _make_disk_row(
    name: str = "disk-orphan-01",
    size_gb: int = 128,
    sku: str = "Premium_LRS",
    created_at: str = _OLD_DATE,
    sub_id: str = "sub-001",
    rg: str = "rg-compute",
    arm_id: str = "/subscriptions/sub-001/resourceGroups/rg-compute/providers/Microsoft.Compute/disks/disk-orphan-01",
) -> Dict[str, Any]:
    return {
        "subscriptionId": sub_id,
        "resourceGroup": rg,
        "name": name,
        "diskSizeGb": size_gb,
        "sku": sku,
        "createdAt": created_at,
        "id": arm_id,
    }


def _make_snapshot_row(
    name: str = "snap-old-01",
    size_gb: int = 64,
    created_at: str = _OLD_DATE,
    days_old: int = 60,
    source_id: str = "/subscriptions/sub-001/disk/disk-01",
    sub_id: str = "sub-001",
    rg: str = "rg-compute",
    arm_id: str = "/subscriptions/sub-001/resourceGroups/rg-compute/providers/Microsoft.Compute/snapshots/snap-old-01",
) -> Dict[str, Any]:
    return {
        "subscriptionId": sub_id,
        "resourceGroup": rg,
        "name": name,
        "snapshotSizeGb": size_gb,
        "createdAt": created_at,
        "daysOld": days_old,
        "sourceResourceId": source_id,
        "id": arm_id,
    }


def _make_cosmos_client(items: List[Dict[str, Any]]) -> MagicMock:
    container = MagicMock()
    container.query_items.return_value = items
    db = MagicMock()
    db.get_container_client.return_value = container
    client = MagicMock()
    client.get_database_client.return_value = db
    return client


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


def test_estimate_disk_cost_premium():
    cost = _estimate_disk_cost(100, "Premium_LRS")
    assert cost == pytest.approx(13.5, 0.01)


def test_estimate_disk_cost_standard():
    cost = _estimate_disk_cost(100, "Standard_LRS")
    assert cost == pytest.approx(5.0, 0.01)


def test_estimate_disk_cost_unknown_sku_uses_default():
    cost = _estimate_disk_cost(100, "Unknown_SKU")
    assert cost == pytest.approx(5.0, 0.01)


def test_estimate_snapshot_cost():
    cost = _estimate_snapshot_cost(100)
    assert cost == pytest.approx(5.0, 0.01)


def test_estimate_disk_cost_zero_size():
    assert _estimate_disk_cost(0, "Premium_LRS") == 0.0


# ---------------------------------------------------------------------------
# _days_old_from_created_at
# ---------------------------------------------------------------------------


def test_days_old_recent():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert _days_old_from_created_at(yesterday) == 1


def test_days_old_60():
    date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    assert _days_old_from_created_at(date) == 60


def test_days_old_invalid_string():
    assert _days_old_from_created_at("not-a-date") == 0


def test_days_old_empty_string():
    assert _days_old_from_created_at("") == 0


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


def test_disk_severity_always_high():
    assert _disk_severity(0) == "high"
    assert _disk_severity(365) == "high"


def test_snapshot_severity_over_90_is_medium():
    assert _snapshot_severity(91) == "medium"
    assert _snapshot_severity(365) == "medium"


def test_snapshot_severity_30_to_90_is_low():
    assert _snapshot_severity(31) == "low"
    assert _snapshot_severity(90) == "low"


# ---------------------------------------------------------------------------
# _build_disk_finding
# ---------------------------------------------------------------------------


def test_build_disk_finding_fields():
    row = _make_disk_row()
    f = _build_disk_finding(row, _SCANNED_AT)

    assert f["resource_type"] == "disk"
    assert f["resource_name"] == "disk-orphan-01"
    assert f["size_gb"] == 128
    assert f["sku"] == "Premium_LRS"
    assert f["severity"] == "high"
    assert f["subscription_id"] == "sub-001"
    assert f["resource_group"] == "rg-compute"
    assert f["scanned_at"] == _SCANNED_AT
    assert f["estimated_monthly_cost_usd"] == pytest.approx(17.28, 0.01)


def test_build_disk_finding_stable_id():
    row = _make_disk_row()
    f1 = _build_disk_finding(row, _SCANNED_AT)
    f2 = _build_disk_finding(row, "2025-01-01T00:00:00+00:00")
    assert f1["id"] == f2["id"]


def test_build_disk_finding_different_ids():
    row_a = _make_disk_row(arm_id="id-a")
    row_b = _make_disk_row(arm_id="id-b")
    assert _build_disk_finding(row_a, _SCANNED_AT)["id"] != _build_disk_finding(row_b, _SCANNED_AT)["id"]


# ---------------------------------------------------------------------------
# _build_snapshot_finding
# ---------------------------------------------------------------------------


def test_build_snapshot_finding_fields():
    row = _make_snapshot_row(days_old=60)
    f = _build_snapshot_finding(row, _SCANNED_AT)

    assert f["resource_type"] == "snapshot"
    assert f["resource_name"] == "snap-old-01"
    assert f["size_gb"] == 64
    assert f["days_old"] == 60
    assert f["severity"] == "low"
    assert f["estimated_monthly_cost_usd"] == pytest.approx(3.2, 0.01)
    assert f["sku"] == ""


def test_build_snapshot_finding_very_old_medium_severity():
    row = _make_snapshot_row(days_old=120)
    f = _build_snapshot_finding(row, _SCANNED_AT)
    assert f["severity"] == "medium"


# ---------------------------------------------------------------------------
# scan_orphaned_disks
# ---------------------------------------------------------------------------


def test_scan_orphaned_disks_empty_subscriptions():
    assert scan_orphaned_disks([]) == []


def test_scan_orphaned_disks_arg_helper_missing():
    with patch.dict("sys.modules", {"arg_helper": None}):
        result = scan_orphaned_disks(["sub-001"])
    assert result == []


def test_scan_orphaned_disks_returns_combined_findings():
    disk_rows = [_make_disk_row()]
    snap_rows = [_make_snapshot_row()]

    import services.api_gateway.disk_audit_service as svc

    call_count = 0

    def _fake_run_arg_query(query: str, subscription_ids: List[str]):
        nonlocal call_count
        call_count += 1
        if "snapshots" in query:
            return snap_rows
        return disk_rows

    with patch.object(svc, "scan_orphaned_disks", wraps=svc.scan_orphaned_disks):
        pass  # covered via direct service test below

    # Direct test via monkeypatching the inner import
    import importlib
    import sys

    mock_arg = MagicMock()
    mock_arg.run_arg_query.side_effect = _fake_run_arg_query
    sys.modules["arg_helper"] = mock_arg

    try:
        result = svc.scan_orphaned_disks(["sub-001"])
        assert len(result) == 2
        types = {f["resource_type"] for f in result}
        assert "disk" in types
        assert "snapshot" in types
    finally:
        del sys.modules["arg_helper"]


def test_scan_orphaned_disks_query_error_returns_partial():
    """If disk query fails but snapshot query succeeds, return snapshots only."""
    import services.api_gateway.disk_audit_service as svc
    import sys

    call_count = 0

    def _fail_first(query: str, subscription_ids: List[str]):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("disk query failed")
        return [_make_snapshot_row()]

    mock_arg = MagicMock()
    mock_arg.run_arg_query.side_effect = _fail_first
    sys.modules["arg_helper"] = mock_arg

    try:
        result = svc.scan_orphaned_disks(["sub-001"])
        assert all(f["resource_type"] == "snapshot" for f in result)
    finally:
        del sys.modules["arg_helper"]


# ---------------------------------------------------------------------------
# persist_disk_findings
# ---------------------------------------------------------------------------


def test_persist_disk_findings_empty():
    client = _make_cosmos_client([])
    persist_disk_findings([], cosmos_client=client)
    client.get_database_client.assert_not_called()


def test_persist_disk_findings_no_client():
    persist_disk_findings([{"id": "x"}], cosmos_client=None)  # must not raise


def test_persist_disk_findings_upserts_all():
    findings = [_build_disk_finding(_make_disk_row(name=f"disk-{i}", arm_id=f"/id/{i}"), _SCANNED_AT) for i in range(4)]
    client = _make_cosmos_client([])
    container = client.get_database_client().get_container_client()

    persist_disk_findings(findings, cosmos_client=client)
    assert container.upsert_item.call_count == 4


def test_persist_disk_findings_cosmos_error_does_not_raise():
    client = MagicMock()
    client.get_database_client.side_effect = Exception("Cosmos unavailable")
    persist_disk_findings([{"id": "x"}], cosmos_client=client)  # must not raise


# ---------------------------------------------------------------------------
# get_disk_findings
# ---------------------------------------------------------------------------


def test_get_disk_findings_no_client():
    assert get_disk_findings(cosmos_client=None) == []


def test_get_disk_findings_strips_cosmos_private_fields():
    raw = {**_build_disk_finding(_make_disk_row(), _SCANNED_AT), "_rid": "abc", "_ts": 999}
    client = _make_cosmos_client([raw])
    result = get_disk_findings(cosmos_client=client)
    assert "_rid" not in result[0]
    assert "_ts" not in result[0]


def test_get_disk_findings_filters_subscription():
    client = _make_cosmos_client([])
    get_disk_findings(cosmos_client=client, subscription_id="sub-x")
    call_args = client.get_database_client().get_container_client().query_items.call_args
    query = call_args.kwargs.get("query") or call_args[0][0]
    assert "subscription_id" in query


def test_get_disk_findings_filters_resource_type():
    client = _make_cosmos_client([])
    get_disk_findings(cosmos_client=client, resource_type="snapshot")
    call_args = client.get_database_client().get_container_client().query_items.call_args
    query = call_args.kwargs.get("query") or call_args[0][0]
    assert "resource_type" in query


def test_get_disk_findings_cosmos_error_returns_empty():
    client = MagicMock()
    client.get_database_client.side_effect = Exception("fail")
    assert get_disk_findings(cosmos_client=client) == []


# ---------------------------------------------------------------------------
# get_disk_summary
# ---------------------------------------------------------------------------


def test_get_disk_summary_no_client():
    result = get_disk_summary(cosmos_client=None)
    assert result["orphaned_disks"] == 0
    assert result["old_snapshots"] == 0
    assert result["total_wasted_gb"] == 0
    assert result["estimated_monthly_cost_usd"] == 0.0


def test_get_disk_summary_counts():
    disk1 = _build_disk_finding(_make_disk_row(size_gb=100, arm_id="/id/d1"), _SCANNED_AT)
    disk2 = _build_disk_finding(_make_disk_row(name="d2", size_gb=200, arm_id="/id/d2"), _SCANNED_AT)
    snap1 = _build_snapshot_finding(_make_snapshot_row(size_gb=50), _SCANNED_AT)

    client = _make_cosmos_client([disk1, disk2, snap1])
    result = get_disk_summary(cosmos_client=client)

    assert result["orphaned_disks"] == 2
    assert result["old_snapshots"] == 1
    assert result["total_wasted_gb"] == 350
    assert result["estimated_monthly_cost_usd"] > 0


def test_get_disk_summary_empty_findings():
    client = _make_cosmos_client([])
    result = get_disk_summary(cosmos_client=client)
    assert result["orphaned_disks"] == 0
    assert result["old_snapshots"] == 0


def test_get_disk_summary_cosmos_error_returns_empty():
    client = MagicMock()
    client.get_database_client.side_effect = Exception("down")
    result = get_disk_summary(cosmos_client=client)
    assert result["orphaned_disks"] == 0
