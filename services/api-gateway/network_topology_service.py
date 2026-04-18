from __future__ import annotations
"""Network Topology Service — Phase 103 Sprint 3.

Queries Azure Resource Graph for VNets, subnets, NSGs, LBs, private endpoints,
gateways, NICs, route tables, NAT gateways, local gateways, VPN connections,
AppGW backends, and firewall policies to assemble a graph representation of
the network topology.  Includes NSG health scoring and path-check evaluation.

Never raises from public functions — errors are logged and empty/partial
results returned to keep the API gateway fault-tolerant.
"""

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from services.api_gateway.arg_helper import run_arg_query
except ImportError:
    run_arg_query = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# ARG Query Constants
# ---------------------------------------------------------------------------

_VNET_SUBNET_QUERY = """
Resources
| where type =~ "microsoft.network/virtualnetworks"
| extend addressSpace = tostring(properties.addressSpace.addressPrefixes)
| mv-expand subnet = properties.subnets
| extend subnetName = tostring(subnet.name)
| extend subnetPrefix = tostring(subnet.properties.addressPrefix)
| extend subnetNsgId = tolower(tostring(subnet.properties.networkSecurityGroup.id))
| extend subnetRouteTableId = tolower(tostring(subnet.properties.routeTable.id))
| extend subnetNatGatewayId = tolower(tostring(subnet.properties.natGateway.id))
| project subscriptionId, resourceGroup, vnetName = name, id,
          addressSpace, subnetName, subnetPrefix, subnetNsgId, location,
          subnetRouteTableId, subnetNatGatewayId
"""

_NSG_RULES_QUERY = """
Resources
| where type =~ "microsoft.network/networksecuritygroups"
| mv-expand rule = properties.securityRules
| project subscriptionId, resourceGroup, nsgName = name, nsgId = tolower(id),
          ruleName = tostring(rule.name),
          priority = toint(rule.properties.priority),
          direction = tostring(rule.properties.direction),
          access = tostring(rule.properties.access),
          protocol = tostring(rule.properties.protocol),
          sourcePrefix = tostring(rule.properties.sourceAddressPrefix),
          sourcePrefixes = rule.properties.sourceAddressPrefixes,
          destPrefix = tostring(rule.properties.destinationAddressPrefix),
          destPrefixes = rule.properties.destinationAddressPrefixes,
          destPortRange = tostring(rule.properties.destinationPortRange),
          destPortRanges = rule.properties.destinationPortRanges
"""

_LB_QUERY = """
Resources
| where type =~ "microsoft.network/loadbalancers"
| mv-expand fip = properties.frontendIPConfigurations
| extend frontendIp = tostring(fip.properties.privateIPAddress)
| extend publicIpId = tolower(tostring(fip.properties.publicIPAddress.id))
| project subscriptionId, resourceGroup, name, id, location,
          sku_name = tostring(sku.name), frontendIp, publicIpId
"""

_LB_BACKEND_QUERY = """
Resources
| where type == "microsoft.network/loadbalancers"
| where array_length(properties.backendAddressPools) > 0
| mv-expand pool = properties.backendAddressPools
| mv-expand ipc = pool.properties.backendIPConfigurations
| extend nicIpConfigId = tolower(tostring(ipc.id))
| extend nicId = tolower(tostring(strcat_array(array_slice(split(nicIpConfigId, "/"), 0, 9), "/")))
| extend lbId = tolower(id)
| project lbId, nicId
| where isnotempty(nicId)
"""

_PE_QUERY = """
Resources
| where type =~ "microsoft.network/privateendpoints"
| extend subnetId = tolower(tostring(properties.subnet.id))
| mv-expand conn = properties.privateLinkServiceConnections
| extend targetResourceId = tolower(tostring(conn.properties.privateLinkServiceId))
| extend groupIds = tostring(conn.properties.groupIds)
| extend connectionState = tostring(conn.properties.privateLinkServiceConnectionState.status)
| project subscriptionId, resourceGroup, name, id, location,
          subnetId, targetResourceId, groupIds, connectionState
"""

_GATEWAY_QUERY = """
Resources
| where type =~ "microsoft.network/virtualnetworkgateways"
| extend gatewayType = tostring(properties.gatewayType)
| extend vpnType = tostring(properties.vpnType)
| extend sku_name = tostring(properties.sku.name)
| extend bgp_enabled = tobool(properties.enableBgp)
| extend provisioningState = tostring(properties.provisioningState)
| mv-expand ipConfig = properties.ipConfigurations
| extend subnetId = tolower(tostring(ipConfig.properties.subnet.id))
| extend publicIpId = tolower(tostring(ipConfig.properties.publicIPAddress.id))
| project subscriptionId, resourceGroup, name, id, location,
          gatewayType, vpnType, sku_name, bgp_enabled, subnetId, publicIpId,
          provisioningState
"""

_PUBLIC_IP_QUERY = """
Resources
| where type =~ "microsoft.network/publicipaddresses"
| extend ipAddress = tostring(properties.ipAddress)
| extend allocationMethod = tostring(properties.publicIPAllocationMethod)
| extend sku_name = tostring(sku.name)
| extend domainNameLabel = tostring(properties.dnsSettings.domainNameLabel)
| project subscriptionId, name, id = tolower(id), ipAddress, allocationMethod,
          sku_name, domainNameLabel
"""

_NIC_NSG_QUERY = """
Resources
| where type =~ "microsoft.network/networkinterfaces"
| extend subnetId = tolower(tostring(properties.ipConfigurations[0].properties.subnet.id))
| extend nsgId = tolower(tostring(properties.networkSecurityGroup.id))
| extend privateIp = tostring(properties.ipConfigurations[0].properties.privateIPAddress)
| where isnotempty(nsgId)
| project subscriptionId, resourceGroup, name, id = tolower(id),
          subnetId, nsgId, privateIp
"""

_VM_QUERY = """
Resources
| where type =~ "microsoft.compute/virtualmachines"
| mv-expand nicRef = properties.networkProfile.networkInterfaces
| extend nicId = tolower(tostring(nicRef.id))
| project subscriptionId, resourceGroup, vmName = name, vmId = tolower(id), location,
          vmSize = tostring(properties.hardwareProfile.vmSize),
          osType = tostring(properties.storageProfile.osDisk.osType),
          nicId
"""

_VMSS_QUERY = """
Resources
| where type =~ "microsoft.compute/virtualmachinescalesets"
| extend subnetId = tolower(tostring(properties.virtualMachineProfile.networkProfile.networkInterfaceConfigurations[0].properties.ipConfigurations[0].properties.subnet.id))
| project subscriptionId, resourceGroup, name, id = tolower(id), location,
          sku_name = tostring(sku.name), capacity = toint(sku.capacity),
          subnetId
"""

_AKS_QUERY = """
Resources
| where type =~ "microsoft.containerservice/managedclusters"
| mv-expand pool = properties.agentPoolProfiles
| extend subnetId = tolower(tostring(pool.properties.vnetSubnetID)), poolName = tostring(pool.name)
| project subscriptionId, resourceGroup, name, id = tolower(id), location,
          kubernetesVersion = tostring(properties.kubernetesVersion),
          nodeCount = toint(pool.count),
          provisioningState = tostring(properties.provisioningState),
          subnetId, poolName
"""

_FIREWALL_QUERY = """
Resources
| where type =~ "microsoft.network/azurefirewalls"
| mv-expand ipConfig = properties.ipConfigurations
| extend subnetId = tolower(tostring(ipConfig.properties.subnet.id))
| extend privateIp = tostring(ipConfig.properties.privateIPAddress)
| extend firewallPolicyId = tolower(tostring(properties.firewallPolicy.id))
| extend mgmtSubnetId = tolower(tostring(properties.managementIpConfiguration.properties.subnet.id))
| extend threatIntelMode = tostring(properties.threatIntelMode)
| extend provisioningState = tostring(properties.provisioningState)
| project subscriptionId, resourceGroup, name, id = tolower(id), location,
          sku_tier = tostring(properties.sku.tier),
          threatIntelMode, subnetId, privateIp,
          firewallPolicyId, mgmtSubnetId, provisioningState
"""

_APP_GATEWAY_QUERY = """
Resources
| where type =~ "microsoft.network/applicationgateways"
| mv-expand ipConfig = properties.gatewayIPConfigurations
| extend subnetId = tolower(tostring(ipConfig.properties.subnet.id))
| extend provisioningState = tostring(properties.provisioningState)
| extend httpListeners = array_length(properties.httpListeners)
| extend requestRoutingRules = array_length(properties.requestRoutingRules)
| extend frontendPublicIpId = tolower(tostring(properties.frontendIPConfigurations[0].properties.publicIPAddress.id))
| project subscriptionId, resourceGroup, name, id = tolower(id), location,
          sku_name = tostring(properties.sku.name),
          sku_tier = tostring(properties.sku.tier),
          capacity = toint(properties.sku.capacity),
          subnetId, provisioningState,
          listenerCount = httpListeners,
          routeRuleCount = requestRoutingRules,
          frontendPublicIpId
"""

_APP_GATEWAY_BACKEND_QUERY = """
Resources
| where type =~ "microsoft.network/applicationgateways"
| mv-expand pool = properties.backendAddressPools
| mv-expand addr = pool.properties.backendAddresses
| extend appgwId = tolower(id)
| extend targetFqdn = tostring(addr.fqdn)
| extend targetIp = tostring(addr.ipAddress)
| project appgwId, targetFqdn, targetIp
| where isnotempty(targetFqdn) or isnotempty(targetIp)
"""

_VNET_PEERING_QUERY = """
Resources
| where type =~ "microsoft.network/virtualnetworks"
| mv-expand peering = properties.virtualNetworkPeerings
| where isnotnull(peering)
| extend peeringName = tostring(peering.name)
| extend remoteVnetId = tolower(tostring(peering.properties.remoteVirtualNetwork.id))
| extend peeringState = tostring(peering.properties.peeringState)
| extend allowForwardedTraffic = tobool(peering.properties.allowForwardedTraffic)
| extend allowGatewayTransit = tobool(peering.properties.allowGatewayTransit)
| project subscriptionId, resourceGroup, vnetId = tolower(id), vnetName = name,
          peeringName, remoteVnetId, peeringState,
          allowForwardedTraffic, allowGatewayTransit
"""

_NIC_SUBNET_QUERY = """
Resources
| where type =~ "microsoft.network/networkinterfaces"
| extend subnetId = tolower(tostring(properties.ipConfigurations[0].properties.subnet.id))
| extend privateIp = tostring(properties.ipConfigurations[0].properties.privateIPAddress)
| extend nsgId = tolower(tostring(properties.networkSecurityGroup.id))
| project subscriptionId, resourceGroup, nicId = tolower(id), subnetId, privateIp, nsgId
"""

_ROUTE_TABLE_QUERY = """
Resources
| where type == "microsoft.network/routetables"
| extend rtId = tolower(id)
| extend name = tostring(name)
| extend location = tostring(location)
| extend routeCount = array_length(properties.routes)
| project rtId, name, location, routeCount
"""

_LOCAL_NETWORK_GATEWAY_QUERY = """
Resources
| where type == "microsoft.network/localnetworkgateways"
| extend lgwId = tolower(id)
| extend name = tostring(name)
| extend gatewayIp = tostring(properties.gatewayIpAddress)
| extend addressPrefixes = tostring(properties.localNetworkAddressSpace.addressPrefixes)
| project lgwId, name, gatewayIp, addressPrefixes
"""

_VPN_CONNECTION_QUERY = """
Resources
| where type == "microsoft.network/connections"
| extend connId = tolower(id)
| extend name = tostring(name)
| extend connectionType = tostring(properties.connectionType)
| extend connectionStatus = tostring(properties.connectionStatus)
| extend vngId = tolower(tostring(properties.virtualNetworkGateway1.id))
| extend lngId = tolower(tostring(properties.localNetworkGateway2.id))
| extend peerId = tolower(tostring(properties.virtualNetworkGateway2.id))
| project connId, name, connectionType, connectionStatus, vngId, lngId, peerId
"""

_NAT_GATEWAY_QUERY = """
Resources
| where type == "microsoft.network/natgateways"
| extend natId = tolower(id)
| extend name = tostring(name)
| extend idleTimeoutMinutes = toint(properties.idleTimeoutInMinutes)
| extend provisioningState = tostring(properties.provisioningState)
| project natId, name, idleTimeoutMinutes, provisioningState
"""

# ---------------------------------------------------------------------------
# In-memory LRU Cache (H-10)
# ---------------------------------------------------------------------------

_TOPOLOGY_TTL_SECONDS = 900
_CACHE_MAX_SIZE = 50  # max subscription-set combinations cached
_cache: OrderedDict = OrderedDict()
_cache_lock = threading.Lock()


def _cache_put(key: str, value: Any) -> None:
    """Insert or update a cache entry with LRU eviction."""
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX_SIZE:
            _cache.popitem(last=False)


def _cache_get(key: str) -> Any:
    """Return cached value and move to end (most-recently-used), or None."""
    with _cache_lock:
        if key not in _cache:
            return None
        _cache.move_to_end(key)
        return _cache[key]


def _get_cached_or_fetch(key: str, ttl: int, fetch_fn: Any) -> Any:
    """Return cached value if within TTL, otherwise call fetch_fn and cache.

    Empty topology results (nodes=[]) are cached with a short 60s TTL so a
    transient startup race or a bad query doesn't poison the cache for 15 min.
    """
    cached_entry = _cache_get(key)
    if cached_entry is not None:
        cached_time, cached_value = cached_entry
        if time.monotonic() - cached_time < ttl:
            return cached_value

    result = fetch_fn()
    # Don't cache empty topology for the full TTL — retry quickly on next request
    effective_ttl = 60 if (isinstance(result, dict) and not result.get("nodes")) else ttl
    _cache_put(key, (time.monotonic() - (ttl - effective_ttl), result))
    return result


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

_COMMON_PORTS = [22, 80, 443, 3389]


def _score_nsg_health(nsg_rules: List[Dict[str, Any]]) -> str:
    """Score NSG health: 'green', 'yellow', or 'red'.

    Yellow if any rule has source='*', destPortRange='*', access='Allow', priority < 1000.
    Green otherwise. Red is set externally by _detect_asymmetries.
    """
    for rule in nsg_rules:
        access = str(rule.get("access", "")).lower()
        source = str(rule.get("sourcePrefix", ""))
        dest_port = str(rule.get("destPortRange", ""))
        priority = rule.get("priority", 65500)
        if access == "allow" and source == "*" and dest_port == "*" and isinstance(priority, int) and priority < 1000:
            return "yellow"
    return "green"


def _score_resource_health(provisioning_state: str) -> str:
    """Score resource health based on provisioning state (H-9).

    - 'Succeeded' or 'Running' → 'green'
    - 'Updating', 'Creating', 'Scaling' → 'yellow'
    - Anything else (Failed, Deleting, Unknown, empty) → 'red'
    """
    state = provisioning_state.strip().lower()
    if state in ("succeeded", "running"):
        return "green"
    if state in ("updating", "creating", "scaling"):
        return "yellow"
    return "red"


def _port_in_range(port: int, range_str: str, ranges_list: Any = None) -> bool:
    """Check if port matches a port range specification."""
    if range_str == "*":
        return True
    # Check single range_str
    if _check_single_range(port, range_str):
        return True
    # Check ranges_list (comma-separated or list)
    if ranges_list:
        if isinstance(ranges_list, str):
            for part in ranges_list.split(","):
                if _check_single_range(port, part.strip()):
                    return True
        elif isinstance(ranges_list, list):
            for part in ranges_list:
                if _check_single_range(port, str(part).strip()):
                    return True
    return False


def _check_single_range(port: int, range_str: str) -> bool:
    """Check if port is in a single range like '80', '1024-65535', or '*'."""
    if not range_str:
        return False
    if range_str == "*":
        return True
    if "-" in range_str:
        parts = range_str.split("-", 1)
        try:
            return int(parts[0]) <= port <= int(parts[1])
        except (ValueError, IndexError):
            return False
    try:
        return int(range_str) == port
    except ValueError:
        return False


def _matches_rule(rule: Dict[str, Any], port: int, protocol: str, src_prefix: str, dst_prefix: str) -> bool:
    """Check if a single NSG rule matches the given traffic parameters."""
    # Protocol match
    rule_protocol = str(rule.get("protocol", "*"))
    if rule_protocol != "*" and rule_protocol.upper() != protocol.upper():
        return False

    # Port match
    dest_port_range = str(rule.get("destPortRange", ""))
    dest_port_ranges = rule.get("destPortRanges")
    if not _port_in_range(port, dest_port_range, dest_port_ranges):
        return False

    # Source prefix match (simplified: * matches all, or exact match)
    rule_source = str(rule.get("sourcePrefix", "*"))
    if rule_source != "*" and rule_source != src_prefix and src_prefix != "*":
        # Check sourcePrefixes list
        source_prefixes = rule.get("sourcePrefixes") or []
        if isinstance(source_prefixes, list) and src_prefix not in source_prefixes and "*" not in source_prefixes:
            return False
        elif not isinstance(source_prefixes, list):
            return False

    # Dest prefix match
    rule_dest = str(rule.get("destPrefix", "*"))
    if rule_dest != "*" and rule_dest != dst_prefix and dst_prefix != "*":
        dest_prefixes = rule.get("destPrefixes") or []
        if isinstance(dest_prefixes, list) and dst_prefix not in dest_prefixes and "*" not in dest_prefixes:
            return False
        elif not isinstance(dest_prefixes, list):
            return False

    return True


def _evaluate_nsg_rules(
    rules: List[Dict[str, Any]],
    port: int,
    protocol: str,
    src_prefix: str,
    dst_prefix: str,
    direction: str,
) -> Dict[str, Any]:
    """Evaluate NSG rules sorted by priority. Return first match or default deny."""
    filtered = [r for r in rules if str(r.get("direction", "")).lower() == direction.lower()]
    filtered.sort(key=lambda r: r.get("priority", 65500))

    for rule in filtered:
        if _matches_rule(rule, port, protocol, src_prefix, dst_prefix):
            return {
                "result": str(rule.get("access", "Deny")),
                "matching_rule": str(rule.get("ruleName", "")),
                "priority": rule.get("priority", 65500),
            }

    # Default deny
    return {"result": "Deny", "matching_rule": "DenyAll (default)", "priority": 65500}


def _detect_asymmetries(
    nsg_rules_map: Dict[str, List[Dict[str, Any]]],
    subnet_nsg_map: Dict[str, str],
    vnet_subnets: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    """Detect NSG asymmetries: source allows outbound but dest denies inbound on common ports."""
    issues: List[Dict[str, Any]] = []
    subnet_ids = list(subnet_nsg_map.keys())

    for i, src_subnet_id in enumerate(subnet_ids):
        src_nsg_id = subnet_nsg_map[src_subnet_id]
        src_rules = nsg_rules_map.get(src_nsg_id, [])
        if not src_rules:
            continue

        for dst_subnet_id in subnet_ids[i + 1:]:
            dst_nsg_id = subnet_nsg_map[dst_subnet_id]
            if src_nsg_id == dst_nsg_id:
                continue
            dst_rules = nsg_rules_map.get(dst_nsg_id, [])
            if not dst_rules:
                continue

            for port in _COMMON_PORTS:
                outbound = _evaluate_nsg_rules(src_rules, port, "TCP", "*", "*", "Outbound")
                inbound = _evaluate_nsg_rules(dst_rules, port, "TCP", "*", "*", "Inbound")

                if outbound["result"] == "Allow" and inbound["result"] == "Deny":
                    issues.append({
                        "source_nsg_id": src_nsg_id,
                        "dest_nsg_id": dst_nsg_id,
                        "port": port,
                        "description": f"Port {port}/TCP: source NSG allows outbound but destination NSG denies inbound",
                    })

    return issues


def _build_rules_for_panel(nsg_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert raw NSG rule rows into compact dicts for the frontend panel."""
    result = []
    for row in nsg_rows:
        dest_port = str(row.get("destPortRange", ""))
        dest_ranges = row.get("destPortRanges")
        if dest_ranges and isinstance(dest_ranges, list) and not dest_port:
            dest_port = ", ".join(str(p) for p in dest_ranges)
        src = str(row.get("sourcePrefix", ""))
        src_list = row.get("sourcePrefixes")
        if src_list and isinstance(src_list, list) and not src:
            src = ", ".join(str(p) for p in src_list)
        dst = str(row.get("destPrefix", ""))
        result.append({
            "name": str(row.get("ruleName", "")),
            "priority": row.get("priority", 65500),
            "direction": str(row.get("direction", "")),
            "access": str(row.get("access", "")),
            "protocol": str(row.get("protocol", "*")),
            "source": src or "*",
            "destination": dst or "*",
            "ports": dest_port or "*",
        })
    # Sort by direction then priority
    result.sort(key=lambda r: (r["direction"], r["priority"]))
    return result


def _clean_address_space(raw: str) -> str:
    """Clean ARG addressSpace which comes back as '["10.0.0.0/16"]' JSON."""
    if not raw:
        return raw
    cleaned = raw.strip()
    if cleaned.startswith("["):
        try:
            import json
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return ", ".join(str(x) for x in parsed)
        except Exception:
            pass
        cleaned = cleaned.strip("[]").replace('"', "").replace("'", "")
    return cleaned


def _assemble_graph(
    vnets: List[Dict[str, Any]],
    nsgs: List[Dict[str, Any]],
    lbs: List[Dict[str, Any]],
    pes: List[Dict[str, Any]],
    gateways: List[Dict[str, Any]],
    public_ips: List[Dict[str, Any]],
    nics: List[Dict[str, Any]],
    vms: Optional[List[Dict[str, Any]]] = None,
    vmss_list: Optional[List[Dict[str, Any]]] = None,
    aks_list: Optional[List[Dict[str, Any]]] = None,
    firewalls: Optional[List[Dict[str, Any]]] = None,
    app_gateways: Optional[List[Dict[str, Any]]] = None,
    nic_subnet_map: Optional[Dict[str, Dict[str, str]]] = None,
    nsg_rules_by_id: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    lb_backends: Optional[List[Dict[str, Any]]] = None,
    route_tables: Optional[List[Dict[str, Any]]] = None,
    local_gateways: Optional[List[Dict[str, Any]]] = None,
    vpn_connections: Optional[List[Dict[str, Any]]] = None,
    app_gw_backends: Optional[List[Dict[str, Any]]] = None,
    nat_gateways: Optional[List[Dict[str, Any]]] = None,
    nic_vm_map: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build nodes and edges lists from raw ARG query results."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_nodes: set = set()

    # VNet and subnet nodes
    for row in vnets:
        vnet_id = str(row.get("id", "")).lower()
        if vnet_id and vnet_id not in seen_nodes:
            seen_nodes.add(vnet_id)
            nodes.append({
                "id": vnet_id,
                "type": "vnet",
                "label": row.get("vnetName", ""),
                "data": {
                    "addressSpace": _clean_address_space(str(row.get("addressSpace", ""))),
                    "subscriptionId": row.get("subscriptionId", ""),
                    "location": row.get("location", ""),
                    "peeringCount": 0,
                },
            })

        subnet_name = row.get("subnetName", "")
        subnet_id = f"{vnet_id}/subnets/{subnet_name}".lower() if subnet_name else ""
        if subnet_id and subnet_id not in seen_nodes:
            seen_nodes.add(subnet_id)
            nodes.append({
                "id": subnet_id,
                "type": "subnet",
                "label": subnet_name,
                "data": {
                    "prefix": row.get("subnetPrefix", ""),
                    "nsgId": row.get("subnetNsgId", ""),
                    "vnetId": vnet_id,
                },
            })
            # Edge: vnet -> subnet (implicit containment)
            edges.append({
                "id": f"edge-{vnet_id}-{subnet_id}",
                "source": vnet_id,
                "target": subnet_id,
                "type": "contains",
                "data": {},
            })

        # H-4: Subnet → Route Table edge
        rt_id = str(row.get("subnetRouteTableId", "")).lower()
        if subnet_id and rt_id:
            edges.append({
                "id": f"edge-rt-{subnet_id}-{rt_id}",
                "source": subnet_id,
                "target": rt_id,
                "type": "subnet-routetable",
                "data": {},
            })

        # M-9: Subnet → NAT Gateway edge
        natgw_id = str(row.get("subnetNatGatewayId", "")).lower()
        if subnet_id and natgw_id:
            edges.append({
                "id": f"edge-natgw-{subnet_id}-{natgw_id}",
                "source": subnet_id,
                "target": natgw_id,
                "type": "subnet-natgw",
                "data": {},
            })

    # Build per-NSG rule list for embedding in nodes
    _rules_by_id: Dict[str, List[Dict[str, Any]]] = nsg_rules_by_id or {}

    # NSG nodes — first from the rules query
    nsg_seen: set = set()
    nsg_rule_counts: Dict[str, int] = {}
    for row in nsgs:
        nsg_id = str(row.get("nsgId", "")).lower()
        if nsg_id:
            nsg_rule_counts[nsg_id] = nsg_rule_counts.get(nsg_id, 0) + 1
        if nsg_id and nsg_id not in seen_nodes:
            seen_nodes.add(nsg_id)
            nsg_seen.add(nsg_id)
            rules_for_node = _build_rules_for_panel(_rules_by_id.get(nsg_id, []))
            nodes.append({
                "id": nsg_id,
                "type": "nsg",
                "label": row.get("nsgName", ""),
                "data": {
                    "health": "green",
                    "rules": rules_for_node,
                    "ruleCount": 0,  # updated below after counting
                },
            })

    # Ensure every NSG referenced by a subnet edge has a node (handles NSGs with no rules)
    for row in vnets:
        vnet_id = str(row.get("id", "")).lower()
        subnet_name = row.get("subnetName", "")
        subnet_id = f"{vnet_id}/subnets/{subnet_name}".lower() if subnet_name else ""
        subnet_nsg_id = str(row.get("subnetNsgId", "")).lower()
        if subnet_nsg_id and subnet_nsg_id not in seen_nodes:
            seen_nodes.add(subnet_nsg_id)
            nsg_seen.add(subnet_nsg_id)
            nsg_label = subnet_nsg_id.rsplit("/", 1)[-1]
            rules_for_node = _build_rules_for_panel(_rules_by_id.get(subnet_nsg_id, []))
            nodes.append({
                "id": subnet_nsg_id,
                "type": "nsg",
                "label": nsg_label,
                "data": {
                    "health": "green",
                    "rules": rules_for_node,
                    "ruleCount": 0,
                },
            })
        if subnet_id and subnet_nsg_id:
            edges.append({
                "id": f"edge-{subnet_id}-{subnet_nsg_id}",
                "source": subnet_id,
                "target": subnet_nsg_id,
                "type": "subnet-nsg",
                "data": {},
            })

    # Stamp ruleCount on NSG nodes now that we've counted all rows
    for node in nodes:
        if node["type"] == "nsg":
            node["data"]["ruleCount"] = nsg_rule_counts.get(node["id"], 0)

    # H-4: Route Table nodes
    for row in (route_tables or []):
        rt_id = str(row.get("rtId", "")).lower()
        if rt_id and rt_id not in seen_nodes:
            seen_nodes.add(rt_id)
            nodes.append({
                "id": rt_id,
                "type": "routetable",
                "label": row.get("name", ""),
                "data": {
                    "location": row.get("location", ""),
                    "routeCount": row.get("routeCount", 0),
                },
            })

    # M-9: NAT Gateway nodes
    for row in (nat_gateways or []):
        natgw_id = str(row.get("natId", "")).lower()
        if natgw_id and natgw_id not in seen_nodes:
            seen_nodes.add(natgw_id)
            nodes.append({
                "id": natgw_id,
                "type": "natgw",
                "label": row.get("name", ""),
                "data": {
                    "idleTimeoutMinutes": row.get("idleTimeoutMinutes", 0),
                    "provisioningState": row.get("provisioningState", ""),
                },
            })

    # H-5: Local Network Gateway nodes
    for row in (local_gateways or []):
        lgw_id = str(row.get("lgwId", "")).lower()
        if lgw_id and lgw_id not in seen_nodes:
            seen_nodes.add(lgw_id)
            nodes.append({
                "id": lgw_id,
                "type": "localgw",
                "label": row.get("name", ""),
                "data": {
                    "gatewayIp": row.get("gatewayIp", ""),
                    "addressPrefixes": row.get("addressPrefixes", ""),
                },
            })

    # LB nodes
    for row in lbs:
        lb_id = str(row.get("id", "")).lower()
        if lb_id and lb_id not in seen_nodes:
            seen_nodes.add(lb_id)
            nodes.append({
                "id": lb_id,
                "type": "lb",
                "label": row.get("name", ""),
                "data": {
                    "sku": row.get("sku_name", ""),
                    "frontendIp": row.get("frontendIp", ""),
                },
            })
        pub_ip_id = str(row.get("publicIpId", "")).lower()
        if lb_id and pub_ip_id:
            edges.append({
                "id": f"resource-publicip-{lb_id}",
                "source": lb_id,
                "target": pub_ip_id,
                "type": "resource-publicip",
                "data": {},
            })

    # PE nodes
    for row in pes:
        pe_id = str(row.get("id", "")).lower()
        connection_state = str(row.get("connectionState", "Approved"))
        if pe_id and pe_id not in seen_nodes:
            seen_nodes.add(pe_id)
            # H-9: PE health based on connection state
            pe_health = "green" if connection_state.lower() == "approved" else "red"
            nodes.append({
                "id": pe_id,
                "type": "pe",
                "label": row.get("name", ""),
                "data": {
                    "targetResourceId": row.get("targetResourceId", ""),
                    "health": pe_health,
                },
            })
        subnet_id = str(row.get("subnetId", "")).lower()
        if pe_id and subnet_id:
            edges.append({
                "id": f"edge-{subnet_id}-{pe_id}",
                "source": subnet_id,
                "target": pe_id,
                "type": "subnet-pe",
                "data": {},
            })

        # C-2: PE → target service edge
        target_id = str(row.get("targetResourceId", "")).lower()
        if pe_id and target_id:
            if target_id not in seen_nodes:
                seen_nodes.add(target_id)
                nodes.append({
                    "id": target_id,
                    "type": "external",
                    "label": target_id.split("/")[-1],
                    "data": {"resourceId": target_id},
                })
            edges.append({
                "id": f"pe-target-{pe_id}",
                "type": "pe-target",
                "source": pe_id,
                "target": target_id,
            })

    # Gateway nodes
    for row in gateways:
        gw_id = str(row.get("id", "")).lower()
        if gw_id and gw_id not in seen_nodes:
            seen_nodes.add(gw_id)
            # H-9: Gateway health based on provisioning state
            gw_health = _score_resource_health(str(row.get("provisioningState", "Succeeded")))
            nodes.append({
                "id": gw_id,
                "type": "gateway",
                "label": row.get("name", ""),
                "data": {
                    "gatewayType": row.get("gatewayType", ""),
                    "vpnType": row.get("vpnType", ""),
                    "sku": row.get("sku_name", ""),
                    "bgpEnabled": row.get("bgp_enabled", False),
                    "health": gw_health,
                },
            })
        subnet_id = str(row.get("subnetId", "")).lower()
        if gw_id and subnet_id:
            edges.append({
                "id": f"edge-{subnet_id}-{gw_id}",
                "source": subnet_id,
                "target": gw_id,
                "type": "subnet-gateway",
                "data": {},
            })
        pub_ip_id = str(row.get("publicIpId", "")).lower()
        if gw_id and pub_ip_id:
            edges.append({
                "id": f"resource-publicip-{gw_id}",
                "source": gw_id,
                "target": pub_ip_id,
                "type": "resource-publicip",
                "data": {},
            })

    # H-5: VPN Connection edges
    for row in (vpn_connections or []):
        vng_id = str(row.get("vngId", "")).lower()
        lng_id = str(row.get("lngId", "")).lower()
        peer_id = str(row.get("peerId", "")).lower()
        conn_id = str(row.get("connId", "")).lower()
        if not vng_id:
            continue
        target = lng_id if lng_id else peer_id
        if target:
            edges.append({
                "id": f"vpn-conn-{conn_id}",
                "type": "vpn-connection",
                "source": vng_id,
                "target": target,
                "data": {
                    "connectionType": row.get("connectionType", ""),
                    "connectionStatus": row.get("connectionStatus", ""),
                },
            })

    # Public IP nodes (C-1)
    for row in public_ips:
        pip_id = str(row.get("id", "")).lower()
        if pip_id and pip_id not in seen_nodes:
            seen_nodes.add(pip_id)
            nodes.append({
                "id": pip_id,
                "type": "publicip",
                "label": row.get("name", ""),
                "data": {
                    "ipAddress": row.get("ipAddress", ""),
                    "allocationMethod": row.get("allocationMethod", ""),
                    "sku": row.get("sku_name", ""),
                    "domainNameLabel": row.get("domainNameLabel", ""),
                },
            })

    # VM nodes — resolve subnet via nic_subnet_map; support multi-NIC (H-1)
    _nic_map: Dict[str, Dict[str, str]] = nic_subnet_map or {}
    _nic_vm: Dict[str, str] = nic_vm_map or {}

    # Build VM private IP map for AppGW backend matching
    vm_ip_map: Dict[str, str] = {}  # private_ip → vm_id

    for row in (vms or []):
        vm_id = str(row.get("vmId", "")).lower()
        nic_id = str(row.get("nicId", "")).lower()
        nic_info = _nic_map.get(nic_id, {})
        private_ip = nic_info.get("privateIp", row.get("privateIp", ""))
        subnet_id = nic_info.get("subnetId", "")
        # Deduplicate VM node — only create once (H-1)
        if vm_id and vm_id not in seen_nodes:
            seen_nodes.add(vm_id)
            nodes.append({
                "id": vm_id,
                "type": "vm",
                "label": row.get("vmName", ""),
                "data": {
                    "vmSize": row.get("vmSize", ""),
                    "osType": row.get("osType", ""),
                    "privateIp": private_ip,
                    "location": row.get("location", ""),
                    "nicId": nic_id,
                },
            })
        if private_ip and vm_id:
            vm_ip_map[private_ip] = vm_id
        # Emit one subnet-vm edge per NIC (H-1)
        if vm_id and subnet_id:
            edge_id = f"edge-{subnet_id}-{vm_id}-{nic_id}"
            edges.append({"id": edge_id, "source": subnet_id, "target": vm_id, "type": "subnet-vm", "data": {}})
        # NIC-level NSG edge (C-4)
        nsg_id = nic_info.get("nsgId", "")
        if vm_id and nsg_id:
            # Ensure NSG node exists
            if nsg_id not in seen_nodes:
                seen_nodes.add(nsg_id)
                nsg_label = nsg_id.rsplit("/", 1)[-1]
                rules_for_node = _build_rules_for_panel(_rules_by_id.get(nsg_id, []))
                nodes.append({
                    "id": nsg_id,
                    "type": "nsg",
                    "label": nsg_label,
                    "data": {
                        "health": "green",
                        "rules": rules_for_node,
                        "ruleCount": nsg_rule_counts.get(nsg_id, 0),
                    },
                })
            edges.append({
                "id": f"nic-nsg-{vm_id}-{nic_id}",
                "source": vm_id,
                "target": nsg_id,
                "type": "nic-nsg",
                "data": {},
            })

    # H-3: LB backend pool edges
    for row in (lb_backends or []):
        lb_id = str(row.get("lbId", "")).lower()
        nic_id = str(row.get("nicId", "")).lower()
        vm_id = _nic_vm.get(nic_id, "")
        if lb_id and vm_id:
            edges.append({
                "id": f"lb-backend-{lb_id}-{vm_id}",
                "type": "lb-backend",
                "source": lb_id,
                "target": vm_id,
                "data": {},
            })

    # VMSS nodes
    for row in (vmss_list or []):
        vmss_id = str(row.get("id", "")).lower()
        if vmss_id and vmss_id not in seen_nodes:
            seen_nodes.add(vmss_id)
            nodes.append({
                "id": vmss_id,
                "type": "vmss",
                "label": row.get("name", ""),
                "data": {
                    "sku": row.get("sku_name", ""),
                    "capacity": row.get("capacity", 0),
                    "location": row.get("location", ""),
                },
            })
        subnet_id = str(row.get("subnetId", "")).lower()
        if vmss_id and subnet_id:
            edges.append({"id": f"edge-{subnet_id}-{vmss_id}", "source": subnet_id, "target": vmss_id, "type": "subnet-vmss", "data": {}})

    # AKS nodes — support multi-pool (H-2)
    for row in (aks_list or []):
        aks_id = str(row.get("id", "")).lower()
        # Deduplicate AKS node — only create once (H-2)
        if aks_id and aks_id not in seen_nodes:
            seen_nodes.add(aks_id)
            # H-9: AKS health based on provisioning state
            aks_health = _score_resource_health(str(row.get("provisioningState", "Succeeded")))
            nodes.append({
                "id": aks_id,
                "type": "aks",
                "label": row.get("name", ""),
                "data": {
                    "kubernetesVersion": row.get("kubernetesVersion", ""),
                    "nodeCount": row.get("nodeCount", 0),
                    "provisioningState": row.get("provisioningState", ""),
                    "location": row.get("location", ""),
                    "health": aks_health,
                },
            })
        # Emit one subnet-aks edge per pool with a non-empty subnetId (H-2)
        subnet_id = str(row.get("subnetId", "")).lower()
        if aks_id and subnet_id:
            pool_name = str(row.get("poolName", ""))
            edge_id = f"edge-{subnet_id}-{aks_id}-{pool_name}" if pool_name else f"edge-{subnet_id}-{aks_id}"
            edges.append({"id": edge_id, "source": subnet_id, "target": aks_id, "type": "subnet-aks", "data": {}})

    # Firewall nodes
    for row in (firewalls or []):
        fw_id = str(row.get("id", "")).lower()
        threat_intel = str(row.get("threatIntelMode", ""))
        if fw_id and fw_id not in seen_nodes:
            seen_nodes.add(fw_id)
            # H-9: Firewall health — base on provisioning state, degrade if ThreatIntel off
            fw_health = _score_resource_health(str(row.get("provisioningState", "Succeeded")))
            if fw_health == "green" and threat_intel.lower() == "off":
                fw_health = "yellow"
            fw_policy_id = str(row.get("firewallPolicyId", "")).lower()
            mgmt_subnet_id = str(row.get("mgmtSubnetId", "")).lower()
            nodes.append({
                "id": fw_id,
                "type": "firewall",
                "label": row.get("name", ""),
                "data": {
                    "skuTier": row.get("sku_tier", ""),
                    "threatIntelMode": threat_intel,
                    "privateIp": row.get("privateIp", ""),
                    "location": row.get("location", ""),
                    "health": fw_health,
                    "firewallPolicyId": fw_policy_id,
                    "mgmtSubnetId": mgmt_subnet_id,
                },
            })
            # H-7: Firewall policy stub node + edge
            if fw_policy_id:
                if fw_policy_id not in seen_nodes:
                    seen_nodes.add(fw_policy_id)
                    nodes.append({
                        "id": fw_policy_id,
                        "type": "firewallpolicy",
                        "label": fw_policy_id.split("/")[-1],
                        "data": {"resourceId": fw_policy_id},
                    })
                edges.append({
                    "id": f"firewall-policy-{fw_id}",
                    "type": "firewall-policy",
                    "source": fw_id,
                    "target": fw_policy_id,
                    "data": {},
                })
            # H-7: Firewall management subnet edge
            if mgmt_subnet_id:
                edges.append({
                    "id": f"firewall-mgmt-subnet-{fw_id}",
                    "type": "firewall-mgmt-subnet",
                    "source": fw_id,
                    "target": mgmt_subnet_id,
                    "data": {},
                })

        subnet_id = str(row.get("subnetId", "")).lower()
        if fw_id and subnet_id:
            edges.append({"id": f"edge-{subnet_id}-{fw_id}", "source": subnet_id, "target": fw_id, "type": "subnet-firewall", "data": {}})
        pub_ip_id = str(row.get("publicIpId", "")).lower()
        if fw_id and pub_ip_id:
            edges.append({
                "id": f"resource-publicip-{fw_id}",
                "source": fw_id,
                "target": pub_ip_id,
                "type": "resource-publicip",
                "data": {},
            })

    # App Gateway nodes
    for row in (app_gateways or []):
        agw_id = str(row.get("id", "")).lower()
        if agw_id and agw_id not in seen_nodes:
            seen_nodes.add(agw_id)
            # H-9: AppGW health
            agw_health = _score_resource_health(str(row.get("provisioningState", "Succeeded")))
            nodes.append({
                "id": agw_id,
                "type": "appgw",
                "label": row.get("name", ""),
                "data": {
                    "sku": row.get("sku_name", ""),
                    "skuTier": row.get("sku_tier", ""),
                    "capacity": row.get("capacity", 0),
                    "location": row.get("location", ""),
                    "health": agw_health,
                    "listenerCount": row.get("listenerCount", 0),
                    "routeRuleCount": row.get("routeRuleCount", 0),
                    "frontendPublicIpId": row.get("frontendPublicIpId", ""),
                },
            })
        subnet_id = str(row.get("subnetId", "")).lower()
        if agw_id and subnet_id:
            edges.append({"id": f"edge-{subnet_id}-{agw_id}", "source": subnet_id, "target": agw_id, "type": "subnet-appgw", "data": {}})
        pub_ip_id = str(row.get("publicIpId", "")).lower()
        if agw_id and pub_ip_id:
            edges.append({
                "id": f"resource-publicip-{agw_id}",
                "source": agw_id,
                "target": pub_ip_id,
                "type": "resource-publicip",
                "data": {},
            })

    # H-6: AppGW backend address edges
    for row in (app_gw_backends or []):
        agw_id = str(row.get("appgwId", "")).lower()
        target_ip = str(row.get("targetIp", ""))
        target_fqdn = str(row.get("targetFqdn", ""))
        if not agw_id:
            continue
        # If IP matches a known VM, emit appgw-backend edge to VM
        vm_target = vm_ip_map.get(target_ip, "") if target_ip else ""
        if vm_target:
            edges.append({
                "id": f"appgw-backend-{agw_id}-{vm_target}",
                "type": "appgw-backend",
                "source": agw_id,
                "target": vm_target,
                "data": {},
            })
        else:
            # Create stub external node with FQDN or IP as label
            label = target_fqdn or target_ip
            stub_id = f"external-appgw-{agw_id}-{label}".lower().replace(".", "-")
            if stub_id and stub_id not in seen_nodes:
                seen_nodes.add(stub_id)
                nodes.append({
                    "id": stub_id,
                    "type": "external",
                    "label": label,
                    "data": {"fqdn": target_fqdn, "ip": target_ip},
                })
            if stub_id:
                edges.append({
                    "id": f"appgw-backend-{agw_id}-{stub_id}",
                    "type": "appgw-backend",
                    "source": agw_id,
                    "target": stub_id,
                    "data": {},
                })

    return nodes, edges


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_network_topology(
    subscription_ids: List[str],
    credential: Any = None,
) -> Dict[str, Any]:
    """Return network topology graph queried live from ARG (15m TTL cache).

    Returns {"nodes": [...], "edges": [...], "issues": [...]}.
    Never raises.
    """
    start_time = time.monotonic()

    if not subscription_ids:
        logger.warning("network_topology_service: called with empty subscription list")
        return {"nodes": [], "edges": [], "issues": []}

    if credential is None:
        logger.warning("network_topology_service: no credential provided")
        return {"nodes": [], "edges": [], "issues": []}

    if run_arg_query is None:
        logger.warning("network_topology_service: arg_helper not available")
        return {"nodes": [], "edges": [], "issues": []}

    cache_key = f"topology:{','.join(sorted(subscription_ids))}"

    def _safe_query(query: str, name: str) -> List[Dict[str, Any]]:
        """Run a single ARG query, returning [] on failure instead of raising."""
        try:
            return run_arg_query(credential, subscription_ids, query)
        except Exception as exc:
            logger.warning(
                "network_topology_service: ARG query '%s' failed | error=%s", name, exc
            )
            return []

    def _fetch() -> Dict[str, Any]:
        try:
            vnets = _safe_query(_VNET_SUBNET_QUERY, "vnets")
            nsgs = _safe_query(_NSG_RULES_QUERY, "nsgs")
            lbs = _safe_query(_LB_QUERY, "lbs")
            pes = _safe_query(_PE_QUERY, "pes")
            gateways = _safe_query(_GATEWAY_QUERY, "gateways")
            public_ips = _safe_query(_PUBLIC_IP_QUERY, "public_ips")
            nics = _safe_query(_NIC_NSG_QUERY, "nics")
            vms = _safe_query(_VM_QUERY, "vms")
            vmss_list = _safe_query(_VMSS_QUERY, "vmss")
            aks_list = _safe_query(_AKS_QUERY, "aks")
            firewalls = _safe_query(_FIREWALL_QUERY, "firewalls")
            app_gateways = _safe_query(_APP_GATEWAY_QUERY, "app_gateways")
            peerings = _safe_query(_VNET_PEERING_QUERY, "peerings")
            nic_rows = _safe_query(_NIC_SUBNET_QUERY, "nic_subnets")
            lb_backends = _safe_query(_LB_BACKEND_QUERY, "lb_backends")
            route_tables = _safe_query(_ROUTE_TABLE_QUERY, "route_tables")
            local_gateways = _safe_query(_LOCAL_NETWORK_GATEWAY_QUERY, "local_gateways")
            vpn_connections = _safe_query(_VPN_CONNECTION_QUERY, "vpn_connections")
            app_gw_backends = _safe_query(_APP_GATEWAY_BACKEND_QUERY, "app_gw_backends")
            nat_gateways = _safe_query(_NAT_GATEWAY_QUERY, "nat_gateways")

            # Build NSG rules map keyed by nsg_id (lower)
            nsg_rules_map: Dict[str, List[Dict[str, Any]]] = {}
            for row in nsgs:
                nsg_id = str(row.get("nsgId", "")).lower()
                if nsg_id:
                    nsg_rules_map.setdefault(nsg_id, []).append(row)

            # Build NIC→subnet lookup for VM wiring
            nic_subnet_map: Dict[str, Dict[str, str]] = {}
            for row in nic_rows:
                nic_id = str(row.get("nicId", "")).lower()
                if nic_id:
                    nic_subnet_map[nic_id] = {
                        "subnetId": str(row.get("subnetId", "")).lower(),
                        "privateIp": str(row.get("privateIp", "")),
                        "nsgId": str(row.get("nsgId", "")).lower(),
                    }

            # H-3: Build NIC → VM map for LB backend wiring
            nic_vm_map: Dict[str, str] = {}
            for row in vms:
                vm_id = str(row.get("vmId", "")).lower()
                nic_id = str(row.get("nicId", "")).lower()
                if nic_id and vm_id:
                    nic_vm_map[nic_id] = vm_id

            nodes, edges = _assemble_graph(
                vnets, nsgs, lbs, pes, gateways, public_ips, nics,
                vms=vms, vmss_list=vmss_list, aks_list=aks_list,
                firewalls=firewalls, app_gateways=app_gateways,
                nic_subnet_map=nic_subnet_map,
                nsg_rules_by_id=nsg_rules_map,
                lb_backends=lb_backends,
                route_tables=route_tables,
                local_gateways=local_gateways,
                vpn_connections=vpn_connections,
                app_gw_backends=app_gw_backends,
                nat_gateways=nat_gateways,
                nic_vm_map=nic_vm_map,
            )

            # Add VNet peering edges — merge asymmetric state (C-5)
            seen_peering_edges: Dict[tuple, Dict[str, Any]] = {}
            for row in peerings:
                vnet_id = str(row.get("vnetId", "")).lower()
                remote_vnet_id = str(row.get("remoteVnetId", "")).lower()
                if not vnet_id or not remote_vnet_id:
                    continue
                peering_state = str(row.get("peeringState", ""))
                edge_key = tuple(sorted([vnet_id, remote_vnet_id]))
                if edge_key in seen_peering_edges:
                    # Merge second side's state (C-5)
                    existing_edge = seen_peering_edges[edge_key]
                    existing_state = existing_edge["data"]["peeringState"]
                    if existing_state != peering_state:
                        merged_state = f"{existing_state}/{peering_state}"
                        existing_edge["data"]["peeringState"] = merged_state
                        # If either side is not Connected, mark as disconnected
                        if existing_state.lower() != "connected" or peering_state.lower() != "connected":
                            existing_edge["type"] = "peering-disconnected"
                    continue
                edge_type = "peering" if peering_state.lower() == "connected" else "peering-disconnected"
                new_edge = {
                    "id": f"edge-peering-{vnet_id}-{remote_vnet_id}",
                    "source": vnet_id,
                    "target": remote_vnet_id,
                    "type": edge_type,
                    "data": {
                        "peeringState": peering_state,
                        "allowForwardedTraffic": row.get("allowForwardedTraffic", False),
                        "allowGatewayTransit": row.get("allowGatewayTransit", False),
                    },
                }
                seen_peering_edges[edge_key] = new_edge
                edges.append(new_edge)

            # Build subnet-NSG map for health scoring and asymmetry detection
            subnet_nsg_map: Dict[str, str] = {}
            for row in vnets:
                subnet_name = row.get("subnetName", "")
                vnet_id = str(row.get("id", "")).lower()
                subnet_id = f"{vnet_id}/subnets/{subnet_name}".lower() if subnet_name else ""
                nsg_id = str(row.get("subnetNsgId", "")).lower()
                if subnet_id and nsg_id:
                    subnet_nsg_map[subnet_id] = nsg_id

            vnet_subnets: Dict[str, List[str]] = {}
            for row in vnets:
                vnet_id = str(row.get("id", "")).lower()
                subnet_name = row.get("subnetName", "")
                subnet_id = f"{vnet_id}/subnets/{subnet_name}".lower() if subnet_name else ""
                if vnet_id and subnet_id:
                    vnet_subnets.setdefault(vnet_id, []).append(subnet_id)

            # Score NSG health
            for node in nodes:
                if node["type"] == "nsg":
                    rules = nsg_rules_map.get(node["id"], [])
                    node["data"]["health"] = _score_nsg_health(rules)

            # Detect asymmetries
            issues = _detect_asymmetries(nsg_rules_map, subnet_nsg_map, vnet_subnets)

            # Mark affected NSGs as red and add asymmetry edges
            red_nsgs = set()
            for issue in issues:
                red_nsgs.add(issue["source_nsg_id"])
                red_nsgs.add(issue["dest_nsg_id"])
                edges.append({
                    "id": f"edge-asymmetry-{issue['source_nsg_id']}-{issue['dest_nsg_id']}-{issue['port']}",
                    "source": issue["source_nsg_id"],
                    "target": issue["dest_nsg_id"],
                    "type": "asymmetry",
                    "data": {"port": issue["port"], "description": issue["description"]},
                })

            for node in nodes:
                if node["type"] == "nsg" and node["id"] in red_nsgs:
                    node["data"]["health"] = "red"

            # Update peeringCount on VNet nodes (M-6)
            vnet_peering_counts: Dict[str, int] = {}
            for edge in edges:
                if edge["type"] in ("peering", "peering-disconnected"):
                    vnet_peering_counts[edge["source"]] = vnet_peering_counts.get(edge["source"], 0) + 1
                    vnet_peering_counts[edge["target"]] = vnet_peering_counts.get(edge["target"], 0) + 1
            for node in nodes:
                if node["type"] == "vnet":
                    node["data"]["peeringCount"] = vnet_peering_counts.get(node["id"], 0)

            result = {"nodes": nodes, "edges": edges, "issues": issues, "_nsg_rules_map": nsg_rules_map, "_nic_subnet_map": nic_subnet_map}
            return result
        except Exception as exc:
            logger.warning("network_topology_service: ARG query failed | error=%s", exc)
            return {"nodes": [], "edges": [], "issues": []}

    try:
        result = _get_cached_or_fetch(cache_key, _TOPOLOGY_TTL_SECONDS, _fetch)
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "network_topology_service: fetch complete | nodes=%d edges=%d issues=%d (%.0fms)",
            len(result.get("nodes", [])),
            len(result.get("edges", [])),
            len(result.get("issues", [])),
            duration_ms,
        )
        # C-7: strip internal NSG rules map — return shallow copy without it
        public_result = {k: v for k, v in result.items() if not k.startswith("_")}
        return public_result
    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.warning("network_topology_service: unexpected error | error=%s (%.0fms)", exc, duration_ms)
        return {"nodes": [], "edges": [], "issues": []}


def evaluate_path_check(
    source_resource_id: str,
    destination_resource_id: str,
    port: int,
    protocol: str,
    subscription_ids: List[str],
    credential: Any = None,
) -> Dict[str, Any]:
    """Evaluate NSG rule chain for source->destination traffic. On-demand, not cached.

    Returns {"verdict": "allowed"|"blocked"|"error", "steps": [...], "blocking_nsg_id": str|None, ...}.
    Never raises.
    """
    start_time = time.monotonic()

    try:
        topology = fetch_network_topology(subscription_ids, credential)
        nodes = topology.get("nodes", [])
        edges = topology.get("edges", [])

        # Build lookup maps
        node_map = {n["id"]: n for n in nodes}

        # Rebuild NSG rules map from the cache directly (bypass public API strip)
        # by re-fetching from the internal cache entry which retains _nsg_rules_map
        cache_key_inner = f"topology:{','.join(sorted(subscription_ids))}"
        cached_entry = _cache_get(cache_key_inner)
        nsg_rules_map: Dict[str, List[Dict[str, Any]]] = {}
        nic_subnet_map: Dict[str, Dict[str, str]] = {}
        if cached_entry is not None:
            _, cached_data = cached_entry
            nsg_rules_map = cached_data.get("_nsg_rules_map", {})
            nic_subnet_map = cached_data.get("_nic_subnet_map", {})

        # Resolve source/dest to their subnet's NSG
        source_resource_id_lower = source_resource_id.lower()
        source_subnet_nsg = _resolve_resource_nsg(source_resource_id_lower, nodes, edges)
        dest_subnet_nsg = _resolve_resource_nsg(destination_resource_id.lower(), nodes, edges)

        steps: List[Dict[str, Any]] = []
        blocking_nsg_id: Optional[str] = None

        # M-7: Try to resolve source IP from nic_subnet_map
        source_ip = "*"
        for nic_id, nic_info in nic_subnet_map.items():
            if nic_info.get("vmId") == source_resource_id_lower:
                source_ip = nic_info.get("privateIp", "*")
                break

        dest_ip = "*"

        # Evaluate outbound from source NSG
        if source_subnet_nsg:
            src_rules = nsg_rules_map.get(source_subnet_nsg, [])
            outbound_result = _evaluate_nsg_rules(src_rules, port, protocol, source_ip, "*", "Outbound")
            src_nsg_node = node_map.get(source_subnet_nsg, {})
            steps.append({
                "nsg_id": source_subnet_nsg,
                "nsg_name": src_nsg_node.get("label", ""),
                "direction": "Outbound",
                "level": "subnet",
                "result": outbound_result["result"],
                "matching_rule": outbound_result["matching_rule"],
                "priority": outbound_result["priority"],
            })
            if outbound_result["result"] == "Deny":
                blocking_nsg_id = source_subnet_nsg
                duration_ms = (time.monotonic() - start_time) * 1000
                logger.info("network_topology_service: path_check verdict=blocked (%.0fms)", duration_ms)
                return {
                    "verdict": "blocked",
                    "steps": steps,
                    "blocking_nsg_id": blocking_nsg_id,
                    "source_ip": source_ip,
                    "destination_ip": dest_ip,
                }

        # Evaluate inbound at destination NSG
        if dest_subnet_nsg:
            dst_rules = nsg_rules_map.get(dest_subnet_nsg, [])
            inbound_result = _evaluate_nsg_rules(dst_rules, port, protocol, source_ip, "*", "Inbound")
            dst_nsg_node = node_map.get(dest_subnet_nsg, {})
            steps.append({
                "nsg_id": dest_subnet_nsg,
                "nsg_name": dst_nsg_node.get("label", ""),
                "direction": "Inbound",
                "level": "subnet",
                "result": inbound_result["result"],
                "matching_rule": inbound_result["matching_rule"],
                "priority": inbound_result["priority"],
            })
            if inbound_result["result"] == "Deny":
                blocking_nsg_id = dest_subnet_nsg
                duration_ms = (time.monotonic() - start_time) * 1000
                logger.info("network_topology_service: path_check verdict=blocked (%.0fms)", duration_ms)
                return {
                    "verdict": "blocked",
                    "steps": steps,
                    "blocking_nsg_id": blocking_nsg_id,
                    "source_ip": source_ip,
                    "destination_ip": dest_ip,
                }

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("network_topology_service: path_check verdict=allowed (%.0fms)", duration_ms)
        return {
            "verdict": "allowed",
            "steps": steps,
            "blocking_nsg_id": None,
            "source_ip": source_ip,
            "destination_ip": dest_ip,
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.warning("network_topology_service: path_check error | error=%s (%.0fms)", exc, duration_ms)
        return {
            "verdict": "error",
            "steps": [],
            "blocking_nsg_id": None,
            "source_ip": "",
            "destination_ip": "",
        }


def _resolve_resource_nsg(
    resource_id: str,
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> Optional[str]:
    """Resolve a resource ID to its associated subnet NSG ID."""
    resource_id_lower = resource_id.lower()

    # Check if the resource is directly a subnet
    for node in nodes:
        if node["type"] == "subnet" and resource_id_lower in node["id"]:
            nsg_id = node.get("data", {}).get("nsgId", "")
            if nsg_id:
                return nsg_id

    # C-3: Find the subnet that contains this resource via a subnet-* edge,
    # then find the NSG attached to that subnet via a subnet-nsg edge.
    _SUBNET_RESOURCE_EDGE_TYPES = {
        "subnet-vm", "subnet-vmss", "subnet-aks", "subnet-pe",
        "subnet-appgw", "subnet-firewall", "subnet-gateway", "subnet-lb",
    }
    subnet_id: Optional[str] = None
    for edge in edges:
        if edge.get("type") in _SUBNET_RESOURCE_EDGE_TYPES and edge.get("target") == resource_id_lower:
            subnet_id = edge.get("source")
            break

    if subnet_id:
        for edge in edges:
            if edge.get("type") == "subnet-nsg" and edge.get("source") == subnet_id:
                return edge.get("target")

    return None
