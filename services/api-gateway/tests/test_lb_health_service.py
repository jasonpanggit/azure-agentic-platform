from __future__ import annotations
"""Tests for lb_health_service.py — Phase 101.

Covers:
- _classify: all severity branches
- scan_lb_health: ARG success, empty, error paths
- persist_lb_findings: upsert, no-op on empty, missing endpoint
- get_lb_findings: with / without filters, cosmos error
- get_lb_summary: aggregation, zero state, error fallback
"""
import os

import os
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_arg_row(
    name: str = "my-lb",
    sku_name: str = "Standard",
    frontend_count: int = 1,
    backend_count: int = 2,
    probe_count: int = 1,
    rule_count: int = 3,
    provisioning: str = "Succeeded",
    location: str = "eastus",
    subscription_id: str = "sub-1",
    resource_group: str = "rg-net",
) -> dict:
    return {
        "id": f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/loadBalancers/{name}",
        "name": name,
        "subscriptionId": subscription_id,
        "resourceGroup": resource_group,
        "location": location,
        "sku_name": sku_name,
        "frontend_count": frontend_count,
        "backend_count": backend_count,
        "probe_count": probe_count,
        "rule_count": rule_count,
        "provisioning": provisioning,
    }


# ---------------------------------------------------------------------------
# _classify tests
# ---------------------------------------------------------------------------

from services.api_gateway.lb_health_service import _classify


class TestClassify:
    def test_all_healthy_standard(self):
        row = _make_arg_row()
        severity, findings = _classify(row)
        assert severity == "info"
        assert findings == []

    def test_no_backends_is_critical(self):
        row = _make_arg_row(backend_count=0)
        severity, findings = _classify(row)
        assert severity == "critical"
        assert any("backend" in f.lower() for f in findings)

    def test_no_probes_is_high(self):
        row = _make_arg_row(probe_count=0)
        severity, findings = _classify(row)
        assert severity == "high"
        assert any("probe" in f.lower() for f in findings)

    def test_no_rules_is_high(self):
        row = _make_arg_row(rule_count=0)
        severity, findings = _classify(row)
        assert severity == "high"
        assert any("rule" in f.lower() for f in findings)

    def test_failed_provisioning_is_high(self):
        row = _make_arg_row(provisioning="Failed")
        severity, findings = _classify(row)
        assert severity == "high"
        assert any("Failed" in f for f in findings)

    def test_basic_sku_is_medium(self):
        row = _make_arg_row(sku_name="Basic")
        severity, findings = _classify(row)
        assert severity == "medium"
        assert any("Basic" in f for f in findings)

    def test_critical_dominates_medium(self):
        """Critical (no backends) must not be downgraded by Basic SKU."""
        row = _make_arg_row(backend_count=0, sku_name="Basic")
        severity, findings = _classify(row)
        assert severity == "critical"

    def test_multiple_high_findings(self):
        row = _make_arg_row(probe_count=0, rule_count=0)
        severity, findings = _classify(row)
        assert severity == "high"
        assert len(findings) == 2

    def test_no_backends_and_no_probes(self):
        """critical dominates high."""
        row = _make_arg_row(backend_count=0, probe_count=0)
        severity, findings = _classify(row)
        assert severity == "critical"
        assert len(findings) == 2


# ---------------------------------------------------------------------------
# scan_lb_health tests
# ---------------------------------------------------------------------------

from services.api_gateway.lb_health_service import scan_lb_health


class TestScanLbHealth:
    def test_empty_subscription_ids(self):
        assert scan_lb_health([]) == []

    def test_returns_findings_on_success(self):
        rows = [_make_arg_row("lb-1"), _make_arg_row("lb-2", backend_count=0)]
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows), \
             patch("azure.identity.DefaultAzureCredential"):
            findings = scan_lb_health(["sub-1"])
        assert len(findings) == 2
        names = [f["lb_name"] for f in findings]
        assert "lb-1" in names
        assert "lb-2" in names

    def test_critical_finding_has_correct_severity(self):
        rows = [_make_arg_row(backend_count=0)]
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows), \
             patch("azure.identity.DefaultAzureCredential"):
            findings = scan_lb_health(["sub-1"])
        assert findings[0]["severity"] == "critical"

    def test_stable_id_is_deterministic(self):
        rows = [_make_arg_row("lb-stable")]
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows), \
             patch("azure.identity.DefaultAzureCredential"):
            f1 = scan_lb_health(["sub-1"])
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows), \
             patch("azure.identity.DefaultAzureCredential"):
            f2 = scan_lb_health(["sub-1"])
        assert f1[0]["id"] == f2[0]["id"]

    def test_arg_error_returns_empty(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=Exception("timeout")), \
             patch("azure.identity.DefaultAzureCredential"):
            findings = scan_lb_health(["sub-1"])
        assert findings == []

    def test_empty_results_returns_empty_list(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=[]), \
             patch("azure.identity.DefaultAzureCredential"):
            findings = scan_lb_health(["sub-1"])
        assert findings == []

    def test_basic_sku_flagged(self):
        rows = [_make_arg_row(sku_name="Basic")]
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows), \
             patch("azure.identity.DefaultAzureCredential"):
            findings = scan_lb_health(["sub-1"])
        assert findings[0]["severity"] == "medium"
        assert findings[0]["sku"] == "Basic"

    def test_finding_has_required_fields(self):
        rows = [_make_arg_row()]
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows), \
             patch("azure.identity.DefaultAzureCredential"):
            findings = scan_lb_health(["sub-1"])
        f = findings[0]
        required = {
            "id", "subscription_id", "resource_group", "lb_name", "sku",
            "location", "frontend_count", "backend_count", "probe_count",
            "rule_count", "provisioning_state", "findings", "severity", "scanned_at",
        }
        assert required.issubset(set(f.keys()))


# ---------------------------------------------------------------------------
# persist_lb_findings tests
# ---------------------------------------------------------------------------

from services.api_gateway.lb_health_service import persist_lb_findings


class TestPersistLbFindings:
    def test_no_op_on_empty(self):
        # Should not raise
        persist_lb_findings([])

    def test_no_op_when_endpoint_missing(self, monkeypatch):
        monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
        # Should not raise
        persist_lb_findings([{"id": "x"}])

    def test_calls_upsert_for_each_finding(self, monkeypatch):
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://fake.cosmos")
        mock_container = MagicMock()
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_client = MagicMock()
        mock_client.get_database_client.return_value = mock_db

        findings = [{"id": "a"}, {"id": "b"}]
        with patch("azure.cosmos.CosmosClient", return_value=mock_client), \
             patch("azure.identity.DefaultAzureCredential"):
            persist_lb_findings(findings)

        assert mock_container.upsert_item.call_count == 2

    def test_cosmos_error_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://fake.cosmos")
        with patch("azure.cosmos.CosmosClient", side_effect=Exception("conn error")), \
             patch("azure.identity.DefaultAzureCredential"):
            persist_lb_findings([{"id": "x"}])  # must not raise


# ---------------------------------------------------------------------------
# get_lb_findings tests
# ---------------------------------------------------------------------------

from services.api_gateway.lb_health_service import get_lb_findings


class TestGetLbFindings:
    def test_returns_empty_when_no_endpoint(self, monkeypatch):
        monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
        assert get_lb_findings() == []

    def test_no_filters(self, monkeypatch):
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://fake.cosmos")
        items = [{"id": "1", "severity": "high"}, {"id": "2", "severity": "info"}]
        mock_container = MagicMock()
        mock_container.query_items.return_value = items
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_client = MagicMock()
        mock_client.get_database_client.return_value = mock_db

        with patch("azure.cosmos.CosmosClient", return_value=mock_client), \
             patch("azure.identity.DefaultAzureCredential"):
            result = get_lb_findings()
        assert len(result) == 2

    def test_subscription_filter_passed(self, monkeypatch):
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://fake.cosmos")
        mock_container = MagicMock()
        mock_container.query_items.return_value = []
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_client = MagicMock()
        mock_client.get_database_client.return_value = mock_db

        with patch("azure.cosmos.CosmosClient", return_value=mock_client), \
             patch("azure.identity.DefaultAzureCredential"):
            get_lb_findings(subscription_id="sub-42")

        call_kwargs = mock_container.query_items.call_args
        assert "sub-42" in str(call_kwargs)

    def test_cosmos_error_returns_empty(self, monkeypatch):
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://fake.cosmos")
        with patch("azure.cosmos.CosmosClient", side_effect=Exception("err")), \
             patch("azure.identity.DefaultAzureCredential"):
            assert get_lb_findings() == []


# ---------------------------------------------------------------------------
# get_lb_summary tests
# ---------------------------------------------------------------------------

from services.api_gateway.lb_health_service import get_lb_summary


class TestGetLbSummary:
    def test_empty_findings(self):
        with patch("services.api_gateway.lb_health_service.get_lb_findings", return_value=[]):
            summary = get_lb_summary()
        assert summary["total"] == 0
        assert summary["basic_sku_count"] == 0

    def test_counts_by_severity(self):
        findings = [
            {"severity": "critical", "sku": "Standard"},
            {"severity": "high", "sku": "Standard"},
            {"severity": "high", "sku": "Standard"},
            {"severity": "medium", "sku": "Basic"},
            {"severity": "info", "sku": "Standard"},
        ]
        with patch("services.api_gateway.lb_health_service.get_lb_findings", return_value=findings):
            summary = get_lb_summary()
        assert summary["total"] == 5
        assert summary["by_severity"]["critical"] == 1
        assert summary["by_severity"]["high"] == 2
        assert summary["by_severity"]["medium"] == 1
        assert summary["by_severity"]["info"] == 1
        assert summary["basic_sku_count"] == 1

    def test_error_returns_safe_default(self):
        with patch("services.api_gateway.lb_health_service.get_lb_findings", side_effect=Exception("boom")):
            summary = get_lb_summary()
        assert summary["total"] == 0
        assert "by_severity" in summary
