"""Tests for storage_security_service — mocks ARG and Cosmos DB.

~30 tests covering:
- Risk scoring logic
- Severity derivation
- Individual finding descriptions
- Multiple findings per account
- scan_storage_security happy path and ARG failure
- Accounts with zero findings are excluded from results
- persist_storage_findings upsert and error
- get_storage_findings with filter combinations
- get_storage_summary counts and top risks
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.storage_security_service import (
    _row_to_finding,
    _score_and_findings,
    _stable_id,
    get_storage_findings,
    get_storage_summary,
    persist_storage_findings,
    scan_storage_security,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_row(
    name: str = "mystorage",
    sub: str = "sub-1",
    rg: str = "rg-1",
    https_only: bool = True,
    allow_blob_public: bool = False,
    min_tls: str = "TLS1_2",
    allow_shared_key: bool = False,
    network_default: str = "Deny",
    pe_count: int = 1,
) -> Dict[str, Any]:
    return {
        "id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/microsoft.storage/storageaccounts/{name}",
        "subscriptionId": sub,
        "resourceGroup": rg,
        "name": name,
        "https_only": https_only,
        "allow_blob_public": allow_blob_public,
        "min_tls": min_tls,
        "allow_shared_key": allow_shared_key,
        "network_default": network_default,
        "pe_count": pe_count,
    }


def _make_cosmos(items: List[Dict[str, Any]]) -> MagicMock:
    container = MagicMock()
    container.read_all_items.return_value = items
    container.query_items.return_value = items
    db = MagicMock()
    db.get_container_client.return_value = container
    cosmos = MagicMock()
    cosmos.get_database_client.return_value = db
    return cosmos


# ── Stable ID ─────────────────────────────────────────────────────────────────

class TestStableId:
    def test_deterministic(self):
        arm = "/subscriptions/sub-1/resourceGroups/rg-1/providers/storage/sa"
        assert _stable_id(arm) == _stable_id(arm)

    def test_case_insensitive(self):
        arm = "/subscriptions/SUB-1/RG"
        assert _stable_id(arm) == _stable_id(arm.lower())

    def test_different_arms_differ(self):
        assert _stable_id("arm-a") != _stable_id("arm-b")


# ── Scoring logic ─────────────────────────────────────────────────────────────

class TestScoreAndFindings:
    def test_clean_account_zero_score(self):
        score, findings, severity = _score_and_findings(_clean_row())
        assert score == 0
        assert findings == []
        assert severity == "low"

    def test_blob_public_adds_40_critical(self):
        row = _clean_row(allow_blob_public=True)
        score, findings, severity = _score_and_findings(row)
        assert score >= 40
        assert severity == "critical"
        assert any("public" in f.lower() for f in findings)

    def test_no_https_adds_25(self):
        row = _clean_row(https_only=False)
        score, findings, severity = _score_and_findings(row)
        assert score >= 25
        assert severity == "high"
        assert any("https" in f.lower() for f in findings)

    def test_tls10_adds_25(self):
        row = _clean_row(min_tls="TLS1_0")
        score, findings, severity = _score_and_findings(row)
        assert score >= 25
        assert severity == "high"
        assert any("tls" in f.lower() for f in findings)

    def test_network_allow_no_pe_adds_20(self):
        row = _clean_row(network_default="Allow", pe_count=0)
        score, findings, severity = _score_and_findings(row)
        assert score >= 20
        assert any("network" in f.lower() or "firewall" in f.lower() for f in findings)

    def test_network_allow_with_pe_no_penalty(self):
        row = _clean_row(network_default="Allow", pe_count=2)
        score, findings, severity = _score_and_findings(row)
        assert not any("network" in f.lower() or "publicly accessible" in f.lower() for f in findings)

    def test_shared_key_adds_10(self):
        row = _clean_row(allow_shared_key=True)
        score, findings, _ = _score_and_findings(row)
        assert score >= 10
        assert any("shared key" in f.lower() for f in findings)

    def test_multiple_findings_accumulate(self):
        row = _clean_row(
            allow_blob_public=True,
            https_only=False,
            min_tls="TLS1_0",
            allow_shared_key=True,
            network_default="Allow",
            pe_count=0,
        )
        score, findings, severity = _score_and_findings(row)
        assert score == 100  # capped at 100
        assert severity == "critical"
        assert len(findings) == 5

    def test_score_capped_at_100(self):
        row = _clean_row(
            allow_blob_public=True,
            https_only=False,
            min_tls="TLS1_0",
            allow_shared_key=True,
            network_default="Allow",
            pe_count=0,
        )
        score, _, _ = _score_and_findings(row)
        assert score <= 100

    def test_severity_medium_at_10_to_24(self):
        row = _clean_row(allow_shared_key=True)  # score = 10
        _, _, severity = _score_and_findings(row)
        assert severity == "medium"


# ── Row → finding construction ────────────────────────────────────────────────

class TestRowToFinding:
    def test_fields_populated(self):
        row = _clean_row(allow_blob_public=True)
        f = _row_to_finding(row, "2026-01-01T00:00:00+00:00")
        assert f.account_name == "mystorage"
        assert f.subscription_id == "sub-1"
        assert f.resource_group == "rg-1"
        assert f.allow_blob_public is True
        assert f.severity == "critical"
        assert f.scanned_at == "2026-01-01T00:00:00+00:00"

    def test_stable_id_from_arm(self):
        row = _clean_row()
        f = _row_to_finding(row, "ts")
        assert f.id == _stable_id(row["id"])

    def test_arm_id_stored(self):
        row = _clean_row()
        f = _row_to_finding(row, "ts")
        assert f.arm_id == row["id"]


# ── scan_storage_security ─────────────────────────────────────────────────────

class TestScanStorageSecurity:
    def test_returns_findings_for_misconfigured_accounts(self):
        rows = [
            _clean_row("sa-bad-1", allow_blob_public=True),
            _clean_row("sa-bad-2", https_only=False),
        ]
        with patch("services.api_gateway.storage_security_service.run_arg_query", return_value=rows):
            result = scan_storage_security(MagicMock(), ["sub-1"])
        assert len(result) == 2

    def test_excludes_clean_accounts(self):
        rows = [_clean_row("sa-clean")]
        with patch("services.api_gateway.storage_security_service.run_arg_query", return_value=rows):
            result = scan_storage_security(MagicMock(), ["sub-1"])
        assert result == []

    def test_returns_empty_when_no_arg_helper(self):
        with patch("services.api_gateway.storage_security_service.run_arg_query", None):
            result = scan_storage_security(MagicMock(), ["sub-1"])
        assert result == []

    def test_returns_empty_on_arg_failure(self):
        with patch(
            "services.api_gateway.storage_security_service.run_arg_query",
            side_effect=RuntimeError("ARG fail"),
        ):
            result = scan_storage_security(MagicMock(), ["sub-1"])
        assert result == []

    def test_result_is_list_of_dicts(self):
        rows = [_clean_row(allow_blob_public=True)]
        with patch("services.api_gateway.storage_security_service.run_arg_query", return_value=rows):
            result = scan_storage_security(MagicMock(), ["sub-1"])
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_findings_field_is_list_of_strings(self):
        rows = [_clean_row(allow_blob_public=True, https_only=False)]
        with patch("services.api_gateway.storage_security_service.run_arg_query", return_value=rows):
            result = scan_storage_security(MagicMock(), ["sub-1"])
        findings_list = result[0]["findings"]
        assert isinstance(findings_list, list)
        assert all(isinstance(s, str) for s in findings_list)

    def test_risk_score_in_result(self):
        rows = [_clean_row(allow_blob_public=True)]
        with patch("services.api_gateway.storage_security_service.run_arg_query", return_value=rows):
            result = scan_storage_security(MagicMock(), ["sub-1"])
        assert result[0]["risk_score"] >= 40


# ── persist_storage_findings ──────────────────────────────────────────────────

class TestPersistStorageFindings:
    def test_upserts_all_findings(self):
        cosmos = _make_cosmos([])
        findings = [{"id": "id-1"}, {"id": "id-2"}]
        persist_storage_findings(cosmos, "aap", findings)
        container = cosmos.get_database_client.return_value.get_container_client.return_value
        assert container.upsert_item.call_count == 2

    def test_no_op_on_empty(self):
        cosmos = _make_cosmos([])
        persist_storage_findings(cosmos, "aap", [])
        container = cosmos.get_database_client.return_value.get_container_client.return_value
        container.upsert_item.assert_not_called()

    def test_never_raises_on_cosmos_error(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("down")
        persist_storage_findings(cosmos, "aap", [{"id": "x"}])  # must not raise


# ── get_storage_findings ──────────────────────────────────────────────────────

class TestGetStorageFindings:
    def _item(self, severity: str = "high", sub: str = "sub-1") -> Dict[str, Any]:
        return {"id": f"id-{severity}", "severity": severity, "subscription_id": sub}

    def test_returns_all_without_filters(self):
        items = [self._item("critical"), self._item("high")]
        cosmos = _make_cosmos(items)
        result = get_storage_findings(cosmos, "aap")
        assert len(result) == 2

    def test_filter_by_subscription(self):
        items = [self._item(sub="sub-1")]
        cosmos = _make_cosmos(items)
        result = get_storage_findings(cosmos, "aap", subscription_id="sub-1")
        assert result == items

    def test_filter_by_severity(self):
        items = [self._item("critical")]
        cosmos = _make_cosmos(items)
        result = get_storage_findings(cosmos, "aap", severity="critical")
        assert result == items

    def test_never_raises_on_cosmos_error(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("fail")
        result = get_storage_findings(cosmos, "aap")
        assert result == []


# ── get_storage_summary ───────────────────────────────────────────────────────

class TestGetStorageSummary:
    def _finding(self, severity: str, findings: List[str]) -> Dict[str, Any]:
        return {"id": f"id-{severity}", "severity": severity, "findings": findings}

    def test_counts_by_severity(self):
        items = [
            self._finding("critical", ["Blob public"]),
            self._finding("high", ["No HTTPS"]),
            self._finding("medium", ["Shared key"]),
            self._finding("low", []),
        ]
        cosmos = _make_cosmos(items)
        summary = get_storage_summary(cosmos, "aap")
        assert summary["critical_count"] == 1
        assert summary["high_count"] == 1
        assert summary["medium_count"] == 1
        assert summary["low_count"] == 1
        assert summary["total_accounts"] == 4

    def test_top_risks_aggregated(self):
        items = [
            self._finding("critical", ["Blob public access is enabled", "No HTTPS"]),
            self._finding("high", ["Blob public access is enabled"]),
        ]
        cosmos = _make_cosmos(items)
        summary = get_storage_summary(cosmos, "aap")
        top = summary["top_risks"]
        # "Blob public access" should be top with count=2
        assert top[0]["description"] == "Blob public access is enabled"
        assert top[0]["count"] == 2

    def test_empty_summary_on_no_findings(self):
        cosmos = _make_cosmos([])
        summary = get_storage_summary(cosmos, "aap")
        assert summary["total_accounts"] == 0
        assert summary["top_risks"] == []

    def test_never_raises_on_cosmos_error(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("fail")
        summary = get_storage_summary(cosmos, "aap")
        assert summary["total_accounts"] == 0
