"""Tests for backup_compliance_service.py (Phase 91).

22 tests covering:
- uuid5 stable IDs
- severity derivation
- health classification
- scan logic (protected / unprotected / unhealthy)
- Python-side VM join
- persist_findings (Cosmos upsert)
- get_findings (query, filters)
- get_backup_summary (aggregation)
- ARG failure handling (never raises)
- empty subscription list handling
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.backup_compliance_service import (
    BackupFinding,
    _classify_health,
    _derive_severity,
    _make_finding_id,
    get_backup_summary,
    get_findings,
    persist_findings,
    scan_backup_compliance,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_VM_ID = "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-a"
_VM_ID_LOWER = _VM_ID.lower()


def _make_vm_row(vm_id: str = _VM_ID_LOWER, name: str = "vm-a") -> Dict[str, Any]:
    return {
        "vm_id": vm_id,
        "vm_name": name,
        "resource_group": "rg",
        "subscription_id": "sub-1",
        "location": "eastus",
    }


def _make_protected_row(
    resource_id: str = _VM_ID_LOWER,
    health_status: str = "Healthy",
    last_backup_status: str = "Completed",
    backup_policy: str = "DailyPolicy",
    last_backup_time: str = "2026-04-16T02:00:00Z",
) -> Dict[str, Any]:
    return {
        "item_id": "item-1",
        "vault_id": "vault-1",
        "resource_id": resource_id,
        "item_name": "vm-a",
        "backup_policy": backup_policy,
        "last_backup_time": last_backup_time,
        "last_backup_status": last_backup_status,
        "health_status": health_status,
        "subscription_id": "sub-1",
    }


def _make_cosmos_item(**overrides) -> Dict[str, Any]:
    base = {
        "id": "finding-1",
        "finding_id": "finding-1",
        "resource_id": _VM_ID_LOWER,
        "resource_name": "vm-a",
        "resource_group": "rg",
        "subscription_id": "sub-1",
        "location": "eastus",
        "backup_status": "protected",
        "backup_policy": "DailyPolicy",
        "last_backup_time": "2026-04-16T02:00:00Z",
        "last_backup_status": "Completed",
        "severity": "info",
        "scanned_at": "2026-04-17T00:00:00Z",
        "ttl": 86400,
    }
    base.update(overrides)
    return base


# ── Unit: stable IDs ──────────────────────────────────────────────────────────

def test_make_finding_id_stable():
    """uuid5 is deterministic for the same resource_id."""
    id1 = _make_finding_id(_VM_ID_LOWER)
    id2 = _make_finding_id(_VM_ID_LOWER)
    assert id1 == id2


def test_make_finding_id_case_insensitive():
    """Finding ID is the same regardless of case."""
    assert _make_finding_id(_VM_ID_LOWER) == _make_finding_id(_VM_ID.upper())


def test_make_finding_id_different_for_different_resources():
    other = "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-b"
    assert _make_finding_id(_VM_ID_LOWER) != _make_finding_id(other.lower())


def test_make_finding_id_is_valid_uuid():
    result = _make_finding_id(_VM_ID_LOWER)
    parsed = uuid.UUID(result)
    assert parsed.version == 5


# ── Unit: severity & health derivation ───────────────────────────────────────

def test_derive_severity_unprotected():
    assert _derive_severity("unprotected", "") == "critical"


def test_derive_severity_unhealthy():
    assert _derive_severity("unhealthy", "") == "high"


def test_derive_severity_failed_backup():
    assert _derive_severity("protected", "Failed") == "high"


def test_derive_severity_healthy():
    assert _derive_severity("protected", "Completed") == "info"


def test_classify_health_action_required():
    assert _classify_health("ActionRequired", "") == "unhealthy"


def test_classify_health_action_suggested():
    assert _classify_health("ActionSuggested", "") == "unhealthy"


def test_classify_health_failed_last_backup():
    assert _classify_health("Healthy", "Failed") == "unhealthy"


def test_classify_health_healthy():
    assert _classify_health("Healthy", "Completed") == "protected"


def test_classify_health_empty_strings():
    assert _classify_health("", "") == "protected"


# ── Unit: scan_backup_compliance ──────────────────────────────────────────────

def test_scan_returns_empty_for_no_subscriptions():
    findings = scan_backup_compliance(MagicMock(), [])
    assert findings == []


def test_scan_protected_vm():
    """A VM that appears in protected items is classified as protected."""
    credential = MagicMock()
    vm_row = _make_vm_row()
    protected_row = _make_protected_row()

    with patch("services.api_gateway.backup_compliance_service.run_arg_query") as mock_arg:
        mock_arg.side_effect = [[vm_row], [protected_row]]
        findings = scan_backup_compliance(credential, ["sub-1"])

    assert len(findings) == 1
    f = findings[0]
    assert f.backup_status == "protected"
    assert f.severity == "info"
    assert f.backup_policy == "DailyPolicy"


def test_scan_unprotected_vm():
    """A VM not in protected items is classified as unprotected."""
    credential = MagicMock()
    vm_row = _make_vm_row()

    with patch("services.api_gateway.backup_compliance_service.run_arg_query") as mock_arg:
        mock_arg.side_effect = [[vm_row], []]
        findings = scan_backup_compliance(credential, ["sub-1"])

    assert len(findings) == 1
    f = findings[0]
    assert f.backup_status == "unprotected"
    assert f.severity == "critical"
    assert f.backup_policy == ""


def test_scan_unhealthy_vm():
    """A VM with ActionRequired health_status is classified as unhealthy."""
    credential = MagicMock()
    vm_row = _make_vm_row()
    protected_row = _make_protected_row(health_status="ActionRequired", last_backup_status="Completed")

    with patch("services.api_gateway.backup_compliance_service.run_arg_query") as mock_arg:
        mock_arg.side_effect = [[vm_row], [protected_row]]
        findings = scan_backup_compliance(credential, ["sub-1"])

    assert findings[0].backup_status == "unhealthy"
    assert findings[0].severity == "high"


def test_scan_arg_failure_returns_empty():
    """ARG failure is swallowed — returns empty list, never raises."""
    credential = MagicMock()
    with patch("services.api_gateway.backup_compliance_service.run_arg_query") as mock_arg:
        mock_arg.side_effect = Exception("ARG unavailable")
        findings = scan_backup_compliance(credential, ["sub-1"])
    assert findings == []


def test_scan_skips_row_with_missing_vm_id():
    credential = MagicMock()
    vm_row = {"vm_id": "", "vm_name": "vm-bad", "resource_group": "rg", "subscription_id": "sub-1", "location": "eastus"}

    with patch("services.api_gateway.backup_compliance_service.run_arg_query") as mock_arg:
        mock_arg.side_effect = [[vm_row], []]
        findings = scan_backup_compliance(credential, ["sub-1"])

    assert findings == []


# ── Unit: persist_findings ────────────────────────────────────────────────────

def test_persist_findings_upserts_each_finding():
    cosmos = MagicMock()
    container = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value = container

    finding = BackupFinding(
        finding_id="fid-1",
        resource_id=_VM_ID_LOWER,
        resource_name="vm-a",
        resource_group="rg",
        subscription_id="sub-1",
        location="eastus",
        backup_status="unprotected",
        backup_policy="",
        last_backup_time="",
        last_backup_status="",
        severity="critical",
        scanned_at="2026-04-17T00:00:00Z",
    )
    persist_findings(cosmos, "aap", [finding])
    container.upsert_item.assert_called_once()
    call_args = container.upsert_item.call_args[0][0]
    assert call_args["id"] == "fid-1"
    assert call_args["backup_status"] == "unprotected"


def test_persist_findings_noop_on_empty():
    cosmos = MagicMock()
    persist_findings(cosmos, "aap", [])
    cosmos.get_database_client.assert_not_called()


def test_persist_findings_never_raises_on_cosmos_error():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("Cosmos down")
    persist_findings(cosmos, "aap", [BackupFinding(
        finding_id="x", resource_id="r", resource_name="n", resource_group="g",
        subscription_id="s", location="l", backup_status="unprotected",
        backup_policy="", last_backup_time="", last_backup_status="",
        severity="critical", scanned_at="now",
    )])
    # No exception raised


# ── Unit: get_findings ────────────────────────────────────────────────────────

def test_get_findings_returns_list():
    cosmos = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value \
        .query_items.return_value = [_make_cosmos_item()]

    results = get_findings(cosmos, "aap")
    assert len(results) == 1
    assert isinstance(results[0], BackupFinding)


def test_get_findings_filters_by_subscription():
    cosmos = MagicMock()
    container = MagicMock()
    container.query_items.return_value = []
    cosmos.get_database_client.return_value.get_container_client.return_value = container

    get_findings(cosmos, "aap", subscription_ids=["sub-1"])
    call_kwargs = container.query_items.call_args[1]
    assert "sub-1" in str(call_kwargs.get("parameters") or "")


def test_get_findings_filters_by_backup_status():
    cosmos = MagicMock()
    container = MagicMock()
    container.query_items.return_value = []
    cosmos.get_database_client.return_value.get_container_client.return_value = container

    get_findings(cosmos, "aap", backup_status="unprotected")
    call_kwargs = container.query_items.call_args[1]
    assert "unprotected" in str(call_kwargs.get("parameters") or "")


def test_get_findings_returns_empty_on_cosmos_error():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("timeout")
    results = get_findings(cosmos, "aap")
    assert results == []


# ── Unit: get_backup_summary ──────────────────────────────────────────────────

def test_get_backup_summary_aggregation():
    cosmos = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value \
        .query_items.return_value = [
            _make_cosmos_item(backup_status="protected", last_backup_status="Completed", severity="info"),
            _make_cosmos_item(backup_status="unprotected", last_backup_status="", severity="critical"),
            _make_cosmos_item(backup_status="unhealthy", last_backup_status="Failed", severity="high"),
        ]

    summary = get_backup_summary(cosmos, "aap")
    assert summary["total_vms"] == 3
    assert summary["protected"] == 1
    assert summary["unprotected"] == 1
    assert summary["unhealthy"] == 1
    assert summary["recent_failures"] == 1
    assert abs(summary["protection_rate"] - 33.3) < 0.1


def test_get_backup_summary_empty():
    cosmos = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value \
        .query_items.return_value = []
    summary = get_backup_summary(cosmos, "aap")
    assert summary["total_vms"] == 0
    assert summary["protection_rate"] == 0.0
