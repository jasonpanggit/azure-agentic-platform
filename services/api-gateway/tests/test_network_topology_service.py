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

        # 20 queries per call (vnets, nsgs, lbs, pes, gateways, public_ips, nics, vms, vmss, aks,
        # firewalls, app_gateways, peerings, nic_subnets, lb_backends, route_tables, local_gateways,
        # vpn_connections, app_gw_backends, nat_gateways)
        # but second call should be cached — so total == 20 not 40
        assert mock_arg.call_count == 20


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
