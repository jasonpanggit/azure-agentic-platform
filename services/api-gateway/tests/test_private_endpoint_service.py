"""Tests for private_endpoint_service — ARG-based public network access audit (Phase 92)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.private_endpoint_service import (
    PrivateEndpointFinding,
    _derive_severity,
    _make_finding_id,
    _make_recommendation,
    _normalise_public_access,
    get_findings,
    get_pe_summary,
    persist_findings,
    scan_private_endpoint_compliance,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

CRED = MagicMock()
SUBS = ["sub-bbbbbbbb-0001"]

STORAGE_ROW = {
    "resource_id": "/subscriptions/sub-bbbbbbbb-0001/resourcegroups/rg-test/providers/microsoft.storage/storageaccounts/mystorageacct",
    "name": "mystorageacct",
    "type": "microsoft.storage/storageaccounts",
    "resource_group": "rg-test",
    "subscription_id": "sub-bbbbbbbb-0001",
    "location": "eastus",
    "public_network_access": "Enabled",
    "private_endpoint_connections": 0,
}

KV_ROW = {
    "resource_id": "/subscriptions/sub-bbbbbbbb-0001/resourcegroups/rg-test/providers/microsoft.keyvault/vaults/myvault",
    "name": "myvault",
    "type": "microsoft.keyvault/vaults",
    "resource_group": "rg-test",
    "subscription_id": "sub-bbbbbbbb-0001",
    "location": "eastus",
    "public_network_access": "Disabled",
    "private_endpoint_connections": 1,
}


def _make_cosmos(items=None):
    mock_cosmos = MagicMock()
    mock_container = MagicMock()
    mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container
    mock_container.query_items.return_value = items or []
    return mock_cosmos, mock_container


def _make_pe_finding(**kwargs) -> PrivateEndpointFinding:
    defaults = dict(
        finding_id="fid-pe-001",
        resource_id="/subs/s/rgs/r/storageaccounts/sa1",
        resource_name="sa1",
        resource_type="Storage Account",
        resource_group="rg-test",
        subscription_id="sub-bbbbbbbb-0001",
        location="eastus",
        public_access="enabled",
        has_private_endpoint=False,
        private_endpoint_count=0,
        severity="high",
        recommendation="Configure a Private Endpoint for this Storage Account and disable public network access.",
        scanned_at="2026-04-17T00:00:00+00:00",
    )
    defaults.update(kwargs)
    return PrivateEndpointFinding(**defaults)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestMakeFindingId:
    def test_deterministic(self):
        fid = _make_finding_id("/subs/abc/storageaccounts/sa1")
        assert fid == _make_finding_id("/subs/abc/storageaccounts/sa1")

    def test_case_insensitive(self):
        assert _make_finding_id("/SUBS/ABC/SA1") == _make_finding_id("/subs/abc/sa1")

    def test_returns_uuid_string(self):
        fid = _make_finding_id("/subs/abc/sa1")
        assert len(fid) == 36
        assert fid.count("-") == 4


class TestNormalisePublicAccess:
    def test_enabled(self):
        assert _normalise_public_access("Enabled") == "enabled"

    def test_allow(self):
        assert _normalise_public_access("Allow") == "enabled"

    def test_disabled(self):
        assert _normalise_public_access("Disabled") == "disabled"

    def test_deny(self):
        assert _normalise_public_access("Deny") == "disabled"

    def test_empty_returns_unknown(self):
        assert _normalise_public_access("") == "unknown"

    def test_none_like_returns_unknown(self):
        assert _normalise_public_access(None) == "unknown"  # type: ignore[arg-type]

    def test_case_insensitive(self):
        assert _normalise_public_access("ENABLED") == "enabled"
        assert _normalise_public_access("DISABLED") == "disabled"


class TestDeriveSeverity:
    def test_enabled_no_pe_is_high(self):
        assert _derive_severity("enabled", 0) == "high"

    def test_enabled_with_pe_is_medium(self):
        assert _derive_severity("enabled", 2) == "medium"

    def test_disabled_is_info(self):
        assert _derive_severity("disabled", 0) == "info"

    def test_disabled_with_pe_is_info(self):
        assert _derive_severity("disabled", 1) == "info"

    def test_unknown_public_access_is_info(self):
        assert _derive_severity("unknown", 0) == "info"


class TestMakeRecommendation:
    def test_enabled_no_pe_recommends_create_pe(self):
        rec = _make_recommendation("enabled", 0, "Storage Account")
        assert "Private Endpoint" in rec
        assert "disable" in rec.lower()

    def test_enabled_with_pe_recommends_disable_public(self):
        rec = _make_recommendation("enabled", 1, "Key Vault")
        assert "public network access is still enabled" in rec
        assert "Disable" in rec

    def test_disabled_is_compliant(self):
        rec = _make_recommendation("disabled", 1, "Cosmos DB")
        assert "compliant" in rec.lower()

    def test_resource_type_appears_in_recommendation(self):
        rec = _make_recommendation("enabled", 0, "Container Registry")
        assert "Container Registry" in rec


# ---------------------------------------------------------------------------
# scan_private_endpoint_compliance
# ---------------------------------------------------------------------------

class TestScanPrivateEndpointCompliance:
    @patch("services.api_gateway.private_endpoint_service.run_arg_query")
    def test_happy_path_public_exposed_resource(self, mock_arg):
        """Storage account with public access and no PE → high finding."""
        mock_arg.return_value = [STORAGE_ROW]
        results = scan_private_endpoint_compliance(CRED, SUBS)

        assert len(results) == 1
        f = results[0]
        assert f.public_access == "enabled"
        assert f.has_private_endpoint is False
        assert f.private_endpoint_count == 0
        assert f.severity == "high"
        assert f.resource_name == "mystorageacct"
        assert f.resource_type == "Storage Account"

    @patch("services.api_gateway.private_endpoint_service.run_arg_query")
    def test_happy_path_compliant_resource(self, mock_arg):
        """Key Vault with disabled public access → info finding."""
        mock_arg.return_value = [KV_ROW]
        results = scan_private_endpoint_compliance(CRED, SUBS)

        assert len(results) == 1
        f = results[0]
        assert f.public_access == "disabled"
        assert f.has_private_endpoint is True
        assert f.severity == "info"
        assert f.resource_type == "Key Vault"

    @patch("services.api_gateway.private_endpoint_service.run_arg_query")
    def test_medium_severity_public_with_pe(self, mock_arg):
        """Resource has public access enabled AND a PE → medium severity."""
        row = {**STORAGE_ROW, "private_endpoint_connections": 1}
        mock_arg.return_value = [row]
        results = scan_private_endpoint_compliance(CRED, SUBS)

        assert results[0].severity == "medium"
        assert results[0].has_private_endpoint is True

    @patch("services.api_gateway.private_endpoint_service.run_arg_query")
    def test_empty_results_returns_empty_list(self, mock_arg):
        """No resources in subscription → empty list."""
        mock_arg.return_value = []
        results = scan_private_endpoint_compliance(CRED, SUBS)
        assert results == []

    @patch("services.api_gateway.private_endpoint_service.run_arg_query")
    def test_empty_subscription_ids_returns_empty_list(self, mock_arg):
        """No subscription IDs → returns [] without calling ARG."""
        results = scan_private_endpoint_compliance(CRED, [])
        assert results == []
        mock_arg.assert_not_called()

    @patch("services.api_gateway.private_endpoint_service.run_arg_query")
    def test_arg_exception_returns_empty_list(self, mock_arg):
        """ARG failure → [] without raising."""
        mock_arg.side_effect = RuntimeError("ARG timeout")
        results = scan_private_endpoint_compliance(CRED, SUBS)
        assert results == []

    @patch("services.api_gateway.private_endpoint_service.run_arg_query")
    def test_row_missing_resource_id_is_skipped(self, mock_arg):
        """Row with empty resource_id is silently skipped."""
        bad_row = {**STORAGE_ROW, "resource_id": ""}
        mock_arg.return_value = [bad_row]
        results = scan_private_endpoint_compliance(CRED, SUBS)
        assert results == []

    @patch("services.api_gateway.private_endpoint_service.run_arg_query")
    def test_unknown_resource_type_uses_raw_type(self, mock_arg):
        """Unknown resource type falls back to the raw type string."""
        row = {**STORAGE_ROW, "type": "microsoft.somefuturetype/widgets"}
        mock_arg.return_value = [row]
        results = scan_private_endpoint_compliance(CRED, SUBS)
        assert results[0].resource_type == "microsoft.somefuturetype/widgets"

    @patch("services.api_gateway.private_endpoint_service.run_arg_query")
    def test_pe_count_none_treated_as_zero(self, mock_arg):
        """None private_endpoint_connections → pe_count=0, has_private_endpoint=False."""
        row = {**STORAGE_ROW, "private_endpoint_connections": None}
        mock_arg.return_value = [row]
        results = scan_private_endpoint_compliance(CRED, SUBS)
        assert results[0].private_endpoint_count == 0
        assert results[0].has_private_endpoint is False

    @patch("services.api_gateway.private_endpoint_service.run_arg_query")
    def test_finding_id_is_deterministic(self, mock_arg):
        """Two scans for the same resource produce the same finding_id."""
        mock_arg.return_value = [STORAGE_ROW]
        r1 = scan_private_endpoint_compliance(CRED, SUBS)
        mock_arg.return_value = [STORAGE_ROW]
        r2 = scan_private_endpoint_compliance(CRED, SUBS)
        assert r1[0].finding_id == r2[0].finding_id


# ---------------------------------------------------------------------------
# persist_findings
# ---------------------------------------------------------------------------

class TestPersistFindings:
    def test_upsert_called_for_each_finding(self):
        cosmos, container = _make_cosmos()
        findings = [
            _make_pe_finding(),
            _make_pe_finding(finding_id="fid-pe-002", resource_id="/x/2"),
        ]
        persist_findings(cosmos, "aap-db", findings)
        assert container.upsert_item.call_count == 2

    def test_upsert_doc_has_id_field(self):
        cosmos, container = _make_cosmos()
        f = _make_pe_finding(finding_id="fid-pe-xyz")
        persist_findings(cosmos, "aap-db", [f])
        doc = container.upsert_item.call_args[0][0]
        assert doc["id"] == "fid-pe-xyz"

    def test_empty_findings_skips_upsert(self):
        cosmos, container = _make_cosmos()
        persist_findings(cosmos, "aap-db", [])
        container.upsert_item.assert_not_called()

    def test_cosmos_exception_does_not_raise(self):
        cosmos, container = _make_cosmos()
        container.upsert_item.side_effect = RuntimeError("Cosmos down")
        # Must not raise
        persist_findings(cosmos, "aap-db", [_make_pe_finding()])


# ---------------------------------------------------------------------------
# get_findings
# ---------------------------------------------------------------------------

class TestGetFindings:
    def test_returns_findings_from_cosmos(self):
        item = {
            "id": "fid-pe-001",
            "finding_id": "fid-pe-001",
            "resource_id": "/subs/s/rgs/r/sa/sa1",
            "resource_name": "sa1",
            "resource_type": "Storage Account",
            "resource_group": "rg-test",
            "subscription_id": "sub-bbbbbbbb-0001",
            "location": "eastus",
            "public_access": "enabled",
            "has_private_endpoint": False,
            "private_endpoint_count": 0,
            "severity": "high",
            "recommendation": "Configure a Private Endpoint.",
            "scanned_at": "2026-04-17T00:00:00+00:00",
            "ttl": 86400,
        }
        cosmos, _ = _make_cosmos(items=[item])
        results = get_findings(cosmos, "aap-db")
        assert len(results) == 1
        assert results[0].resource_name == "sa1"

    def test_empty_cosmos_returns_empty_list(self):
        cosmos, _ = _make_cosmos(items=[])
        results = get_findings(cosmos, "aap-db")
        assert results == []

    def test_cosmos_exception_returns_empty_list(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = RuntimeError("network timeout")
        results = get_findings(cosmos, "aap-db")
        assert results == []

    def test_subscription_filter_adds_param(self):
        cosmos, container = _make_cosmos(items=[])
        get_findings(cosmos, "aap-db", subscription_ids=["sub-001"])
        call_kwargs = container.query_items.call_args[1]
        params = call_kwargs.get("parameters") or []
        assert any(p["value"] == "sub-001" for p in params)

    def test_severity_filter_adds_param(self):
        cosmos, container = _make_cosmos(items=[])
        get_findings(cosmos, "aap-db", severity="high")
        call_kwargs = container.query_items.call_args[1]
        params = call_kwargs.get("parameters") or []
        assert any(p["value"] == "high" for p in params)

    def test_resource_type_filter_adds_param(self):
        cosmos, container = _make_cosmos(items=[])
        get_findings(cosmos, "aap-db", resource_type="Key Vault")
        call_kwargs = container.query_items.call_args[1]
        params = call_kwargs.get("parameters") or []
        assert any(p["value"] == "Key Vault" for p in params)


# ---------------------------------------------------------------------------
# get_pe_summary
# ---------------------------------------------------------------------------

class TestGetPeSummary:
    def test_summary_counts_correctly(self):
        findings = [
            _make_pe_finding(severity="high"),
            _make_pe_finding(finding_id="f2", resource_id="/x/2", severity="medium"),
            _make_pe_finding(finding_id="f3", resource_id="/x/3", severity="info"),
            _make_pe_finding(finding_id="f4", resource_id="/x/4", severity="info"),
        ]
        cosmos = MagicMock()
        with patch("services.api_gateway.private_endpoint_service.get_findings", return_value=findings):
            summary = get_pe_summary(cosmos, "aap-db")

        assert summary["total_resources"] == 4
        assert summary["high_count"] == 1
        assert summary["medium_count"] == 1
        assert summary["info_count"] == 2
        assert summary["pe_coverage_pct"] == 50.0

    def test_summary_empty_returns_zeros(self):
        cosmos = MagicMock()
        with patch("services.api_gateway.private_endpoint_service.get_findings", return_value=[]):
            summary = get_pe_summary(cosmos, "aap-db")

        assert summary["total_resources"] == 0
        assert summary["pe_coverage_pct"] == 0.0
        assert summary["by_resource_type"] == {}

    def test_summary_by_resource_type(self):
        findings = [
            _make_pe_finding(resource_type="Storage Account", severity="high"),
            _make_pe_finding(finding_id="f2", resource_id="/x/2", resource_type="Storage Account", severity="info"),
            _make_pe_finding(finding_id="f3", resource_id="/x/3", resource_type="Key Vault", severity="high"),
        ]
        cosmos = MagicMock()
        with patch("services.api_gateway.private_endpoint_service.get_findings", return_value=findings):
            summary = get_pe_summary(cosmos, "aap-db")

        by_type = summary["by_resource_type"]
        assert by_type["Storage Account"]["total"] == 2
        assert by_type["Storage Account"]["high"] == 1
        assert by_type["Storage Account"]["info"] == 1
        assert by_type["Key Vault"]["total"] == 1
        assert by_type["Key Vault"]["high"] == 1

    def test_all_compliant_coverage_is_100(self):
        findings = [
            _make_pe_finding(severity="info"),
            _make_pe_finding(finding_id="f2", resource_id="/x/2", severity="info"),
        ]
        cosmos = MagicMock()
        with patch("services.api_gateway.private_endpoint_service.get_findings", return_value=findings):
            summary = get_pe_summary(cosmos, "aap-db")

        assert summary["pe_coverage_pct"] == 100.0
        assert summary["high_count"] == 0
        assert summary["medium_count"] == 0
