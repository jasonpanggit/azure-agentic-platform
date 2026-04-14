"""Unit tests for Network Agent tools (Phase 20 — Plan 20-04).

Tests all 7 network tools + ALLOWED_MCP_TOOLS.
Each tool has success path, error path, and SDK-missing path tests.
Pattern follows agents/tests/patch/test_patch_tools.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_with_name(mock_name: str, **kwargs) -> MagicMock:
    """Create a MagicMock with .name as a real attribute, not the mock's internal name."""
    m = MagicMock(**kwargs)
    # MagicMock(name=...) sets mock's repr name, not the .name attribute.
    # We must explicitly set .name after construction.
    m.name = mock_name
    return m


# ---------------------------------------------------------------------------
# ALLOWED_MCP_TOOLS
# ---------------------------------------------------------------------------


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_mcp_tools_has_exactly_four_entries(self):
        from agents.network.tools import ALLOWED_MCP_TOOLS

        assert len(ALLOWED_MCP_TOOLS) == 4

    def test_allowed_mcp_tools_contains_expected_entries(self):
        from agents.network.tools import ALLOWED_MCP_TOOLS

        assert "monitor" in ALLOWED_MCP_TOOLS
        assert "resourcehealth" in ALLOWED_MCP_TOOLS
        assert "advisor" in ALLOWED_MCP_TOOLS
        assert "compute" in ALLOWED_MCP_TOOLS

    def test_allowed_mcp_tools_no_wildcards(self):
        from agents.network.tools import ALLOWED_MCP_TOOLS

        for tool in ALLOWED_MCP_TOOLS:
            assert "*" not in tool, f"Wildcard found in tool: {tool}"

    def test_allowed_mcp_tools_no_dotted_names(self):
        """v2 uses namespace names, not dotted names."""
        from agents.network.tools import ALLOWED_MCP_TOOLS

        for tool in ALLOWED_MCP_TOOLS:
            assert "." not in tool, (
                f"Dotted tool name '{tool}' found — must use v2 namespace name"
            )


# ---------------------------------------------------------------------------
# query_nsg_rules
# ---------------------------------------------------------------------------


class TestQueryNsgRules:
    """Verify query_nsg_rules returns expected structure."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_success_with_rules(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_rule = _mock_with_name(
            "allow-https",
            priority=100,
            direction="Inbound",
            access="Allow",
            protocol="Tcp",
            source_address_prefix="*",
            destination_address_prefix="*",
            source_port_range="*",
            destination_port_range="443",
        )
        mock_default = _mock_with_name(
            "DenyAllInBound",
            priority=65500,
            direction="Inbound",
            access="Deny",
            protocol="*",
            source_address_prefix="*",
            destination_address_prefix="*",
            source_port_range="*",
            destination_port_range="*",
        )
        mock_nsg = MagicMock(
            security_rules=[mock_rule],
            default_security_rules=[mock_default],
        )
        mock_client_cls.return_value.network_security_groups.get.return_value = mock_nsg

        from agents.network.tools import query_nsg_rules

        result = query_nsg_rules(
            resource_group="rg-test",
            nsg_name="nsg-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "success"
        assert len(result["security_rules"]) == 1
        assert result["security_rules"][0]["name"] == "allow-https"
        assert result["security_rules"][0]["priority"] == 100
        assert result["security_rules"][0]["destination_port_range"] == "443"
        assert result["rule_count"] == 1
        assert len(result["default_security_rules"]) == 1
        assert result["default_security_rules"][0]["name"] == "DenyAllInBound"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.network_security_groups.get.side_effect = Exception(
            "NSG not found"
        )

        from agents.network.tools import query_nsg_rules

        result = query_nsg_rules(
            resource_group="rg-test",
            nsg_name="nsg-bad",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "NSG not found" in result["error"]
        assert result["security_rules"] == []

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.network.tools import query_nsg_rules

        result = query_nsg_rules(
            resource_group="rg-test",
            nsg_name="nsg-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_vnet_topology
# ---------------------------------------------------------------------------


class TestQueryVnetTopology:
    """Verify query_vnet_topology returns expected structure."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_success_with_topology(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_subnet = _mock_with_name(
            "snet-1",
            address_prefix="10.0.1.0/24",
            network_security_group=None,
            route_table=None,
            delegations=[],
        )
        mock_peering = _mock_with_name(
            "peer-1",
            peering_state="Connected",
            remote_virtual_network=MagicMock(id="/sub/vnet-remote"),
            allow_forwarded_traffic=True,
            allow_gateway_transit=False,
        )
        mock_address_space = MagicMock(address_prefixes=["10.0.0.0/16"])
        mock_vnet = MagicMock(
            address_space=mock_address_space,
            subnets=[mock_subnet],
            virtual_network_peerings=[mock_peering],
        )
        mock_client_cls.return_value.virtual_networks.get.return_value = mock_vnet

        from agents.network.tools import query_vnet_topology

        result = query_vnet_topology(
            resource_group="rg-test",
            vnet_name="vnet-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "success"
        assert result["address_space"] == ["10.0.0.0/16"]
        assert result["subnet_count"] == 1
        assert result["peering_count"] == 1
        assert result["subnets"][0]["name"] == "snet-1"
        assert result["subnets"][0]["address_prefix"] == "10.0.1.0/24"
        assert result["peerings"][0]["peering_state"] == "Connected"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.virtual_networks.get.side_effect = Exception(
            "VNet not found"
        )

        from agents.network.tools import query_vnet_topology

        result = query_vnet_topology(
            resource_group="rg-test",
            vnet_name="vnet-bad",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "VNet not found" in result["error"]

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.network.tools import query_vnet_topology

        result = query_vnet_topology(
            resource_group="rg-test",
            vnet_name="vnet-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_load_balancer_health
# ---------------------------------------------------------------------------


class TestQueryLoadBalancerHealth:
    """Verify query_load_balancer_health returns expected structure."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_success_with_lb_data(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_probe = _mock_with_name(
            "http-probe",
            protocol="Http",
            port=80,
            interval_in_seconds=15,
            number_of_probes=2,
            request_path="/health",
        )
        mock_pool = _mock_with_name(
            "pool-1",
            backend_ip_configurations=[MagicMock(), MagicMock()],
        )
        mock_rule = _mock_with_name(
            "rule-1",
            frontend_port=80,
            backend_port=80,
            protocol="Tcp",
            idle_timeout_in_minutes=4,
            enable_floating_ip=False,
            load_distribution="Default",
        )
        mock_fip = _mock_with_name(
            "fip-1",
            private_ip_address="10.0.0.4",
            public_ip_address=None,
            subnet=MagicMock(id="/sub/snet-1"),
        )
        mock_lb = MagicMock(
            probes=[mock_probe],
            backend_address_pools=[mock_pool],
            load_balancing_rules=[mock_rule],
            frontend_ip_configurations=[mock_fip],
        )
        mock_client_cls.return_value.load_balancers.get.return_value = mock_lb

        from agents.network.tools import query_load_balancer_health

        result = query_load_balancer_health(
            resource_group="rg-test",
            lb_name="lb-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "success"
        assert len(result["health_probes"]) == 1
        assert result["health_probes"][0]["name"] == "http-probe"
        assert result["health_probes"][0]["port"] == 80
        assert len(result["backend_pools"]) == 1
        assert result["backend_pools"][0]["backend_ip_config_count"] == 2
        assert len(result["load_balancing_rules"]) == 1
        assert result["load_balancing_rules"][0]["name"] == "rule-1"
        assert len(result["frontend_configs"]) == 1

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.load_balancers.get.side_effect = Exception(
            "LB not found"
        )

        from agents.network.tools import query_load_balancer_health

        result = query_load_balancer_health(
            resource_group="rg-test",
            lb_name="lb-bad",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "LB not found" in result["error"]

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.network.tools import query_load_balancer_health

        result = query_load_balancer_health(
            resource_group="rg-test",
            lb_name="lb-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_peering_status
# ---------------------------------------------------------------------------


class TestQueryPeeringStatus:
    """Verify query_peering_status returns expected structure."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_success_with_peerings(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_peering = _mock_with_name(
            "peer-1",
            peering_state="Connected",
            remote_virtual_network=MagicMock(id="/sub/vnet-remote"),
            allow_virtual_network_access=True,
            allow_forwarded_traffic=False,
            allow_gateway_transit=False,
            use_remote_gateways=False,
        )
        mock_client_cls.return_value.virtual_network_peerings.list.return_value = [
            mock_peering
        ]

        from agents.network.tools import query_peering_status

        result = query_peering_status(
            resource_group="rg-test",
            vnet_name="vnet-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "success"
        assert result["peering_count"] == 1
        assert result["peerings"][0]["name"] == "peer-1"
        assert result["peerings"][0]["peering_state"] == "Connected"
        assert result["peerings"][0]["remote_virtual_network_id"] == "/sub/vnet-remote"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.virtual_network_peerings.list.side_effect = (
            Exception("Peering list failed")
        )

        from agents.network.tools import query_peering_status

        result = query_peering_status(
            resource_group="rg-test",
            vnet_name="vnet-bad",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "Peering list failed" in result["error"]

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.network.tools import query_peering_status

        result = query_peering_status(
            resource_group="rg-test",
            vnet_name="vnet-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_flow_logs
# ---------------------------------------------------------------------------


class TestQueryFlowLogs:
    """Verify query_flow_logs returns expected structure."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_success_with_flow_logs(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_fl = _mock_with_name(
            "nsg-flow-1",
            target_resource_id="/sub/nsg-1",
            storage_id="/sub/storage-1",
            enabled=True,
            retention_policy=MagicMock(enabled=True, days=7),
            format=MagicMock(type="JSON", version=2),
            flow_analytics_configuration=None,
        )
        mock_client_cls.return_value.flow_logs.list.return_value = [mock_fl]

        from agents.network.tools import query_flow_logs

        result = query_flow_logs(
            resource_group="rg-test",
            network_watcher_name="nw-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "success"
        assert result["flow_log_count"] == 1
        assert result["flow_logs"][0]["name"] == "nsg-flow-1"
        assert result["flow_logs"][0]["enabled"] is True
        assert result["flow_logs"][0]["retention_policy"]["days"] == 7

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.flow_logs.list.side_effect = Exception(
            "Network Watcher not found"
        )

        from agents.network.tools import query_flow_logs

        result = query_flow_logs(
            resource_group="rg-test",
            network_watcher_name="nw-bad",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "Network Watcher not found" in result["error"]

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.network.tools import query_flow_logs

        result = query_flow_logs(
            resource_group="rg-test",
            network_watcher_name="nw-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_expressroute_health
# ---------------------------------------------------------------------------


class TestQueryExpressrouteHealth:
    """Verify query_expressroute_health returns expected structure."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_success_with_circuit(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_peering = _mock_with_name(
            "AzurePrivatePeering",
            peering_type="AzurePrivatePeering",
            state="Enabled",
            azure_asn=12076,
            peer_asn=65515,
            primary_peer_address_prefix="172.16.0.0/30",
            secondary_peer_address_prefix="172.16.0.4/30",
            vlan_id=100,
        )
        mock_circuit = MagicMock(
            circuit_provisioning_state="Enabled",
            service_provider_provisioning_state="Provisioned",
            sku=MagicMock(name="Premium_MeteredData", tier="Premium", family="MeteredData"),
            bandwidth_in_mbps=1000,
            peerings=[mock_peering],
        )
        mock_client_cls.return_value.express_route_circuits.get.return_value = mock_circuit

        from agents.network.tools import query_expressroute_health

        result = query_expressroute_health(
            resource_group="rg-test",
            circuit_name="er-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "success"
        assert result["provisioning_state"] == "Enabled"
        assert result["service_provider_state"] == "Provisioned"
        assert result["bandwidth_mbps"] == 1000
        assert result["peering_count"] == 1
        assert result["peerings"][0]["name"] == "AzurePrivatePeering"
        assert result["peerings"][0]["state"] == "Enabled"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.express_route_circuits.get.side_effect = Exception(
            "Circuit not found"
        )

        from agents.network.tools import query_expressroute_health

        result = query_expressroute_health(
            resource_group="rg-test",
            circuit_name="er-bad",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "Circuit not found" in result["error"]

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.NetworkManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.network.tools import query_expressroute_health

        result = query_expressroute_health(
            resource_group="rg-test",
            circuit_name="er-test",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# check_connectivity
# ---------------------------------------------------------------------------


class TestCheckConnectivity:
    """Verify check_connectivity returns expected structure."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.ConnectivityDestination", MagicMock())
    @patch("agents.network.tools.ConnectivitySource", MagicMock())
    @patch("agents.network.tools.ConnectivityParameters", MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_success_reachable(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock(
            connection_status="Reachable",
            avg_latency_in_ms=12,
            min_latency_in_ms=8,
            max_latency_in_ms=20,
            probes_sent=4,
            probes_failed=0,
            hops=[],
        )
        mock_poller = MagicMock()
        mock_poller.result.return_value = mock_result
        mock_client_cls.return_value.network_watchers.begin_check_connectivity.return_value = (
            mock_poller
        )

        from agents.network.tools import check_connectivity

        result = check_connectivity(
            source_resource_id="/sub/vm-1",
            destination_address="10.0.0.5",
            destination_port=443,
            network_watcher_resource_group="rg-nw",
            network_watcher_name="nw-1",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "success"
        assert result["connection_status"] == "Reachable"
        assert result["avg_latency_ms"] == 12

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.ConnectivityDestination", MagicMock())
    @patch("agents.network.tools.ConnectivitySource", MagicMock())
    @patch("agents.network.tools.ConnectivityParameters", MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_success_unreachable(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock(
            connection_status="Unreachable",
            avg_latency_in_ms=None,
            min_latency_in_ms=None,
            max_latency_in_ms=None,
            probes_sent=4,
            probes_failed=4,
            hops=[],
        )
        mock_poller = MagicMock()
        mock_poller.result.return_value = mock_result
        mock_client_cls.return_value.network_watchers.begin_check_connectivity.return_value = (
            mock_poller
        )

        from agents.network.tools import check_connectivity

        result = check_connectivity(
            source_resource_id="/sub/vm-1",
            destination_address="10.0.0.5",
            destination_port=443,
            network_watcher_resource_group="rg-nw",
            network_watcher_name="nw-1",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "success"
        assert result["connection_status"] == "Unreachable"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.ConnectivityDestination", MagicMock())
    @patch("agents.network.tools.ConnectivitySource", MagicMock())
    @patch("agents.network.tools.ConnectivityParameters", MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_timeout_on_poller_timeout(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_poller = MagicMock()
        mock_poller.result.side_effect = Exception("Operation timed out")
        mock_client_cls.return_value.network_watchers.begin_check_connectivity.return_value = (
            mock_poller
        )

        from agents.network.tools import check_connectivity

        result = check_connectivity(
            source_resource_id="/sub/vm-1",
            destination_address="10.0.0.5",
            destination_port=443,
            network_watcher_resource_group="rg-nw",
            network_watcher_name="nw-1",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "timeout"
        assert "timed out" in result["error"]

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.ConnectivityDestination", MagicMock())
    @patch("agents.network.tools.ConnectivitySource", MagicMock())
    @patch("agents.network.tools.ConnectivityParameters", MagicMock())
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.network_watchers.begin_check_connectivity.side_effect = (
            Exception("Network Watcher unavailable")
        )

        from agents.network.tools import check_connectivity

        result = check_connectivity(
            source_resource_id="/sub/vm-1",
            destination_address="10.0.0.5",
            destination_port=443,
            network_watcher_resource_group="rg-nw",
            network_watcher_name="nw-1",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "Network Watcher unavailable" in result["error"]

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    @patch("agents.network.tools.ConnectivityParameters", None)
    @patch("agents.network.tools.NetworkManagementClient")
    def test_returns_error_when_sdk_missing(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.network.tools import check_connectivity

        result = check_connectivity(
            source_resource_id="/sub/vm-1",
            destination_address="10.0.0.5",
            destination_port=443,
            network_watcher_resource_group="rg-nw",
            network_watcher_name="nw-1",
            subscription_id="sub-test-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# _extract_subscription_id
# ---------------------------------------------------------------------------


class TestExtractSubscriptionId:
    """Verify _extract_subscription_id handles valid and invalid inputs."""

    def test_extracts_from_valid_resource_id(self):
        from agents.network.tools import _extract_subscription_id

        result = _extract_subscription_id(
            "/subscriptions/abc-123/resourceGroups/rg/providers/Microsoft.Network/nsg/nsg-1"
        )
        assert result == "abc-123"

    def test_case_insensitive(self):
        from agents.network.tools import _extract_subscription_id

        result = _extract_subscription_id(
            "/Subscriptions/ABC-123/resourceGroups/rg/providers/Microsoft.Network/nsg/nsg-1"
        )
        assert result == "abc-123"

    @pytest.mark.parametrize("bad_id", [
        "",
        "/no-subs-here/foo",
        "not/a/resource/id",
    ])
    def test_raises_on_invalid_resource_id(self, bad_id):
        from agents.network.tools import _extract_subscription_id

        with pytest.raises(ValueError, match="Cannot extract subscription_id"):
            _extract_subscription_id(bad_id)
