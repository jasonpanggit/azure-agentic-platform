"""Network Agent tool functions — azure-mgmt-network SDK wrappers + Monitor.

The Azure MCP Server has limited dedicated networking tools (no direct VNet/NSG/LB
tools confirmed GA). The Network Agent supplements MCP tools with @ai_function
wrappers around the azure-mgmt-network SDK.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_logs, monitor.query_metrics,
    resourcehealth.get_availability_status, advisor.list_recommendations

NOTE: Direct VNet/NSG/LB/FlowLog/ExpressRoute/Connectivity operations use
azure-mgmt-network SDK wrappers (not Azure MCP Server tools) due to the Azure
MCP networking coverage gap.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry

# Lazy import — azure-mgmt-network may not be installed in all envs
try:
    from azure.mgmt.network import NetworkManagementClient
except ImportError:
    NetworkManagementClient = None  # type: ignore[assignment,misc]

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
    subscription_id: str,
    resource_group: str,
    nsg_name: str,
) -> Dict[str, Any]:
    """List effective NSG security rules for a network security group.

    Uses the azure-mgmt-network SDK (not Azure MCP Server — networking
    coverage gap). Retrieves both default and custom security rules to
    identify rule changes that may be blocking traffic (TRIAGE-003).

    Args:
        subscription_id: Azure subscription ID containing the NSG.
        resource_group: Resource group containing the NSG.
        nsg_name: Name of the Network Security Group.

    Returns:
        Dict with keys:
            resource_group (str): Resource group queried.
            nsg_name (str): NSG name.
            provisioning_state (str): NSG provisioning state.
            security_rules (list): Custom security rules.
            default_security_rules (list): Default (platform) rules.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "nsg_name": nsg_name,
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

            client = NetworkManagementClient(get_credential(), subscription_id)
            nsg = client.network_security_groups.get(resource_group, nsg_name)

            def _map_rule(rule: Any) -> Dict[str, Any]:
                return {
                    "name": rule.name,
                    "priority": rule.priority,
                    "direction": rule.direction,
                    "access": rule.access,
                    "protocol": rule.protocol,
                    "source_address_prefix": rule.source_address_prefix,
                    "destination_address_prefix": rule.destination_address_prefix,
                    "destination_port_ranges": (
                        rule.destination_port_ranges
                        if rule.destination_port_ranges
                        else ([rule.destination_port_range] if rule.destination_port_range else [])
                    ),
                }

            security_rules = [_map_rule(r) for r in (nsg.security_rules or [])]
            default_security_rules = [_map_rule(r) for r in (nsg.default_security_rules or [])]

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_nsg_rules: complete | nsg=%s rules=%d default_rules=%d duration_ms=%.0f",
                nsg_name,
                len(security_rules),
                len(default_security_rules),
                duration_ms,
            )
            return {
                "resource_group": resource_group,
                "nsg_name": nsg_name,
                "provisioning_state": nsg.provisioning_state,
                "security_rules": security_rules,
                "default_security_rules": default_security_rules,
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
                "security_rules": [],
                "default_security_rules": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_peering_status(
    subscription_id: str,
    resource_group: str,
    vnet_name: str,
) -> Dict[str, Any]:
    """Check VNet peering connection states for connectivity issues.

    Uses the azure-mgmt-network SDK to retrieve peering state
    (Connected/Disconnected/Initiated/Updating) for all peerings.

    Args:
        subscription_id: Azure subscription ID containing the VNet.
        resource_group: Resource group containing the VNet.
        vnet_name: Name of the Virtual Network to check peerings for.

    Returns:
        Dict with keys:
            resource_group (str): Resource group queried.
            vnet_name (str): VNet name.
            peerings (list): Peering objects with state and remote VNet.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "vnet_name": vnet_name,
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

            client = NetworkManagementClient(get_credential(), subscription_id)
            peerings_iter = client.virtual_network_peerings.list(resource_group, vnet_name)

            peerings = [
                {
                    "name": p.name,
                    "peering_state": p.peering_state,
                    "remote_virtual_network_id": (
                        p.remote_virtual_network.id if p.remote_virtual_network else None
                    ),
                    "allow_virtual_network_access": p.allow_virtual_network_access,
                    "allow_forwarded_traffic": p.allow_forwarded_traffic,
                    "use_remote_gateways": p.use_remote_gateways,
                }
                for p in peerings_iter
            ]

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
                "peerings": peerings,
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
                "peerings": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_vnet_topology(
    subscription_id: str,
    resource_group: str,
    vnet_name: str,
) -> Dict[str, Any]:
    """Retrieve VNet address space, subnets, and peering topology.

    Uses the azure-mgmt-network SDK to inspect VNet configuration
    for routing anomalies or subnet misconfiguration.

    Args:
        subscription_id: Azure subscription ID containing the VNet.
        resource_group: Resource group containing the VNet.
        vnet_name: Name of the Virtual Network.

    Returns:
        Dict with keys:
            resource_group (str): Resource group queried.
            vnet_name (str): VNet name.
            provisioning_state (str): VNet provisioning state.
            address_space (list): VNet address prefixes.
            subnets (list): Subnet configurations with NSG/route table flags.
            peerings (list): VNet peering connections.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "vnet_name": vnet_name,
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

            client = NetworkManagementClient(get_credential(), subscription_id)
            vnet = client.virtual_networks.get(resource_group, vnet_name)

            address_space: List[str] = (
                vnet.address_space.address_prefixes
                if vnet.address_space and vnet.address_space.address_prefixes
                else []
            )

            subnets = [
                {
                    "name": s.name,
                    "address_prefix": s.address_prefix,
                    "nsg_attached": s.network_security_group is not None,
                    "route_table_attached": s.route_table is not None,
                    "service_endpoints": [
                        se.service for se in (s.service_endpoints or []) if se.service
                    ],
                }
                for s in (vnet.subnets or [])
            ]

            peerings = [
                {
                    "name": p.name,
                    "peering_state": p.peering_state,
                    "remote_virtual_network_id": (
                        p.remote_virtual_network.id if p.remote_virtual_network else None
                    ),
                }
                for p in (vnet.virtual_network_peerings or [])
            ]

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
                "provisioning_state": vnet.provisioning_state,
                "address_space": address_space,
                "subnets": subnets,
                "peerings": peerings,
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
                "address_space": [],
                "subnets": [],
                "peerings": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_load_balancer_health(
    subscription_id: str,
    resource_group: str,
    lb_name: str,
) -> Dict[str, Any]:
    """Get load balancer health probe configuration and backend pool status.

    Uses the azure-mgmt-network SDK to retrieve health probe settings,
    backend address pool configuration, and load balancing rules.

    Args:
        subscription_id: Azure subscription ID containing the load balancer.
        resource_group: Resource group containing the load balancer.
        lb_name: Name of the load balancer.

    Returns:
        Dict with keys:
            resource_group (str): Resource group queried.
            lb_name (str): Load balancer name.
            sku (str | None): Load balancer SKU name.
            health_probes (list): Health probe configurations.
            backend_pools (list): Backend address pool members.
            load_balancing_rules (list): Load balancing rule configurations.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "lb_name": lb_name,
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

            client = NetworkManagementClient(get_credential(), subscription_id)
            lb = client.load_balancers.get(resource_group, lb_name)

            health_probes = [
                {
                    "name": p.name,
                    "protocol": p.protocol,
                    "port": p.port,
                    "interval_in_seconds": p.interval_in_seconds,
                    "number_of_probes": p.number_of_probes,
                }
                for p in (lb.probes or [])
            ]

            backend_pools = [
                {
                    "name": pool.name,
                    "ip_configurations_count": len(pool.backend_ip_configurations or []),
                }
                for pool in (lb.backend_address_pools or [])
            ]

            load_balancing_rules = [
                {
                    "name": r.name,
                    "protocol": r.protocol,
                    "frontend_port": r.frontend_port,
                    "backend_port": r.backend_port,
                    "enable_floating_ip": r.enable_floating_ip,
                }
                for r in (lb.load_balancing_rules or [])
            ]

            sku = lb.sku.name if lb.sku else None

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
                "sku": sku,
                "health_probes": health_probes,
                "backend_pools": backend_pools,
                "load_balancing_rules": load_balancing_rules,
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
                "health_probes": [],
                "backend_pools": [],
                "load_balancing_rules": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_flow_logs(
    subscription_id: str,
    resource_group: str,
    network_watcher_name: str,
    flow_log_name: str,
) -> Dict[str, Any]:
    """Get Network Watcher flow log configuration and traffic analytics status.

    Uses the azure-mgmt-network SDK to retrieve flow log settings.
    A disabled flow log means no traffic forensics are available for
    the associated NSG — this represents a diagnostic coverage gap that
    hinders incident investigation.

    Args:
        subscription_id: Azure subscription ID.
        resource_group: Resource group containing the Network Watcher.
        network_watcher_name: Name of the Network Watcher resource.
        flow_log_name: Name of the flow log resource.

    Returns:
        Dict with keys:
            flow_log_name (str): Flow log name.
            enabled (bool): Whether flow logging is active.
            storage_id (str | None): Storage account resource ID for logs.
            retention_days (int | None): Log retention period in days.
            traffic_analytics_enabled (bool): Whether traffic analytics is on.
            workspace_id (str | None): Log Analytics workspace for analytics.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "network_watcher_name": network_watcher_name,
        "flow_log_name": flow_log_name,
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

            client = NetworkManagementClient(get_credential(), subscription_id)
            fl = client.flow_logs.get(resource_group, network_watcher_name, flow_log_name)

            retention_days = (
                fl.retention_policy.days if fl.retention_policy else None
            )

            traffic_analytics_enabled = False
            workspace_id = None
            if fl.flow_analytics_configuration:
                nwfac = fl.flow_analytics_configuration.network_watcher_flow_analytics_configuration
                if nwfac:
                    traffic_analytics_enabled = bool(nwfac.enabled)
                    workspace_id = getattr(nwfac, "workspace_id", None)

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_flow_logs: complete | flow_log=%s enabled=%s duration_ms=%.0f",
                flow_log_name,
                fl.enabled,
                duration_ms,
            )
            return {
                "flow_log_name": flow_log_name,
                "enabled": fl.enabled,
                "storage_id": fl.storage_id,
                "retention_days": retention_days,
                "traffic_analytics_enabled": traffic_analytics_enabled,
                "workspace_id": workspace_id,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_flow_logs: failed | flow_log=%s error=%s duration_ms=%.0f",
                flow_log_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "flow_log_name": flow_log_name,
                "enabled": False,
                "storage_id": None,
                "retention_days": None,
                "traffic_analytics_enabled": False,
                "workspace_id": None,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_expressroute_circuit(
    subscription_id: str,
    resource_group: str,
    circuit_name: str,
) -> Dict[str, Any]:
    """Get ExpressRoute circuit status for hybrid connectivity incident diagnosis.

    Uses the azure-mgmt-network SDK to retrieve ExpressRoute circuit
    configuration, provisioning state, and BGP peering status. Use this
    tool when investigating connectivity issues between on-premises networks
    and Azure resources via ExpressRoute.

    Args:
        subscription_id: Azure subscription ID.
        resource_group: Resource group containing the ExpressRoute circuit.
        circuit_name: Name of the ExpressRoute circuit.

    Returns:
        Dict with keys:
            circuit_name (str): Circuit name.
            service_provider (str | None): Service provider name.
            peering_location (str | None): Peering location.
            bandwidth_mbps (int | None): Circuit bandwidth in Mbps.
            circuit_provisioning_state (str | None): Circuit provisioning state.
            service_provider_provisioning_state (str | None): Provider state.
            sku (str | None): Circuit SKU name.
            peerings (list): BGP peering configurations.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "circuit_name": circuit_name,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="network-agent",
        agent_id=agent_id,
        tool_name="query_expressroute_circuit",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if NetworkManagementClient is None:
                raise ImportError("azure-mgmt-network is not installed")

            client = NetworkManagementClient(get_credential(), subscription_id)
            circuit = client.express_route_circuits.get(resource_group, circuit_name)

            spp = circuit.service_provider_properties
            service_provider = spp.service_provider_name if spp else None
            peering_location = spp.peering_location if spp else None
            bandwidth_mbps = spp.bandwidth_in_mbps if spp else None

            peerings = [
                {
                    "name": p.name,
                    "peering_type": p.peering_type,
                    "state": p.state,
                }
                for p in (circuit.peerings or [])
            ]

            sku = circuit.sku.name if circuit.sku else None

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_expressroute_circuit: complete | circuit=%s provider=%s duration_ms=%.0f",
                circuit_name,
                service_provider,
                duration_ms,
            )
            return {
                "circuit_name": circuit_name,
                "service_provider": service_provider,
                "peering_location": peering_location,
                "bandwidth_mbps": bandwidth_mbps,
                "circuit_provisioning_state": circuit.circuit_provisioning_state,
                "service_provider_provisioning_state": circuit.service_provider_provisioning_state,
                "sku": sku,
                "peerings": peerings,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_expressroute_circuit: failed | circuit=%s error=%s duration_ms=%.0f",
                circuit_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "circuit_name": circuit_name,
                "service_provider": None,
                "peering_location": None,
                "bandwidth_mbps": None,
                "circuit_provisioning_state": None,
                "service_provider_provisioning_state": None,
                "sku": None,
                "peerings": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def run_connectivity_check(
    subscription_id: str,
    source_resource_id: str,
    destination_address: str,
    destination_port: int,
    network_watcher_rg: str,
    network_watcher_name: str,
) -> Dict[str, Any]:
    """Run a Network Watcher connectivity check between a source VM and destination.

    Uses the azure-mgmt-network SDK long-running operation (LRO) pattern to
    initiate and poll a connectivity check. The source VM must be running
    (not deallocated) for the check to succeed.

    Requirements:
        - Caller must have Network Contributor or a custom role on the Network Watcher.
        - Source VM must be in a running (not deallocated) state.
        - LRO timeout is 60 seconds; long-running checks will raise on timeout.

    Args:
        subscription_id: Azure subscription ID.
        source_resource_id: Resource ID of the source VM.
        destination_address: IP address or FQDN of the destination.
        destination_port: TCP port number to test connectivity to.
        network_watcher_rg: Resource group of the Network Watcher.
        network_watcher_name: Name of the Network Watcher resource.

    Returns:
        Dict with keys:
            connection_status (str | None): "Reachable" or "Unreachable".
            avg_latency_ms (int | None): Average round-trip latency in ms.
            min_latency_ms (int | None): Minimum latency observed.
            max_latency_ms (int | None): Maximum latency observed.
            probes_sent (int | None): Number of probes sent.
            probes_failed (int | None): Number of probes that failed.
            hops (list): Network hop addresses along the path.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "source_resource_id": source_resource_id,
        "destination_address": destination_address,
        "destination_port": destination_port,
        "network_watcher_rg": network_watcher_rg,
        "network_watcher_name": network_watcher_name,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="network-agent",
        agent_id=agent_id,
        tool_name="run_connectivity_check",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if NetworkManagementClient is None:
                raise ImportError("azure-mgmt-network is not installed")

            client = NetworkManagementClient(get_credential(), subscription_id)
            poller = client.network_watchers.begin_check_connectivity(
                network_watcher_rg,
                network_watcher_name,
                {
                    "source": {"resource_id": source_resource_id},
                    "destination": {
                        "address": destination_address,
                        "port": destination_port,
                    },
                },
            )
            result = poller.result(timeout=60)

            hops = [
                hop.address
                for hop in (result.hops or [])
                if hop.address
            ]

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "run_connectivity_check: complete | source=%s dest=%s:%d status=%s duration_ms=%.0f",
                source_resource_id,
                destination_address,
                destination_port,
                result.connection_status,
                duration_ms,
            )
            return {
                "connection_status": result.connection_status,
                "avg_latency_ms": result.avg_latency_in_ms,
                "min_latency_ms": result.min_latency_in_ms,
                "max_latency_ms": result.max_latency_in_ms,
                "probes_sent": result.probes_sent,
                "probes_failed": result.probes_failed,
                "hops": hops,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "run_connectivity_check: failed | source=%s dest=%s error=%s duration_ms=%.0f",
                source_resource_id,
                destination_address,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "connection_status": None,
                "avg_latency_ms": None,
                "min_latency_ms": None,
                "max_latency_ms": None,
                "probes_sent": None,
                "probes_failed": None,
                "hops": [],
                "query_status": "error",
                "error": str(e),
            }
