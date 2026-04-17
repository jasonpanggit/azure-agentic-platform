"""Tests for policy_compliance_service.py (Phase 84).

Covers:
- _stable_id: deterministic UUID generation
- _extract_resource_name: ARM ID parsing
- _friendly_resource_type: short type names
- _classify_severity: effect-to-severity mapping
- scan_policy_compliance: SDK unavailable, empty subs, full scan, error handling
- persist_violations: happy path, error handling
- get_violations: filters, error handling
- get_policy_summary: computation, error handling
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.policy_compliance_service import (
    PolicyViolation,
    _classify_severity,
    _extract_resource_name,
    _friendly_resource_type,
    _stable_id,
    get_policy_summary,
    get_violations,
    persist_violations,
    scan_policy_compliance,
)


# ---------------------------------------------------------------------------
# _stable_id
# ---------------------------------------------------------------------------

class TestStableId:
    def test_deterministic(self):
        a = _stable_id("/subscriptions/sub1/resourcegroups/rg/policy-states/abc")
        b = _stable_id("/subscriptions/sub1/resourcegroups/rg/policy-states/abc")
        assert a == b

    def test_different_inputs_differ(self):
        assert _stable_id("id-one") != _stable_id("id-two")

    def test_uuid_format(self):
        result = _stable_id("any-value")
        assert len(result) == 36
        assert result.count("-") == 4


# ---------------------------------------------------------------------------
# _extract_resource_name
# ---------------------------------------------------------------------------

class TestExtractResourceName:
    def test_standard_arm_id(self):
        arm = "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/myvm"
        assert _extract_resource_name(arm) == "myvm"

    def test_empty_string(self):
        assert _extract_resource_name("") == ""

    def test_trailing_slash(self):
        assert _extract_resource_name("/subscriptions/sub1/") == "sub1"


# ---------------------------------------------------------------------------
# _friendly_resource_type
# ---------------------------------------------------------------------------

class TestFriendlyResourceType:
    def test_two_segments(self):
        result = _friendly_resource_type("microsoft.compute/virtualmachines")
        assert result == "microsoft.compute/virtualmachines"

    def test_three_segments(self):
        result = _friendly_resource_type("microsoft.network/virtualnetworks/subnets")
        assert result == "virtualnetworks/subnets"

    def test_single_segment(self):
        result = _friendly_resource_type("microsoft")
        assert result == "microsoft"

    def test_empty(self):
        assert _friendly_resource_type("") == ""


# ---------------------------------------------------------------------------
# _classify_severity
# ---------------------------------------------------------------------------

class TestClassifySeverity:
    def test_deny_is_high(self):
        assert _classify_severity("Deny") == "high"
        assert _classify_severity("deny") == "high"

    def test_audit_is_medium(self):
        assert _classify_severity("Audit") == "medium"
        assert _classify_severity("audit") == "medium"

    def test_auditifnotexists_is_medium(self):
        assert _classify_severity("AuditIfNotExists") == "medium"

    def test_deployifnotexists_is_low(self):
        assert _classify_severity("DeployIfNotExists") == "low"

    def test_unknown_is_low(self):
        assert _classify_severity("SomeOtherEffect") == "low"
        assert _classify_severity("") == "low"


# ---------------------------------------------------------------------------
# scan_policy_compliance
# ---------------------------------------------------------------------------

class TestScanPolicyCompliance:
    def test_returns_empty_when_sdk_unavailable(self):
        with patch("services.api_gateway.policy_compliance_service._ARG_AVAILABLE", False):
            result = scan_policy_compliance(MagicMock(), ["sub1"])
        assert result == []

    def test_returns_empty_when_no_subscriptions(self):
        with patch("services.api_gateway.policy_compliance_service._ARG_AVAILABLE", True):
            result = scan_policy_compliance(MagicMock(), [])
        assert result == []

    def test_full_scan_returns_violations(self):
        row = {
            "state_id": "/subscriptions/sub1/policy-states/abc",
            "subscription_id": "sub1",
            "resource_id": "/subscriptions/sub1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1",
            "resource_type": "microsoft.compute/virtualmachines",
            "resource_group": "rg",
            "policy_definition_id": "/providers/Microsoft.Authorization/policyDefinitions/abc",
            "policy_name": "abc",
            "policy_display_name": "Require HTTPS",
            "initiative_name": "",
            "effect": "Deny",
            "timestamp": "2026-04-17T00:00:00Z",
        }
        mock_resp = MagicMock()
        mock_resp.data = [row]
        mock_resp.skip_token = None
        mock_client = MagicMock()
        mock_client.resources.return_value = mock_resp

        with patch("services.api_gateway.policy_compliance_service._ARG_AVAILABLE", True), \
             patch("services.api_gateway.policy_compliance_service.ResourceGraphClient", return_value=mock_client), \
             patch("services.api_gateway.policy_compliance_service.QueryRequest", side_effect=lambda **kw: MagicMock()), \
             patch("services.api_gateway.policy_compliance_service.QueryRequestOptions", side_effect=lambda **kw: MagicMock()):
            result = scan_policy_compliance(MagicMock(), ["sub1"])

        assert len(result) == 1
        v = result[0]
        assert v.resource_name == "vm1"
        assert v.severity == "high"
        assert v.effect == "Deny"
        assert v.policy_display_name == "Require HTTPS"

    def test_never_raises_on_exception(self):
        with patch("services.api_gateway.policy_compliance_service._ARG_AVAILABLE", True), \
             patch("services.api_gateway.policy_compliance_service.ResourceGraphClient", side_effect=RuntimeError("boom")):
            result = scan_policy_compliance(MagicMock(), ["sub1"])
        assert result == []

    def test_audit_effect_classified_medium(self):
        row = {
            "state_id": "state-1",
            "subscription_id": "sub1",
            "resource_id": "/sub/rg/vm",
            "resource_type": "microsoft.compute/virtualmachines",
            "resource_group": "rg",
            "policy_definition_id": "pid",
            "policy_name": "p",
            "policy_display_name": "Audit policy",
            "initiative_name": "init",
            "effect": "Audit",
            "timestamp": "2026-04-17T00:00:00Z",
        }
        mock_resp = MagicMock()
        mock_resp.data = [row]
        mock_resp.skip_token = None
        mock_client = MagicMock()
        mock_client.resources.return_value = mock_resp

        with patch("services.api_gateway.policy_compliance_service._ARG_AVAILABLE", True), \
             patch("services.api_gateway.policy_compliance_service.ResourceGraphClient", return_value=mock_client), \
             patch("services.api_gateway.policy_compliance_service.QueryRequest", side_effect=lambda **kw: MagicMock()), \
             patch("services.api_gateway.policy_compliance_service.QueryRequestOptions", side_effect=lambda **kw: MagicMock()):
            result = scan_policy_compliance(MagicMock(), ["sub1"])

        assert result[0].severity == "medium"


# ---------------------------------------------------------------------------
# persist_violations
# ---------------------------------------------------------------------------

class TestPersistViolations:
    def _make_violation(self) -> PolicyViolation:
        return PolicyViolation(
            violation_id="uuid-1",
            subscription_id="sub1",
            resource_id="/sub/rg/vm",
            resource_name="vm",
            resource_type="compute/virtualmachines",
            resource_group="rg",
            policy_definition_id="pid",
            policy_name="p",
            policy_display_name="Require TLS",
            initiative_name="",
            effect="Deny",
            severity="high",
            timestamp="2026-04-17T00:00:00Z",
            captured_at="2026-04-17T00:00:00Z",
        )

    def test_upserts_item(self):
        mock_container = MagicMock()
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db

        persist_violations(mock_cosmos, "aap", [self._make_violation()])
        mock_container.upsert_item.assert_called_once()

    def test_never_raises(self):
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.side_effect = RuntimeError("cosmos down")
        persist_violations(mock_cosmos, "aap", [self._make_violation()])

    def test_no_op_on_empty(self):
        mock_cosmos = MagicMock()
        persist_violations(mock_cosmos, "aap", [])
        mock_cosmos.get_database_client.assert_not_called()


# ---------------------------------------------------------------------------
# get_violations
# ---------------------------------------------------------------------------

class TestGetViolations:
    def _make_cosmos(self, items: list) -> MagicMock:
        mock_container = MagicMock()
        mock_container.query_items.return_value = items
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db
        return mock_cosmos

    def test_returns_items(self):
        cosmos = self._make_cosmos([{"violation_id": "1"}])
        result = get_violations(cosmos, "aap")
        assert len(result) == 1

    def test_severity_filter_in_query(self):
        cosmos = self._make_cosmos([])
        get_violations(cosmos, "aap", severity="high")
        call = cosmos.get_database_client().get_container_client().query_items.call_args
        assert "high" in str(call)

    def test_policy_name_filter_in_query(self):
        cosmos = self._make_cosmos([])
        get_violations(cosmos, "aap", policy_name="TLS")
        call = cosmos.get_database_client().get_container_client().query_items.call_args
        assert "TLS" in str(call)

    def test_never_raises(self):
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.side_effect = RuntimeError("boom")
        result = get_violations(mock_cosmos, "aap")
        assert result == []


# ---------------------------------------------------------------------------
# get_policy_summary
# ---------------------------------------------------------------------------

class TestGetPolicySummary:
    def _make_violations(self) -> list:
        return [
            {"severity": "high", "policy_display_name": "Require HTTPS", "policy_name": "p1", "subscription_id": "sub1"},
            {"severity": "high", "policy_display_name": "Require HTTPS", "policy_name": "p1", "subscription_id": "sub1"},
            {"severity": "medium", "policy_display_name": "Audit Storage", "policy_name": "p2", "subscription_id": "sub2"},
            {"severity": "low", "policy_display_name": "Tag Resources", "policy_name": "p3", "subscription_id": "sub1"},
        ]

    def test_correct_totals(self):
        mock_container = MagicMock()
        mock_container.query_items.return_value = self._make_violations()
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db

        summary = get_policy_summary(mock_cosmos, "aap")
        assert summary["total_violations"] == 4
        assert summary["by_severity"]["high"] == 2
        assert summary["by_severity"]["medium"] == 1
        assert summary["by_severity"]["low"] == 1

    def test_top_violated_policies(self):
        mock_container = MagicMock()
        mock_container.query_items.return_value = self._make_violations()
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db

        summary = get_policy_summary(mock_cosmos, "aap")
        assert summary["top_violated_policies"][0]["policy_name"] == "Require HTTPS"
        assert summary["top_violated_policies"][0]["count"] == 2

    def test_never_raises(self):
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.side_effect = RuntimeError("boom")
        result = get_policy_summary(mock_cosmos, "aap")
        assert result["total_violations"] == 0
