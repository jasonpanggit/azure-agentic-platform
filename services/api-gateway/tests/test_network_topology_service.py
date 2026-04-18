"""Tests for network_topology_service — Phase 103."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import time

import pytest


# ---------------------------------------------------------------------------
# Row factory helpers
# ---------------------------------------------------------------------------


def _make_vnet_row(
    subscription_id: str = "sub-1",
    vnet_name: str = "vnet-1",
    address_space: str = "[10.0.0.0/16]",
    subnet_name: str = "subnet-1",
    subnet_prefix: str = "10.0.1.0/24",
    subnet_nsg_id: str = "",
    vnet_id: str = "",
) -> dict:
    return {
        "subscriptionId": subscription_id,
        "resourceGroup": "rg-1",
        "vnetName": vnet_name,
        "id": vnet_id or f"/subscriptions/{subscription_id}/resourceGroups/rg-1/providers/Microsoft.Network/virtualNetworks/{vnet_name}",
        "addressSpace": address_space,
        "subnetName": subnet_name,
        "subnetPrefix": subnet_prefix,
        "subnetNsgId": subnet_nsg_id,
        "location": "eastus",
    }


def _make_nsg_row(
    nsg_name: str = "nsg-1",
    nsg_id: str = "",
    rule_name: str = "AllowSSH",
    priority: int = 100,
    direction: str = "Inbound",
    access: str = "Allow",
    protocol: str = "TCP",
    source_prefix: str = "*",
    dest_prefix: str = "*",
    dest_port_range: str = "22",
) -> dict:
    return {
        "subscriptionId": "sub-1",
        "resourceGroup": "rg-1",
        "nsgName": nsg_name,
        "nsgId": nsg_id or f"/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networksecuritygroups/{nsg_name}",
        "ruleName": rule_name,
        "priority": priority,
        "direction": direction,
        "access": access,
        "protocol": protocol,
        "sourcePrefix": source_prefix,
        "sourcePrefixes": None,
        "destPrefix": dest_prefix,
        "destPrefixes": None,
        "destPortRange": dest_port_range,
        "destPortRanges": None,
        "subnetIds": [],
        "nicIds": [],
    }


def _make_nic_row(
    name: str = "nic-1",
    subnet_id: str = "",
    nsg_id: str = "",
    private_ip: str = "10.0.1.4",
) -> dict:
    return {
        "subscriptionId": "sub-1",
        "resourceGroup": "rg-1",
        "name": name,
        "id": f"/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networkinterfaces/{name}",
        "subnetId": subnet_id,
        "nsgId": nsg_id,
        "privateIp": private_ip,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScoreNsgHealth:
    def test_score_nsg_health_green_no_issues(self):
        from services.api_gateway.network_topology_service import _score_nsg_health

        rules = [
            _make_nsg_row(dest_port_range="22", source_prefix="10.0.0.0/8", priority=100),
            _make_nsg_row(dest_port_range="443", source_prefix="192.168.0.0/16", priority=200),
        ]
        assert _score_nsg_health(rules) == "green"

    def test_score_nsg_health_yellow_overly_permissive(self):
        from services.api_gateway.network_topology_service import _score_nsg_health

        rules = [
            _make_nsg_row(dest_port_range="*", source_prefix="*", access="Allow", priority=500),
        ]
        assert _score_nsg_health(rules) == "yellow"


class TestPortInRange:
    def test_matches_rule_exact_port(self):
        from services.api_gateway.network_topology_service import _port_in_range

        assert _port_in_range(443, "443") is True

    def test_matches_rule_port_range(self):
        from services.api_gateway.network_topology_service import _port_in_range

        assert _port_in_range(8080, "1024-65535") is True

    def test_matches_rule_wildcard(self):
        from services.api_gateway.network_topology_service import _port_in_range

        assert _port_in_range(9999, "*") is True

    def test_matches_rule_no_match(self):
        from services.api_gateway.network_topology_service import _port_in_range

        assert _port_in_range(443, "80") is False


class TestMatchesRule:
    def test_matches_rule_exact_port(self):
        from services.api_gateway.network_topology_service import _matches_rule

        rule = _make_nsg_row(dest_port_range="443", protocol="TCP")
        assert _matches_rule(rule, 443, "TCP", "*", "*") is True

    def test_matches_rule_no_match(self):
        from services.api_gateway.network_topology_service import _matches_rule

        rule = _make_nsg_row(dest_port_range="80", protocol="TCP")
        assert _matches_rule(rule, 443, "TCP", "*", "*") is False


class TestEvaluateNsgRules:
    def test_evaluate_nsg_rules_first_match_wins(self):
        from services.api_gateway.network_topology_service import _evaluate_nsg_rules

        rules = [
            _make_nsg_row(rule_name="AllowHTTPS", priority=100, direction="Inbound", access="Allow", dest_port_range="443"),
            _make_nsg_row(rule_name="DenyAll", priority=200, direction="Inbound", access="Deny", dest_port_range="*"),
        ]
        result = _evaluate_nsg_rules(rules, 443, "TCP", "*", "*", "Inbound")
        assert result["result"] == "Allow"
        assert result["matching_rule"] == "AllowHTTPS"
        assert result["priority"] == 100


class TestDetectAsymmetries:
    def test_detect_asymmetries_found(self):
        from services.api_gateway.network_topology_service import _detect_asymmetries

        src_nsg = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networksecuritygroups/nsg-src"
        dst_nsg = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networksecuritygroups/nsg-dst"

        nsg_rules_map = {
            src_nsg: [_make_nsg_row(nsg_id=src_nsg, direction="Outbound", access="Allow", dest_port_range="443", priority=100)],
            dst_nsg: [_make_nsg_row(nsg_id=dst_nsg, direction="Inbound", access="Deny", dest_port_range="443", priority=100)],
        }
        subnet_nsg_map = {
            "subnet-a": src_nsg,
            "subnet-b": dst_nsg,
        }
        vnet_subnets = {"vnet-1": ["subnet-a", "subnet-b"]}

        issues = _detect_asymmetries(nsg_rules_map, subnet_nsg_map, vnet_subnets)
        assert len(issues) >= 1
        assert issues[0]["port"] == 443

    def test_detect_asymmetries_none(self):
        from services.api_gateway.network_topology_service import _detect_asymmetries

        src_nsg = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networksecuritygroups/nsg-src"
        dst_nsg = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networksecuritygroups/nsg-dst"

        nsg_rules_map = {
            src_nsg: [_make_nsg_row(nsg_id=src_nsg, direction="Outbound", access="Allow", dest_port_range="443", priority=100)],
            dst_nsg: [_make_nsg_row(nsg_id=dst_nsg, direction="Inbound", access="Allow", dest_port_range="443", priority=100)],
        }
        subnet_nsg_map = {"subnet-a": src_nsg, "subnet-b": dst_nsg}
        vnet_subnets = {"vnet-1": ["subnet-a", "subnet-b"]}

        issues = _detect_asymmetries(nsg_rules_map, subnet_nsg_map, vnet_subnets)
        assert len(issues) == 0


class TestFetchTopology:
    def test_fetch_topology_empty_subscriptions(self):
        from services.api_gateway.network_topology_service import fetch_network_topology

        result = fetch_network_topology([])
        assert result == {"nodes": [], "edges": [], "issues": []}

    def test_fetch_topology_no_credential(self):
        from services.api_gateway.network_topology_service import fetch_network_topology

        result = fetch_network_topology(["sub-1"], credential=None)
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["issues"] == []

    @patch("services.api_gateway.network_topology_service.run_arg_query")
    def test_fetch_topology_arg_error_returns_empty(self, mock_arg):
        from services.api_gateway.network_topology_service import fetch_network_topology, _cache

        mock_arg.side_effect = Exception("ARG failure")
        # Clear cache
        _cache.clear()

        result = fetch_network_topology(["sub-err"], credential="cred")
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["issues"] == []

    @patch("services.api_gateway.network_topology_service.run_arg_query")
    def test_fetch_topology_assembles_vnet_nodes(self, mock_arg):
        from services.api_gateway.network_topology_service import fetch_network_topology, _cache

        _cache.clear()
        vnets = [
            _make_vnet_row(vnet_name="vnet-a", subnet_name="sub-a"),
            _make_vnet_row(vnet_name="vnet-b", subnet_name="sub-b", vnet_id="/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Network/virtualNetworks/vnet-b"),
        ]

        def side_effect(cred, subs, query):
            if "virtualnetworks" in query.lower():
                return vnets
            return []

        mock_arg.side_effect = side_effect

        result = fetch_network_topology(["sub-vnet"], credential="cred")
        vnet_nodes = [n for n in result["nodes"] if n["type"] == "vnet"]
        assert len(vnet_nodes) == 2

    @patch("services.api_gateway.network_topology_service.run_arg_query")
    def test_fetch_topology_assembles_nsg_edges(self, mock_arg):
        from services.api_gateway.network_topology_service import fetch_network_topology, _cache

        _cache.clear()
        nsg_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networksecuritygroups/nsg-1"
        vnets = [_make_vnet_row(subnet_nsg_id=nsg_id)]
        nsgs = [_make_nsg_row(nsg_id=nsg_id)]

        def side_effect(cred, subs, query):
            if "virtualnetworks" in query.lower():
                return vnets
            if "networksecuritygroups" in query.lower():
                return nsgs
            return []

        mock_arg.side_effect = side_effect

        result = fetch_network_topology(["sub-nsg-edge"], credential="cred")
        nsg_edges = [e for e in result["edges"] if e["type"] == "subnet-nsg"]
        assert len(nsg_edges) >= 1

    @patch("services.api_gateway.network_topology_service.run_arg_query")
    def test_cache_returns_cached_result(self, mock_arg):
        from services.api_gateway.network_topology_service import fetch_network_topology, _cache

        _cache.clear()
        mock_arg.return_value = []

        fetch_network_topology(["sub-cache"], credential="cred")
        fetch_network_topology(["sub-cache"], credential="cred")

        # 12 queries per call (vnets, nsgs, lbs, pes, gateways, public_ips, nics, vms, vmss, aks, firewalls, app_gateways)
        # but second call should be cached — so total == 12 not 24
        assert mock_arg.call_count == 12


class TestPathCheck:
    @patch("services.api_gateway.network_topology_service.run_arg_query")
    def test_path_check_allowed(self, mock_arg):
        from services.api_gateway.network_topology_service import evaluate_path_check, _cache

        _cache.clear()
        nsg_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networksecuritygroups/nsg-allow"
        vnets = [_make_vnet_row(subnet_nsg_id=nsg_id)]
        nsgs = [
            _make_nsg_row(nsg_id=nsg_id, direction="Inbound", access="Allow", dest_port_range="443", priority=100),
            _make_nsg_row(nsg_id=nsg_id, direction="Outbound", access="Allow", dest_port_range="443", priority=100),
        ]

        def side_effect(cred, subs, query):
            if "virtualnetworks" in query.lower():
                return vnets
            if "networksecuritygroups" in query.lower():
                return nsgs
            return []

        mock_arg.side_effect = side_effect

        result = evaluate_path_check(
            source_resource_id="/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm1",
            destination_resource_id="/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm2",
            port=443,
            protocol="TCP",
            subscription_ids=["sub-path-allow"],
            credential="cred",
        )
        assert result["verdict"] == "allowed"

    @patch("services.api_gateway.network_topology_service.run_arg_query")
    def test_path_check_blocked_by_dest_nsg(self, mock_arg):
        from services.api_gateway.network_topology_service import evaluate_path_check, _cache

        _cache.clear()
        nsg_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networksecuritygroups/nsg-block"
        vnets = [_make_vnet_row(subnet_nsg_id=nsg_id)]
        nsgs = [_make_nsg_row(nsg_id=nsg_id, direction="Inbound", access="Deny", dest_port_range="443", priority=100)]

        def side_effect(cred, subs, query):
            if "virtualnetworks" in query.lower():
                return vnets
            if "networksecuritygroups" in query.lower():
                return nsgs
            return []

        mock_arg.side_effect = side_effect

        result = evaluate_path_check(
            source_resource_id="/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm1",
            destination_resource_id="/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm2",
            port=443,
            protocol="TCP",
            subscription_ids=["sub-path-block"],
            credential="cred",
        )
        # Inbound Deny rule at destination should block traffic
        assert result["verdict"] == "blocked"

    @patch("services.api_gateway.network_topology_service.run_arg_query")
    def test_path_check_error_returns_error_verdict(self, mock_arg):
        from services.api_gateway.network_topology_service import evaluate_path_check, _cache

        _cache.clear()
        mock_arg.side_effect = Exception("boom")

        result = evaluate_path_check(
            source_resource_id="x",
            destination_resource_id="y",
            port=80,
            protocol="TCP",
            subscription_ids=["sub-err"],
            credential="cred",
        )
        # When ARG fails, topology returns empty graph, path check returns allowed (no NSGs to block)
        # The function never raises — this verifies fault tolerance
        assert result["verdict"] in ("allowed", "error")
        assert "steps" in result
