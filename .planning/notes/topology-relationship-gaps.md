# Network Topology — Relationship Gap Audit
_Generated: 2026-04-19_

## Critical (graph is misleading without these)
1. **PE → target service edge** — `targetResourceId` in PE node data but no edge emitted
2. **Public IP nodes** — `_PUBLIC_IP_QUERY` runs but results silently discarded in `_assemble_graph`
3. **LB → backend pool members** — frontends shown, backends completely missing
4. **NIC-level NSG edges** — both `_NSG_RULES_QUERY.nicIds` and `_NIC_NSG_QUERY.nsgId` fetched but never turned into edges

## High
5. Firewall → firewallPolicy (`properties.firewallPolicy.id` missing from `_FIREWALL_QUERY`)
6. Gateway → localNetworkGateway (no `microsoft.network/localnetworkgateways` query)
7. AppGW → backend pools + listeners (`backendAddressPools`, `httpListeners` not projected)
8. Subnet → routeTable (no route table query at all)
9. AKS → all agent pool subnets (only `agentPoolProfiles[0]` indexed)
10. VM → multiple NICs (only `networkInterfaces[0]`)

## Medium
11. NSG `subnetIds`/`nicIds` reverse edges (fetched, never used)
12. Gateway → publicIp (fetched, never used)
13. LB → subnet (internal LB frontend subnet)
14. Firewall → publicIp / management subnet
15. `topology.py`: VMSS, AppGW, Firewall, VPN Gateway not in `_TOPOLOGY_RESOURCE_TYPES`

## Dead/Wasted ARG Calls (data fetched but dropped)
- `_NSG_RULES_QUERY`: `subnetIds`, `nicIds` — never consumed
- `_LB_QUERY`: `publicIpId` — no public IP nodes to link to
- `_GATEWAY_QUERY`: `publicIpId` — same
- `_PUBLIC_IP_QUERY`: entire result — `_assemble_graph(public_ips=...)` param accepted but never iterated
- `_NIC_NSG_QUERY`/`_NIC_SUBNET_QUERY`: `nsgId` — only used for subnet wiring, no nic→nsg edges

## New ARG Queries Needed
| Query | Purpose |
|-------|---------|
| `_LB_BACKEND_QUERY` | backendAddressPools → VM NICs |
| `_ROUTE_TABLE_QUERY` | routetable → subnet edges |
| `_LOCAL_NETWORK_GATEWAY_QUERY` | on-prem gateway nodes |
| `_VPN_CONNECTION_QUERY` | VPN/ER connection objects |
| `_APP_GATEWAY_BACKEND_QUERY` | backendAddressPools, httpListeners, requestRoutingRules |
| Extend `_VM_QUERY` | mv-expand networkInterfaces (multi-NIC) |
| Extend `_AKS_QUERY` | mv-expand agentPoolProfiles (all node pools) |
| Extend `_VNET_SUBNET_QUERY` | subnetRouteTableId, subnetNatGatewayId |
| Extend `_APP_GATEWAY_QUERY` | frontendIPConfigurations[*].publicIPAddress.id, firewallPolicy.id |
| Extend `_FIREWALL_QUERY` | firewallPolicy.id, publicIPAddress.id, managementIpConfiguration |
