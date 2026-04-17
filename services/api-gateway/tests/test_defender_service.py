from __future__ import annotations
"""Tests for defender_service.py — 25+ tests covering parsing, normalization, summary, persistence."""

import json
import uuid
from dataclasses import asdict
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, call

import pytest

from services.api_gateway.defender_service import (
    DefenderAlert,
    DefenderRecommendation,
    _normalise_severity,
    _stable_id,
    _parse_json_list,
    _extract_resource_ids,
    scan_defender_alerts,
    scan_defender_recommendations,
    persist_defender_data,
    get_alerts,
    get_recommendations,
    get_defender_summary,
    DEFENDER_ALERTS_TTL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_CREDENTIAL = MagicMock()
SUBSCRIPTION_IDS = ["sub-aaa-111", "sub-bbb-222"]

SAMPLE_ALERT_ROW = {
    "arm_id": "/subscriptions/sub-aaa-111/providers/microsoft.security/locations/eastus/alerts/alert-1",
    "subscription_id": "sub-aaa-111",
    "display_name": "Suspicious PowerShell activity detected",
    "description": "A PowerShell command was executed with suspicious flags.",
    "severity": "High",
    "status": "Active",
    "resource_identifiers": json.dumps([
        {"AzureResourceId": "/subscriptions/sub-aaa-111/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"}
    ]),
    "generated_at": "2026-04-17T10:00:00Z",
    "remediation_steps": json.dumps(["Isolate the VM", "Review process tree"]),
}

SAMPLE_REC_ROW = {
    "arm_id": "/subscriptions/sub-aaa-111/providers/microsoft.security/assessments/rec-1",
    "subscription_id": "sub-aaa-111",
    "resource_group": "rg-production",
    "display_name": "Enable MFA for all users",
    "severity": "High",
    "description": "Multi-factor authentication should be enabled.",
    "remediation": "Enable MFA in Azure AD Conditional Access.",
    "resource_id": "/subscriptions/sub-aaa-111/resourceGroups/rg-production",
    "category": "Identity",
}


def make_cosmos_mock(items: List[Dict[str, Any]]) -> MagicMock:
    """Build a mock CosmosClient that returns given items from query_items."""
    container_mock = MagicMock()
    container_mock.query_items.return_value = iter(items)
    container_mock.upsert_item = MagicMock()
    db_mock = MagicMock()
    db_mock.get_container_client.return_value = container_mock
    cosmos_mock = MagicMock()
    cosmos_mock.get_database_client.return_value = db_mock
    return cosmos_mock


# ---------------------------------------------------------------------------
# Unit: helper functions
# ---------------------------------------------------------------------------

class TestNormaliseSeverity:
    def test_high(self):
        assert _normalise_severity("High") == "High"

    def test_high_lower(self):
        assert _normalise_severity("high") == "High"

    def test_medium(self):
        assert _normalise_severity("medium") == "Medium"

    def test_low(self):
        assert _normalise_severity("low") == "Low"

    def test_informational(self):
        assert _normalise_severity("informational") == "Informational"

    def test_critical_maps_to_high(self):
        assert _normalise_severity("critical") == "High"

    def test_unknown_capitalised(self):
        assert _normalise_severity("unknown") == "Unknown"


class TestStableId:
    def test_deterministic(self):
        arm_id = "/subscriptions/sub-1/providers/security/alerts/abc"
        assert _stable_id(arm_id) == _stable_id(arm_id)

    def test_case_insensitive(self):
        assert _stable_id("/Sub/Alert/ABC") == _stable_id("/sub/alert/abc")

    def test_valid_uuid(self):
        result = _stable_id("/some/arm/id")
        # Should not raise
        uuid.UUID(result)


class TestParseJsonList:
    def test_empty_string(self):
        assert _parse_json_list("") == []

    def test_valid_list(self):
        assert _parse_json_list('["a", "b"]') == ["a", "b"]

    def test_invalid_json(self):
        assert _parse_json_list("not-json") == []

    def test_non_list_json(self):
        assert _parse_json_list('{"key": "val"}') == []


class TestExtractResourceIds:
    def test_azure_resource_id_field(self):
        raw = json.dumps([{"AzureResourceId": "/subs/s/rg/r/vm/v"}])
        result = _extract_resource_ids(raw)
        assert result == ["/subs/s/rg/r/vm/v"]

    def test_id_field_fallback(self):
        raw = json.dumps([{"id": "/subs/s/rg/r"}])
        result = _extract_resource_ids(raw)
        assert result == ["/subs/s/rg/r"]

    def test_empty_items(self):
        assert _extract_resource_ids("") == []

    def test_multiple_resources(self):
        raw = json.dumps([
            {"AzureResourceId": "/subs/s/vm/vm1"},
            {"AzureResourceId": "/subs/s/vm/vm2"},
        ])
        result = _extract_resource_ids(raw)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# scan_defender_alerts
# ---------------------------------------------------------------------------

class TestScanDefenderAlerts:
    def test_returns_empty_for_no_subscriptions(self):
        result = scan_defender_alerts(MOCK_CREDENTIAL, [])
        assert result == []

    def test_parses_row_correctly(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=[SAMPLE_ALERT_ROW]):
            alerts = scan_defender_alerts(MOCK_CREDENTIAL, SUBSCRIPTION_IDS)
        assert len(alerts) == 1
        a = alerts[0]
        assert a.display_name == "Suspicious PowerShell activity detected"
        assert a.severity == "High"
        assert a.status == "Active"
        assert len(a.resource_ids) == 1
        assert len(a.remediation_steps) == 2

    def test_stable_id_from_arm_id(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=[SAMPLE_ALERT_ROW]):
            alerts = scan_defender_alerts(MOCK_CREDENTIAL, SUBSCRIPTION_IDS)
        expected = _stable_id(SAMPLE_ALERT_ROW["arm_id"])
        assert alerts[0].alert_id == expected

    def test_ttl_set_correctly(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=[SAMPLE_ALERT_ROW]):
            alerts = scan_defender_alerts(MOCK_CREDENTIAL, SUBSCRIPTION_IDS)
        assert alerts[0].ttl == DEFENDER_ALERTS_TTL

    def test_returns_empty_on_arg_error(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=Exception("ARG down")):
            result = scan_defender_alerts(MOCK_CREDENTIAL, SUBSCRIPTION_IDS)
        assert result == []

    def test_severity_normalised(self):
        row = {**SAMPLE_ALERT_ROW, "severity": "medium"}
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=[row]):
            alerts = scan_defender_alerts(MOCK_CREDENTIAL, SUBSCRIPTION_IDS)
        assert alerts[0].severity == "Medium"


# ---------------------------------------------------------------------------
# scan_defender_recommendations
# ---------------------------------------------------------------------------

class TestScanDefenderRecommendations:
    def test_returns_empty_for_no_subscriptions(self):
        result = scan_defender_recommendations(MOCK_CREDENTIAL, [])
        assert result == []

    def test_parses_row_correctly(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=[SAMPLE_REC_ROW]):
            recs = scan_defender_recommendations(MOCK_CREDENTIAL, SUBSCRIPTION_IDS)
        assert len(recs) == 1
        r = recs[0]
        assert r.display_name == "Enable MFA for all users"
        assert r.severity == "High"
        assert r.category == "Identity"
        assert r.resource_group == "rg-production"

    def test_returns_empty_on_arg_error(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=RuntimeError("timeout")):
            result = scan_defender_recommendations(MOCK_CREDENTIAL, SUBSCRIPTION_IDS)
        assert result == []

    def test_ttl_set_correctly(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=[SAMPLE_REC_ROW]):
            recs = scan_defender_recommendations(MOCK_CREDENTIAL, SUBSCRIPTION_IDS)
        assert recs[0].ttl == DEFENDER_ALERTS_TTL


# ---------------------------------------------------------------------------
# persist_defender_data
# ---------------------------------------------------------------------------

class TestPersistDefenderData:
    def test_upserts_alerts_and_recs(self):
        cosmos = make_cosmos_mock([])
        alert = DefenderAlert(
            alert_id="a1", subscription_id="sub1", display_name="Alert 1",
            description="desc", severity="High", status="Active",
            resource_ids=[], generated_at="2026-04-17T00:00:00Z",
            remediation_steps=[], captured_at="2026-04-17T00:00:00Z",
        )
        rec = DefenderRecommendation(
            rec_id="r1", subscription_id="sub1", resource_group="rg1",
            display_name="Rec 1", severity="Medium", description="desc",
            remediation="fix it", resource_id="/sub/r", category="Compute",
            captured_at="2026-04-17T00:00:00Z",
        )
        persist_defender_data(cosmos, "aap", [alert], [rec])
        container = cosmos.get_database_client("aap").get_container_client("defender_alerts")
        assert container.upsert_item.call_count == 2

    def test_no_raise_on_upsert_error(self):
        cosmos = make_cosmos_mock([])
        container = cosmos.get_database_client("aap").get_container_client("defender_alerts")
        container.upsert_item.side_effect = Exception("Cosmos error")
        # Should not raise
        persist_defender_data(cosmos, "aap", [
            DefenderAlert(
                alert_id="a1", subscription_id="sub1", display_name="A",
                description="", severity="High", status="Active",
                resource_ids=[], generated_at="", remediation_steps=[], captured_at="",
            )
        ], [])

    def test_skips_when_no_cosmos(self):
        # Should not raise, does nothing
        persist_defender_data(None, "aap", [], [])


# ---------------------------------------------------------------------------
# get_alerts / get_recommendations
# ---------------------------------------------------------------------------

class TestGetAlerts:
    def _make_alert_doc(self, severity: str = "High", sub: str = "sub1") -> Dict[str, Any]:
        return {
            "id": "a1", "alert_id": "a1", "subscription_id": sub,
            "display_name": "Test Alert", "description": "",
            "severity": severity, "status": "Active",
            "resource_ids": [], "generated_at": "2026-04-17T00:00:00Z",
            "remediation_steps": [], "captured_at": "2026-04-17T00:00:00Z",
            "ttl": 172800, "record_type": "alert",
        }

    def test_returns_alerts(self):
        cosmos = make_cosmos_mock([self._make_alert_doc()])
        result = get_alerts(cosmos, "aap")
        assert len(result) == 1
        assert isinstance(result[0], DefenderAlert)

    def test_filters_by_subscription(self):
        docs = [self._make_alert_doc(sub="sub1"), self._make_alert_doc(sub="sub2")]
        cosmos = make_cosmos_mock(docs)
        result = get_alerts(cosmos, "aap", subscription_ids=["sub1"])
        assert all(a.subscription_id == "sub1" for a in result)

    def test_returns_empty_on_cosmos_error(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = Exception("Cosmos down")
        result = get_alerts(cosmos, "aap")
        assert result == []

    def test_returns_empty_when_no_cosmos(self):
        result = get_alerts(None, "aap")
        assert result == []


class TestGetRecommendations:
    def _make_rec_doc(self, severity: str = "High", category: str = "Compute") -> Dict[str, Any]:
        return {
            "id": "r1", "rec_id": "r1", "subscription_id": "sub1",
            "resource_group": "rg1", "display_name": "Test Rec",
            "severity": severity, "description": "", "remediation": "",
            "resource_id": "/sub/r", "category": category,
            "captured_at": "2026-04-17T00:00:00Z",
            "ttl": 172800, "record_type": "recommendation",
        }

    def test_returns_recommendations(self):
        cosmos = make_cosmos_mock([self._make_rec_doc()])
        result = get_recommendations(cosmos, "aap")
        assert len(result) == 1
        assert isinstance(result[0], DefenderRecommendation)

    def test_returns_empty_on_error(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = Exception("err")
        result = get_recommendations(cosmos, "aap")
        assert result == []


# ---------------------------------------------------------------------------
# get_defender_summary
# ---------------------------------------------------------------------------

class TestGetDefenderSummary:
    def _make_alert(self, severity: str, resource_id: str = "/sub/r/vm1") -> DefenderAlert:
        return DefenderAlert(
            alert_id=str(uuid.uuid4()), subscription_id="sub1",
            display_name="Alert", description="", severity=severity,
            status="Active", resource_ids=[resource_id],
            generated_at="2026-04-17T00:00:00Z", remediation_steps=[],
            captured_at="2026-04-17T00:00:00Z",
        )

    def test_counts_by_severity(self):
        alerts = [
            self._make_alert("High"), self._make_alert("High"),
            self._make_alert("Medium"), self._make_alert("Low"),
        ]
        with patch("services.api_gateway.defender_service.get_alerts", return_value=alerts), \
             patch("services.api_gateway.defender_service.get_recommendations", return_value=[]):
            summary = get_defender_summary(None, "aap")
        assert summary["alert_counts_by_severity"]["High"] == 2
        assert summary["alert_counts_by_severity"]["Medium"] == 1
        assert summary["alert_counts_by_severity"]["Low"] == 1
        assert summary["total_alerts"] == 4

    def test_secure_score_always_null(self):
        with patch("services.api_gateway.defender_service.get_alerts", return_value=[]), \
             patch("services.api_gateway.defender_service.get_recommendations", return_value=[]):
            summary = get_defender_summary(None, "aap")
        assert summary["secure_score_estimate"] is None

    def test_top_affected_resources(self):
        vm1 = "/sub/r/vm1"
        vm2 = "/sub/r/vm2"
        alerts = [
            self._make_alert("High", vm1),
            self._make_alert("High", vm1),
            self._make_alert("Medium", vm2),
        ]
        with patch("services.api_gateway.defender_service.get_alerts", return_value=alerts), \
             patch("services.api_gateway.defender_service.get_recommendations", return_value=[]):
            summary = get_defender_summary(None, "aap")
        top = summary["top_affected_resources"]
        assert top[0]["resource_id"] == vm1
        assert top[0]["alert_count"] == 2

    def test_returns_zeros_on_error(self):
        with patch("services.api_gateway.defender_service.get_alerts", side_effect=Exception("boom")):
            summary = get_defender_summary(None, "aap")
        assert summary["total_alerts"] == 0
        assert "error" in summary

    def test_recommendation_counts(self):
        from services.api_gateway.defender_service import DefenderRecommendation
        recs = [
            DefenderRecommendation(
                rec_id="r1", subscription_id="sub1", resource_group="rg",
                display_name="R", severity="High", description="", remediation="",
                resource_id="", category="Compute", captured_at="",
            ),
            DefenderRecommendation(
                rec_id="r2", subscription_id="sub1", resource_group="rg",
                display_name="R2", severity="Medium", description="", remediation="",
                resource_id="", category="Network", captured_at="",
            ),
        ]
        with patch("services.api_gateway.defender_service.get_alerts", return_value=[]), \
             patch("services.api_gateway.defender_service.get_recommendations", return_value=recs):
            summary = get_defender_summary(None, "aap")
        assert summary["recommendation_counts_by_severity"]["High"] == 1
        assert summary["recommendation_counts_by_severity"]["Medium"] == 1
        assert summary["total_recommendations"] == 2
