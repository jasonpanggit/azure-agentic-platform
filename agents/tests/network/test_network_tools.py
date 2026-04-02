"""Unit tests for Network Agent tools — ~40 tests across 8 test classes."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_instrument_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


def _make_nsg(security_rules=None, default_security_rules=None):
    nsg = MagicMock()
    nsg.provisioning_state = "Succeeded"
    nsg.security_rules = security_rules or []
    nsg.default_security_rules = default_security_rules or []
    return nsg


def _make_rule(name="Allow80", priority=100):
    rule = MagicMock()
    rule.name = name
    rule.priority = priority
    rule.direction = "Inbound"
    rule.access = "Allow"
    rule.protocol = "Tcp"
    rule.source_address_prefix = "*"
    rule.destination_address_prefix = "*"
    rule.destination_port_ranges = ["80"]
    rule.destination_port_range = None
    return rule


def _make_peering(name="peer-1", state="Connected"):
    p = MagicMock()
    p.name = name
    p.peering_state = state
    remote_vnet = MagicMock()
    remote_vnet.id = "/subscriptions/sub-2/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-remote"
    p.remote_virtual_network = remote_vnet
    p.allow_virtual_network_access = True
    p.allow_forwarded_traffic = False
    p.use_remote_gateways = False
    return p


def _make_subnet(name="snet-1", has_nsg=True, has_route_table=False, service_endpoints=None):
    s = MagicMock()
    s.name = name
    s.address_prefix = "10.0.1.0/24"
    s.network_security_group = MagicMock() if has_nsg else None
    s.route_table = MagicMock() if has_route_table else None
    eps = []
    for svc in (service_endpoints or []):
        ep = MagicMock()
        ep.service = svc
        eps.append(ep)
    s.service_endpoints = eps
    return s


def _make_vnet(address_prefixes=None, subnets=None, peerings=None):
    vnet = MagicMock()
    vnet.provisioning_state = "Succeeded"
    vnet.address_space = MagicMock()
    vnet.address_space.address_prefixes = address_prefixes or ["10.0.0.0/16"]
    vnet.subnets = subnets or []
    vnet.virtual_network_peerings = peerings or []
    return vnet


def _make_probe(name="probe-1"):
    p = MagicMock()
    p.name = name
    p.protocol = "Tcp"
    p.port = 80
    p.interval_in_seconds = 5
    p.number_of_probes = 2
    return p


def _make_backend_pool(name="pool-1", ip_count=3):
    pool = MagicMock()
    pool.name = name
    pool.backend_ip_configurations = [MagicMock() for _ in range(ip_count)]
    return pool


def _make_lb_rule(name="rule-1"):
    r = MagicMock()
    r.name = name
    r.protocol = "Tcp"
    r.frontend_port = 80
    r.backend_port = 8080
    r.enable_floating_ip = False
    return r


def _make_lb(probes=None, backend_pools=None, lb_rules=None, sku_name="Standard"):
    lb = MagicMock()
    lb.probes = probes or []
    lb.backend_address_pools = backend_pools or []
    lb.load_balancing_rules = lb_rules or []
    lb.sku = MagicMock()
    lb.sku.name = sku_name
    return lb


def _make_flow_log(enabled=True, storage_id="/subscriptions/sub/storage", retention_days=30,
                   analytics_enabled=False, workspace_id=None):
    fl = MagicMock()
    fl.enabled = enabled
    fl.storage_id = storage_id
    fl.retention_policy = MagicMock()
    fl.retention_policy.days = retention_days
    # traffic analytics
    nwfac = MagicMock()
    nwfac.enabled = analytics_enabled
    nwfac.workspace_id = workspace_id
    fl.flow_analytics_configuration = MagicMock()
    fl.flow_analytics_configuration.network_watcher_flow_analytics_configuration = nwfac
    return fl


def _make_circuit(circuit_name="circuit-1"):
    circuit = MagicMock()
    circuit.circuit_provisioning_state = "Enabled"
    circuit.service_provider_provisioning_state = "Provisioned"
    circuit.service_provider_properties = MagicMock()
    circuit.service_provider_properties.service_provider_name = "Equinix"
    circuit.service_provider_properties.peering_location = "Silicon Valley"
    circuit.service_provider_properties.bandwidth_in_mbps = 1000
    circuit.sku = MagicMock()
    circuit.sku.name = "Premium_MeteredData"
    peering = MagicMock()
    peering.name = "AzurePrivatePeering"
    peering.peering_type = "AzurePrivatePeering"
    peering.state = "Enabled"
    circuit.peerings = [peering]
    return circuit


def _make_connectivity_result(status="Reachable", hops=None):
    result = MagicMock()
    result.connection_status = status
    result.avg_latency_in_ms = 5
    result.min_latency_in_ms = 3
    result.max_latency_in_ms = 10
    result.probes_sent = 3
    result.probes_failed = 0
    hop_objs = []
    for addr in (hops or ["10.0.0.1", "10.0.0.2"]):
        h = MagicMock()
        h.address = addr
        hop_objs.append(h)
    result.hops = hop_objs
    return result


# ---------------------------------------------------------------------------
# TestAllowedMcpTools
# ---------------------------------------------------------------------------


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_tools_is_list(self):
        from agents.network.tools import ALLOWED_MCP_TOOLS

        assert isinstance(ALLOWED_MCP_TOOLS, list)

    def test_no_wildcard_in_allowed_tools(self):
        from agents.network.tools import ALLOWED_MCP_TOOLS

        for entry in ALLOWED_MCP_TOOLS:
            assert "*" not in entry, f"Wildcard found in tool: {entry}"

    def test_allowed_tools_contains_expected_entries(self):
        from agents.network.tools import ALLOWED_MCP_TOOLS

        assert "monitor.query_logs" in ALLOWED_MCP_TOOLS
        assert "monitor.query_metrics" in ALLOWED_MCP_TOOLS
        assert "resourcehealth.get_availability_status" in ALLOWED_MCP_TOOLS


# ---------------------------------------------------------------------------
# TestQueryNsgRules
# ---------------------------------------------------------------------------


class TestQueryNsgRules:
    """Verify query_nsg_rules — SDK calls, rule mapping, and error handling."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_success_returns_security_rules(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        rule = _make_rule()
        nsg = _make_nsg(security_rules=[rule])
        mock_client_cls.return_value.network_security_groups.get.return_value = nsg

        from agents.network.tools import query_nsg_rules

        result = query_nsg_rules(
            subscription_id="sub-1",
            resource_group="rg",
            nsg_name="nsg-test",
        )

        assert result["query_status"] == "success"
        assert len(result["security_rules"]) == 1
        assert result["security_rules"][0]["name"] == "Allow80"
        assert result["provisioning_state"] == "Succeeded"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.network_security_groups.get.side_effect = Exception(
            "ResourceNotFound"
        )

        from agents.network.tools import query_nsg_rules

        result = query_nsg_rules(
            subscription_id="sub-1",
            resource_group="rg",
            nsg_name="nsg-missing",
        )

        assert result["query_status"] == "error"
        assert "ResourceNotFound" in result["error"]

    def test_sdk_not_installed_returns_error(self):
        import agents.network.tools as tools_mod

        original = tools_mod.NetworkManagementClient
        tools_mod.NetworkManagementClient = None
        try:
            with patch("agents.network.tools.instrument_tool_call") as mock_inst, \
                 patch("agents.network.tools.get_agent_identity", return_value="test-id"):
                mock_inst.return_value = _make_instrument_mock()
                from agents.network.tools import query_nsg_rules

                result = query_nsg_rules(
                    subscription_id="sub-1",
                    resource_group="rg",
                    nsg_name="nsg",
                )
                assert result["query_status"] == "error"
                assert "not installed" in result["error"]
        finally:
            tools_mod.NetworkManagementClient = original

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_subscription_id_passed_to_client(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        nsg = _make_nsg()
        mock_client_cls.return_value.network_security_groups.get.return_value = nsg

        from agents.network.tools import query_nsg_rules

        query_nsg_rules(
            subscription_id="sub-xyz",
            resource_group="rg",
            nsg_name="nsg",
        )

        mock_client_cls.assert_called_once_with(mock_cred.return_value, "sub-xyz")

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_empty_rules_returns_success_with_empty_lists(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        nsg = _make_nsg(security_rules=[], default_security_rules=[])
        mock_client_cls.return_value.network_security_groups.get.return_value = nsg

        from agents.network.tools import query_nsg_rules

        result = query_nsg_rules(
            subscription_id="sub-1",
            resource_group="rg",
            nsg_name="empty-nsg",
        )

        assert result["query_status"] == "success"
        assert result["security_rules"] == []
        assert result["default_security_rules"] == []


# ---------------------------------------------------------------------------
# TestQueryPeeringStatus
# ---------------------------------------------------------------------------


class TestQueryPeeringStatus:
    """Verify query_peering_status — peering iteration and error handling."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_success_returns_peerings_list(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        peering = _make_peering()
        mock_client_cls.return_value.virtual_network_peerings.list.return_value = [peering]

        from agents.network.tools import query_peering_status

        result = query_peering_status(
            subscription_id="sub-1",
            resource_group="rg",
            vnet_name="vnet-1",
        )

        assert result["query_status"] == "success"
        assert len(result["peerings"]) == 1
        assert result["peerings"][0]["name"] == "peer-1"
        assert result["peerings"][0]["peering_state"] == "Connected"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.virtual_network_peerings.list.side_effect = Exception(
            "AuthorizationFailed"
        )

        from agents.network.tools import query_peering_status

        result = query_peering_status(
            subscription_id="sub-1",
            resource_group="rg",
            vnet_name="vnet-1",
        )

        assert result["query_status"] == "error"
        assert "AuthorizationFailed" in result["error"]

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_disconnected_peering_state_preserved(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        peering = _make_peering(state="Disconnected")
        mock_client_cls.return_value.virtual_network_peerings.list.return_value = [peering]

        from agents.network.tools import query_peering_status

        result = query_peering_status(
            subscription_id="sub-1",
            resource_group="rg",
            vnet_name="vnet-1",
        )

        assert result["query_status"] == "success"
        assert result["peerings"][0]["peering_state"] == "Disconnected"

    def test_sdk_not_installed_returns_error(self):
        import agents.network.tools as tools_mod

        original = tools_mod.NetworkManagementClient
        tools_mod.NetworkManagementClient = None
        try:
            with patch("agents.network.tools.instrument_tool_call") as mock_inst, \
                 patch("agents.network.tools.get_agent_identity", return_value="test-id"):
                mock_inst.return_value = _make_instrument_mock()
                from agents.network.tools import query_peering_status

                result = query_peering_status(
                    subscription_id="sub-1",
                    resource_group="rg",
                    vnet_name="vnet-1",
                )
                assert result["query_status"] == "error"
                assert "not installed" in result["error"]
        finally:
            tools_mod.NetworkManagementClient = original


# ---------------------------------------------------------------------------
# TestQueryVnetTopology
# ---------------------------------------------------------------------------


class TestQueryVnetTopology:
    """Verify query_vnet_topology — VNet detail extraction and error handling."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_success_returns_address_space(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        vnet = _make_vnet(address_prefixes=["10.0.0.0/16", "192.168.0.0/24"])
        mock_client_cls.return_value.virtual_networks.get.return_value = vnet

        from agents.network.tools import query_vnet_topology

        result = query_vnet_topology(
            subscription_id="sub-1",
            resource_group="rg",
            vnet_name="vnet-1",
        )

        assert result["query_status"] == "success"
        assert "10.0.0.0/16" in result["address_space"]
        assert "192.168.0.0/24" in result["address_space"]

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_subnets_include_nsg_attached_flag(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        subnet_with_nsg = _make_subnet("snet-1", has_nsg=True)
        subnet_without_nsg = _make_subnet("snet-2", has_nsg=False)
        vnet = _make_vnet(subnets=[subnet_with_nsg, subnet_without_nsg])
        mock_client_cls.return_value.virtual_networks.get.return_value = vnet

        from agents.network.tools import query_vnet_topology

        result = query_vnet_topology(
            subscription_id="sub-1",
            resource_group="rg",
            vnet_name="vnet-1",
        )

        assert result["subnets"][0]["nsg_attached"] is True
        assert result["subnets"][1]["nsg_attached"] is False

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_subnets_include_service_endpoints(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        subnet = _make_subnet("snet-1", service_endpoints=["Microsoft.Storage", "Microsoft.KeyVault"])
        vnet = _make_vnet(subnets=[subnet])
        mock_client_cls.return_value.virtual_networks.get.return_value = vnet

        from agents.network.tools import query_vnet_topology

        result = query_vnet_topology(
            subscription_id="sub-1",
            resource_group="rg",
            vnet_name="vnet-1",
        )

        svc_eps = result["subnets"][0]["service_endpoints"]
        assert "Microsoft.Storage" in svc_eps
        assert "Microsoft.KeyVault" in svc_eps

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.virtual_networks.get.side_effect = Exception("NotFound")

        from agents.network.tools import query_vnet_topology

        result = query_vnet_topology(
            subscription_id="sub-1",
            resource_group="rg",
            vnet_name="vnet-missing",
        )

        assert result["query_status"] == "error"
        assert "NotFound" in result["error"]

    def test_sdk_not_installed_returns_error(self):
        import agents.network.tools as tools_mod

        original = tools_mod.NetworkManagementClient
        tools_mod.NetworkManagementClient = None
        try:
            with patch("agents.network.tools.instrument_tool_call") as mock_inst, \
                 patch("agents.network.tools.get_agent_identity", return_value="test-id"):
                mock_inst.return_value = _make_instrument_mock()
                from agents.network.tools import query_vnet_topology

                result = query_vnet_topology(
                    subscription_id="sub-1",
                    resource_group="rg",
                    vnet_name="vnet",
                )
                assert result["query_status"] == "error"
                assert "not installed" in result["error"]
        finally:
            tools_mod.NetworkManagementClient = original


# ---------------------------------------------------------------------------
# TestQueryLoadBalancerHealth
# ---------------------------------------------------------------------------


class TestQueryLoadBalancerHealth:
    """Verify query_load_balancer_health — probe/pool/rule mapping and errors."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_success_returns_health_probes(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        probe = _make_probe()
        lb = _make_lb(probes=[probe])
        mock_client_cls.return_value.load_balancers.get.return_value = lb

        from agents.network.tools import query_load_balancer_health

        result = query_load_balancer_health(
            subscription_id="sub-1",
            resource_group="rg",
            lb_name="lb-1",
        )

        assert result["query_status"] == "success"
        assert len(result["health_probes"]) == 1
        assert result["health_probes"][0]["name"] == "probe-1"
        assert result["health_probes"][0]["port"] == 80

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_success_returns_backend_pools(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        pool = _make_backend_pool(ip_count=5)
        lb = _make_lb(backend_pools=[pool])
        mock_client_cls.return_value.load_balancers.get.return_value = lb

        from agents.network.tools import query_load_balancer_health

        result = query_load_balancer_health(
            subscription_id="sub-1",
            resource_group="rg",
            lb_name="lb-1",
        )

        assert result["query_status"] == "success"
        assert result["backend_pools"][0]["ip_configurations_count"] == 5

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_success_includes_sku(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        lb = _make_lb(sku_name="Standard")
        mock_client_cls.return_value.load_balancers.get.return_value = lb

        from agents.network.tools import query_load_balancer_health

        result = query_load_balancer_health(
            subscription_id="sub-1",
            resource_group="rg",
            lb_name="lb-1",
        )

        assert result["sku"] == "Standard"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.load_balancers.get.side_effect = Exception("LBNotFound")

        from agents.network.tools import query_load_balancer_health

        result = query_load_balancer_health(
            subscription_id="sub-1",
            resource_group="rg",
            lb_name="lb-missing",
        )

        assert result["query_status"] == "error"
        assert "LBNotFound" in result["error"]

    def test_sdk_not_installed_returns_error(self):
        import agents.network.tools as tools_mod

        original = tools_mod.NetworkManagementClient
        tools_mod.NetworkManagementClient = None
        try:
            with patch("agents.network.tools.instrument_tool_call") as mock_inst, \
                 patch("agents.network.tools.get_agent_identity", return_value="test-id"):
                mock_inst.return_value = _make_instrument_mock()
                from agents.network.tools import query_load_balancer_health

                result = query_load_balancer_health(
                    subscription_id="sub-1",
                    resource_group="rg",
                    lb_name="lb",
                )
                assert result["query_status"] == "error"
                assert "not installed" in result["error"]
        finally:
            tools_mod.NetworkManagementClient = original


# ---------------------------------------------------------------------------
# TestQueryFlowLogs
# ---------------------------------------------------------------------------


class TestQueryFlowLogs:
    """Verify query_flow_logs — enabled/disabled states and traffic analytics."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_enabled_flow_log_returns_storage_id(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        fl = _make_flow_log(enabled=True, storage_id="/subscriptions/sub/storage/sa-1")
        mock_client_cls.return_value.flow_logs.get.return_value = fl

        from agents.network.tools import query_flow_logs

        result = query_flow_logs(
            subscription_id="sub-1",
            resource_group="rg",
            network_watcher_name="nw-1",
            flow_log_name="fl-1",
        )

        assert result["query_status"] == "success"
        assert result["enabled"] is True
        assert result["storage_id"] == "/subscriptions/sub/storage/sa-1"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_disabled_flow_log_returns_enabled_false(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        fl = _make_flow_log(enabled=False, storage_id="/subscriptions/sub/storage/sa-1")
        mock_client_cls.return_value.flow_logs.get.return_value = fl

        from agents.network.tools import query_flow_logs

        result = query_flow_logs(
            subscription_id="sub-1",
            resource_group="rg",
            network_watcher_name="nw-1",
            flow_log_name="fl-1",
        )

        assert result["query_status"] == "success"
        assert result["enabled"] is False

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_traffic_analytics_enabled_flag_extracted(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        fl = _make_flow_log(
            analytics_enabled=True,
            workspace_id="/subscriptions/sub/workspaces/ws-1",
        )
        mock_client_cls.return_value.flow_logs.get.return_value = fl

        from agents.network.tools import query_flow_logs

        result = query_flow_logs(
            subscription_id="sub-1",
            resource_group="rg",
            network_watcher_name="nw-1",
            flow_log_name="fl-1",
        )

        assert result["traffic_analytics_enabled"] is True
        assert result["workspace_id"] == "/subscriptions/sub/workspaces/ws-1"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.flow_logs.get.side_effect = Exception("FlowLogNotFound")

        from agents.network.tools import query_flow_logs

        result = query_flow_logs(
            subscription_id="sub-1",
            resource_group="rg",
            network_watcher_name="nw-1",
            flow_log_name="fl-missing",
        )

        assert result["query_status"] == "error"
        assert "FlowLogNotFound" in result["error"]

    def test_sdk_not_installed_returns_error(self):
        import agents.network.tools as tools_mod

        original = tools_mod.NetworkManagementClient
        tools_mod.NetworkManagementClient = None
        try:
            with patch("agents.network.tools.instrument_tool_call") as mock_inst, \
                 patch("agents.network.tools.get_agent_identity", return_value="test-id"):
                mock_inst.return_value = _make_instrument_mock()
                from agents.network.tools import query_flow_logs

                result = query_flow_logs(
                    subscription_id="sub-1",
                    resource_group="rg",
                    network_watcher_name="nw-1",
                    flow_log_name="fl-1",
                )
                assert result["query_status"] == "error"
                assert "not installed" in result["error"]
        finally:
            tools_mod.NetworkManagementClient = original


# ---------------------------------------------------------------------------
# TestQueryExpressrouteCircuit
# ---------------------------------------------------------------------------


class TestQueryExpressrouteCircuit:
    """Verify query_expressroute_circuit — field extraction and error handling."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_success_returns_circuit_fields(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        circuit = _make_circuit()
        mock_client_cls.return_value.express_route_circuits.get.return_value = circuit

        from agents.network.tools import query_expressroute_circuit

        result = query_expressroute_circuit(
            subscription_id="sub-1",
            resource_group="rg",
            circuit_name="circuit-1",
        )

        assert result["query_status"] == "success"
        assert result["circuit_name"] == "circuit-1"
        assert result["circuit_provisioning_state"] == "Enabled"
        assert result["service_provider_provisioning_state"] == "Provisioned"
        assert result["sku"] == "Premium_MeteredData"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_peerings_list_populated(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        circuit = _make_circuit()
        mock_client_cls.return_value.express_route_circuits.get.return_value = circuit

        from agents.network.tools import query_expressroute_circuit

        result = query_expressroute_circuit(
            subscription_id="sub-1",
            resource_group="rg",
            circuit_name="circuit-1",
        )

        assert len(result["peerings"]) == 1
        assert result["peerings"][0]["name"] == "AzurePrivatePeering"
        assert result["peerings"][0]["state"] == "Enabled"

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.express_route_circuits.get.side_effect = Exception(
            "CircuitNotFound"
        )

        from agents.network.tools import query_expressroute_circuit

        result = query_expressroute_circuit(
            subscription_id="sub-1",
            resource_group="rg",
            circuit_name="circuit-missing",
        )

        assert result["query_status"] == "error"
        assert "CircuitNotFound" in result["error"]

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_bandwidth_and_location_extracted(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        circuit = _make_circuit()
        mock_client_cls.return_value.express_route_circuits.get.return_value = circuit

        from agents.network.tools import query_expressroute_circuit

        result = query_expressroute_circuit(
            subscription_id="sub-1",
            resource_group="rg",
            circuit_name="circuit-1",
        )

        assert result["bandwidth_mbps"] == 1000
        assert result["peering_location"] == "Silicon Valley"
        assert result["service_provider"] == "Equinix"

    def test_sdk_not_installed_returns_error(self):
        import agents.network.tools as tools_mod

        original = tools_mod.NetworkManagementClient
        tools_mod.NetworkManagementClient = None
        try:
            with patch("agents.network.tools.instrument_tool_call") as mock_inst, \
                 patch("agents.network.tools.get_agent_identity", return_value="test-id"):
                mock_inst.return_value = _make_instrument_mock()
                from agents.network.tools import query_expressroute_circuit

                result = query_expressroute_circuit(
                    subscription_id="sub-1",
                    resource_group="rg",
                    circuit_name="circuit-1",
                )
                assert result["query_status"] == "error"
                assert "not installed" in result["error"]
        finally:
            tools_mod.NetworkManagementClient = original


# ---------------------------------------------------------------------------
# TestRunConnectivityCheck
# ---------------------------------------------------------------------------


class TestRunConnectivityCheck:
    """Verify run_connectivity_check — LRO pattern, hops, and error handling."""

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_success_returns_connection_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_result = _make_connectivity_result(status="Reachable")
        mock_poller = MagicMock()
        mock_poller.result.return_value = mock_result
        mock_client_cls.return_value.network_watchers.begin_check_connectivity.return_value = mock_poller

        from agents.network.tools import run_connectivity_check

        result = run_connectivity_check(
            subscription_id="sub-1",
            source_resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            destination_address="10.0.0.5",
            destination_port=443,
            network_watcher_rg="rg-nw",
            network_watcher_name="nw-1",
        )

        assert result["query_status"] == "success"
        assert result["connection_status"] == "Reachable"
        assert result["avg_latency_ms"] == 5
        assert result["probes_sent"] == 3

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_poller_result_called_with_timeout_60(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_result = _make_connectivity_result()
        mock_poller = MagicMock()
        mock_poller.result.return_value = mock_result
        mock_client_cls.return_value.network_watchers.begin_check_connectivity.return_value = mock_poller

        from agents.network.tools import run_connectivity_check

        run_connectivity_check(
            subscription_id="sub-1",
            source_resource_id="/subscriptions/sub-1/rg/vm-1",
            destination_address="10.0.0.5",
            destination_port=80,
            network_watcher_rg="rg-nw",
            network_watcher_name="nw-1",
        )

        mock_poller.result.assert_called_once_with(timeout=60)

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_hops_list_populated(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_result = _make_connectivity_result(hops=["10.0.0.1", "10.0.0.2", "192.168.1.1"])
        mock_poller = MagicMock()
        mock_poller.result.return_value = mock_result
        mock_client_cls.return_value.network_watchers.begin_check_connectivity.return_value = mock_poller

        from agents.network.tools import run_connectivity_check

        result = run_connectivity_check(
            subscription_id="sub-1",
            source_resource_id="/subscriptions/sub-1/rg/vm-1",
            destination_address="192.168.1.1",
            destination_port=22,
            network_watcher_rg="rg-nw",
            network_watcher_name="nw-1",
        )

        assert result["hops"] == ["10.0.0.1", "10.0.0.2", "192.168.1.1"]

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.network_watchers.begin_check_connectivity.side_effect = (
            Exception("HttpResponseError: VM not running")
        )

        from agents.network.tools import run_connectivity_check

        result = run_connectivity_check(
            subscription_id="sub-1",
            source_resource_id="/subscriptions/sub-1/rg/vm-1",
            destination_address="10.0.0.5",
            destination_port=443,
            network_watcher_rg="rg-nw",
            network_watcher_name="nw-1",
        )

        assert result["query_status"] == "error"
        assert "HttpResponseError" in result["error"]
        assert result["connection_status"] is None

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_lro_timeout_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_poller = MagicMock()
        mock_poller.result.side_effect = Exception("LRO operation timed out after 60 seconds")
        mock_client_cls.return_value.network_watchers.begin_check_connectivity.return_value = mock_poller

        from agents.network.tools import run_connectivity_check

        result = run_connectivity_check(
            subscription_id="sub-1",
            source_resource_id="/subscriptions/sub-1/rg/vm-1",
            destination_address="10.0.0.5",
            destination_port=443,
            network_watcher_rg="rg-nw",
            network_watcher_name="nw-1",
        )

        assert result["query_status"] == "error"
        assert "timed out" in result["error"]

    def test_sdk_not_installed_returns_error(self):
        import agents.network.tools as tools_mod

        original = tools_mod.NetworkManagementClient
        tools_mod.NetworkManagementClient = None
        try:
            with patch("agents.network.tools.instrument_tool_call") as mock_inst, \
                 patch("agents.network.tools.get_agent_identity", return_value="test-id"):
                mock_inst.return_value = _make_instrument_mock()
                from agents.network.tools import run_connectivity_check

                result = run_connectivity_check(
                    subscription_id="sub-1",
                    source_resource_id="/subscriptions/sub-1/rg/vm-1",
                    destination_address="10.0.0.5",
                    destination_port=443,
                    network_watcher_rg="rg-nw",
                    network_watcher_name="nw-1",
                )
                assert result["query_status"] == "error"
                assert "not installed" in result["error"]
        finally:
            tools_mod.NetworkManagementClient = original

    @patch("agents.network.tools.instrument_tool_call")
    @patch("agents.network.tools.get_agent_identity", return_value="test-id")
    @patch("agents.network.tools.NetworkManagementClient")
    @patch("agents.network.tools.get_credential", return_value=MagicMock())
    def test_destination_port_forwarded_to_sdk(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_result = _make_connectivity_result()
        mock_poller = MagicMock()
        mock_poller.result.return_value = mock_result
        mock_client_cls.return_value.network_watchers.begin_check_connectivity.return_value = mock_poller

        from agents.network.tools import run_connectivity_check

        run_connectivity_check(
            subscription_id="sub-1",
            source_resource_id="/subscriptions/sub-1/rg/vm-1",
            destination_address="10.0.0.5",
            destination_port=8443,
            network_watcher_rg="rg-nw",
            network_watcher_name="nw-1",
        )

        call_args = mock_client_cls.return_value.network_watchers.begin_check_connectivity.call_args
        params_dict = call_args[0][2]
        assert params_dict["destination"]["port"] == 8443
        assert params_dict["destination"]["address"] == "10.0.0.5"
