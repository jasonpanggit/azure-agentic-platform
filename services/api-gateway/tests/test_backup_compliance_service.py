from __future__ import annotations
"""Tests for backup_compliance_service — ARG-based VM backup coverage scan (Phase 91)."""

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


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

CRED = MagicMock()
SUBS = ["sub-aaaaaaaa-0001"]

VM_ROW = {
    "vm_id": "/subscriptions/sub-aaaaaaaa-0001/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm-web-01",
    "vm_name": "vm-web-01",
    "resource_group": "rg-test",
    "subscription_id": "sub-aaaaaaaa-0001",
    "location": "eastus",
}

PROTECTED_ROW = {
    "resource_id": VM_ROW["vm_id"],
    "backup_policy": "DailyPolicy",
    "last_backup_time": "2026-04-16T02:00:00Z",
    "last_backup_status": "Completed",
    "health_status": "Passed",
}


def _make_cosmos(items=None):
    mock_cosmos = MagicMock()
    mock_container = MagicMock()
    mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container
    mock_container.query_items.return_value = items or []
    return mock_cosmos, mock_container


def _make_finding(**kwargs) -> BackupFinding:
    defaults = dict(
        finding_id="fid-001",
        resource_id="/subs/s/rgs/r/vms/vm1",
        resource_name="vm1",
        resource_group="rg-test",
        subscription_id="sub-aaaaaaaa-0001",
        location="eastus",
        backup_status="protected",
        backup_policy="DailyPolicy",
        last_backup_time="2026-04-16T02:00:00Z",
        last_backup_status="Completed",
        severity="info",
        scanned_at="2026-04-17T00:00:00+00:00",
    )
    defaults.update(kwargs)
    return BackupFinding(**defaults)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestMakeFindingId:
    def test_deterministic(self):
        fid = _make_finding_id("/subs/abc/vms/vm1")
        assert fid == _make_finding_id("/subs/abc/vms/vm1")

    def test_case_insensitive(self):
        assert _make_finding_id("/SUBS/ABC/VMS/VM1") == _make_finding_id("/subs/abc/vms/vm1")

    def test_returns_uuid_string(self):
        fid = _make_finding_id("/subs/abc/vms/vm1")
        assert len(fid) == 36
        assert fid.count("-") == 4


class TestDeriveSeverity:
    def test_unprotected_is_critical(self):
        assert _derive_severity("unprotected", "") == "critical"

    def test_unhealthy_is_high(self):
        assert _derive_severity("unhealthy", "Completed") == "high"

    def test_failed_last_backup_is_high(self):
        assert _derive_severity("protected", "Failed") == "high"

    def test_protected_with_good_backup_is_info(self):
        assert _derive_severity("protected", "Completed") == "info"

    def test_protected_with_empty_last_status_is_info(self):
        assert _derive_severity("protected", "") == "info"


class TestClassifyHealth:
    def test_actionrequired_returns_unhealthy(self):
        assert _classify_health("ActionRequired", "Completed") == "unhealthy"

    def test_actionsuggested_returns_unhealthy(self):
        assert _classify_health("ActionSuggested", "Completed") == "unhealthy"

    def test_failed_last_backup_returns_unhealthy(self):
        assert _classify_health("Passed", "Failed") == "unhealthy"

    def test_healthy_returns_protected(self):
        assert _classify_health("Passed", "Completed") == "protected"

    def test_empty_strings_return_protected(self):
        assert _classify_health("", "") == "protected"

    def test_case_insensitive_health_status(self):
        assert _classify_health("ACTIONREQUIRED", "Completed") == "unhealthy"


# ---------------------------------------------------------------------------
# scan_backup_compliance
# ---------------------------------------------------------------------------

class TestScanBackupCompliance:
    @patch("services.api_gateway.backup_compliance_service.run_arg_query")
    def test_happy_path_protected_vm(self, mock_arg):
        """VM with a healthy protected item → protected finding."""
        mock_arg.side_effect = [
            [VM_ROW],
            [PROTECTED_ROW],
        ]
        results = scan_backup_compliance(CRED, SUBS)

        assert len(results) == 1
        f = results[0]
        assert f.backup_status == "protected"
        assert f.backup_policy == "DailyPolicy"
        assert f.severity == "info"
        assert f.resource_name == "vm-web-01"

    @patch("services.api_gateway.backup_compliance_service.run_arg_query")
    def test_happy_path_unprotected_vm(self, mock_arg):
        """VM with no protected item → unprotected/critical finding."""
        mock_arg.side_effect = [
            [VM_ROW],
            [],  # no protected items
        ]
        results = scan_backup_compliance(CRED, SUBS)

        assert len(results) == 1
        f = results[0]
        assert f.backup_status == "unprotected"
        assert f.severity == "critical"
        assert f.backup_policy == ""
        assert f.last_backup_time == ""

    @patch("services.api_gateway.backup_compliance_service.run_arg_query")
    def test_happy_path_unhealthy_vm(self, mock_arg):
        """VM with failed last backup → unhealthy/high finding."""
        protected = {**PROTECTED_ROW, "last_backup_status": "Failed", "health_status": "Passed"}
        mock_arg.side_effect = [[VM_ROW], [protected]]
        results = scan_backup_compliance(CRED, SUBS)

        assert results[0].backup_status == "unhealthy"
        assert results[0].severity == "high"

    @patch("services.api_gateway.backup_compliance_service.run_arg_query")
    def test_empty_vms_returns_empty_list(self, mock_arg):
        """No VMs in subscription → empty list."""
        mock_arg.side_effect = [[], []]
        results = scan_backup_compliance(CRED, SUBS)
        assert results == []

    @patch("services.api_gateway.backup_compliance_service.run_arg_query")
    def test_empty_subscription_ids_returns_empty_list(self, mock_arg):
        """No subscription IDs provided → empty list, ARG not called."""
        results = scan_backup_compliance(CRED, [])
        assert results == []
        mock_arg.assert_not_called()

    @patch("services.api_gateway.backup_compliance_service.run_arg_query")
    def test_arg_exception_returns_empty_list(self, mock_arg):
        """ARG query failure → returns [] without raising."""
        mock_arg.side_effect = RuntimeError("ARG unavailable")
        results = scan_backup_compliance(CRED, SUBS)
        assert results == []

    @patch("services.api_gateway.backup_compliance_service.run_arg_query")
    def test_vm_row_missing_vm_id_is_skipped(self, mock_arg):
        """VM row with no vm_id is silently skipped."""
        mock_arg.side_effect = [[{"vm_id": "", "vm_name": "ghost"}], []]
        results = scan_backup_compliance(CRED, SUBS)
        assert results == []

    @patch("services.api_gateway.backup_compliance_service.run_arg_query")
    def test_multiple_vms_mixed_status(self, mock_arg):
        """Two VMs — one protected, one unprotected."""
        vm2_row = {
            "vm_id": "/subscriptions/sub-aaaaaaaa-0001/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm-db-01",
            "vm_name": "vm-db-01",
            "resource_group": "rg-test",
            "subscription_id": "sub-aaaaaaaa-0001",
            "location": "westus",
        }
        protected = {**PROTECTED_ROW}  # only covers vm-web-01
        mock_arg.side_effect = [[VM_ROW, vm2_row], [protected]]
        results = scan_backup_compliance(CRED, SUBS)

        assert len(results) == 2
        statuses = {f.resource_name: f.backup_status for f in results}
        assert statuses["vm-web-01"] == "protected"
        assert statuses["vm-db-01"] == "unprotected"

    @patch("services.api_gateway.backup_compliance_service.run_arg_query")
    def test_finding_id_is_deterministic(self, mock_arg):
        """Two scans for the same VM produce the same finding_id."""
        mock_arg.side_effect = [[VM_ROW], [PROTECTED_ROW]]
        r1 = scan_backup_compliance(CRED, SUBS)
        mock_arg.side_effect = [[VM_ROW], [PROTECTED_ROW]]
        r2 = scan_backup_compliance(CRED, SUBS)
        assert r1[0].finding_id == r2[0].finding_id


# ---------------------------------------------------------------------------
# persist_findings
# ---------------------------------------------------------------------------

class TestPersistFindings:
    def test_upsert_called_for_each_finding(self):
        cosmos, container = _make_cosmos()
        findings = [_make_finding(), _make_finding(finding_id="fid-002", resource_id="/subs/s/rgs/r/vms/vm2")]
        persist_findings(cosmos, "aap-db", findings)
        assert container.upsert_item.call_count == 2

    def test_upsert_doc_has_id_field(self):
        cosmos, container = _make_cosmos()
        f = _make_finding(finding_id="fid-abc")
        persist_findings(cosmos, "aap-db", [f])
        doc = container.upsert_item.call_args[0][0]
        assert doc["id"] == "fid-abc"

    def test_empty_findings_skips_upsert(self):
        cosmos, container = _make_cosmos()
        persist_findings(cosmos, "aap-db", [])
        container.upsert_item.assert_not_called()

    def test_cosmos_exception_does_not_raise(self):
        cosmos, container = _make_cosmos()
        container.upsert_item.side_effect = RuntimeError("Cosmos unavailable")
        # Must not raise
        persist_findings(cosmos, "aap-db", [_make_finding()])


# ---------------------------------------------------------------------------
# get_findings
# ---------------------------------------------------------------------------

class TestGetFindings:
    def test_returns_findings_from_cosmos(self):
        item = {
            "id": "fid-001",
            "finding_id": "fid-001",
            "resource_id": "/subs/s/rgs/r/vms/vm1",
            "resource_name": "vm1",
            "resource_group": "rg-test",
            "subscription_id": "sub-aaaaaaaa-0001",
            "location": "eastus",
            "backup_status": "protected",
            "backup_policy": "DailyPolicy",
            "last_backup_time": "2026-04-16T02:00:00Z",
            "last_backup_status": "Completed",
            "severity": "info",
            "scanned_at": "2026-04-17T00:00:00+00:00",
            "ttl": 86400,
        }
        cosmos, _ = _make_cosmos(items=[item])
        results = get_findings(cosmos, "aap-db")
        assert len(results) == 1
        assert results[0].resource_name == "vm1"

    def test_empty_cosmos_returns_empty_list(self):
        cosmos, _ = _make_cosmos(items=[])
        results = get_findings(cosmos, "aap-db")
        assert results == []

    def test_cosmos_exception_returns_empty_list(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("network error")
        results = get_findings(cosmos, "aap-db")
        assert results == []

    def test_subscription_filter_adds_param(self):
        cosmos, container = _make_cosmos(items=[])
        get_findings(cosmos, "aap-db", subscription_ids=["sub-001"])
        call_kwargs = container.query_items.call_args[1]
        params = call_kwargs.get("parameters") or []
        assert any(p["value"] == "sub-001" for p in params)

    def test_backup_status_filter_adds_param(self):
        cosmos, container = _make_cosmos(items=[])
        get_findings(cosmos, "aap-db", backup_status="unprotected")
        call_kwargs = container.query_items.call_args[1]
        params = call_kwargs.get("parameters") or []
        assert any(p["value"] == "unprotected" for p in params)

    def test_malformed_item_is_skipped_gracefully(self):
        """A Cosmos item missing required fields should be skipped, not crash."""
        cosmos, container = _make_cosmos()
        # Return one good item followed by a malformed one
        good = {
            "id": "fid-001", "finding_id": "fid-001",
            "resource_id": "/x", "resource_name": "vm1",
            "resource_group": "rg", "subscription_id": "sub-1",
            "location": "eastus", "backup_status": "protected",
            "backup_policy": "", "last_backup_time": "",
            "last_backup_status": "", "severity": "info",
            "scanned_at": "2026-04-17T00:00:00+00:00",
        }
        malformed = {"id": "bad"}  # missing many fields → BackupFinding __init__ will use defaults
        container.query_items.return_value = [good, malformed]
        results = get_findings(cosmos, "aap-db")
        # At minimum the good item should be returned
        assert any(r.resource_name == "vm1" for r in results)


# ---------------------------------------------------------------------------
# get_backup_summary
# ---------------------------------------------------------------------------

class TestGetBackupSummary:
    def _cosmos_with_findings(self, findings: list[BackupFinding]):
        """Patch get_findings to return the given list."""
        cosmos = MagicMock()
        return cosmos, findings

    def test_summary_counts_correctly(self):
        findings = [
            _make_finding(backup_status="protected", severity="info"),
            _make_finding(finding_id="f2", resource_id="/x/2", backup_status="unprotected", severity="critical", last_backup_status=""),
            _make_finding(finding_id="f3", resource_id="/x/3", backup_status="unhealthy", severity="high"),
            _make_finding(finding_id="f4", resource_id="/x/4", backup_status="protected", severity="info", last_backup_status="Failed"),
        ]
        cosmos = MagicMock()
        with patch("services.api_gateway.backup_compliance_service.get_findings", return_value=findings):
            summary = get_backup_summary(cosmos, "aap-db")

        assert summary["total_vms"] == 4
        assert summary["protected"] == 2
        assert summary["unprotected"] == 1
        assert summary["unhealthy"] == 1
        assert summary["recent_failures"] == 1
        assert summary["protection_rate"] == 50.0

    def test_summary_empty_cosmos_returns_zeros(self):
        cosmos = MagicMock()
        with patch("services.api_gateway.backup_compliance_service.get_findings", return_value=[]):
            summary = get_backup_summary(cosmos, "aap-db")

        assert summary["total_vms"] == 0
        assert summary["protection_rate"] == 0.0

    def test_all_protected_rate_is_100(self):
        findings = [
            _make_finding(backup_status="protected"),
            _make_finding(finding_id="f2", resource_id="/x/2", backup_status="protected"),
        ]
        cosmos = MagicMock()
        with patch("services.api_gateway.backup_compliance_service.get_findings", return_value=findings):
            summary = get_backup_summary(cosmos, "aap-db")

        assert summary["protection_rate"] == 100.0
        assert summary["unprotected"] == 0
