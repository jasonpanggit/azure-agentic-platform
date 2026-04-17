from __future__ import annotations
"""Tests for NSG audit service (Phase 77).

Coverage:
- classify_rule: risk classification for critical/high/medium/info/safe rules
- scan_nsg_compliance: ARG integration with mocked results
- get_findings: filtering by severity and subscription
- get_summary: aggregation logic
- API endpoints: GET findings, GET summary, POST scan
"""
import os

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.nsg_audit_service import (
    NSGFinding,
    classify_rule,
    get_findings,
    get_summary,
    persist_findings,
    scan_nsg_compliance,
    _is_internet_source,
    _is_broad_cidr,
    _port_in_set,
    SENSITIVE_PORTS_CRITICAL,
    SENSITIVE_PORTS_HIGH,
    SENSITIVE_PORTS_ALL,
)


# ---------------------------------------------------------------------------
# classify_rule — risk classification
# ---------------------------------------------------------------------------


class TestClassifyRule:
    def test_internet_ssh_is_critical(self):
        result = classify_rule("*", "22", "")
        assert result is not None
        assert result["severity"] == "critical"
        assert "SSH" in result["description"]

    def test_internet_rdp_is_critical(self):
        result = classify_rule("*", "3389", "")
        assert result is not None
        assert result["severity"] == "critical"
        assert "RDP" in result["description"]

    def test_internet_smb_is_critical(self):
        result = classify_rule("Internet", "445", "")
        assert result is not None
        assert result["severity"] == "critical"

    def test_internet_telnet_is_critical(self):
        result = classify_rule("0.0.0.0/0", "23", "")
        assert result is not None
        assert result["severity"] == "critical"

    def test_internet_sql_server_is_high(self):
        result = classify_rule("*", "1433", "")
        assert result is not None
        assert result["severity"] == "high"
        assert "SQL" in result["description"]

    def test_internet_mysql_is_high(self):
        result = classify_rule("*", "3306", "")
        assert result is not None
        assert result["severity"] == "high"

    def test_internet_postgres_is_high(self):
        result = classify_rule("0.0.0.0/0", "5432", "")
        assert result is not None
        assert result["severity"] == "high"

    def test_broad_cidr_slash8_ssh_is_medium(self):
        result = classify_rule("10.0.0.0/8", "22", "")
        assert result is not None
        assert result["severity"] == "medium"

    def test_broad_cidr_slash16_rdp_is_medium(self):
        result = classify_rule("192.168.0.0/16", "3389", "")
        assert result is not None
        assert result["severity"] == "medium"

    def test_broad_cidr_slash24_is_not_medium(self):
        # /24 is specific enough — should not be medium for broad CIDR reason
        result = classify_rule("10.1.2.0/24", "22", "")
        # /24 is not broad, so not triggered; not internet either — no finding
        assert result is None

    def test_wildcard_port_from_private_source_is_info(self):
        result = classify_rule("10.0.0.1", "*", "")
        assert result is not None
        assert result["severity"] == "info"

    def test_wildcard_port_from_internet_is_critical_ssh_check_first(self):
        # * means all ports, which includes SSH (22) — triggers critical first
        result = classify_rule("*", "*", "")
        assert result is not None
        assert result["severity"] == "critical"

    def test_safe_rule_returns_none(self):
        # Private IP to non-sensitive port
        result = classify_rule("10.0.0.5", "80", "")
        assert result is None

    def test_safe_rule_specific_cidr(self):
        result = classify_rule("10.1.0.0/24", "443", "")
        assert result is None

    def test_destination_ports_list_critical(self):
        # Multi-port list containing SSH
        result = classify_rule("*", "", '["22","80","443"]')
        assert result is not None
        assert result["severity"] == "critical"

    def test_destination_ports_list_high(self):
        result = classify_rule("*", "", '["80","3306"]')
        assert result is not None
        assert result["severity"] == "high"

    def test_remediation_present(self):
        result = classify_rule("*", "22", "")
        assert result is not None
        assert len(result["remediation"]) > 10

    def test_internet_source_case_insensitive(self):
        result = classify_rule("INTERNET", "3389", "")
        assert result is not None
        assert result["severity"] == "critical"


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_is_internet_source_star(self):
        assert _is_internet_source("*") is True

    def test_is_internet_source_any(self):
        assert _is_internet_source("Internet") is True

    def test_is_internet_source_cidr(self):
        assert _is_internet_source("0.0.0.0/0") is True

    def test_is_internet_source_private(self):
        assert _is_internet_source("10.0.0.0/8") is False

    def test_is_broad_cidr_slash8(self):
        assert _is_broad_cidr("10.0.0.0/8") is True

    def test_is_broad_cidr_slash16(self):
        assert _is_broad_cidr("192.168.0.0/16") is True

    def test_is_broad_cidr_slash24_false(self):
        assert _is_broad_cidr("10.1.0.0/24") is False

    def test_port_in_set_exact_match(self):
        assert _port_in_set("22", SENSITIVE_PORTS_CRITICAL) is True

    def test_port_in_set_wildcard(self):
        assert _port_in_set("*", SENSITIVE_PORTS_CRITICAL) is True

    def test_port_in_set_range_includes_sensitive(self):
        assert _port_in_set("20-25", SENSITIVE_PORTS_CRITICAL) is True

    def test_port_in_set_no_match(self):
        assert _port_in_set("80", SENSITIVE_PORTS_CRITICAL) is False


# ---------------------------------------------------------------------------
# scan_nsg_compliance
# ---------------------------------------------------------------------------


def _make_arg_row(
    nsg_name: str = "test-nsg",
    rule_name: str = "AllowSSH",
    source: str = "*",
    port: str = "22",
    ports: str = "",
    subscription_id: str = "sub-001",
) -> Dict[str, Any]:
    return {
        "nsg_id": f"/subscriptions/{subscription_id}/resourcegroups/rg/providers/microsoft.network/networksecuritygroups/{nsg_name}",
        "nsg_name": nsg_name,
        "resourceGroup": "rg-test",
        "subscriptionId": subscription_id,
        "location": "eastus",
        "rule_name": rule_name,
        "priority": 100,
        "source_address": source,
        "destination_port": port,
        "destination_ports": ports,
    }


class TestScanNsgCompliance:
    def test_returns_empty_on_empty_subscriptions(self):
        credential = MagicMock()
        result = scan_nsg_compliance(credential, [])
        assert result == []

    def test_returns_findings_for_critical_rule(self):
        credential = MagicMock()
        rows = [_make_arg_row(source="*", port="22")]
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows):
            findings = scan_nsg_compliance(credential, ["sub-001"])
        assert len(findings) == 1
        assert findings[0].severity == "critical"
        assert findings[0].nsg_name == "test-nsg"

    def test_filters_out_safe_rules(self):
        credential = MagicMock()
        rows = [_make_arg_row(source="10.0.0.5", port="80")]
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows):
            findings = scan_nsg_compliance(credential, ["sub-001"])
        assert findings == []

    def test_returns_multiple_findings(self):
        credential = MagicMock()
        rows = [
            _make_arg_row(rule_name="AllowSSH", source="*", port="22"),
            _make_arg_row(rule_name="AllowRDP", source="*", port="3389"),
            _make_arg_row(rule_name="AllowSQL", source="*", port="1433"),
        ]
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows):
            findings = scan_nsg_compliance(credential, ["sub-001"])
        assert len(findings) == 3
        severities = {f.severity for f in findings}
        assert "critical" in severities
        assert "high" in severities

    def test_returns_empty_on_arg_exception(self):
        credential = MagicMock()
        with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=Exception("ARG error")):
            findings = scan_nsg_compliance(credential, ["sub-001"])
        assert findings == []

    def test_finding_id_is_stable(self):
        credential = MagicMock()
        rows = [_make_arg_row(source="*", port="22")]
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows):
            findings1 = scan_nsg_compliance(credential, ["sub-001"])
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows):
            findings2 = scan_nsg_compliance(credential, ["sub-001"])
        assert findings1[0].finding_id == findings2[0].finding_id


# ---------------------------------------------------------------------------
# get_findings
# ---------------------------------------------------------------------------


def _make_cosmos_container(items: List[Dict[str, Any]]) -> MagicMock:
    container = MagicMock()
    container.read.return_value = None
    container.query_items.return_value = iter(items)
    return container


def _make_cosmos_client(items: List[Dict[str, Any]]) -> MagicMock:
    container = _make_cosmos_container(items)
    db = MagicMock()
    db.get_container_client.return_value = container
    client = MagicMock()
    client.get_database_client.return_value = db
    return client


class TestGetFindings:
    def test_returns_all_findings_no_filter(self):
        item = NSGFinding(
            finding_id="f1", nsg_id="nsg1", nsg_name="nsg1", resource_group="rg",
            subscription_id="sub-001", location="eastus", rule_name="r1", priority=100,
            direction="Inbound", access="Allow", source_address="*",
            destination_port="22", severity="critical",
            description="desc", remediation="rem", scanned_at="2026-01-01T00:00:00Z",
        ).to_dict()
        cosmos_client = _make_cosmos_client([item])
        findings = get_findings(cosmos_client, "aap-db")
        assert len(findings) == 1
        assert findings[0].severity == "critical"

    def test_returns_empty_on_cosmos_failure(self):
        cosmos_client = MagicMock()
        cosmos_client.get_database_client.side_effect = Exception("cosmos down")
        findings = get_findings(cosmos_client, "aap-db")
        assert findings == []

    def test_severity_filter_passed_to_query(self):
        cosmos_client = _make_cosmos_client([])
        get_findings(cosmos_client, "aap-db", severity="high")
        call_args = cosmos_client.get_database_client().get_container_client().query_items.call_args
        assert call_args is not None
        query = call_args.kwargs.get("query", "") or call_args.args[0] if call_args.args else ""
        assert "@severity" in str(call_args)

    def test_subscription_filter_passed_to_query(self):
        cosmos_client = _make_cosmos_client([])
        get_findings(cosmos_client, "aap-db", subscription_ids=["sub-001"])
        call_args = cosmos_client.get_database_client().get_container_client().query_items.call_args
        assert "@sub0" in str(call_args)


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------


class TestGetSummary:
    def test_counts_by_severity(self):
        items = [
            {"severity": "critical", "nsg_id": "nsg1", "nsg_name": "n1"},
            {"severity": "critical", "nsg_id": "nsg2", "nsg_name": "n2"},
            {"severity": "high",     "nsg_id": "nsg1", "nsg_name": "n1"},
            {"severity": "medium",   "nsg_id": "nsg3", "nsg_name": "n3"},
            {"severity": "info",     "nsg_id": "nsg4", "nsg_name": "n4"},
        ]
        cosmos_client = _make_cosmos_client(items)
        summary = get_summary(cosmos_client, "aap-db")
        assert summary["counts"]["critical"] == 2
        assert summary["counts"]["high"] == 1
        assert summary["counts"]["medium"] == 1
        assert summary["counts"]["info"] == 1
        assert summary["counts"]["total"] == 5

    def test_top_risky_nsgs_sorted_by_count(self):
        items = [
            {"severity": "critical", "nsg_id": "nsg1", "nsg_name": "n1"},
            {"severity": "high",     "nsg_id": "nsg1", "nsg_name": "n1"},
            {"severity": "medium",   "nsg_id": "nsg2", "nsg_name": "n2"},
        ]
        cosmos_client = _make_cosmos_client(items)
        summary = get_summary(cosmos_client, "aap-db")
        top = summary["top_risky_nsgs"]
        assert top[0]["nsg_id"] == "nsg1"
        assert top[0]["finding_count"] == 2

    def test_returns_empty_summary_on_failure(self):
        cosmos_client = MagicMock()
        cosmos_client.get_database_client.side_effect = Exception("fail")
        summary = get_summary(cosmos_client, "aap-db")
        assert summary["counts"]["total"] == 0
        assert summary["top_risky_nsgs"] == []

    def test_generated_at_present(self):
        cosmos_client = _make_cosmos_client([])
        summary = get_summary(cosmos_client, "aap-db")
        assert "generated_at" in summary
        assert summary["generated_at"]


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_client():
    """Build a TestClient with mocked app.state dependencies."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.api_gateway.nsg_audit_endpoints import router
    from services.api_gateway.dependencies import get_scoped_credential, get_cosmos_client

    application = FastAPI()
    application.include_router(router)

    cosmos_mock = MagicMock()
    credential_mock = MagicMock()

    # Wire state
    application.state.cosmos_client = cosmos_mock
    application.state.credential = credential_mock

    # Override scoped credential — NSG endpoints don't have a /{subscription_id} path param,
    # so get_scoped_credential would fail with 422. Return the flat credential instead.
    async def _mock_scoped_credential() -> object:
        return credential_mock

    application.dependency_overrides[get_scoped_credential] = _mock_scoped_credential
    application.dependency_overrides[get_cosmos_client] = lambda: cosmos_mock

    return TestClient(application), cosmos_mock, credential_mock


class TestNsgEndpoints:
    def test_get_findings_returns_200(self, app_client):
        client, cosmos_mock, _ = app_client
        container = _make_cosmos_container([])
        db = MagicMock()
        db.get_container_client.return_value = container
        cosmos_mock.get_database_client.return_value = db

        resp = client.get("/api/v1/nsg/findings")
        assert resp.status_code == 200
        data = resp.json()
        assert "findings" in data
        assert "count" in data

    def test_get_findings_invalid_severity_returns_422(self, app_client):
        client, _, _ = app_client
        resp = client.get("/api/v1/nsg/findings?severity=bogus")
        assert resp.status_code == 422

    def test_get_summary_returns_200(self, app_client):
        client, cosmos_mock, _ = app_client
        container = _make_cosmos_container([])
        db = MagicMock()
        db.get_container_client.return_value = container
        cosmos_mock.get_database_client.return_value = db

        resp = client.get("/api/v1/nsg/findings/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "counts" in data
        assert "top_risky_nsgs" in data

    def test_post_scan_returns_queued(self, app_client):
        client, cosmos_mock, _ = app_client
        container = _make_cosmos_container([])
        db = MagicMock()
        db.get_container_client.return_value = container
        cosmos_mock.get_database_client.return_value = db

        with patch.dict("os.environ", {"SUBSCRIPTION_IDS": "sub-001,sub-002"}):
            resp = client.post("/api/v1/nsg/scan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert "scan_id" in data
        assert data["subscription_count"] == 2

    def test_post_scan_no_subscriptions_returns_422(self, app_client):
        client, _, _ = app_client
        with patch.dict("os.environ", {"SUBSCRIPTION_IDS": ""}):
            resp = client.post("/api/v1/nsg/scan")
        assert resp.status_code == 422
