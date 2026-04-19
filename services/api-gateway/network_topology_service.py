from __future__ import annotations
"""Network Topology Service — Phase 103 Sprint 3.

Queries Azure Resource Graph for VNets, subnets, NSGs, LBs, private endpoints,
gateways, NICs, route tables, NAT gateways, local gateways, VPN connections,
AppGW backends, and firewall policies to assemble a graph representation of
the network topology.  Includes NSG health scoring and path-check evaluation.

Never raises from public functions — errors are logged and empty/partial
results returned to keep the API gateway fault-tolerant.
"""

import hashlib
import ipaddress
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple, TypedDict

logger = logging.getLogger(__name__)

try:
    from services.api_gateway.arg_helper import run_arg_query
except ImportError:
    run_arg_query = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Unified NetworkIssue Schema (Phase 108)
# ---------------------------------------------------------------------------


class NetworkIssue(TypedDict, total=False):
    id: str
    type: str
    severity: str
    title: str
    explanation: str
    impact: str
    affected_resource_id: str
    affected_resource_name: str
    related_resource_ids: List[str]
    remediation_steps: List[Dict[str, Any]]
    portal_link: str
    auto_fix_available: bool
    auto_fix_label: Optional[str]
    # Backward-compat fields for focusIssue() on asymmetry issues
    source_nsg_id: Optional[str]
    dest_nsg_id: Optional[str]
    port: Optional[int]
    description: Optional[str]
    source: Optional[str]  # "rule" | "ai" | None — added Phase 109


_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_ISSUE_TYPES: Dict[str, Dict[str, str]] = {
    "nsg_asymmetry":              {"severity": "high",     "title": "NSG Asymmetry"},
    "port_open_internet":         {"severity": "critical",  "title": "Sensitive Port Open to Internet"},
    "any_to_any_allow":           {"severity": "high",     "title": "Any-to-Any Allow Rule"},
    "subnet_no_nsg":              {"severity": "high",     "title": "Subnet Without NSG"},
    "nsg_rule_shadowed":          {"severity": "medium",   "title": "Shadowed NSG Rule"},
    "vnet_peering_disconnected":  {"severity": "critical",  "title": "VNet Peering Disconnected"},
    "vpn_bgp_disabled":           {"severity": "medium",   "title": "VPN BGP Disabled"},
    "gateway_not_zone_redundant": {"severity": "medium",   "title": "Gateway Not Zone Redundant"},
    "pe_not_approved":            {"severity": "critical",  "title": "Private Endpoint Not Approved"},
    "vm_public_ip":               {"severity": "critical",  "title": "VM Has Direct Public IP"},
    "lb_empty_backend":           {"severity": "high",     "title": "Load Balancer Has Empty Backend Pool"},
    "lb_pip_sku_mismatch":        {"severity": "high",     "title": "LB and Public IP SKU Mismatch"},
    "firewall_no_policy":         {"severity": "critical",  "title": "Firewall Has No Policy"},
    "firewall_threatintel_off":   {"severity": "high",     "title": "Firewall Threat Intelligence Disabled"},
    "aks_not_private":            {"severity": "high",     "title": "AKS API Server Not Private"},
    "route_default_internet":     {"severity": "high",     "title": "Default Route Points to Internet"},
    "subnet_overlap":             {"severity": "high",     "title": "Overlapping Subnet CIDRs"},
    "missing_hub_spoke":          {"severity": "low",      "title": "Possible Missing Hub-Spoke Link"},
}


def _make_issue_id(issue_type: str, resource_id: str) -> str:
    """Return a deterministic 16-char hex ID for a (type, resource_id) pair."""
    return hashlib.sha256(f"{issue_type}:{resource_id}".encode()).hexdigest()[:16]


def _portal_link(resource_id: str, blade: str = "overview") -> str:
    """Return Azure Portal deep-link for a resource."""
    return f"https://portal.azure.com/#resource{resource_id}/{blade}"


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

_NIC_PUBLIC_IP_QUERY = """
Resources
| where type =~ "microsoft.network/networkinterfaces"
| mv-expand ipc = properties.ipConfigurations
| extend publicIpId = tolower(tostring(ipc.properties.publicIPAddress.id))
| where isnotempty(publicIpId)
| project nicId = tolower(id), publicIpId
"""

_LB_EMPTY_BACKEND_QUERY = """
Resources
| where type == "microsoft.network/loadbalancers"
| mv-expand pool = properties.backendAddressPools
| extend memberCount = array_length(pool.properties.backendIPConfigurations)
| extend addrCount = array_length(pool.properties.loadBalancerBackendAddresses)
| where (memberCount == 0 or isnull(memberCount)) and (addrCount == 0 or isnull(addrCount))
| project lbId = tolower(id), lbName = name, emptyPool = tostring(pool.name)
"""

_AKS_PRIVATE_QUERY = """
Resources
| where type =~ "microsoft.containerservice/managedclusters"
| extend isPrivate = tobool(properties.apiServerAccessProfile.enablePrivateCluster)
| where isPrivate != true
| project aksId = tolower(id), aksName = name
"""

_ROUTE_DEFAULT_INTERNET_QUERY = """
Resources
| where type == "microsoft.network/routetables"
| mv-expand route = properties.routes
| extend addressPrefix = tostring(route.properties.addressPrefix)
| extend nextHopType = tostring(route.properties.nextHopType)
| where addressPrefix == "0.0.0.0/0" and nextHopType == "Internet"
| project rtId = tolower(id), rtName = name, routeName = tostring(route.name)
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
    nic_nsg_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Detect NSG asymmetries: source allows outbound but dest denies inbound on common ports.

    Returns unified NetworkIssue dicts with backward-compat fields.
    """
    issues: List[Dict[str, Any]] = []

    # Merge subnet-level and NIC-level NSG mappings
    all_nsg_ids = list(set(subnet_nsg_map.values()))
    if nic_nsg_map:
        for nsg_id in nic_nsg_map.values():
            if nsg_id and nsg_id not in all_nsg_ids:
                all_nsg_ids.append(nsg_id)

    for i, src_nsg_id in enumerate(all_nsg_ids):
        src_rules = nsg_rules_map.get(src_nsg_id, [])
        if not src_rules:
            continue

        for j, dst_nsg_id in enumerate(all_nsg_ids):
            if i == j or src_nsg_id == dst_nsg_id:
                continue
            dst_rules = nsg_rules_map.get(dst_nsg_id, [])
            if not dst_rules:
                continue

            for port in _COMMON_PORTS:
                outbound = _evaluate_nsg_rules(src_rules, port, "TCP", "*", "*", "Outbound")
                inbound = _evaluate_nsg_rules(dst_rules, port, "TCP", "*", "*", "Inbound")

                if outbound["result"] == "Allow" and inbound["result"] == "Deny":
                    src_name = src_nsg_id.rsplit("/", 1)[-1]
                    dst_name = dst_nsg_id.rsplit("/", 1)[-1]
                    desc = f"Port {port}/TCP: source NSG allows outbound but destination NSG denies inbound"
                    issue: Dict[str, Any] = {
                        "id": _make_issue_id("nsg_asymmetry", f"{src_nsg_id}:{dst_nsg_id}:{port}"),
                        "type": "nsg_asymmetry",
                        "severity": "high",
                        "title": f"NSG Asymmetry on port {port}",
                        "explanation": desc,
                        "impact": "Traffic from the source subnet may be silently dropped at the destination, causing intermittent connectivity failures.",
                        "affected_resource_id": dst_nsg_id,
                        "affected_resource_name": dst_name,
                        "related_resource_ids": [src_nsg_id],
                        "remediation_steps": [
                            {"step": 1, "action": "Open the destination NSG in the Azure portal", "cli": f"az network nsg show --ids {dst_nsg_id}"},
                            {"step": 2, "action": f"Find the inbound deny rule blocking port {port}", "cli": None},
                            {"step": 3, "action": f"Add an inbound Allow rule for port {port}/TCP to match the source NSG outbound rule", "cli": f"az network nsg rule create --nsg-name {dst_name} --name AllowInbound{port} --priority 200 --direction Inbound --access Allow --protocol TCP --destination-port-ranges {port}"},
                        ],
                        "portal_link": _portal_link(dst_nsg_id, "securityRules"),
                        "auto_fix_available": False,
                        "auto_fix_label": None,
                        # backward-compat
                        "source_nsg_id": src_nsg_id,
                        "dest_nsg_id": dst_nsg_id,
                        "port": port,
                        "description": desc,
                    }
                    issues.append(issue)

    return issues


# ---------------------------------------------------------------------------
# Quick-Win Detectors (Task 1.3) — no new ARG queries needed
# ---------------------------------------------------------------------------

_SENSITIVE_PORTS = [22, 3389, 1433, 3306, 5432]
_SYSTEM_SUBNETS = {"gatewaysubnet", "azurebastionsubnet", "azurefirewallsubnet", "azurefirewallmanagementsubnet"}


def _detect_port_open_internet(nsg_rules_map: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """A1: Inbound Allow where source=*/Internet and dest port covers sensitive ports."""
    issues: List[Dict[str, Any]] = []
    for nsg_id, rules in nsg_rules_map.items():
        for rule in rules:
            if str(rule.get("direction", "")).lower() != "inbound":
                continue
            if str(rule.get("access", "")).lower() != "allow":
                continue
            source = str(rule.get("sourcePrefix", ""))
            if source not in ("*", "Internet"):
                continue
            dest_port = str(rule.get("destPortRange", ""))
            dest_ranges = rule.get("destPortRanges")
            for port in _SENSITIVE_PORTS:
                if _port_in_range(port, dest_port, dest_ranges):
                    nsg_name = nsg_id.rsplit("/", 1)[-1]
                    rule_name = str(rule.get("ruleName", ""))
                    issues.append({
                        "id": _make_issue_id("port_open_internet", f"{nsg_id}:{port}"),
                        "type": "port_open_internet",
                        "severity": "critical",
                        "title": f"Port {port} open to Internet on {nsg_name}",
                        "explanation": f"NSG rule '{rule_name}' allows inbound traffic from the Internet on port {port}.",
                        "impact": "Exposes the resource to brute-force, exploitation, and scanning attacks from the public internet.",
                        "affected_resource_id": nsg_id,
                        "affected_resource_name": nsg_name,
                        "related_resource_ids": [],
                        "remediation_steps": [
                            {"step": 1, "action": f"Remove or restrict rule '{rule_name}' to specific source IP ranges", "cli": f"az network nsg rule delete --nsg-name {nsg_name} --name {rule_name}"},
                        ],
                        "portal_link": _portal_link(nsg_id, "securityRules"),
                        "auto_fix_available": False,
                        "auto_fix_label": None,
                        "source_nsg_id": None, "dest_nsg_id": None, "port": port, "description": None,
                    })
    return issues


def _detect_any_to_any_allow(nsg_rules_map: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """A2: NSG rules with source=*, destPort=*, access=Allow, direction=Inbound."""
    issues: List[Dict[str, Any]] = []
    for nsg_id, rules in nsg_rules_map.items():
        for rule in rules:
            if str(rule.get("direction", "")).lower() != "inbound":
                continue
            if str(rule.get("access", "")).lower() != "allow":
                continue
            if str(rule.get("sourcePrefix", "")) != "*":
                continue
            if str(rule.get("destPortRange", "")) != "*":
                continue
            nsg_name = nsg_id.rsplit("/", 1)[-1]
            rule_name = str(rule.get("ruleName", ""))
            issues.append({
                "id": _make_issue_id("any_to_any_allow", f"{nsg_id}:{rule_name}"),
                "type": "any_to_any_allow",
                "severity": "high",
                "title": f"Any-to-any allow rule '{rule_name}' on {nsg_name}",
                "explanation": f"Rule '{rule_name}' allows all inbound traffic from any source on all ports.",
                "impact": "Effectively disables the NSG, leaving all resources in the subnet accessible from anywhere.",
                "affected_resource_id": nsg_id,
                "affected_resource_name": nsg_name,
                "related_resource_ids": [],
                "remediation_steps": [
                    {"step": 1, "action": f"Replace rule '{rule_name}' with specific allow rules for required ports and sources only", "cli": None},
                ],
                "portal_link": _portal_link(nsg_id, "securityRules"),
                "auto_fix_available": False,
                "auto_fix_label": None,
                "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
            })
    return issues


def _detect_subnet_no_nsg(vnet_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A3: Subnets without an NSG (excluding system subnets)."""
    issues: List[Dict[str, Any]] = []
    seen: set = set()
    for row in vnet_rows:
        subnet_name = str(row.get("subnetName", ""))
        if subnet_name.lower() in _SYSTEM_SUBNETS:
            continue
        nsg_id = str(row.get("subnetNsgId", ""))
        if nsg_id:
            continue
        vnet_id = str(row.get("id", "")).lower()
        subnet_id = f"{vnet_id}/subnets/{subnet_name}".lower()
        if subnet_id in seen:
            continue
        seen.add(subnet_id)
        issues.append({
            "id": _make_issue_id("subnet_no_nsg", subnet_id),
            "type": "subnet_no_nsg",
            "severity": "high",
            "title": f"Subnet '{subnet_name}' has no NSG",
            "explanation": f"Subnet '{subnet_name}' in VNet '{row.get('vnetName', '')}' has no Network Security Group attached.",
            "impact": "All traffic to and from resources in this subnet is unrestricted by NSG rules.",
            "affected_resource_id": subnet_id,
            "affected_resource_name": subnet_name,
            "related_resource_ids": [vnet_id],
            "remediation_steps": [
                {"step": 1, "action": "Create an NSG with appropriate rules", "cli": f"az network nsg create --name nsg-{subnet_name} --resource-group {row.get('resourceGroup', '')}"},
                {"step": 2, "action": "Associate the NSG with the subnet", "cli": f"az network vnet subnet update --vnet-name {row.get('vnetName', '')} --name {subnet_name} --network-security-group nsg-{subnet_name} --resource-group {row.get('resourceGroup', '')}"},
            ],
            "portal_link": _portal_link(vnet_id, "subnets"),
            "auto_fix_available": False,
            "auto_fix_label": None,
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


def _detect_nsg_rule_shadowing(nsg_rules_map: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """A4: Detect rules completely shadowed by a higher-priority rule with opposite access."""
    issues: List[Dict[str, Any]] = []
    for nsg_id, rules in nsg_rules_map.items():
        for direction in ("Inbound", "Outbound"):
            dir_rules = [r for r in rules if str(r.get("direction", "")).lower() == direction.lower()]
            dir_rules.sort(key=lambda r: r.get("priority", 65500))
            for i, lower_rule in enumerate(dir_rules):
                for upper_rule in dir_rules[:i]:
                    # Same access = not shadowed (both allow or both deny)
                    if str(upper_rule.get("access", "")).lower() == str(lower_rule.get("access", "")).lower():
                        continue
                    # Check if upper_rule covers lower_rule's port and source
                    up_port = str(upper_rule.get("destPortRange", ""))
                    lo_port = str(lower_rule.get("destPortRange", ""))
                    up_src = str(upper_rule.get("sourcePrefix", ""))
                    lo_src = str(lower_rule.get("sourcePrefix", ""))
                    # Simple shadowing: upper covers * ports and * sources
                    if up_port == "*" and up_src == "*":
                        nsg_name = nsg_id.rsplit("/", 1)[-1]
                        rule_name = str(lower_rule.get("ruleName", ""))
                        shadow_name = str(upper_rule.get("ruleName", ""))
                        issues.append({
                            "id": _make_issue_id("nsg_rule_shadowed", f"{nsg_id}:{rule_name}"),
                            "type": "nsg_rule_shadowed",
                            "severity": "medium",
                            "title": f"Rule '{rule_name}' shadowed by '{shadow_name}' on {nsg_name}",
                            "explanation": f"Rule '{rule_name}' (priority {lower_rule.get('priority')}) is completely shadowed by '{shadow_name}' (priority {upper_rule.get('priority')}) which has opposite access and covers all ports and sources.",
                            "impact": "The shadowed rule has no effect. Traffic will always match the higher-priority rule first.",
                            "affected_resource_id": nsg_id,
                            "affected_resource_name": nsg_name,
                            "related_resource_ids": [],
                            "remediation_steps": [
                                {"step": 1, "action": f"Review rule '{rule_name}' — if it is intended to override '{shadow_name}', assign it a lower priority number", "cli": None},
                                {"step": 2, "action": "Remove the rule if it is dead code", "cli": f"az network nsg rule delete --nsg-name {nsg_name} --name {rule_name}"},
                            ],
                            "portal_link": _portal_link(nsg_id, "securityRules"),
                            "auto_fix_available": False,
                            "auto_fix_label": None,
                            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
                        })
    return issues


def _detect_peering_disconnected(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """B1: VNet peering edges with type=peering-disconnected."""
    issues: List[Dict[str, Any]] = []
    for edge in edges:
        if edge.get("type") != "peering-disconnected":
            continue
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        peering_state = str(edge.get("data", {}).get("peeringState", ""))
        issues.append({
            "id": _make_issue_id("vnet_peering_disconnected", f"{src}:{tgt}"),
            "type": "vnet_peering_disconnected",
            "severity": "critical",
            "title": f"VNet peering disconnected ({peering_state})",
            "explanation": f"VNet peering between '{src.rsplit('/', 1)[-1]}' and '{tgt.rsplit('/', 1)[-1]}' is in state '{peering_state}' instead of 'Connected'.",
            "impact": "Resources in the two VNets cannot communicate over the peering link.",
            "affected_resource_id": src,
            "affected_resource_name": src.rsplit("/", 1)[-1],
            "related_resource_ids": [tgt],
            "remediation_steps": [
                {"step": 1, "action": "Check the peering status on both VNets", "cli": f"az network vnet peering list --vnet-name {src.rsplit('/', 1)[-1]} --resource-group <rg>"},
                {"step": 2, "action": "Re-initiate the peering from the Azure portal or re-run the peering creation command", "cli": None},
            ],
            "portal_link": _portal_link(src, "peerings"),
            "auto_fix_available": False,
            "auto_fix_label": None,
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


def _detect_vpn_bgp_disabled(gateway_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """B2: VPN gateways with BGP disabled."""
    issues: List[Dict[str, Any]] = []
    for node in gateway_nodes:
        if node.get("data", {}).get("gatewayType", "").lower() != "vpn":
            continue
        if node["data"].get("bgpEnabled") is not False:
            continue
        gw_id = node["id"]
        gw_name = node.get("label", gw_id.rsplit("/", 1)[-1])
        issues.append({
            "id": _make_issue_id("vpn_bgp_disabled", gw_id),
            "type": "vpn_bgp_disabled",
            "severity": "medium",
            "title": f"BGP disabled on VPN gateway '{gw_name}'",
            "explanation": f"VPN gateway '{gw_name}' does not have BGP enabled.",
            "impact": "Without BGP, dynamic routing is unavailable. Static routes must be managed manually, increasing operational risk.",
            "affected_resource_id": gw_id,
            "affected_resource_name": gw_name,
            "related_resource_ids": [],
            "remediation_steps": [
                {"step": 1, "action": "Enable BGP on the VPN gateway (requires gateway recreation)", "cli": f"az network vnet-gateway update --name {gw_name} --enable-bgp true --resource-group <rg>"},
            ],
            "portal_link": _portal_link(gw_id, "configuration"),
            "auto_fix_available": False,
            "auto_fix_label": None,
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


def _detect_gateway_not_zone_redundant(gateway_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """B3: Gateways whose SKU does not end in 'AZ'."""
    issues: List[Dict[str, Any]] = []
    for node in gateway_nodes:
        sku = str(node.get("data", {}).get("sku", ""))
        if sku.upper().endswith("AZ"):
            continue
        gw_id = node["id"]
        gw_name = node.get("label", gw_id.rsplit("/", 1)[-1])
        issues.append({
            "id": _make_issue_id("gateway_not_zone_redundant", gw_id),
            "type": "gateway_not_zone_redundant",
            "severity": "medium",
            "title": f"Gateway '{gw_name}' is not zone redundant (SKU: {sku})",
            "explanation": f"Gateway '{gw_name}' uses SKU '{sku}' which is not zone redundant.",
            "impact": "A zonal outage can take down the gateway, disrupting all VPN/ExpressRoute connectivity.",
            "affected_resource_id": gw_id,
            "affected_resource_name": gw_name,
            "related_resource_ids": [],
            "remediation_steps": [
                {"step": 1, "action": f"Migrate to a zone-redundant SKU (e.g. {sku}AZ if available)", "cli": None},
            ],
            "portal_link": _portal_link(gw_id, "configuration"),
            "auto_fix_available": False,
            "auto_fix_label": None,
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


def _detect_pe_not_approved(pe_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """B4: Private endpoints where connectionState != Approved."""
    issues: List[Dict[str, Any]] = []
    for node in pe_nodes:
        conn_state = str(node.get("data", {}).get("health", "green"))
        if conn_state != "red":
            continue
        pe_id = node["id"]
        pe_name = node.get("label", pe_id.rsplit("/", 1)[-1])
        issues.append({
            "id": _make_issue_id("pe_not_approved", pe_id),
            "type": "pe_not_approved",
            "severity": "critical",
            "title": f"Private endpoint '{pe_name}' connection not approved",
            "explanation": f"Private endpoint '{pe_name}' has a connection that is not in 'Approved' state.",
            "impact": "The private endpoint cannot route traffic to the target service until the connection is approved.",
            "affected_resource_id": pe_id,
            "affected_resource_name": pe_name,
            "related_resource_ids": [],
            "remediation_steps": [
                {"step": 1, "action": "Approve the private endpoint connection on the target resource", "cli": None},
            ],
            "portal_link": _portal_link(pe_id, "overview"),
            "auto_fix_available": True,
            "auto_fix_label": "Approve Connection",
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


def _detect_firewall_no_policy(firewall_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """C4: Azure Firewalls with no firewall policy attached."""
    issues: List[Dict[str, Any]] = []
    for node in firewall_nodes:
        policy_id = str(node.get("data", {}).get("firewallPolicyId", ""))
        if policy_id:
            continue
        fw_id = node["id"]
        fw_name = node.get("label", fw_id.rsplit("/", 1)[-1])
        issues.append({
            "id": _make_issue_id("firewall_no_policy", fw_id),
            "type": "firewall_no_policy",
            "severity": "critical",
            "title": f"Firewall '{fw_name}' has no policy",
            "explanation": f"Azure Firewall '{fw_name}' does not have a Firewall Policy attached.",
            "impact": "Without a policy, the firewall may not enforce traffic filtering rules correctly.",
            "affected_resource_id": fw_id,
            "affected_resource_name": fw_name,
            "related_resource_ids": [],
            "remediation_steps": [
                {"step": 1, "action": "Create a Firewall Policy and attach it to the firewall", "cli": f"az network firewall policy create --name policy-{fw_name} --resource-group <rg>"},
                {"step": 2, "action": "Associate the policy with the firewall", "cli": f"az network firewall update --name {fw_name} --resource-group <rg> --firewall-policy policy-{fw_name}"},
            ],
            "portal_link": _portal_link(fw_id, "overview"),
            "auto_fix_available": False,
            "auto_fix_label": None,
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


def _detect_firewall_threatintel_off(firewall_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """C5: Azure Firewalls with ThreatIntel mode = Off."""
    issues: List[Dict[str, Any]] = []
    for node in firewall_nodes:
        ti_mode = str(node.get("data", {}).get("threatIntelMode", ""))
        if ti_mode.lower() != "off":
            continue
        fw_id = node["id"]
        fw_name = node.get("label", fw_id.rsplit("/", 1)[-1])
        issues.append({
            "id": _make_issue_id("firewall_threatintel_off", fw_id),
            "type": "firewall_threatintel_off",
            "severity": "high",
            "title": f"Threat Intelligence disabled on firewall '{fw_name}'",
            "explanation": f"Azure Firewall '{fw_name}' has Threat Intelligence mode set to 'Off'.",
            "impact": "Known malicious IPs and domains are not blocked, increasing exposure to external threats.",
            "affected_resource_id": fw_id,
            "affected_resource_name": fw_name,
            "related_resource_ids": [],
            "remediation_steps": [
                {"step": 1, "action": "Set Threat Intelligence mode to 'Alert' or 'Deny'", "cli": f"az network firewall update --name {fw_name} --resource-group <rg> --threat-intel-mode Deny"},
            ],
            "portal_link": _portal_link(fw_id, "configuration"),
            "auto_fix_available": True,
            "auto_fix_label": "Enable Threat Intelligence",
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


# ---------------------------------------------------------------------------
# Detectors Using New ARG Query Data (Task 1.5)
# ---------------------------------------------------------------------------


def _detect_vm_public_ip(
    nic_public_ip_rows: List[Dict[str, Any]],
    vm_nic_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    """C1: VMs with a public IP directly attached to a NIC."""
    issues: List[Dict[str, Any]] = []
    nic_to_vm = {v_nic: v_vm for v_nic, v_vm in vm_nic_map.items()}
    for row in nic_public_ip_rows:
        nic_id = str(row.get("nicId", "")).lower()
        vm_id = nic_to_vm.get(nic_id, "")
        if not vm_id:
            continue
        pip_id = str(row.get("publicIpId", ""))
        vm_name = vm_id.rsplit("/", 1)[-1]
        issues.append({
            "id": _make_issue_id("vm_public_ip", vm_id),
            "type": "vm_public_ip",
            "severity": "critical",
            "title": f"VM '{vm_name}' has a direct public IP",
            "explanation": f"VM '{vm_name}' has a public IP address attached directly to NIC '{nic_id.rsplit('/', 1)[-1]}'.",
            "impact": "The VM is directly reachable from the internet. Use a load balancer or Azure Bastion instead.",
            "affected_resource_id": vm_id,
            "affected_resource_name": vm_name,
            "related_resource_ids": [pip_id, nic_id],
            "remediation_steps": [
                {"step": 1, "action": "Disassociate the public IP from the NIC", "cli": f"az network nic ip-config update --nic-name {nic_id.rsplit('/', 1)[-1]} --name ipconfig1 --remove publicIpAddress --resource-group <rg>"},
                {"step": 2, "action": "Use Azure Bastion or a load balancer for access", "cli": None},
            ],
            "portal_link": _portal_link(vm_id, "networking"),
            "auto_fix_available": False,
            "auto_fix_label": None,
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


def _detect_lb_empty_backend(lb_empty_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """C2: Load balancers with empty backend pools."""
    issues: List[Dict[str, Any]] = []
    seen: set = set()
    for row in lb_empty_rows:
        lb_id = str(row.get("lbId", ""))
        if lb_id in seen:
            continue
        seen.add(lb_id)
        lb_name = str(row.get("lbName", lb_id.rsplit("/", 1)[-1]))
        pool_name = str(row.get("emptyPool", ""))
        issues.append({
            "id": _make_issue_id("lb_empty_backend", lb_id),
            "type": "lb_empty_backend",
            "severity": "high",
            "title": f"Load balancer '{lb_name}' has empty backend pool '{pool_name}'",
            "explanation": f"Backend pool '{pool_name}' on load balancer '{lb_name}' has no members.",
            "impact": "Traffic sent to this load balancer will not be forwarded to any backend. Service is effectively down.",
            "affected_resource_id": lb_id,
            "affected_resource_name": lb_name,
            "related_resource_ids": [],
            "remediation_steps": [
                {"step": 1, "action": "Add VMs or NICs to the backend pool", "cli": f"az network lb address-pool address add --lb-name {lb_name} --pool-name {pool_name} --resource-group <rg> --name <addr-name> --ip-address <ip>"},
            ],
            "portal_link": _portal_link(lb_id, "backendPools"),
            "auto_fix_available": False,
            "auto_fix_label": None,
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


def _detect_lb_pip_sku_mismatch(
    lb_nodes: List[Dict[str, Any]],
    public_ip_map: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """C3: LB and its frontend Public IP have mismatched SKUs."""
    issues: List[Dict[str, Any]] = []
    for node in lb_nodes:
        lb_id = node["id"]
        lb_sku = str(node.get("data", {}).get("sku", "")).lower()
        # Find any public IP edges from this LB node
        pip_id = str(node.get("data", {}).get("publicIpId", "")).lower()
        if not pip_id:
            continue
        pip_info = public_ip_map.get(pip_id, {})
        pip_sku = str(pip_info.get("sku_name", "")).lower()
        if not pip_sku or lb_sku == pip_sku:
            continue
        lb_name = node.get("label", lb_id.rsplit("/", 1)[-1])
        issues.append({
            "id": _make_issue_id("lb_pip_sku_mismatch", lb_id),
            "type": "lb_pip_sku_mismatch",
            "severity": "high",
            "title": f"LB '{lb_name}' SKU ({lb_sku}) mismatches Public IP SKU ({pip_sku})",
            "explanation": f"Load balancer '{lb_name}' uses SKU '{lb_sku}' but its frontend public IP uses SKU '{pip_sku}'.",
            "impact": "SKU mismatch causes deployment failures or degraded functionality.",
            "affected_resource_id": lb_id,
            "affected_resource_name": lb_name,
            "related_resource_ids": [pip_id],
            "remediation_steps": [
                {"step": 1, "action": f"Ensure the public IP SKU matches the load balancer SKU (both should be '{lb_sku}')", "cli": None},
            ],
            "portal_link": _portal_link(lb_id, "frontendIPConfigurations"),
            "auto_fix_available": False,
            "auto_fix_label": None,
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


def _detect_aks_not_private(aks_private_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """C6: AKS clusters without a private API server."""
    issues: List[Dict[str, Any]] = []
    for row in aks_private_rows:
        aks_id = str(row.get("aksId", ""))
        aks_name = str(row.get("aksName", aks_id.rsplit("/", 1)[-1]))
        issues.append({
            "id": _make_issue_id("aks_not_private", aks_id),
            "type": "aks_not_private",
            "severity": "high",
            "title": f"AKS cluster '{aks_name}' API server is not private",
            "explanation": f"AKS cluster '{aks_name}' does not have the private cluster API server enabled.",
            "impact": "The Kubernetes API server is publicly accessible, increasing attack surface.",
            "affected_resource_id": aks_id,
            "affected_resource_name": aks_name,
            "related_resource_ids": [],
            "remediation_steps": [
                {"step": 1, "action": "Enable private cluster (requires cluster recreation or use az aks update on supported versions)", "cli": f"az aks update --name {aks_name} --resource-group <rg> --enable-private-cluster"},
            ],
            "portal_link": _portal_link(aks_id, "overview"),
            "auto_fix_available": False,
            "auto_fix_label": None,
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


def _detect_route_default_internet(route_default_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """D1: Route tables with 0.0.0.0/0 → Internet next hop."""
    issues: List[Dict[str, Any]] = []
    for row in route_default_rows:
        rt_id = str(row.get("rtId", ""))
        rt_name = str(row.get("rtName", rt_id.rsplit("/", 1)[-1]))
        route_name = str(row.get("routeName", ""))
        issues.append({
            "id": _make_issue_id("route_default_internet", rt_id),
            "type": "route_default_internet",
            "severity": "high",
            "title": f"Route table '{rt_name}' sends default traffic to Internet",
            "explanation": f"Route '{route_name}' in route table '{rt_name}' sends 0.0.0.0/0 traffic directly to the Internet.",
            "impact": "All outbound traffic bypasses Azure Firewall or NVA, potentially leaking data and avoiding security controls.",
            "affected_resource_id": rt_id,
            "affected_resource_name": rt_name,
            "related_resource_ids": [],
            "remediation_steps": [
                {"step": 1, "action": "Update the default route to point to Azure Firewall or NVA instead of Internet", "cli": f"az network route-table route update --route-table-name {rt_name} --name {route_name} --next-hop-type VirtualAppliance --next-hop-ip-address <firewall-ip> --resource-group <rg>"},
            ],
            "portal_link": _portal_link(rt_id, "routes"),
            "auto_fix_available": False,
            "auto_fix_label": None,
            "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
        })
    return issues


def _detect_subnet_overlap(vnet_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """D2: Detect overlapping subnet CIDRs across different VNets (capped at 500 subnets)."""
    issues: List[Dict[str, Any]] = []
    # Collect (vnet_id, subnet_id, cidr)
    subnets: List[Tuple[str, str, str]] = []
    seen_subnets: set = set()
    for row in vnet_rows:
        vnet_id = str(row.get("id", "")).lower()
        subnet_name = str(row.get("subnetName", ""))
        cidr = str(row.get("subnetPrefix", ""))
        if not cidr:
            continue
        subnet_id = f"{vnet_id}/subnets/{subnet_name}".lower()
        if subnet_id in seen_subnets:
            continue
        seen_subnets.add(subnet_id)
        subnets.append((vnet_id, subnet_id, cidr))

    if len(subnets) > 500:
        logger.warning("network_topology_service: subnet overlap check capped at 500 subnets (found %d)", len(subnets))
        subnets = subnets[:500]

    seen_pairs: set = set()
    for i, (vnet_a, subnet_a, cidr_a) in enumerate(subnets):
        try:
            net_a = ipaddress.ip_network(cidr_a, strict=False)
        except ValueError:
            continue
        for vnet_b, subnet_b, cidr_b in subnets[i + 1:]:
            if vnet_a == vnet_b:
                continue  # Only flag cross-VNet overlaps
            try:
                net_b = ipaddress.ip_network(cidr_b, strict=False)
            except ValueError:
                continue
            if net_a.overlaps(net_b):
                pair_key = tuple(sorted([subnet_a, subnet_b]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                issues.append({
                    "id": _make_issue_id("subnet_overlap", f"{subnet_a}:{subnet_b}"),
                    "type": "subnet_overlap",
                    "severity": "high",
                    "title": f"Subnet CIDR overlap: {cidr_a} and {cidr_b}",
                    "explanation": f"Subnet '{subnet_a.rsplit('/', 1)[-1]}' ({cidr_a}) in VNet '{vnet_a.rsplit('/', 1)[-1]}' overlaps with subnet '{subnet_b.rsplit('/', 1)[-1]}' ({cidr_b}) in VNet '{vnet_b.rsplit('/', 1)[-1]}'.",
                    "impact": "Overlapping CIDRs cause routing conflicts and prevent VNet peering between these VNets.",
                    "affected_resource_id": subnet_a,
                    "affected_resource_name": subnet_a.rsplit("/", 1)[-1],
                    "related_resource_ids": [subnet_b],
                    "remediation_steps": [
                        {"step": 1, "action": "Re-IP one of the subnets to a non-overlapping CIDR range", "cli": None},
                    ],
                    "portal_link": _portal_link(vnet_a, "subnets"),
                    "auto_fix_available": False,
                    "auto_fix_label": None,
                    "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
                })
    return issues


def _detect_missing_hub_spoke(
    vnet_nodes: List[Dict[str, Any]],
    peering_edges: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """D3: Heuristic — VNets with 3+ peerings are likely hubs; check spoke VNets have a return peering."""
    issues: List[Dict[str, Any]] = []
    # Count peerings per VNet
    peering_count: Dict[str, int] = {}
    peered_with: Dict[str, set] = {}
    for edge in peering_edges:
        if edge.get("type") not in ("peering", "peering-disconnected"):
            continue
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        peering_count[src] = peering_count.get(src, 0) + 1
        peering_count[tgt] = peering_count.get(tgt, 0) + 1
        # Track one-directional peerings for hub-spoke asymmetry detection
        peered_with.setdefault(src, set()).add(tgt)

    # Identify hubs (3+ peerings)
    hubs = {v for v, cnt in peering_count.items() if cnt >= 3}
    if not hubs:
        return issues

    all_vnet_ids = {n["id"] for n in vnet_nodes if n.get("type") == "vnet"}
    checked: set = set()
    for hub_id in hubs:
        spokes = peered_with.get(hub_id, set())
        for spoke_id in spokes:
            if spoke_id not in all_vnet_ids:
                continue
            if spoke_id in checked:
                continue
            # Spoke should peer back to hub
            if hub_id not in peered_with.get(spoke_id, set()):
                checked.add(spoke_id)
                spoke_name = spoke_id.rsplit("/", 1)[-1]
                hub_name = hub_id.rsplit("/", 1)[-1]
                issues.append({
                    "id": _make_issue_id("missing_hub_spoke", f"{hub_id}:{spoke_id}"),
                    "type": "missing_hub_spoke",
                    "severity": "low",
                    "title": f"Possible missing hub-spoke link: '{spoke_name}' → '{hub_name}'",
                    "explanation": f"(Heuristic) VNet '{hub_name}' appears to be a hub (≥3 peerings), but spoke VNet '{spoke_name}' does not have a return peering. This may indicate a misconfiguration.",
                    "impact": "Asymmetric peering may cause connectivity issues in hub-spoke topology.",
                    "affected_resource_id": spoke_id,
                    "affected_resource_name": spoke_name,
                    "related_resource_ids": [hub_id],
                    "remediation_steps": [
                        {"step": 1, "action": f"Verify that VNet '{spoke_name}' should peer with hub '{hub_name}' and add the peering if missing", "cli": None},
                    ],
                    "portal_link": _portal_link(spoke_id, "peerings"),
                    "auto_fix_available": False,
                    "auto_fix_label": None,
                    "source_nsg_id": None, "dest_nsg_id": None, "port": None, "description": None,
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
            # Phase 108: 4 new queries for additional detectors
            nic_public_ip_rows = _safe_query(_NIC_PUBLIC_IP_QUERY, "nic_public_ips")
            lb_empty_rows = _safe_query(_LB_EMPTY_BACKEND_QUERY, "lb_empty_backends")
            aks_private_rows = _safe_query(_AKS_PRIVATE_QUERY, "aks_private")
            route_default_rows = _safe_query(_ROUTE_DEFAULT_INTERNET_QUERY, "route_default_internet")

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

            # Build NIC-level NSG map for asymmetry detection
            nic_nsg_map: Dict[str, str] = {
                nic_id: info["nsgId"]
                for nic_id, info in nic_subnet_map.items()
                if info.get("nsgId")
            }

            # Detect asymmetries (unified NetworkIssue schema)
            issues: List[Dict[str, Any]] = _detect_asymmetries(
                nsg_rules_map, subnet_nsg_map, vnet_subnets, nic_nsg_map
            )

            # Mark affected NSGs as red and add asymmetry edges
            red_nsgs = set()
            for issue in issues:
                src_nsg = issue.get("source_nsg_id")
                dst_nsg = issue.get("dest_nsg_id")
                port = issue.get("port")
                desc = issue.get("description", "")
                if src_nsg:
                    red_nsgs.add(src_nsg)
                if dst_nsg:
                    red_nsgs.add(dst_nsg)
                if src_nsg and dst_nsg and port is not None:
                    edges.append({
                        "id": f"edge-asymmetry-{src_nsg}-{dst_nsg}-{port}",
                        "source": src_nsg,
                        "target": dst_nsg,
                        "type": "asymmetry",
                        "data": {"port": port, "description": desc},
                    })

            for node in nodes:
                if node["type"] == "nsg" and node["id"] in red_nsgs:
                    node["data"]["health"] = "red"

            # Extract typed node lists for detectors
            gateway_nodes = [n for n in nodes if n.get("type") == "gateway"]
            pe_nodes = [n for n in nodes if n.get("type") == "pe"]
            firewall_nodes = [n for n in nodes if n.get("type") == "firewall"]
            lb_nodes = [n for n in nodes if n.get("type") == "lb"]
            vnet_nodes = [n for n in nodes if n.get("type") == "vnet"]
            peering_edges = [e for e in edges if e.get("type") in ("peering", "peering-disconnected")]

            # Build public IP lookup map
            public_ip_map: Dict[str, Dict[str, Any]] = {
                str(row.get("id", "")).lower(): row for row in public_ips
            }

            # Run all 17 detectors and collect issues
            all_issues: List[Dict[str, Any]] = list(issues)  # start with asymmetries
            all_issues.extend(_detect_port_open_internet(nsg_rules_map))
            all_issues.extend(_detect_any_to_any_allow(nsg_rules_map))
            all_issues.extend(_detect_subnet_no_nsg(vnets))
            all_issues.extend(_detect_nsg_rule_shadowing(nsg_rules_map))
            all_issues.extend(_detect_peering_disconnected(edges))
            all_issues.extend(_detect_vpn_bgp_disabled(gateway_nodes))
            all_issues.extend(_detect_gateway_not_zone_redundant(gateway_nodes))
            all_issues.extend(_detect_pe_not_approved(pe_nodes))
            all_issues.extend(_detect_firewall_no_policy(firewall_nodes))
            all_issues.extend(_detect_firewall_threatintel_off(firewall_nodes))
            all_issues.extend(_detect_vm_public_ip(nic_public_ip_rows, nic_vm_map))
            all_issues.extend(_detect_lb_empty_backend(lb_empty_rows))
            all_issues.extend(_detect_lb_pip_sku_mismatch(lb_nodes, public_ip_map))
            all_issues.extend(_detect_aks_not_private(aks_private_rows))
            all_issues.extend(_detect_route_default_internet(route_default_rows))
            all_issues.extend(_detect_subnet_overlap(vnets))
            all_issues.extend(_detect_missing_hub_spoke(vnet_nodes, peering_edges))

            # De-duplicate by id, sort by severity
            seen_ids: set = set()
            deduped: List[Dict[str, Any]] = []
            for issue in all_issues:
                issue_id = issue.get("id", "")
                if issue_id and issue_id in seen_ids:
                    continue
                seen_ids.add(issue_id)
                deduped.append(issue)

            deduped.sort(key=lambda i: _SEVERITY_ORDER.get(i.get("severity", "low"), 99))

            # Update peeringCount on VNet nodes (M-6)
            vnet_peering_counts: Dict[str, int] = {}
            for edge in edges:
                if edge["type"] in ("peering", "peering-disconnected"):
                    vnet_peering_counts[edge["source"]] = vnet_peering_counts.get(edge["source"], 0) + 1
                    vnet_peering_counts[edge["target"]] = vnet_peering_counts.get(edge["target"], 0) + 1
            for node in nodes:
                if node["type"] == "vnet":
                    node["data"]["peeringCount"] = vnet_peering_counts.get(node["id"], 0)

            result = {"nodes": nodes, "edges": edges, "issues": deduped, "_nsg_rules_map": nsg_rules_map, "_nic_subnet_map": nic_subnet_map}
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
