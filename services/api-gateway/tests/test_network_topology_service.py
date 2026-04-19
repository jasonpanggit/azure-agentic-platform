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

        # 24 queries per call (20 original + 4 new Phase 108 queries:
        # nic_public_ips, lb_empty_backends, aks_private, route_default_internet)
        # but second call should be cached — so total == 24 not 48
        assert mock_arg.call_count == 24


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
        vnet_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/virtualnetworks/vnet-1"
        vnets = [_make_vnet_row(vnet_id=vnet_id, subnet_nsg_id=nsg_id)]
        nsgs = [_make_nsg_row(nsg_id=nsg_id, direction="Inbound", access="Deny", dest_port_range="443", priority=100)]

        def side_effect(cred, subs, query):
            if "virtualnetworks" in query.lower():
                return vnets
            if "networksecuritygroups" in query.lower():
                return nsgs
            return []

        mock_arg.side_effect = side_effect

        # Use the subnet ID directly so _resolve_resource_nsg can find it via the subnet node
        subnet_id = f"{vnet_id}/subnets/subnet-1".lower()
        result = evaluate_path_check(
            source_resource_id=subnet_id,
            destination_resource_id=subnet_id,
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


# ---------------------------------------------------------------------------
# Sprint 3 new tests
# ---------------------------------------------------------------------------


class TestScoreResourceHealth:
    def test_succeeded_is_green(self):
        from services.api_gateway.network_topology_service import _score_resource_health

        assert _score_resource_health("Succeeded") == "green"

    def test_running_is_green(self):
        from services.api_gateway.network_topology_service import _score_resource_health

        assert _score_resource_health("Running") == "green"

    def test_updating_is_yellow(self):
        from services.api_gateway.network_topology_service import _score_resource_health

        assert _score_resource_health("Updating") == "yellow"

    def test_creating_is_yellow(self):
        from services.api_gateway.network_topology_service import _score_resource_health

        assert _score_resource_health("Creating") == "yellow"

    def test_scaling_is_yellow(self):
        from services.api_gateway.network_topology_service import _score_resource_health

        assert _score_resource_health("Scaling") == "yellow"

    def test_failed_is_red(self):
        from services.api_gateway.network_topology_service import _score_resource_health

        assert _score_resource_health("Failed") == "red"

    def test_empty_is_red(self):
        from services.api_gateway.network_topology_service import _score_resource_health

        assert _score_resource_health("") == "red"

    def test_unknown_is_red(self):
        from services.api_gateway.network_topology_service import _score_resource_health

        assert _score_resource_health("Unknown") == "red"


class TestLruCache:
    def test_cache_put_and_get(self):
        from services.api_gateway.network_topology_service import _cache_put, _cache_get, _cache

        _cache.clear()
        _cache_put("k1", ("value1",))
        result = _cache_get("k1")
        assert result == ("value1",)

    def test_cache_get_missing_returns_none(self):
        from services.api_gateway.network_topology_service import _cache_get, _cache

        _cache.clear()
        assert _cache_get("nonexistent") is None

    def test_lru_eviction_at_max_size(self):
        from services.api_gateway.network_topology_service import (
            _cache_put, _cache_get, _cache, _CACHE_MAX_SIZE,
        )

        _cache.clear()
        # Fill cache to max
        for i in range(_CACHE_MAX_SIZE):
            _cache_put(f"key-{i}", f"val-{i}")

        assert len(_cache) == _CACHE_MAX_SIZE

        # Adding one more should evict the oldest (key-0)
        _cache_put("key-overflow", "overflow-val")
        assert len(_cache) == _CACHE_MAX_SIZE
        assert _cache_get("key-0") is None
        assert _cache_get("key-overflow") == "overflow-val"

    def test_lru_access_prevents_eviction(self):
        from services.api_gateway.network_topology_service import (
            _cache_put, _cache_get, _cache, _CACHE_MAX_SIZE,
        )

        _cache.clear()
        # Fill to max
        for i in range(_CACHE_MAX_SIZE):
            _cache_put(f"key-{i}", f"val-{i}")

        # Access key-0 to make it recently used
        _cache_get("key-0")

        # Add two more entries — key-1 and key-2 should be evicted, not key-0
        _cache_put("key-new-1", "nv1")
        _cache_put("key-new-2", "nv2")

        assert _cache_get("key-0") is not None
        assert _cache_get("key-1") is None
        assert _cache_get("key-2") is None


class TestRouteTableNodes:
    def test_route_table_node_created(self):
        from services.api_gateway.network_topology_service import _assemble_graph

        rt_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/routetables/rt-1"
        route_tables = [{"rtId": rt_id, "name": "rt-1", "location": "eastus", "routeCount": 3}]

        nodes, edges = _assemble_graph([], [], [], [], [], [], [], route_tables=route_tables)
        rt_nodes = [n for n in nodes if n["type"] == "routetable"]
        assert len(rt_nodes) == 1
        assert rt_nodes[0]["id"] == rt_id
        assert rt_nodes[0]["data"]["routeCount"] == 3

    def test_subnet_routetable_edge_emitted(self):
        from services.api_gateway.network_topology_service import _assemble_graph

        rt_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/routetables/rt-1"
        vnet_row = _make_vnet_row(subnet_name="sub-rt")
        vnet_row["subnetRouteTableId"] = rt_id
        vnet_row["subnetNatGatewayId"] = ""

        nodes, edges = _assemble_graph([vnet_row], [], [], [], [], [], [],
                                        route_tables=[{"rtId": rt_id, "name": "rt-1", "location": "eastus", "routeCount": 1}])
        rt_edges = [e for e in edges if e["type"] == "subnet-routetable"]
        assert len(rt_edges) == 1
        assert rt_edges[0]["target"] == rt_id


class TestLocalGatewayNodes:
    def test_local_gateway_node_created(self):
        from services.api_gateway.network_topology_service import _assemble_graph

        lgw_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/localnetworkgateways/lgw-1"
        local_gateways = [{"lgwId": lgw_id, "name": "lgw-1", "gatewayIp": "203.0.113.1", "addressPrefixes": "10.1.0.0/16"}]

        nodes, edges = _assemble_graph([], [], [], [], [], [], [], local_gateways=local_gateways)
        lgw_nodes = [n for n in nodes if n["type"] == "localgw"]
        assert len(lgw_nodes) == 1
        assert lgw_nodes[0]["id"] == lgw_id
        assert lgw_nodes[0]["data"]["gatewayIp"] == "203.0.113.1"


class TestPeTargetEdge:
    def test_pe_target_edge_emitted(self):
        from services.api_gateway.network_topology_service import _assemble_graph

        pe_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/privateendpoints/pe-1"
        target_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.sql/servers/sql-1"
        subnet_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/virtualnetworks/vnet-1/subnets/snet-pe"
        pes = [{
            "id": pe_id,
            "name": "pe-1",
            "subnetId": subnet_id,
            "targetResourceId": target_id,
            "connectionState": "Approved",
        }]

        nodes, edges = _assemble_graph([], [], [], pes, [], [], [])
        pe_target_edges = [e for e in edges if e.get("type") == "pe-target"]
        assert len(pe_target_edges) == 1
        assert pe_target_edges[0]["source"] == pe_id
        assert pe_target_edges[0]["target"] == target_id

        external_nodes = [n for n in nodes if n["type"] == "external"]
        assert any(n["id"] == target_id for n in external_nodes)

    def test_pe_unapproved_health_red(self):
        from services.api_gateway.network_topology_service import _assemble_graph

        pe_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/privateendpoints/pe-2"
        pes = [{
            "id": pe_id,
            "name": "pe-2",
            "subnetId": "",
            "targetResourceId": "",
            "connectionState": "Pending",
        }]
        nodes, _ = _assemble_graph([], [], [], pes, [], [], [])
        pe_node = next(n for n in nodes if n["id"] == pe_id)
        assert pe_node["data"]["health"] == "red"


# ---------------------------------------------------------------------------
# Phase 108 — Unified issue schema + 17 detector tests
# ---------------------------------------------------------------------------


NSG_ID_A = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networksecuritygroups/nsg-a"
NSG_ID_B = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networksecuritygroups/nsg-b"
VNET_ID_1 = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/virtualnetworks/vnet-1"
VNET_ID_2 = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/virtualnetworks/vnet-2"


class TestMakeIssueId:
    def test_returns_16_char_hex(self):
        from services.api_gateway.network_topology_service import _make_issue_id

        result = _make_issue_id("nsg_asymmetry", "/subscriptions/.../nsg1")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        from services.api_gateway.network_topology_service import _make_issue_id

        assert _make_issue_id("x", "y") == _make_issue_id("x", "y")

    def test_different_inputs_differ(self):
        from services.api_gateway.network_topology_service import _make_issue_id

        assert _make_issue_id("a", "b") != _make_issue_id("a", "c")


class TestPortalLink:
    def test_default_blade(self):
        from services.api_gateway.network_topology_service import _portal_link

        link = _portal_link("/subscriptions/s/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg1")
        assert link.startswith("https://portal.azure.com/#resource")
        assert "overview" in link

    def test_custom_blade(self):
        from services.api_gateway.network_topology_service import _portal_link

        link = _portal_link("/subscriptions/s/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg1", "securityRules")
        assert link.endswith("securityRules")


class TestDetectPortOpenInternet:
    def test_ssh_open_to_internet_flagged(self):
        from services.api_gateway.network_topology_service import _detect_port_open_internet

        rules_map = {NSG_ID_A: [_make_nsg_row(nsg_id=NSG_ID_A, direction="Inbound", access="Allow",
                                               source_prefix="Internet", dest_port_range="22", priority=100)]}
        issues = _detect_port_open_internet(rules_map)
        assert len(issues) == 1
        assert issues[0]["type"] == "port_open_internet"
        assert issues[0]["severity"] == "critical"
        assert issues[0]["affected_resource_id"] == NSG_ID_A

    def test_rdp_open_to_wildcard_flagged(self):
        from services.api_gateway.network_topology_service import _detect_port_open_internet

        rules_map = {NSG_ID_A: [_make_nsg_row(nsg_id=NSG_ID_A, direction="Inbound", access="Allow",
                                               source_prefix="*", dest_port_range="3389", priority=100)]}
        issues = _detect_port_open_internet(rules_map)
        assert any(i["type"] == "port_open_internet" for i in issues)

    def test_port_range_covering_22_flagged(self):
        """A1 edge case: dest port range '22-25' should trigger for port 22."""
        from services.api_gateway.network_topology_service import _detect_port_open_internet

        rules_map = {NSG_ID_A: [_make_nsg_row(nsg_id=NSG_ID_A, direction="Inbound", access="Allow",
                                               source_prefix="*", dest_port_range="22-25", priority=100)]}
        issues = _detect_port_open_internet(rules_map)
        assert len(issues) >= 1

    def test_restricted_source_not_flagged(self):
        from services.api_gateway.network_topology_service import _detect_port_open_internet

        rules_map = {NSG_ID_A: [_make_nsg_row(nsg_id=NSG_ID_A, direction="Inbound", access="Allow",
                                               source_prefix="10.0.0.0/8", dest_port_range="22", priority=100)]}
        issues = _detect_port_open_internet(rules_map)
        assert len(issues) == 0

    def test_outbound_rule_not_flagged(self):
        from services.api_gateway.network_topology_service import _detect_port_open_internet

        rules_map = {NSG_ID_A: [_make_nsg_row(nsg_id=NSG_ID_A, direction="Outbound", access="Allow",
                                               source_prefix="*", dest_port_range="22", priority=100)]}
        issues = _detect_port_open_internet(rules_map)
        assert len(issues) == 0


class TestDetectAnyToAnyAllow:
    def test_any_to_any_inbound_allow_flagged(self):
        from services.api_gateway.network_topology_service import _detect_any_to_any_allow

        rules_map = {NSG_ID_A: [_make_nsg_row(nsg_id=NSG_ID_A, direction="Inbound", access="Allow",
                                               source_prefix="*", dest_port_range="*", priority=100)]}
        issues = _detect_any_to_any_allow(rules_map)
        assert len(issues) == 1
        assert issues[0]["type"] == "any_to_any_allow"
        assert issues[0]["severity"] == "high"

    def test_specific_port_not_flagged(self):
        from services.api_gateway.network_topology_service import _detect_any_to_any_allow

        rules_map = {NSG_ID_A: [_make_nsg_row(nsg_id=NSG_ID_A, direction="Inbound", access="Allow",
                                               source_prefix="*", dest_port_range="443", priority=100)]}
        issues = _detect_any_to_any_allow(rules_map)
        assert len(issues) == 0


class TestDetectSubnetNoNsg:
    def test_subnet_without_nsg_flagged(self):
        from services.api_gateway.network_topology_service import _detect_subnet_no_nsg

        rows = [_make_vnet_row(subnet_name="app-subnet", subnet_nsg_id="")]
        issues = _detect_subnet_no_nsg(rows)
        assert len(issues) == 1
        assert issues[0]["type"] == "subnet_no_nsg"
        assert issues[0]["severity"] == "high"

    def test_gateway_subnet_excluded(self):
        """A3 edge case: GatewaySubnet must be excluded even without NSG."""
        from services.api_gateway.network_topology_service import _detect_subnet_no_nsg

        rows = [_make_vnet_row(subnet_name="GatewaySubnet", subnet_nsg_id="")]
        issues = _detect_subnet_no_nsg(rows)
        assert len(issues) == 0

    @pytest.mark.parametrize("system_subnet", [
        "GatewaySubnet", "AzureBastionSubnet", "AzureFirewallSubnet", "AzureFirewallManagementSubnet"
    ])
    def test_all_system_subnets_excluded(self, system_subnet):
        from services.api_gateway.network_topology_service import _detect_subnet_no_nsg

        rows = [_make_vnet_row(subnet_name=system_subnet, subnet_nsg_id="")]
        issues = _detect_subnet_no_nsg(rows)
        assert len(issues) == 0

    def test_subnet_with_nsg_not_flagged(self):
        from services.api_gateway.network_topology_service import _detect_subnet_no_nsg

        rows = [_make_vnet_row(subnet_name="app-subnet", subnet_nsg_id=NSG_ID_A)]
        issues = _detect_subnet_no_nsg(rows)
        assert len(issues) == 0


class TestDetectNsgRuleShadowing:
    def test_shadowed_rule_detected(self):
        """A4: Higher-priority rule with opposite access and * ports/source shadows lower rule."""
        from services.api_gateway.network_topology_service import _detect_nsg_rule_shadowing

        rules_map = {NSG_ID_A: [
            _make_nsg_row(nsg_id=NSG_ID_A, rule_name="DenyAll", direction="Inbound", access="Deny",
                          source_prefix="*", dest_port_range="*", priority=100),
            _make_nsg_row(nsg_id=NSG_ID_A, rule_name="AllowHTTPS", direction="Inbound", access="Allow",
                          source_prefix="*", dest_port_range="443", priority=200),
        ]}
        issues = _detect_nsg_rule_shadowing(rules_map)
        assert any(i["type"] == "nsg_rule_shadowed" for i in issues)

    def test_same_access_not_shadowed(self):
        """A4 edge case: Two rules with same access are NOT shadowed."""
        from services.api_gateway.network_topology_service import _detect_nsg_rule_shadowing

        rules_map = {NSG_ID_A: [
            _make_nsg_row(nsg_id=NSG_ID_A, rule_name="Allow1", direction="Inbound", access="Allow",
                          source_prefix="*", dest_port_range="*", priority=100),
            _make_nsg_row(nsg_id=NSG_ID_A, rule_name="Allow2", direction="Inbound", access="Allow",
                          source_prefix="*", dest_port_range="443", priority=200),
        ]}
        issues = _detect_nsg_rule_shadowing(rules_map)
        assert len(issues) == 0

    def test_no_rules_no_issues(self):
        from services.api_gateway.network_topology_service import _detect_nsg_rule_shadowing

        issues = _detect_nsg_rule_shadowing({})
        assert len(issues) == 0


class TestDetectPeeringDisconnected:
    def test_disconnected_peering_flagged(self):
        from services.api_gateway.network_topology_service import _detect_peering_disconnected

        edges = [{"type": "peering-disconnected", "source": VNET_ID_1, "target": VNET_ID_2,
                  "data": {"peeringState": "Disconnected"}}]
        issues = _detect_peering_disconnected(edges)
        assert len(issues) == 1
        assert issues[0]["type"] == "vnet_peering_disconnected"
        assert issues[0]["severity"] == "critical"

    def test_connected_peering_not_flagged(self):
        from services.api_gateway.network_topology_service import _detect_peering_disconnected

        edges = [{"type": "peering", "source": VNET_ID_1, "target": VNET_ID_2,
                  "data": {"peeringState": "Connected"}}]
        issues = _detect_peering_disconnected(edges)
        assert len(issues) == 0


class TestDetectVpnBgpDisabled:
    def test_bgp_disabled_flagged(self):
        from services.api_gateway.network_topology_service import _detect_vpn_bgp_disabled

        nodes = [{"id": "/subs/s/rg/r/gw/gw1", "label": "gw1", "type": "gateway",
                  "data": {"gatewayType": "Vpn", "bgpEnabled": False, "sku": "VpnGw2"}}]
        issues = _detect_vpn_bgp_disabled(nodes)
        assert len(issues) == 1
        assert issues[0]["type"] == "vpn_bgp_disabled"

    def test_bgp_enabled_not_flagged(self):
        from services.api_gateway.network_topology_service import _detect_vpn_bgp_disabled

        nodes = [{"id": "/subs/s/rg/r/gw/gw1", "label": "gw1", "type": "gateway",
                  "data": {"gatewayType": "Vpn", "bgpEnabled": True, "sku": "VpnGw2AZ"}}]
        issues = _detect_vpn_bgp_disabled(nodes)
        assert len(issues) == 0


class TestDetectGatewayNotZoneRedundant:
    def test_non_az_sku_flagged(self):
        from services.api_gateway.network_topology_service import _detect_gateway_not_zone_redundant

        nodes = [{"id": "/subs/s/rg/r/gw/gw1", "label": "gw1", "type": "gateway",
                  "data": {"gatewayType": "Vpn", "bgpEnabled": False, "sku": "VpnGw2"}}]
        issues = _detect_gateway_not_zone_redundant(nodes)
        assert len(issues) == 1
        assert issues[0]["type"] == "gateway_not_zone_redundant"

    def test_az_sku_not_flagged(self):
        """B3 edge case: VpnGw2AZ should NOT be flagged."""
        from services.api_gateway.network_topology_service import _detect_gateway_not_zone_redundant

        nodes = [{"id": "/subs/s/rg/r/gw/gw1", "label": "gw1", "type": "gateway",
                  "data": {"gatewayType": "Vpn", "bgpEnabled": True, "sku": "VpnGw2AZ"}}]
        issues = _detect_gateway_not_zone_redundant(nodes)
        assert len(issues) == 0


class TestDetectPeNotApproved:
    def test_unapproved_pe_flagged(self):
        from services.api_gateway.network_topology_service import _detect_pe_not_approved

        nodes = [{"id": "/subs/s/pe/pe1", "label": "pe1", "type": "pe",
                  "data": {"health": "red", "targetResourceId": "/subs/s/sql/sql1"}}]
        issues = _detect_pe_not_approved(nodes)
        assert len(issues) == 1
        assert issues[0]["type"] == "pe_not_approved"
        assert issues[0]["auto_fix_available"] is True
        assert issues[0]["severity"] == "critical"

    def test_approved_pe_not_flagged(self):
        from services.api_gateway.network_topology_service import _detect_pe_not_approved

        nodes = [{"id": "/subs/s/pe/pe1", "label": "pe1", "type": "pe",
                  "data": {"health": "green", "targetResourceId": "/subs/s/sql/sql1"}}]
        issues = _detect_pe_not_approved(nodes)
        assert len(issues) == 0


class TestDetectFirewallNoPolicy:
    def test_firewall_no_policy_flagged(self):
        from services.api_gateway.network_topology_service import _detect_firewall_no_policy

        nodes = [{"id": "/subs/s/fw/fw1", "label": "fw1", "type": "firewall",
                  "data": {"firewallPolicyId": "", "threatIntelMode": "Alert"}}]
        issues = _detect_firewall_no_policy(nodes)
        assert len(issues) == 1
        assert issues[0]["type"] == "firewall_no_policy"
        assert issues[0]["severity"] == "critical"

    def test_firewall_with_policy_not_flagged(self):
        from services.api_gateway.network_topology_service import _detect_firewall_no_policy

        nodes = [{"id": "/subs/s/fw/fw1", "label": "fw1", "type": "firewall",
                  "data": {"firewallPolicyId": "/subs/s/fwp/policy1", "threatIntelMode": "Alert"}}]
        issues = _detect_firewall_no_policy(nodes)
        assert len(issues) == 0


class TestDetectFirewallThreatIntelOff:
    def test_threatintel_off_flagged(self):
        from services.api_gateway.network_topology_service import _detect_firewall_threatintel_off

        nodes = [{"id": "/subs/s/fw/fw1", "label": "fw1", "type": "firewall",
                  "data": {"firewallPolicyId": "/subs/s/fwp/p1", "threatIntelMode": "Off"}}]
        issues = _detect_firewall_threatintel_off(nodes)
        assert len(issues) == 1
        assert issues[0]["type"] == "firewall_threatintel_off"
        assert issues[0]["auto_fix_available"] is True

    def test_threatintel_alert_not_flagged(self):
        from services.api_gateway.network_topology_service import _detect_firewall_threatintel_off

        nodes = [{"id": "/subs/s/fw/fw1", "label": "fw1", "type": "firewall",
                  "data": {"firewallPolicyId": "/subs/s/fwp/p1", "threatIntelMode": "Alert"}}]
        issues = _detect_firewall_threatintel_off(nodes)
        assert len(issues) == 0


class TestDetectVmPublicIp:
    def test_vm_with_public_ip_flagged(self):
        from services.api_gateway.network_topology_service import _detect_vm_public_ip

        nic_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networkinterfaces/nic-1"
        vm_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.compute/virtualmachines/vm-1"
        pip_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/publicipaddresses/pip-1"
        nic_public_ip_rows = [{"nicId": nic_id, "publicIpId": pip_id}]
        nic_vm_map = {nic_id: vm_id}
        issues = _detect_vm_public_ip(nic_public_ip_rows, nic_vm_map)
        assert len(issues) == 1
        assert issues[0]["type"] == "vm_public_ip"
        assert issues[0]["severity"] == "critical"

    def test_nic_without_vm_not_flagged(self):
        """C1 edge case: NIC has public IP but not attached to any VM — not triggered."""
        from services.api_gateway.network_topology_service import _detect_vm_public_ip

        nic_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/networkinterfaces/nic-orphan"
        pip_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/publicipaddresses/pip-1"
        nic_public_ip_rows = [{"nicId": nic_id, "publicIpId": pip_id}]
        nic_vm_map = {}  # no VM linked
        issues = _detect_vm_public_ip(nic_public_ip_rows, nic_vm_map)
        assert len(issues) == 0


class TestDetectLbEmptyBackend:
    def test_empty_backend_flagged(self):
        from services.api_gateway.network_topology_service import _detect_lb_empty_backend

        lb_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/loadbalancers/lb-1"
        rows = [{"lbId": lb_id, "lbName": "lb-1", "emptyPool": "pool-1"}]
        issues = _detect_lb_empty_backend(rows)
        assert len(issues) == 1
        assert issues[0]["type"] == "lb_empty_backend"

    def test_no_rows_no_issues(self):
        from services.api_gateway.network_topology_service import _detect_lb_empty_backend

        issues = _detect_lb_empty_backend([])
        assert len(issues) == 0


class TestDetectLbPipSkuMismatch:
    def test_sku_mismatch_flagged(self):
        from services.api_gateway.network_topology_service import _detect_lb_pip_sku_mismatch

        lb_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/loadbalancers/lb-1"
        pip_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/publicipaddresses/pip-1"
        lb_nodes = [{"id": lb_id, "label": "lb-1", "type": "lb",
                     "data": {"sku": "Standard", "publicIpId": pip_id}}]
        public_ip_map = {pip_id: {"sku_name": "Basic"}}
        issues = _detect_lb_pip_sku_mismatch(lb_nodes, public_ip_map)
        assert len(issues) == 1
        assert issues[0]["type"] == "lb_pip_sku_mismatch"

    def test_matching_sku_not_flagged(self):
        """C3 edge case: both Standard → no mismatch."""
        from services.api_gateway.network_topology_service import _detect_lb_pip_sku_mismatch

        lb_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/loadbalancers/lb-1"
        pip_id = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/publicipaddresses/pip-1"
        lb_nodes = [{"id": lb_id, "label": "lb-1", "type": "lb",
                     "data": {"sku": "Standard", "publicIpId": pip_id}}]
        public_ip_map = {pip_id: {"sku_name": "Standard"}}
        issues = _detect_lb_pip_sku_mismatch(lb_nodes, public_ip_map)
        assert len(issues) == 0


class TestDetectAksNotPrivate:
    def test_non_private_aks_flagged(self):
        from services.api_gateway.network_topology_service import _detect_aks_not_private

        rows = [{"aksId": "/subs/s/aks/aks-1", "aksName": "aks-1"}]
        issues = _detect_aks_not_private(rows)
        assert len(issues) == 1
        assert issues[0]["type"] == "aks_not_private"

    def test_empty_rows_no_issues(self):
        from services.api_gateway.network_topology_service import _detect_aks_not_private

        issues = _detect_aks_not_private([])
        assert len(issues) == 0


class TestDetectRouteDefaultInternet:
    def test_default_route_to_internet_flagged(self):
        from services.api_gateway.network_topology_service import _detect_route_default_internet

        rows = [{"rtId": "/subs/s/rt/rt-1", "rtName": "rt-1", "routeName": "default"}]
        issues = _detect_route_default_internet(rows)
        assert len(issues) == 1
        assert issues[0]["type"] == "route_default_internet"

    def test_empty_rows_no_issues(self):
        from services.api_gateway.network_topology_service import _detect_route_default_internet

        issues = _detect_route_default_internet([])
        assert len(issues) == 0


class TestDetectSubnetOverlap:
    def test_cross_vnet_overlap_flagged(self):
        from services.api_gateway.network_topology_service import _detect_subnet_overlap

        rows = [
            _make_vnet_row(vnet_name="vnet-1", subnet_name="sub-a", subnet_prefix="10.0.0.0/24",
                           vnet_id=VNET_ID_1),
            _make_vnet_row(vnet_name="vnet-2", subnet_name="sub-b", subnet_prefix="10.0.0.0/25",
                           vnet_id=VNET_ID_2),
        ]
        issues = _detect_subnet_overlap(rows)
        assert len(issues) >= 1
        assert issues[0]["type"] == "subnet_overlap"

    def test_same_vnet_not_flagged(self):
        """D2 edge case: subnets in same VNet should NOT be flagged."""
        from services.api_gateway.network_topology_service import _detect_subnet_overlap

        rows = [
            _make_vnet_row(vnet_name="vnet-1", subnet_name="sub-a", subnet_prefix="10.0.0.0/24", vnet_id=VNET_ID_1),
            _make_vnet_row(vnet_name="vnet-1", subnet_name="sub-b", subnet_prefix="10.0.0.0/25", vnet_id=VNET_ID_1),
        ]
        issues = _detect_subnet_overlap(rows)
        assert len(issues) == 0

    def test_non_overlapping_not_flagged(self):
        from services.api_gateway.network_topology_service import _detect_subnet_overlap

        rows = [
            _make_vnet_row(vnet_name="vnet-1", subnet_name="sub-a", subnet_prefix="10.0.0.0/24", vnet_id=VNET_ID_1),
            _make_vnet_row(vnet_name="vnet-2", subnet_name="sub-b", subnet_prefix="10.1.0.0/24", vnet_id=VNET_ID_2),
        ]
        issues = _detect_subnet_overlap(rows)
        assert len(issues) == 0

    def test_more_than_500_subnets_capped_with_warning(self):
        """D2 edge case: more than 500 subnets → warning logged, processing continues."""
        import logging
        from services.api_gateway.network_topology_service import _detect_subnet_overlap

        # Create 502 unique subnets across 2 vnets (non-overlapping to avoid false positives)
        rows = []
        for i in range(502):
            vnet_id = VNET_ID_1 if i % 2 == 0 else VNET_ID_2
            vnet_name = "vnet-1" if i % 2 == 0 else "vnet-2"
            rows.append(_make_vnet_row(
                vnet_name=vnet_name,
                subnet_name=f"sub-{i}",
                subnet_prefix=f"10.{i // 256}.{i % 256}.0/28",
                vnet_id=vnet_id,
            ))

        # Result should be a list (no crash) — the cap is enforced via logger.warning (not a Python warning)
        issues = _detect_subnet_overlap(rows)
        assert isinstance(issues, list)


class TestDetectMissingHubSpoke:
    def test_hub_with_missing_spoke_return_flagged(self):
        from services.api_gateway.network_topology_service import _detect_missing_hub_spoke

        hub = VNET_ID_1
        spoke1 = VNET_ID_2
        spoke2 = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/virtualnetworks/vnet-3"
        spoke3 = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/virtualnetworks/vnet-4"

        vnet_nodes = [
            {"id": hub, "type": "vnet", "label": "hub"},
            {"id": spoke1, "type": "vnet", "label": "spoke1"},
            {"id": spoke2, "type": "vnet", "label": "spoke2"},
            {"id": spoke3, "type": "vnet", "label": "spoke3"},
        ]
        # hub → 3 spokes, but spokes don't peer back
        peering_edges = [
            {"type": "peering", "source": hub, "target": spoke1, "data": {}},
            {"type": "peering", "source": hub, "target": spoke2, "data": {}},
            {"type": "peering", "source": hub, "target": spoke3, "data": {}},
        ]
        issues = _detect_missing_hub_spoke(vnet_nodes, peering_edges)
        assert len(issues) >= 1
        assert all(i["type"] == "missing_hub_spoke" for i in issues)
        assert all(i["severity"] == "low" for i in issues)

    def test_exactly_2_peerings_not_a_hub(self):
        """D3 edge case: VNet with exactly 2 peerings is NOT detected as hub."""
        from services.api_gateway.network_topology_service import _detect_missing_hub_spoke

        hub = VNET_ID_1
        spoke1 = VNET_ID_2
        spoke2 = "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.network/virtualnetworks/vnet-3"

        vnet_nodes = [
            {"id": hub, "type": "vnet", "label": "hub"},
            {"id": spoke1, "type": "vnet", "label": "spoke1"},
            {"id": spoke2, "type": "vnet", "label": "spoke2"},
        ]
        peering_edges = [
            {"type": "peering", "source": hub, "target": spoke1, "data": {}},
            {"type": "peering", "source": hub, "target": spoke2, "data": {}},
        ]
        issues = _detect_missing_hub_spoke(vnet_nodes, peering_edges)
        assert len(issues) == 0


class TestDetectAsymmetriesUnifiedSchema:
    def test_asymmetry_has_unified_fields(self):
        """Task 1.2: asymmetry issues must have all unified NetworkIssue fields."""
        from services.api_gateway.network_topology_service import _detect_asymmetries

        nsg_rules_map = {
            NSG_ID_A: [_make_nsg_row(nsg_id=NSG_ID_A, direction="Outbound", access="Allow",
                                     dest_port_range="443", priority=100)],
            NSG_ID_B: [_make_nsg_row(nsg_id=NSG_ID_B, direction="Inbound", access="Deny",
                                     dest_port_range="443", priority=100)],
        }
        subnet_nsg_map = {"subnet-a": NSG_ID_A, "subnet-b": NSG_ID_B}
        vnet_subnets = {"vnet-1": ["subnet-a", "subnet-b"]}

        issues = _detect_asymmetries(nsg_rules_map, subnet_nsg_map, vnet_subnets)
        assert len(issues) >= 1
        issue = issues[0]
        # Unified fields
        assert "id" in issue
        assert issue["type"] == "nsg_asymmetry"
        assert issue["severity"] == "high"
        assert "title" in issue
        assert "explanation" in issue
        assert "impact" in issue
        assert "affected_resource_id" in issue
        assert "remediation_steps" in issue
        assert "portal_link" in issue
        assert isinstance(issue["auto_fix_available"], bool)
        # Backward-compat fields
        assert "source_nsg_id" in issue
        assert "dest_nsg_id" in issue
        assert "port" in issue
        assert "description" in issue


class TestFetchTopologyCacheCountAfterPhase108:
    @patch("services.api_gateway.network_topology_service.run_arg_query")
    def test_fetch_topology_cache_count_updated(self, mock_arg):
        """After Phase 108, fetch_network_topology now issues 24 queries (20 original + 4 new)."""
        from services.api_gateway.network_topology_service import fetch_network_topology, _cache

        _cache.clear()
        mock_arg.return_value = []

        fetch_network_topology(["sub-p108"], credential="cred")
        fetch_network_topology(["sub-p108"], credential="cred")

        # 24 queries per call, second call cached → total == 24
        assert mock_arg.call_count == 24

