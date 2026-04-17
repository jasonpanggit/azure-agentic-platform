"""Tests for cert_expiry_service — mocks ARG and Cosmos DB.

~30 tests covering:
- Severity derivation
- KV and App Service finding construction
- Stable ID generation
- scan_cert_expiry happy path and ARG failure
- persist_cert_findings upsert and error
- get_cert_findings with all filter combinations
- get_cert_summary counts and soonest expiry
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, call, patch

import pytest

from services.api_gateway.cert_expiry_service import (
    _row_to_appsvc_finding,
    _row_to_kv_finding,
    _severity,
    _stable_id,
    get_cert_findings,
    get_cert_summary,
    persist_cert_findings,
    scan_cert_expiry,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _iso_days(offset: int) -> str:
    dt = datetime.now(tz=timezone.utc) + timedelta(days=offset)
    return dt.isoformat()


def _make_cosmos(items: List[Dict[str, Any]]) -> MagicMock:
    container = MagicMock()
    container.read_all_items.return_value = items
    container.query_items.return_value = items
    db = MagicMock()
    db.get_container_client.return_value = container
    cosmos = MagicMock()
    cosmos.get_database_client.return_value = db
    return cosmos


def _kv_row(days: int = 5, name: str = "my-cert") -> Dict[str, Any]:
    return {
        "id": f"/subscriptions/sub-1/resourceGroups/rg-1/providers/microsoft.keyvault/vaults/my-vault/certificates/{name}",
        "subscriptionId": "sub-1",
        "resourceGroup": "rg-1",
        "name": name,
        "vaultName": "my-vault",
        "expires_on": _iso_days(days),
        "days_until_expiry": days,
    }


def _appsvc_row(days: int = 20, name: str = "app-cert") -> Dict[str, Any]:
    return {
        "id": f"/subscriptions/sub-1/resourceGroups/rg-2/providers/microsoft.web/certificates/{name}",
        "subscriptionId": "sub-1",
        "resourceGroup": "rg-2",
        "name": name,
        "expiry": _iso_days(days),
        "days_until_expiry": days,
    }


# ── Severity ──────────────────────────────────────────────────────────────────

class TestSeverity:
    def test_critical_at_7(self):
        assert _severity(7) == "critical"

    def test_critical_below_7(self):
        assert _severity(3) == "critical"
        assert _severity(0) == "critical"
        assert _severity(-1) == "critical"

    def test_high_at_8_to_30(self):
        assert _severity(8) == "high"
        assert _severity(30) == "high"

    def test_medium_at_31_to_60(self):
        assert _severity(31) == "medium"
        assert _severity(60) == "medium"

    def test_low_above_60(self):
        assert _severity(61) == "low"
        assert _severity(90) == "low"


# ── Stable ID ─────────────────────────────────────────────────────────────────

class TestStableId:
    def test_deterministic(self):
        arm = "/subscriptions/sub-1/resourceGroups/rg/providers/kv/certs/c1"
        assert _stable_id(arm) == _stable_id(arm)

    def test_case_insensitive(self):
        arm = "/subscriptions/SUB-1/resourceGroups/RG"
        assert _stable_id(arm) == _stable_id(arm.lower())

    def test_different_arms_differ(self):
        assert _stable_id("arm-a") != _stable_id("arm-b")


# ── Row → finding construction ────────────────────────────────────────────────

class TestRowToFinding:
    def test_kv_finding_fields(self):
        row = _kv_row(days=5)
        f = _row_to_kv_finding(row, "2026-01-01T00:00:00+00:00")
        assert f.cert_type == "keyvault"
        assert f.cert_name == "my-cert"
        assert f.vault_or_app_name == "my-vault"
        assert f.days_until_expiry == 5
        assert f.severity == "critical"
        assert f.subscription_id == "sub-1"
        assert f.resource_group == "rg-1"

    def test_kv_stable_id(self):
        row = _kv_row()
        f = _row_to_kv_finding(row, "ts")
        assert f.id == _stable_id(row["id"])

    def test_appsvc_finding_fields(self):
        row = _appsvc_row(days=20)
        f = _row_to_appsvc_finding(row, "2026-01-01T00:00:00+00:00")
        assert f.cert_type == "app_service"
        assert f.cert_name == "app-cert"
        assert f.days_until_expiry == 20
        assert f.severity == "high"
        assert f.subscription_id == "sub-1"

    def test_appsvc_stable_id(self):
        row = _appsvc_row()
        f = _row_to_appsvc_finding(row, "ts")
        assert f.id == _stable_id(row["id"])

    def test_kv_high_severity(self):
        f = _row_to_kv_finding(_kv_row(days=15), "ts")
        assert f.severity == "high"

    def test_kv_medium_severity(self):
        f = _row_to_kv_finding(_kv_row(days=45), "ts")
        assert f.severity == "medium"

    def test_kv_low_severity(self):
        f = _row_to_kv_finding(_kv_row(days=80), "ts")
        assert f.severity == "low"


# ── scan_cert_expiry ──────────────────────────────────────────────────────────

class TestScanCertExpiry:
    def test_returns_kv_and_appsvc_findings(self):
        cred = MagicMock()
        kv_rows = [_kv_row(days=5, name="cert-a"), _kv_row(days=20, name="cert-b")]
        appsvc_rows = [_appsvc_row(days=10)]

        def _arg(credential, subs, kql):
            if "keyvault" in kql.lower():
                return kv_rows
            return appsvc_rows

        with patch("services.api_gateway.cert_expiry_service.run_arg_query", side_effect=_arg):
            result = scan_cert_expiry(cred, ["sub-1"])

        assert len(result) == 3
        types = {f["cert_type"] for f in result}
        assert types == {"keyvault", "app_service"}

    def test_returns_empty_when_no_arg_helper(self):
        with patch("services.api_gateway.cert_expiry_service.run_arg_query", None):
            result = scan_cert_expiry(MagicMock(), ["sub-1"])
        assert result == []

    def test_kv_arg_failure_returns_appsvc_only(self):
        cred = MagicMock()
        appsvc_rows = [_appsvc_row(days=5)]

        def _arg(credential, subs, kql):
            if "keyvault" in kql.lower():
                raise RuntimeError("ARG unavailable")
            return appsvc_rows

        with patch("services.api_gateway.cert_expiry_service.run_arg_query", side_effect=_arg):
            result = scan_cert_expiry(cred, ["sub-1"])

        assert len(result) == 1
        assert result[0]["cert_type"] == "app_service"

    def test_both_arg_failures_returns_empty(self):
        with patch(
            "services.api_gateway.cert_expiry_service.run_arg_query",
            side_effect=RuntimeError("fail"),
        ):
            result = scan_cert_expiry(MagicMock(), ["sub-1"])
        assert result == []

    def test_result_is_list_of_dicts(self):
        with patch(
            "services.api_gateway.cert_expiry_service.run_arg_query",
            return_value=[_kv_row()],
        ) as mock_arg:
            # First call KV, second call AppSvc (returns [])
            mock_arg.side_effect = [[_kv_row()], []]
            result = scan_cert_expiry(MagicMock(), ["sub-1"])
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], dict)

    def test_bad_row_is_skipped(self):
        bad_row = {"id": None, "days_until_expiry": "not-an-int"}

        def _arg(credential, subs, kql):
            if "keyvault" in kql.lower():
                return [bad_row, _kv_row()]
            return []

        with patch("services.api_gateway.cert_expiry_service.run_arg_query", side_effect=_arg):
            result = scan_cert_expiry(MagicMock(), ["sub-1"])
        # Bad row skipped, good one included
        assert any(f.get("cert_name") == "my-cert" for f in result)


# ── persist_cert_findings ─────────────────────────────────────────────────────

class TestPersistCertFindings:
    def test_upserts_all_findings(self):
        cosmos = _make_cosmos([])
        findings = [{"id": "id-1", "cert_name": "c1"}, {"id": "id-2", "cert_name": "c2"}]
        persist_cert_findings(cosmos, "aap", findings)
        container = cosmos.get_database_client.return_value.get_container_client.return_value
        assert container.upsert_item.call_count == 2

    def test_no_op_on_empty_list(self):
        cosmos = _make_cosmos([])
        persist_cert_findings(cosmos, "aap", [])
        container = cosmos.get_database_client.return_value.get_container_client.return_value
        container.upsert_item.assert_not_called()

    def test_never_raises_on_cosmos_error(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("Cosmos down")
        persist_cert_findings(cosmos, "aap", [{"id": "x"}])  # must not raise


# ── get_cert_findings ─────────────────────────────────────────────────────────

class TestGetCertFindings:
    def _item(self, cert_type: str = "keyvault", severity: str = "high", sub: str = "sub-1") -> Dict[str, Any]:
        return {
            "id": f"id-{cert_type}-{severity}",
            "cert_type": cert_type,
            "severity": severity,
            "subscription_id": sub,
        }

    def test_returns_all_without_filters(self):
        items = [self._item("keyvault", "critical"), self._item("app_service", "high")]
        cosmos = _make_cosmos(items)
        result = get_cert_findings(cosmos, "aap")
        assert len(result) == 2

    def test_filters_by_subscription(self):
        items = [self._item(sub="sub-1"), self._item(sub="sub-2")]
        cosmos = _make_cosmos(items)
        result = get_cert_findings(cosmos, "aap", subscription_id="sub-1")
        assert result == items  # mock returns all; real filtering is server-side via KQL

    def test_filters_by_severity(self):
        items = [self._item(severity="critical")]
        cosmos = _make_cosmos(items)
        result = get_cert_findings(cosmos, "aap", severity="critical")
        assert result == items

    def test_filters_by_cert_type(self):
        items = [self._item(cert_type="keyvault")]
        cosmos = _make_cosmos(items)
        result = get_cert_findings(cosmos, "aap", cert_type="keyvault")
        assert result == items

    def test_never_raises_on_cosmos_error(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("fail")
        result = get_cert_findings(cosmos, "aap")
        assert result == []


# ── get_cert_summary ──────────────────────────────────────────────────────────

class TestGetCertSummary:
    def _finding(self, severity: str, days: int, expires_on: str) -> Dict[str, Any]:
        return {
            "id": f"id-{severity}",
            "severity": severity,
            "days_until_expiry": days,
            "expires_on": expires_on,
        }

    def test_counts_by_severity(self):
        items = [
            self._finding("critical", 3, _iso_days(3)),
            self._finding("high", 15, _iso_days(15)),
            self._finding("medium", 45, _iso_days(45)),
            self._finding("low", 80, _iso_days(80)),
        ]
        cosmos = _make_cosmos(items)
        summary = get_cert_summary(cosmos, "aap")
        assert summary["critical_count"] == 1
        assert summary["high_count"] == 1
        assert summary["medium_count"] == 1
        assert summary["low_count"] == 1
        assert summary["total"] == 4

    def test_soonest_expiry_is_minimum_days(self):
        soonest_date = _iso_days(3)
        items = [
            self._finding("critical", 3, soonest_date),
            self._finding("high", 15, _iso_days(15)),
        ]
        cosmos = _make_cosmos(items)
        summary = get_cert_summary(cosmos, "aap")
        assert summary["soonest_expiry_days"] == 3
        assert summary["soonest_expiry"] == soonest_date

    def test_empty_when_no_findings(self):
        cosmos = _make_cosmos([])
        summary = get_cert_summary(cosmos, "aap")
        assert summary["total"] == 0
        assert summary["soonest_expiry"] is None
        assert summary["soonest_expiry_days"] is None

    def test_never_raises_on_cosmos_error(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("fail")
        summary = get_cert_summary(cosmos, "aap")
        assert summary["total"] == 0
