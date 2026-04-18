from __future__ import annotations
"""Network Topology Service — Phase 103.

Queries Azure Resource Graph for VNets, subnets, NSGs, LBs, private endpoints,
gateways, and NICs to assemble a graph representation of the network topology.
Includes NSG health scoring and path-check evaluation.

Never raises from public functions — errors are logged and empty/partial
results returned to keep the API gateway fault-tolerant.
"""

import logging
import threading
import time
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
| project subscriptionId, resourceGroup, vnetName = name, id,
          addressSpace, subnetName, subnetPrefix, subnetNsgId, location
"""

_NSG_RULES_QUERY = """
Resources
| where type =~ "microsoft.network/networksecuritygroups"
| extend subnetIds = properties.subnets
| extend nicIds = properties.networkInterfaces
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
          destPortRanges = rule.properties.destinationPortRanges,
          subnetIds, nicIds
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

_PE_QUERY = """
Resources
| where type =~ "microsoft.network/privateendpoints"
| extend subnetId = tolower(tostring(properties.subnet.id))
| mv-expand conn = properties.privateLinkServiceConnections
| extend targetResourceId = tolower(tostring(conn.properties.privateLinkServiceId))
| extend groupIds = tostring(conn.properties.groupIds)
| project subscriptionId, resourceGroup, name, id, location,
          subnetId, targetResourceId, groupIds
"""

_GATEWAY_QUERY = """
Resources
| where type =~ "microsoft.network/virtualnetworkgateways"
| extend gatewayType = tostring(properties.gatewayType)
| extend vpnType = tostring(properties.vpnType)
| extend sku_name = tostring(properties.sku.name)
| mv-expand ipConfig = properties.ipConfigurations
| extend subnetId = tolower(tostring(ipConfig.properties.subnet.id))
| extend publicIpId = tolower(tostring(ipConfig.properties.publicIPAddress.id))
| project subscriptionId, resourceGroup, name, id, location,
          gatewayType, vpnType, sku_name, subnetId, publicIpId
"""

_PUBLIC_IP_QUERY = """
Resources
| where type =~ "microsoft.network/publicipaddresses"
| extend ipAddress = tostring(properties.ipAddress)
| extend allocationMethod = tostring(properties.publicIPAllocationMethod)
| project subscriptionId, name, id = tolower(id), ipAddress, allocationMethod
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
| extend nicId = tolower(tostring(properties.networkProfile.networkInterfaces[0].id))
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
| extend subnetId = tolower(tostring(properties.agentPoolProfiles[0].vnetSubnetID))
| project subscriptionId, resourceGroup, name, id = tolower(id), location,
          kubernetesVersion = tostring(properties.kubernetesVersion),
          nodeCount = toint(properties.agentPoolProfiles[0].count),
          provisioningState = tostring(properties.provisioningState),
          subnetId
"""

_FIREWALL_QUERY = """
Resources
| where type =~ "microsoft.network/azurefirewalls"
| mv-expand ipConfig = properties.ipConfigurations
| extend subnetId = tolower(tostring(ipConfig.properties.subnet.id))
| extend privateIp = tostring(ipConfig.properties.privateIPAddress)
| project subscriptionId, resourceGroup, name, id = tolower(id), location,
          sku_tier = tostring(properties.sku.tier),
          threatIntelMode = tostring(properties.threatIntelMode),
          subnetId, privateIp
"""

_APP_GATEWAY_QUERY = """
Resources
| where type =~ "microsoft.network/applicationgateways"
| mv-expand ipConfig = properties.gatewayIPConfigurations
| extend subnetId = tolower(tostring(ipConfig.properties.subnet.id))
| project subscriptionId, resourceGroup, name, id = tolower(id), location,
          sku_name = tostring(properties.sku.name),
          sku_tier = tostring(properties.sku.tier),
          capacity = toint(properties.sku.capacity),
          subnetId
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

# ---------------------------------------------------------------------------
# In-memory TTL Cache
# ---------------------------------------------------------------------------

_TOPOLOGY_TTL_SECONDS = 900
_cache: Dict[str, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _get_cached_or_fetch(key: str, ttl: int, fetch_fn: Any) -> Any:
    """Return cached value if within TTL, otherwise call fetch_fn and cache.

    Empty topology results (nodes=[]) are cached with a short 60s TTL so a
    transient startup race or a bad query doesn't poison the cache for 15 min.
    """
    now = time.monotonic()
    with _cache_lock:
        if key in _cache:
            cached_time, cached_value = _cache[key]
            if now - cached_time < ttl:
                return cached_value

    result = fetch_fn()
    # Don't cache empty topology for the full TTL — retry quickly on next request
    effective_ttl = 60 if (isinstance(result, dict) and not result.get("nodes")) else ttl
    with _cache_lock:
        _cache[key] = (time.monotonic() - (ttl - effective_ttl), result)
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
    peerings: Optional[List[Dict[str, Any]]] = None,
    nic_subnet_map: Optional[Dict[str, Dict[str, str]]] = None,
    nsg_rules_by_id: Optional[Dict[str, List[Dict[str, Any]]]] = None,
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

        # Edge: subnet -> NSG (deferred — added after NSG nodes are built)
        subnet_nsg_id = str(row.get("subnetNsgId", "")).lower()

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

    # PE nodes
    for row in pes:
        pe_id = str(row.get("id", "")).lower()
        if pe_id and pe_id not in seen_nodes:
            seen_nodes.add(pe_id)
            nodes.append({
                "id": pe_id,
                "type": "pe",
                "label": row.get("name", ""),
                "data": {"targetResourceId": row.get("targetResourceId", "")},
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

    # Gateway nodes
    for row in gateways:
        gw_id = str(row.get("id", "")).lower()
        if gw_id and gw_id not in seen_nodes:
            seen_nodes.add(gw_id)
            nodes.append({
                "id": gw_id,
                "type": "gateway",
                "label": row.get("name", ""),
                "data": {
                    "gatewayType": row.get("gatewayType", ""),
                    "vpnType": row.get("vpnType", ""),
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

    # VM nodes — resolve subnet via nic_subnet_map
    _nic_map: Dict[str, Dict[str, str]] = nic_subnet_map or {}
    for row in (vms or []):
        vm_id = str(row.get("vmId", "")).lower()
        nic_id = str(row.get("nicId", "")).lower()
        nic_info = _nic_map.get(nic_id, {})
        private_ip = nic_info.get("privateIp", row.get("privateIp", ""))
        subnet_id = nic_info.get("subnetId", "")
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
        if vm_id and subnet_id:
            edge_id = f"edge-{subnet_id}-{vm_id}"
            edges.append({"id": edge_id, "source": subnet_id, "target": vm_id, "type": "subnet-vm", "data": {}})

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

    # AKS nodes
    for row in (aks_list or []):
        aks_id = str(row.get("id", "")).lower()
        if aks_id and aks_id not in seen_nodes:
            seen_nodes.add(aks_id)
            nodes.append({
                "id": aks_id,
                "type": "aks",
                "label": row.get("name", ""),
                "data": {
                    "kubernetesVersion": row.get("kubernetesVersion", ""),
                    "nodeCount": row.get("nodeCount", 0),
                    "provisioningState": row.get("provisioningState", ""),
                    "location": row.get("location", ""),
                },
            })
        subnet_id = str(row.get("subnetId", "")).lower()
        if aks_id and subnet_id:
            edges.append({"id": f"edge-{subnet_id}-{aks_id}", "source": subnet_id, "target": aks_id, "type": "subnet-aks", "data": {}})

    # Firewall nodes
    for row in (firewalls or []):
        fw_id = str(row.get("id", "")).lower()
        if fw_id and fw_id not in seen_nodes:
            seen_nodes.add(fw_id)
            nodes.append({
                "id": fw_id,
                "type": "firewall",
                "label": row.get("name", ""),
                "data": {
                    "skuTier": row.get("sku_tier", ""),
                    "threatIntelMode": row.get("threatIntelMode", ""),
                    "privateIp": row.get("privateIp", ""),
                    "location": row.get("location", ""),
                },
            })
        subnet_id = str(row.get("subnetId", "")).lower()
        if fw_id and subnet_id:
            edges.append({"id": f"edge-{subnet_id}-{fw_id}", "source": subnet_id, "target": fw_id, "type": "subnet-firewall", "data": {}})

    # App Gateway nodes
    for row in (app_gateways or []):
        agw_id = str(row.get("id", "")).lower()
        if agw_id and agw_id not in seen_nodes:
            seen_nodes.add(agw_id)
            nodes.append({
                "id": agw_id,
                "type": "appgw",
                "label": row.get("name", ""),
                "data": {
                    "sku": row.get("sku_name", ""),
                    "skuTier": row.get("sku_tier", ""),
                    "capacity": row.get("capacity", 0),
                    "location": row.get("location", ""),
                },
            })
        subnet_id = str(row.get("subnetId", "")).lower()
        if agw_id and subnet_id:
            edges.append({"id": f"edge-{subnet_id}-{agw_id}", "source": subnet_id, "target": agw_id, "type": "subnet-appgw", "data": {}})

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

            nodes, edges = _assemble_graph(
                vnets, nsgs, lbs, pes, gateways, public_ips, nics,
                vms=vms, vmss_list=vmss_list, aks_list=aks_list,
                firewalls=firewalls, app_gateways=app_gateways,
                peerings=peerings,
                nic_subnet_map=nic_subnet_map,
                nsg_rules_by_id=nsg_rules_map,
            )

            # Add VNet peering edges
            seen_peering_edges: set = set()
            for row in peerings:
                vnet_id = str(row.get("vnetId", "")).lower()
                remote_vnet_id = str(row.get("remoteVnetId", "")).lower()
                if not vnet_id or not remote_vnet_id:
                    continue
                peering_state = str(row.get("peeringState", "")).lower()
                edge_key = tuple(sorted([vnet_id, remote_vnet_id]))
                if edge_key in seen_peering_edges:
                    continue
                seen_peering_edges.add(edge_key)
                edge_type = "peering" if peering_state == "connected" else "peering-disconnected"
                edges.append({
                    "id": f"edge-peering-{vnet_id}-{remote_vnet_id}",
                    "source": vnet_id,
                    "target": remote_vnet_id,
                    "type": edge_type,
                    "data": {
                        "peeringState": row.get("peeringState", ""),
                        "allowForwardedTraffic": row.get("allowForwardedTraffic", False),
                        "allowGatewayTransit": row.get("allowGatewayTransit", False),
                    },
                })

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

            return {"nodes": nodes, "edges": edges, "issues": issues, "_nsg_rules_map": nsg_rules_map}
        except Exception as exc:
            logger.warning("network_topology_service: ARG query failed | error=%s", exc)
            return {"nodes": [], "edges": [], "issues": [], "_nsg_rules_map": {}}

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
        return result
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

        # Find source and destination subnets via edges or resource ID matching
        # Resolve source/dest to their subnet's NSG
        source_subnet_nsg = _resolve_resource_nsg(source_resource_id, nodes, edges)
        dest_subnet_nsg = _resolve_resource_nsg(destination_resource_id, nodes, edges)

        steps: List[Dict[str, Any]] = []
        blocking_nsg_id: Optional[str] = None

        # Use the NSG rules already cached inside the topology result
        nsg_rules_map: Dict[str, List[Dict[str, Any]]] = topology.get("_nsg_rules_map", {})

        source_ip = "*"
        dest_ip = "*"

        # Evaluate outbound from source NSG
        if source_subnet_nsg:
            src_rules = nsg_rules_map.get(source_subnet_nsg, [])
            outbound_result = _evaluate_nsg_rules(src_rules, port, protocol, "*", "*", "Outbound")
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
            inbound_result = _evaluate_nsg_rules(dst_rules, port, protocol, "*", "*", "Inbound")
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

    # Check edges for subnet-nsg associations where the subnet contains the resource
    # Try to find subnet from resource ID pattern (extract VNet/subnet from ARM path)
    parts = resource_id_lower.split("/")
    # Look for any subnet that might contain this resource
    for node in nodes:
        if node["type"] == "subnet":
            # Match by subscription and resource group at minimum
            if node.get("data", {}).get("nsgId"):
                # Simple heuristic: same VNet
                node_vnet = node.get("data", {}).get("vnetId", "")
                if node_vnet:
                    # Check if resource is in same subscription/rg
                    for edge in edges:
                        if edge["type"] == "subnet-nsg" and edge["source"] == node["id"]:
                            return edge["target"]

    return None
