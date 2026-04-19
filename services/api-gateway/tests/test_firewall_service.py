from __future__ import annotations
"""Unit tests for firewall_service.py (Phase 104).

Tests cover:
- classify_firewall_rule: too_wide_source, too_wide_ports, clean rule
- detect_overlapping_rules: overlap_shadowed detection
- get_firewall_rules: empty subscription list
- get_firewall_audit: no firewalls → empty findings + zero summary
"""

import os
from typing import List
from unittest.mock import patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.firewall_service import (
    FirewallAuditFinding,
    FirewallRule,
    classify_firewall_rule,
    detect_overlapping_rules,
    get_firewall_audit,
    get_firewall_rules,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(
    firewall_name: str = "fw-prod",
    rule_name: str = "rule1",
    collection_name: str = "net-collection",
    collection_priority: int = 100,
    action: str = "Allow",
    source_addresses: List[str] = None,
    destination_addresses: List[str] = None,
    destination_ports: List[str] = None,
) -> FirewallRule:
    return FirewallRule(
        firewall_id="/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/azureFirewalls/fw-prod",
        firewall_name=firewall_name,
        resource_group="rg1",
        subscription_id="sub1",
        location="eastus",
        sku_tier="Premium",
        threat_intel_mode="Alert",
        policy_id="/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/firewallPolicies/policy1",
        policy_name="policy1",
        collection_name=collection_name,
        collection_priority=collection_priority,
        action=action,
        rule_name=rule_name,
        rule_type="NetworkRule",
        source_addresses=source_addresses or ["10.0.0.0/24"],
        destination_addresses=destination_addresses or ["10.1.0.0/24"],
        destination_ports=destination_ports or ["443"],
        protocols=["TCP"],
    )


# ---------------------------------------------------------------------------
# classify_firewall_rule tests
# ---------------------------------------------------------------------------


class TestClassifyFirewallRule:
    def test_too_wide_source_wildcard_allow_is_critical(self):
        rule = _make_rule(
            action="Allow",
            source_addresses=["*"],
            destination_addresses=["10.1.0.0/24"],
            destination_ports=["443"],
        )
        findings: List[FirewallAuditFinding] = classify_firewall_rule(rule)
        wide_source = [f for f in findings if f.issue_type == "too_wide_source"]
        assert wide_source, "Expected a too_wide_source finding"
        assert wide_source[0].severity == "critical"

    def test_too_wide_source_inet_cidr_is_critical(self):
        rule = _make_rule(
            action="Allow",
            source_addresses=["0.0.0.0/0"],
        )
        findings = classify_firewall_rule(rule)
        wide_source = [f for f in findings if f.issue_type == "too_wide_source"]
        assert wide_source
        assert wide_source[0].severity == "critical"

    def test_too_wide_ports_wildcard_allow_is_high(self):
        rule = _make_rule(
            action="Allow",
            source_addresses=["10.0.0.0/24"],
            destination_addresses=["10.1.0.0/24"],
            destination_ports=["*"],
        )
        findings = classify_firewall_rule(rule)
        wide_ports = [f for f in findings if f.issue_type == "too_wide_ports"]
        assert wide_ports, "Expected a too_wide_ports finding"
        assert wide_ports[0].severity == "high"

    def test_too_wide_ports_full_range_allow_is_high(self):
        rule = _make_rule(
            action="Allow",
            source_addresses=["10.0.0.0/24"],
            destination_addresses=["10.1.0.0/24"],
            destination_ports=["0-65535"],
        )
        findings = classify_firewall_rule(rule)
        wide_ports = [f for f in findings if f.issue_type == "too_wide_ports"]
        assert wide_ports
        assert wide_ports[0].severity == "high"

    def test_clean_rule_returns_no_findings(self):
        rule = _make_rule(
            action="Allow",
            source_addresses=["10.0.0.0/24"],
            destination_addresses=["10.1.0.0/24"],
            destination_ports=["443"],
        )
        findings = classify_firewall_rule(rule)
        assert findings == [], f"Expected no findings for clean rule, got {findings}"

    def test_too_wide_destination_both_wildcard_is_high(self):
        rule = _make_rule(
            action="Allow",
            source_addresses=["10.0.0.0/24"],
            destination_addresses=["*"],
            destination_ports=["*"],
        )
        findings = classify_firewall_rule(rule)
        wide_dest = [f for f in findings if f.issue_type == "too_wide_destination"]
        assert wide_dest, "Expected a too_wide_destination finding"
        assert wide_dest[0].severity == "high"

    def test_deny_rule_with_wildcard_source_is_high_not_critical(self):
        """Deny rules with wildcard source should produce high, not critical."""
        rule = _make_rule(
            action="Deny",
            source_addresses=["*"],
        )
        findings = classify_firewall_rule(rule)
        wide_source = [f for f in findings if f.issue_type == "too_wide_source"]
        assert wide_source
        assert wide_source[0].severity == "high"


# ---------------------------------------------------------------------------
# detect_overlapping_rules tests
# ---------------------------------------------------------------------------


class TestDetectOverlappingRules:
    def test_overlap_shadowed_different_priority(self):
        rule1 = _make_rule(
            rule_name="rule-a",
            collection_priority=100,
            source_addresses=["10.0.0.0/24"],
            destination_addresses=["10.1.0.0/24"],
            destination_ports=["80"],
        )
        rule2 = _make_rule(
            rule_name="rule-b",
            collection_priority=200,
            source_addresses=["10.0.0.0/24"],
            destination_addresses=["10.1.0.0/24"],
            destination_ports=["80"],
        )
        findings = detect_overlapping_rules([rule1, rule2])
        overlap = [f for f in findings if f.issue_type == "overlap_shadowed"]
        assert overlap, "Expected an overlap_shadowed finding"
        assert overlap[0].severity == "medium"

    def test_no_overlap_different_ports(self):
        rule1 = _make_rule(rule_name="rule-a", destination_ports=["80"])
        rule2 = _make_rule(rule_name="rule-b", destination_ports=["443"])
        findings = detect_overlapping_rules([rule1, rule2])
        assert not findings

    def test_no_overlap_same_priority(self):
        """Same fingerprint and same priority → not flagged as shadowed."""
        rule1 = _make_rule(rule_name="rule-a", collection_priority=100)
        rule2 = _make_rule(rule_name="rule-b", collection_priority=100)
        findings = detect_overlapping_rules([rule1, rule2])
        assert not findings

    def test_empty_list(self):
        assert detect_overlapping_rules([]) == []


# ---------------------------------------------------------------------------
# get_firewall_rules: empty subscription_ids
# ---------------------------------------------------------------------------


class TestGetFirewallRules:
    def test_empty_subscription_ids_returns_empty(self):
        result = get_firewall_rules(subscription_ids=[], credential=None)
        assert result["firewalls"] == []
        assert result["rules"] == []
        assert result["count"] == 0

    def test_arg_failure_returns_empty(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=Exception("ARG down")):
            result = get_firewall_rules(["sub-1"], credential=None)
        assert result["firewalls"] == []
        assert result["rules"] == []
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# get_firewall_audit: no firewalls → empty findings + zero summary
# ---------------------------------------------------------------------------


class TestGetFirewallAudit:
    def test_empty_subscription_ids_returns_empty_findings(self):
        result = get_firewall_audit(subscription_ids=[], credential=None)
        assert result["findings"] == []
        assert result["summary"]["total"] == 0
        assert result["summary"]["critical"] == 0
        assert result["summary"]["high"] == 0
        assert result["summary"]["medium"] == 0
        assert "generated_at" in result

    def test_arg_returns_no_firewalls_produces_empty_findings(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", return_value=[]):
            result = get_firewall_audit(["sub-1"], credential=None)
        assert result["findings"] == []
        assert result["summary"]["total"] == 0

    def test_arg_failure_returns_empty(self):
        with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=Exception("timeout")):
            result = get_firewall_audit(["sub-1"], credential=None)
        assert result["findings"] == []
        assert result["summary"]["total"] == 0
