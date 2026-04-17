"""Tests for lock_audit_service.py — 25+ unit tests covering classification,
scan logic, remediation script generation, and endpoint responses.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.lock_audit_service import (
    LockFinding,
    _RESOURCE_TYPE_LABELS,
    generate_lock_remediation_script,
    get_lock_findings,
    get_lock_summary,
    persist_lock_findings,
    scan_lock_compliance,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SUBSCRIPTION_ID = "sub-00000000-0000-0000-0000-000000000001"


def _make_resource(
    name: str = "my-vm",
    resource_type: str = "microsoft.compute/virtualmachines",
    resource_group: str = "rg-prod",
    subscription_id: str = SUBSCRIPTION_ID,
    location: str = "eastus",
) -> Dict[str, Any]:
    rid = f"/subscriptions/{subscription_id}/resourcegroups/{resource_group}/providers/{resource_type}/{name}"
    return {
        "resource_id": rid.lower(),
        "name": name,
        "resource_type": resource_type.lower(),
        "resourceGroup": resource_group.lower(),
        "subscriptionId": subscription_id,
        "location": location,
    }


def _make_lock(
    scope: str,
    lock_name: str = "NoDelete",
    lock_level: str = "CanNotDelete",
) -> Dict[str, Any]:
    lid = f"{scope}/providers/microsoft.authorization/locks/{lock_name}"
    return {
        "lock_id": lid.lower(),
        "lock_name": lock_name,
        "lock_level": lock_level,
        "scope": scope.lower(),
    }


def _mock_cosmos_container(docs: List[Dict[str, Any]]) -> MagicMock:
    container = MagicMock()
    container.query_items.return_value = docs
    return container


def _mock_cosmos_client(docs: List[Dict[str, Any]]) -> MagicMock:
    container = _mock_cosmos_container(docs)
    db = MagicMock()
    db.get_container_client.return_value = container
    client = MagicMock()
    client.get_database_client.return_value = db
    return client


# ---------------------------------------------------------------------------
# scan_lock_compliance — classification tests
# ---------------------------------------------------------------------------


def _run_scan_with(resources, locks):
    """Helper: patch run_arg_query and run the scan."""
    call_count = 0

    def fake_arg_query(credential, sub_ids, kql):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return resources
        return locks

    credential = MagicMock()
    with patch("services.api_gateway.lock_audit_service.run_arg_query", new=fake_arg_query):
        return scan_lock_compliance(credential, [SUBSCRIPTION_ID])


class TestScanClassification:
    def test_no_lock_returns_high_severity(self):
        resources = [_make_resource("vm1")]
        findings = _run_scan_with(resources, [])
        assert len(findings) == 1
        assert findings[0].severity == "high"
        assert findings[0].lock_status == "no_lock"

    def test_resource_lock_not_reported(self):
        res = _make_resource("vm1")
        lock = _make_lock(res["resource_id"])
        findings = _run_scan_with([res], [lock])
        assert len(findings) == 0

    def test_rg_lock_only_returns_medium_severity(self):
        res = _make_resource("vm1", resource_group="rg-prod")
        rg_scope = f"/subscriptions/{SUBSCRIPTION_ID}/resourcegroups/rg-prod"
        lock = _make_lock(rg_scope)
        findings = _run_scan_with([res], [lock])
        assert len(findings) == 1
        assert findings[0].severity == "medium"
        assert findings[0].lock_status == "rg_lock_only"

    def test_finding_id_is_deterministic_uuid5(self):
        resources = [_make_resource("vm-stable")]
        f1 = _run_scan_with(resources, [])
        f2 = _run_scan_with(resources, [])
        assert f1[0].finding_id == f2[0].finding_id

    def test_finding_id_matches_uuid5_of_resource_id(self):
        res = _make_resource("vm-abc")
        findings = _run_scan_with([res], [])
        expected = str(uuid.uuid5(uuid.NAMESPACE_URL, res["resource_id"]))
        assert findings[0].finding_id == expected

    def test_multiple_resources_all_unlocked(self):
        resources = [
            _make_resource("vm1"),
            _make_resource("sa1", resource_type="microsoft.storage/storageaccounts"),
            _make_resource("kv1", resource_type="microsoft.keyvault/vaults"),
        ]
        findings = _run_scan_with(resources, [])
        assert len(findings) == 3

    def test_mixed_locked_and_unlocked(self):
        vm = _make_resource("vm1")
        sa = _make_resource("sa1", resource_type="microsoft.storage/storageaccounts")
        lock = _make_lock(vm["resource_id"])
        findings = _run_scan_with([vm, sa], [lock])
        assert len(findings) == 1
        assert findings[0].resource_name == "sa1"

    def test_resource_type_label_resolved_correctly(self):
        for raw_type, label in _RESOURCE_TYPE_LABELS.items():
            res = _make_resource("r1", resource_type=raw_type)
            findings = _run_scan_with([res], [])
            assert findings[0].resource_type == label

    def test_empty_subscription_ids_returns_empty(self):
        credential = MagicMock()
        result = scan_lock_compliance(credential, [])
        assert result == []

    def test_arg_query_exception_returns_empty(self):
        credential = MagicMock()
        with patch(
            "services.api_gateway.lock_audit_service.run_arg_query",
            side_effect=Exception("ARG unavailable"),
        ):
            result = scan_lock_compliance(credential, [SUBSCRIPTION_ID])
        assert result == []

    def test_rg_lock_on_different_rg_does_not_protect_resource(self):
        res = _make_resource("vm1", resource_group="rg-prod")
        # Lock is on a different RG
        rg_scope = f"/subscriptions/{SUBSCRIPTION_ID}/resourcegroups/rg-other"
        lock = _make_lock(rg_scope)
        findings = _run_scan_with([res], [lock])
        assert findings[0].severity == "high"

    def test_recommendation_present(self):
        findings = _run_scan_with([_make_resource("vm1")], [])
        assert findings[0].recommendation
        assert "CanNotDelete" in findings[0].recommendation

    def test_ttl_default_is_7_days(self):
        findings = _run_scan_with([_make_resource("vm1")], [])
        assert findings[0].ttl == 604800

    def test_subscription_id_propagated(self):
        findings = _run_scan_with([_make_resource("vm1")], [])
        assert findings[0].subscription_id == SUBSCRIPTION_ID

    def test_resource_with_empty_id_skipped(self):
        res = _make_resource("vm1")
        res["resource_id"] = ""
        findings = _run_scan_with([res], [])
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# generate_lock_remediation_script
# ---------------------------------------------------------------------------


class TestRemediationScript:
    def _make_finding(
        self,
        name: str = "my-vm",
        rg: str = "rg-prod",
        raw_type: str = "microsoft.compute/virtualmachines",
        severity: str = "high",
    ) -> LockFinding:
        return LockFinding(
            finding_id=str(uuid.uuid4()),
            resource_id=f"/subscriptions/{SUBSCRIPTION_ID}/resourcegroups/{rg}/providers/{raw_type}/{name}",
            resource_name=name,
            resource_type=_RESOURCE_TYPE_LABELS.get(raw_type, raw_type),
            resource_type_raw=raw_type,
            resource_group=rg,
            subscription_id=SUBSCRIPTION_ID,
            location="eastus",
            lock_status="no_lock" if severity == "high" else "rg_lock_only",
            severity=severity,
            recommendation="Add lock",
            scanned_at="2026-04-17T00:00:00+00:00",
        )

    def test_script_is_bash(self):
        script = generate_lock_remediation_script([self._make_finding()])
        assert script.startswith("#!/bin/bash")

    def test_script_contains_az_lock_create(self):
        script = generate_lock_remediation_script([self._make_finding()])
        assert "az lock create" in script

    def test_script_contains_resource_name(self):
        script = generate_lock_remediation_script([self._make_finding("my-special-vm")])
        assert "my-special-vm" in script

    def test_script_uses_can_not_delete(self):
        script = generate_lock_remediation_script([self._make_finding()])
        assert "CanNotDelete" in script

    def test_empty_findings_no_az_commands(self):
        script = generate_lock_remediation_script([])
        assert "az lock create" not in script

    def test_high_and_medium_sections_present(self):
        high = self._make_finding("vm-high", severity="high")
        medium = self._make_finding("kv-medium", severity="medium")
        script = generate_lock_remediation_script([high, medium])
        assert "HIGH SEVERITY" in script
        assert "MEDIUM SEVERITY" in script

    def test_script_includes_subscription_flag(self):
        script = generate_lock_remediation_script([self._make_finding()])
        assert "--subscription" in script


# ---------------------------------------------------------------------------
# persist / get findings (Cosmos mocks)
# ---------------------------------------------------------------------------


class TestCosmosOperations:
    def test_persist_calls_upsert_for_each_finding(self):
        container = MagicMock()
        db = MagicMock()
        db.get_container_client.return_value = container
        client = MagicMock()
        client.get_database_client.return_value = db

        findings = _run_scan_with([_make_resource("vm1"), _make_resource("vm2")], [])
        persist_lock_findings(client, "aap-db", findings)
        assert container.upsert_item.call_count == 2

    def test_persist_empty_findings_no_calls(self):
        client = MagicMock()
        persist_lock_findings(client, "aap-db", [])
        client.get_database_client.assert_not_called()

    def test_persist_exception_does_not_raise(self):
        client = MagicMock()
        client.get_database_client.side_effect = Exception("Cosmos down")
        # Should not raise
        persist_lock_findings(client, "aap-db", [LockFinding(
            finding_id="x", resource_id="/sub/rg/r", resource_name="r",
            resource_type="VM", resource_type_raw="microsoft.compute/virtualmachines",
            resource_group="rg", subscription_id="sub", location="eastus",
            lock_status="no_lock", severity="high", recommendation="Fix",
            scanned_at="2026-01-01T00:00:00+00:00"
        )])

    def test_get_findings_returns_list(self):
        doc = {
            "id": "f1", "finding_id": "f1", "resource_id": "/sub/rg/r",
            "resource_name": "vm1", "resource_type": "Virtual Machine",
            "resource_type_raw": "microsoft.compute/virtualmachines",
            "resource_group": "rg", "subscription_id": "sub", "location": "eastus",
            "lock_status": "no_lock", "severity": "high",
            "recommendation": "Add lock", "scanned_at": "2026-01-01T00:00:00+00:00",
            "ttl": 604800,
        }
        client = _mock_cosmos_client([doc])
        results = get_lock_findings(client, "aap-db")
        assert len(results) == 1
        assert results[0].resource_name == "vm1"

    def test_get_findings_exception_returns_empty(self):
        client = MagicMock()
        client.get_database_client.side_effect = Exception("Cosmos down")
        results = get_lock_findings(client, "aap-db")
        assert results == []

    def test_get_summary_counts_correctly(self):
        docs = [
            {"id": "1", "finding_id": "1", "resource_id": "/r1", "resource_name": "vm1",
             "resource_type": "Virtual Machine", "resource_type_raw": "microsoft.compute/virtualmachines",
             "resource_group": "rg", "subscription_id": "sub1", "location": "eastus",
             "lock_status": "no_lock", "severity": "high", "recommendation": "", "scanned_at": "",},
            {"id": "2", "finding_id": "2", "resource_id": "/r2", "resource_name": "kv1",
             "resource_type": "Key Vault", "resource_type_raw": "microsoft.keyvault/vaults",
             "resource_group": "rg", "subscription_id": "sub1", "location": "eastus",
             "lock_status": "rg_lock_only", "severity": "medium", "recommendation": "", "scanned_at": "",},
        ]
        client = _mock_cosmos_client(docs)
        summary = get_lock_summary(client, "aap-db")
        assert summary["total_unprotected"] == 2
        assert summary["high_count"] == 1
        assert summary["medium_count"] == 1
        assert "Virtual Machine" in summary["by_resource_type"]

    def test_get_summary_exception_returns_zeros(self):
        client = MagicMock()
        client.get_database_client.side_effect = Exception("down")
        summary = get_lock_summary(client, "aap-db")
        assert summary["total_unprotected"] == 0
        assert summary["high_count"] == 0
