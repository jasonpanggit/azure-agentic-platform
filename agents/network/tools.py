"""Network Agent tool functions — azure-mgmt-network SDK wrappers + Monitor.

The Azure MCP Server has limited dedicated networking tools (no direct VNet/NSG/LB
tools confirmed GA). The Network Agent supplements MCP tools with @ai_function
wrappers around the azure-mgmt-network SDK.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_logs, monitor.query_metrics,
    resourcehealth.get_availability_status, advisor.list_recommendations,
    compute.list_vms

NOTE: Direct VNet/NSG/LB operations use azure-mgmt-network SDK wrappers
(not Azure MCP Server tools) due to the Azure MCP networking coverage gap.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry

# Lazy import — azure-mgmt-network may not be installed in all envs
try:
    from azure.mgmt.network import NetworkManagementClient
except ImportError:
    NetworkManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — connectivity check models
try:
    from azure.mgmt.network.models import (
        ConnectivityDestination,
        ConnectivityParameters,
        ConnectivitySource,
    )
except ImportError:
    ConnectivityParameters = None  # type: ignore[assignment,misc]
    ConnectivitySource = None  # type: ignore[assignment,misc]
    ConnectivityDestination = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-network-agent")
logger = logging.getLogger(__name__)

# Explicit MCP tool allowlist — no wildcards permitted.
# NOTE: azure-mgmt-network SDK (not available in Azure MCP Server).
# Direct VNet/NSG/LB operations are provided as @ai_function wrappers below.
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
    "advisor.list_recommendations",
    "compute.list_vms",
]


def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {
        "azure-mgmt-network": "azure.mgmt.network",
    }
    for pkg, module in packages.items():
        try:
            __import__(module)
            logger.info("network_tools: sdk_available | package=%s", pkg)
        except ImportError:
            logger.warning(
                "network_tools: sdk_missing | package=%s — tool will return error", pkg
            )


_log_sdk_availability()


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from an Azure resource ID.

    Args:
        resource_id: Azure resource ID in the form
            /subscriptions/{sub}/resourceGroups/{rg}/providers/{type}/{name}

    Returns:
        Subscription ID string (lowercase).

    Raises:
        ValueError: If the subscription segment cannot be found.
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        raise ValueError(
            f"Cannot extract subscription_id from resource_id: {resource_id}"
        )


@ai_function
def query_nsg_rules(
    resource_group: str,
    nsg_name: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """List effective NSG security rules for a network security group.

    Uses the azure-mgmt-network SDK (not Azure MCP Server — networking
    coverage gap). Retrieves both default and custom security rules to
    identify rule changes that may be blocking traffic (TRIAGE-003).

    Args:
        resource_group: Resource group containing the NSG.
        nsg_name: Name of the Network Security Group.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            resource_group (str): Resource group queried.
            nsg_name (str): NSG name.
            subscription_id (str): Subscription ID.
            security_rules (list): Custom security rules.
            default_security_rules (list): Default (platform) rules.
            rule_count (int): Number of custom rules.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "resource_group": resource_group,
        "nsg_name": nsg_name,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="network-agent",
        agent_id=agent_id,
        tool_name="query_nsg_rules",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if NetworkManagementClient is None:
                raise ImportError("azure-mgmt-network is not installed")

            credential = get_credential()
            client = NetworkManagementClient(credential, subscription_id)
            nsg = client.network_security_groups.get(resource_group, nsg_name)

            security_rules: List[Dict[str, Any]] = []
            for rule in nsg.security_rules or []:
                security_rules.append({
                    "name": rule.name,
                    "priority": rule.priority,
                    "direction": rule.direction,
                    "access": rule.access,
                    "protocol": rule.protocol,
                    "source_address_prefix": rule.source_address_prefix,
                    "destination_address_prefix": rule.destination_address_prefix,
                    "source_port_range": rule.source_port_range,
                    "destination_port_range": rule.destination_port_range,
                })

            default_rules: List[Dict[str, Any]] = []
            for rule in nsg.default_security_rules or []:
                default_rules.append({
                    "name": rule.name,
                    "priority": rule.priority,
                    "direction": rule.direction,
                    "access": rule.access,
                    "protocol": rule.protocol,
                    "source_address_prefix": rule.source_address_prefix,
                    "destination_address_prefix": rule.destination_address_prefix,
                    "source_port_range": rule.source_port_range,
                    "destination_port_range": rule.destination_port_range,
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_nsg_rules: complete | nsg=%s rules=%d duration_ms=%.0f",
                nsg_name,
                len(security_rules),
                duration_ms,
            )
            return {
                "resource_group": resource_group,
                "nsg_name": nsg_name,
                "subscription_id": subscription_id,
                "security_rules": security_rules,
                "default_security_rules": default_rules,
                "rule_count": len(security_rules),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_nsg_rules: failed | nsg=%s error=%s duration_ms=%.0f",
                nsg_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_group": resource_group,
                "nsg_name": nsg_name,
                "subscription_id": subscription_id,
                "security_rules": [],
                "default_security_rules": [],
                "rule_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_vnet_topology(
    resource_group: str,
    vnet_name: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Retrieve VNet address space, subnets, and peering topology.

    Uses the azure-mgmt-network SDK to inspect VNet configuration
    for routing anomalies or subnet misconfiguration.

    Args:
        resource_group: Resource group containing the VNet.
        vnet_name: Name of the Virtual Network.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            resource_group (str): Resource group queried.
            vnet_name (str): VNet name.
            subscription_id (str): Subscription ID.
            address_space (list): VNet address prefixes.
            subnets (list): Subnet configurations.
            peerings (list): VNet peering connections.
            subnet_count (int): Number of subnets.
            peering_count (int): Number of peerings.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "resource_group": resource_group,
        "vnet_name": vnet_name,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="network-agent",
        agent_id=agent_id,
        tool_name="query_vnet_topology",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if NetworkManagementClient is None:
                raise ImportError("azure-mgmt-network is not installed")

            credential = get_credential()
            client = NetworkManagementClient(credential, subscription_id)
            vnet = client.virtual_networks.get(resource_group, vnet_name)

            address_prefixes = list(vnet.address_space.address_prefixes or []) if vnet.address_space else []

            subnets: List[Dict[str, Any]] = []
            for subnet in vnet.subnets or []:
                delegations = []
                for d in subnet.delegations or []:
                    delegations.append(d.service_name)
                subnets.append({
                    "name": subnet.name,
                    "address_prefix": subnet.address_prefix,
                    "nsg_id": subnet.network_security_group.id if subnet.network_security_group else None,
                    "route_table_id": subnet.route_table.id if subnet.route_table else None,
                    "delegations": delegations,
                })

            peerings: List[Dict[str, Any]] = []
            for peering in vnet.virtual_network_peerings or []:
                peerings.append({
                    "name": peering.name,
                    "peering_state": peering.peering_state,
                    "remote_vnet_id": peering.remote_virtual_network.id if peering.remote_virtual_network else None,
                    "allow_forwarded_traffic": peering.allow_forwarded_traffic,
                    "allow_gateway_transit": peering.allow_gateway_transit,
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_vnet_topology: complete | vnet=%s subnets=%d peerings=%d duration_ms=%.0f",
                vnet_name,
                len(subnets),
                len(peerings),
                duration_ms,
            )
            return {
                "resource_group": resource_group,
                "vnet_name": vnet_name,
                "subscription_id": subscription_id,
                "address_space": address_prefixes,
                "subnets": subnets,
                "peerings": peerings,
                "subnet_count": len(subnets),
                "peering_count": len(peerings),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_vnet_topology: failed | vnet=%s error=%s duration_ms=%.0f",
                vnet_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_group": resource_group,
                "vnet_name": vnet_name,
                "subscription_id": subscription_id,
                "address_space": [],
                "subnets": [],
                "peerings": [],
                "subnet_count": 0,
                "peering_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_load_balancer_health(
    resource_group: str,
    lb_name: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Get load balancer health probe configuration and backend pool status.

    Uses the azure-mgmt-network SDK to retrieve health probe settings,
    backend address pool configuration, load balancing rules, and
    frontend IP configurations.

    Args:
        resource_group: Resource group containing the load balancer.
        lb_name: Name of the load balancer.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            resource_group (str): Resource group queried.
            lb_name (str): Load balancer name.
            subscription_id (str): Subscription ID.
            health_probes (list): Health probe configurations.
            backend_pools (list): Backend address pool members.
            load_balancing_rules (list): Load balancing rule configs.
            frontend_configs (list): Frontend IP configurations.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "resource_group": resource_group,
        "lb_name": lb_name,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="network-agent",
        agent_id=agent_id,
        tool_name="query_load_balancer_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if NetworkManagementClient is None:
                raise ImportError("azure-mgmt-network is not installed")

            credential = get_credential()
            client = NetworkManagementClient(credential, subscription_id)
            lb = client.load_balancers.get(resource_group, lb_name)

            health_probes: List[Dict[str, Any]] = []
            for probe in lb.probes or []:
                health_probes.append({
                    "name": probe.name,
                    "protocol": probe.protocol,
                    "port": probe.port,
                    "interval_in_seconds": probe.interval_in_seconds,
                    "number_of_probes": probe.number_of_probes,
                    "request_path": probe.request_path,
                })

            backend_pools: List[Dict[str, Any]] = []
            for pool in lb.backend_address_pools or []:
                backend_pools.append({
                    "name": pool.name,
                    "backend_ip_config_count": len(pool.backend_ip_configurations) if pool.backend_ip_configurations else 0,
                })

            lb_rules: List[Dict[str, Any]] = []
            for rule in lb.load_balancing_rules or []:
                lb_rules.append({
                    "name": rule.name,
                    "frontend_port": rule.frontend_port,
                    "backend_port": rule.backend_port,
                    "protocol": rule.protocol,
                    "idle_timeout_in_minutes": rule.idle_timeout_in_minutes,
                    "enable_floating_ip": rule.enable_floating_ip,
                    "load_distribution": rule.load_distribution,
                })

            frontend_configs: List[Dict[str, Any]] = []
            for fip in lb.frontend_ip_configurations or []:
                frontend_configs.append({
                    "name": fip.name,
                    "private_ip_address": fip.private_ip_address,
                    "public_ip_address_id": fip.public_ip_address.id if fip.public_ip_address else None,
                    "subnet_id": fip.subnet.id if fip.subnet else None,
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_load_balancer_health: complete | lb=%s probes=%d pools=%d duration_ms=%.0f",
                lb_name,
                len(health_probes),
                len(backend_pools),
                duration_ms,
            )
            return {
                "resource_group": resource_group,
                "lb_name": lb_name,
                "subscription_id": subscription_id,
                "health_probes": health_probes,
                "backend_pools": backend_pools,
                "load_balancing_rules": lb_rules,
                "frontend_configs": frontend_configs,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_load_balancer_health: failed | lb=%s error=%s duration_ms=%.0f",
                lb_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_group": resource_group,
                "lb_name": lb_name,
                "subscription_id": subscription_id,
                "health_probes": [],
                "backend_pools": [],
                "load_balancing_rules": [],
                "frontend_configs": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_peering_status(
    resource_group: str,
    vnet_name: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Check VNet peering connection states for connectivity issues.

    Uses the azure-mgmt-network SDK to retrieve peering state
    (Connected/Disconnected/Initiated/Updating) for all peerings.

    Args:
        resource_group: Resource group containing the VNet.
        vnet_name: Name of the Virtual Network to check peerings for.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            resource_group (str): Resource group queried.
            vnet_name (str): VNet name.
            subscription_id (str): Subscription ID.
            peerings (list): Peering objects with state and remote VNet.
            peering_count (int): Number of peerings.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "resource_group": resource_group,
        "vnet_name": vnet_name,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="network-agent",
        agent_id=agent_id,
        tool_name="query_peering_status",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if NetworkManagementClient is None:
                raise ImportError("azure-mgmt-network is not installed")

            credential = get_credential()
            client = NetworkManagementClient(credential, subscription_id)
            peering_list = client.virtual_network_peerings.list(resource_group, vnet_name)

            peerings: List[Dict[str, Any]] = []
            for peering in peering_list:
                peerings.append({
                    "name": peering.name,
                    "peering_state": peering.peering_state,
                    "remote_virtual_network_id": peering.remote_virtual_network.id if peering.remote_virtual_network else None,
                    "allow_virtual_network_access": peering.allow_virtual_network_access,
                    "allow_forwarded_traffic": peering.allow_forwarded_traffic,
                    "allow_gateway_transit": peering.allow_gateway_transit,
                    "use_remote_gateways": peering.use_remote_gateways,
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_peering_status: complete | vnet=%s peerings=%d duration_ms=%.0f",
                vnet_name,
                len(peerings),
                duration_ms,
            )
            return {
                "resource_group": resource_group,
                "vnet_name": vnet_name,
                "subscription_id": subscription_id,
                "peerings": peerings,
                "peering_count": len(peerings),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_peering_status: failed | vnet=%s error=%s duration_ms=%.0f",
                vnet_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_group": resource_group,
                "vnet_name": vnet_name,
                "subscription_id": subscription_id,
                "peerings": [],
                "peering_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_flow_logs(
    resource_group: str,
    network_watcher_name: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Query NSG flow log configurations for a Network Watcher.

    Retrieves flow log configuration metadata (not raw flow data — that
    resides in Log Analytics / storage). Useful for verifying that flow
    logging is enabled and correctly configured for network forensics.

    Args:
        resource_group: Resource group containing the Network Watcher.
        network_watcher_name: Name of the Network Watcher.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            resource_group (str): Resource group queried.
            network_watcher_name (str): Network Watcher name.
            subscription_id (str): Subscription ID.
            flow_logs (list): Flow log configuration objects.
            flow_log_count (int): Number of flow logs.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "resource_group": resource_group,
        "network_watcher_name": network_watcher_name,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="network-agent",
        agent_id=agent_id,
        tool_name="query_flow_logs",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if NetworkManagementClient is None:
                raise ImportError("azure-mgmt-network is not installed")

            credential = get_credential()
            client = NetworkManagementClient(credential, subscription_id)
            flow_log_list = client.flow_logs.list(resource_group, network_watcher_name)

            flow_logs: List[Dict[str, Any]] = []
            for fl in flow_log_list:
                retention = None
                if fl.retention_policy:
                    retention = {
                        "enabled": fl.retention_policy.enabled,
                        "days": fl.retention_policy.days,
                    }

                fmt = None
                if fl.format:
                    fmt = {
                        "type": fl.format.type,
                        "version": fl.format.version,
                    }

                analytics_config = None
                if fl.flow_analytics_configuration and fl.flow_analytics_configuration.network_watcher_flow_analytics_configuration:
                    nwfac = fl.flow_analytics_configuration.network_watcher_flow_analytics_configuration
                    analytics_config = {
                        "enabled": nwfac.enabled,
                        "workspace_id": nwfac.workspace_id,
                        "traffic_analytics_interval": nwfac.traffic_analytics_interval,
                    }

                flow_logs.append({
                    "name": fl.name,
                    "target_resource_id": fl.target_resource_id,
                    "storage_id": fl.storage_id,
                    "enabled": fl.enabled,
                    "retention_policy": retention,
                    "format": fmt,
                    "flow_analytics_configuration": analytics_config,
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_flow_logs: complete | watcher=%s flow_logs=%d duration_ms=%.0f",
                network_watcher_name,
                len(flow_logs),
                duration_ms,
            )
            return {
                "resource_group": resource_group,
                "network_watcher_name": network_watcher_name,
                "subscription_id": subscription_id,
                "flow_logs": flow_logs,
                "flow_log_count": len(flow_logs),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_flow_logs: failed | watcher=%s error=%s duration_ms=%.0f",
                network_watcher_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_group": resource_group,
                "network_watcher_name": network_watcher_name,
                "subscription_id": subscription_id,
                "flow_logs": [],
                "flow_log_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_expressroute_health(
    resource_group: str,
    circuit_name: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Check ExpressRoute circuit provisioning state and BGP peering health.

    Retrieves the circuit's provisioning state, service provider state,
    SKU, bandwidth, and all BGP peerings with their operational status.

    Args:
        resource_group: Resource group containing the ExpressRoute circuit.
        circuit_name: Name of the ExpressRoute circuit.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            resource_group (str): Resource group queried.
            circuit_name (str): Circuit name.
            subscription_id (str): Subscription ID.
            provisioning_state (str): Circuit provisioning state.
            service_provider_state (str): Provider provisioning state.
            sku (dict): SKU details (name, tier, family).
            bandwidth_mbps (int): Bandwidth in Mbps.
            peerings (list): BGP peering objects.
            peering_count (int): Number of peerings.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "resource_group": resource_group,
        "circuit_name": circuit_name,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="network-agent",
        agent_id=agent_id,
        tool_name="query_expressroute_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if NetworkManagementClient is None:
                raise ImportError("azure-mgmt-network is not installed")

            credential = get_credential()
            client = NetworkManagementClient(credential, subscription_id)
            circuit = client.express_route_circuits.get(resource_group, circuit_name)

            sku_info = None
            if circuit.sku:
                sku_info = {
                    "name": circuit.sku.name,
                    "tier": circuit.sku.tier,
                    "family": circuit.sku.family,
                }

            peerings: List[Dict[str, Any]] = []
            for peering in circuit.peerings or []:
                peerings.append({
                    "name": peering.name,
                    "peering_type": peering.peering_type,
                    "state": peering.state,
                    "azure_asn": peering.azure_asn,
                    "peer_asn": peering.peer_asn,
                    "primary_peer_address_prefix": peering.primary_peer_address_prefix,
                    "secondary_peer_address_prefix": peering.secondary_peer_address_prefix,
                    "vlan_id": peering.vlan_id,
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_expressroute_health: complete | circuit=%s state=%s peerings=%d duration_ms=%.0f",
                circuit_name,
                circuit.circuit_provisioning_state,
                len(peerings),
                duration_ms,
            )
            return {
                "resource_group": resource_group,
                "circuit_name": circuit_name,
                "subscription_id": subscription_id,
                "provisioning_state": circuit.circuit_provisioning_state,
                "service_provider_state": circuit.service_provider_provisioning_state,
                "sku": sku_info,
                "bandwidth_mbps": circuit.bandwidth_in_mbps,
                "peerings": peerings,
                "peering_count": len(peerings),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_expressroute_health: failed | circuit=%s error=%s duration_ms=%.0f",
                circuit_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "resource_group": resource_group,
                "circuit_name": circuit_name,
                "subscription_id": subscription_id,
                "provisioning_state": None,
                "service_provider_state": None,
                "sku": None,
                "bandwidth_mbps": None,
                "peerings": [],
                "peering_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def check_connectivity(
    source_resource_id: str,
    destination_address: str,
    destination_port: int,
    network_watcher_resource_group: str,
    network_watcher_name: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Diagnose network connectivity between a source VM and a destination.

    Uses Network Watcher's connectivity check (LRO) to determine whether
    a source VM can reach a destination address:port. Returns hop-by-hop
    trace with latency and any issues encountered.

    Note: The source VM must have the Network Watcher extension installed.
    This is a diagnostic (read-only) operation, not a mutation.

    Args:
        source_resource_id: Azure resource ID of the source VM.
        destination_address: Destination IP address or FQDN.
        destination_port: Destination TCP port.
        network_watcher_resource_group: Resource group of the Network Watcher.
        network_watcher_name: Name of the Network Watcher.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            source_resource_id (str): Source VM resource ID.
            destination_address (str): Destination address.
            destination_port (int): Destination port.
            connection_status (str): "Reachable" or "Unreachable".
            avg_latency_ms (int | None): Average latency.
            min_latency_ms (int | None): Minimum latency.
            max_latency_ms (int | None): Maximum latency.
            probes_sent (int | None): Number of probes sent.
            probes_failed (int | None): Number of probes failed.
            hops (list): Hop-by-hop trace.
            hop_count (int): Number of hops.
            query_status (str): "success", "timeout", or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "source_resource_id": source_resource_id,
        "destination_address": destination_address,
        "destination_port": destination_port,
        "network_watcher_resource_group": network_watcher_resource_group,
        "network_watcher_name": network_watcher_name,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="network-agent",
        agent_id=agent_id,
        tool_name="check_connectivity",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if NetworkManagementClient is None:
                raise ImportError("azure-mgmt-network is not installed")
            if ConnectivityParameters is None:
                raise ImportError("azure-mgmt-network connectivity models are not installed")

            credential = get_credential()
            client = NetworkManagementClient(credential, subscription_id)

            params = ConnectivityParameters(
                source=ConnectivitySource(resource_id=source_resource_id),
                destination=ConnectivityDestination(
                    address=destination_address,
                    port=destination_port,
                ),
            )

            poller = client.network_watchers.begin_check_connectivity(
                network_watcher_resource_group,
                network_watcher_name,
                parameters=params,
            )

            try:
                result = poller.result(timeout=120)
            except Exception as timeout_err:
                duration_ms = (time.monotonic() - start_time) * 1000
                logger.warning(
                    "check_connectivity: timeout | source=%s dest=%s:%d duration_ms=%.0f",
                    source_resource_id,
                    destination_address,
                    destination_port,
                    duration_ms,
                )
                return {
                    "source_resource_id": source_resource_id,
                    "destination_address": destination_address,
                    "destination_port": destination_port,
                    "connection_status": None,
                    "avg_latency_ms": None,
                    "min_latency_ms": None,
                    "max_latency_ms": None,
                    "probes_sent": None,
                    "probes_failed": None,
                    "hops": [],
                    "hop_count": 0,
                    "query_status": "timeout",
                    "error": "Connectivity check timed out after 120 seconds",
                }

            hops: List[Dict[str, Any]] = []
            for hop in result.hops or []:
                issues = []
                for issue in hop.issues or []:
                    issues.append({
                        "origin": issue.origin,
                        "severity": issue.severity,
                        "type": issue.type,
                        "context": [{"key": c.key, "value": c.value} for c in (issue.context or [])],
                    })
                hops.append({
                    "type": hop.type,
                    "id": hop.id,
                    "address": hop.address,
                    "issues": issues,
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "check_connectivity: complete | source=%s dest=%s:%d status=%s duration_ms=%.0f",
                source_resource_id,
                destination_address,
                destination_port,
                result.connection_status,
                duration_ms,
            )
            return {
                "source_resource_id": source_resource_id,
                "destination_address": destination_address,
                "destination_port": destination_port,
                "connection_status": result.connection_status,
                "avg_latency_ms": result.avg_latency_in_ms,
                "min_latency_ms": result.min_latency_in_ms,
                "max_latency_ms": result.max_latency_in_ms,
                "probes_sent": result.probes_sent,
                "probes_failed": result.probes_failed,
                "hops": hops,
                "hop_count": len(hops),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "check_connectivity: failed | source=%s dest=%s:%d error=%s duration_ms=%.0f",
                source_resource_id,
                destination_address,
                destination_port,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "source_resource_id": source_resource_id,
                "destination_address": destination_address,
                "destination_port": destination_port,
                "connection_status": None,
                "avg_latency_ms": None,
                "min_latency_ms": None,
                "max_latency_ms": None,
                "probes_sent": None,
                "probes_failed": None,
                "hops": [],
                "hop_count": 0,
                "query_status": "error",
                "error": str(e),
            }
