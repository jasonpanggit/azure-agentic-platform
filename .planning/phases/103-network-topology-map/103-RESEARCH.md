# Phase 103: Network Topology Map — Research

**Date:** 2026-04-18
**Status:** Complete

---

## 1. React Flow (@xyflow/react) — Visualization Library

### Version & Package
- Package: `@xyflow/react` (v12+, rebranded from `reactflow`)
- Install: `npm install @xyflow/react`
- Peer deps: React 18+

### Custom Nodes with Status Badges
React Flow custom nodes are plain React components registered via `nodeTypes`:

```tsx
import { Handle, Position, type NodeProps } from '@xyflow/react';

interface NsgNodeData {
  label: string;
  healthStatus: 'green' | 'yellow' | 'red';
  ruleCount: number;
}

function NsgNode({ data }: NodeProps<NsgNodeData>) {
  return (
    <div className="rounded-lg border p-3" style={{ background: 'var(--bg-canvas)' }}>
      <Handle type="target" position={Position.Left} />
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
          {data.label}
        </span>
        <span
          className="h-2.5 w-2.5 rounded-full"
          style={{ background: `var(--accent-${data.healthStatus === 'green' ? 'green' : data.healthStatus === 'yellow' ? 'yellow' : 'red'})` }}
        />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { nsgNode: NsgNode, vnetNode: VNetNode, lbNode: LBNode, ... };
```

### Auto-Layout: ELK vs Dagre

| Feature | Dagre (`@dagrejs/dagre`) | ELK.js (`elkjs`) |
|---------|--------------------------|-------------------|
| Layout quality | Good for simple hierarchies | Superior for complex graphs |
| Configuration | Minimal (rankdir, nodesep) | Rich (layered, force, stress) |
| Grouping/nesting | No native support | Native compound node support |
| Bundle size | ~30KB | ~150KB |
| Async | No | Yes (Web Worker support) |

**Recommendation: ELK.js** — compound node support (VNet as parent containing subnets) aligns with D-06 (hierarchical subscription > VNet grouping). Use `elk.layered` algorithm with `direction: RIGHT`.

```ts
import ELK from 'elkjs/lib/elk.bundled.js';

const elk = new ELK();
const graph = {
  id: 'root',
  layoutOptions: { 'elk.algorithm': 'layered', 'elk.direction': 'RIGHT' },
  children: nodes.map(n => ({ id: n.id, width: n.width, height: n.height })),
  edges: edges.map(e => ({ id: e.id, sources: [e.source], targets: [e.target] })),
};
const layout = await elk.layout(graph);
```

### Programmatic Highlighting (Path Check Results)
Use React Flow's `setNodes` / `setEdges` to update styles dynamically:

```ts
// Highlight blocking NSG in red
setNodes(nds => nds.map(n =>
  n.id === blockingNsgId
    ? { ...n, style: { ...n.style, border: '2px solid var(--accent-red)' } }
    : { ...n, style: { ...n.style, border: undefined } }
));

// Highlight path edges
setEdges(eds => eds.map(e =>
  pathEdgeIds.includes(e.id)
    ? { ...e, animated: true, style: { stroke: 'var(--accent-red)' } }
    : { ...e, animated: false, style: {} }
));
```

### Animated Edges for Peerings
React Flow supports `animated: true` on edges (dashed moving line). Use `type: 'smoothstep'` for clean routing.

---

## 2. NSG Rule Evaluation Algorithm

### Azure NSG Evaluation Order
Azure evaluates NSG rules using **first-match-wins by priority** (lowest number = highest priority):

1. **Inbound traffic:**
   - Subnet NSG inbound rules evaluated first
   - NIC NSG inbound rules evaluated second
2. **Outbound traffic:**
   - NIC NSG outbound rules evaluated first
   - Subnet NSG outbound rules evaluated second

**Both NSGs must allow** — if either denies, traffic is blocked.

### Priority & Default Rules
- Custom rule priorities: 100–4096
- Default rules (cannot be deleted):
  - 65000: `AllowVNetInBound` / `AllowVNetOutBound` (Allow)
  - 65001: `AllowAzureLoadBalancerInBound` (Allow)
  - 65500: `DenyAllInBound` / `DenyAllOutBound` (Deny)

### Path Check Algorithm (Source -> Destination)

```
evaluate_path(src_resource, dst_resource, port, protocol):
  1. Resolve src subnet NSG + src NIC NSG
  2. Resolve dst subnet NSG + dst NIC NSG
  3. Evaluate OUTBOUND on src:
     a. Check NIC NSG outbound rules (first match by priority)
     b. Check subnet NSG outbound rules (first match by priority)
     c. Both must allow for outbound to pass
  4. Evaluate INBOUND on dst:
     a. Check subnet NSG inbound rules (first match by priority)
     b. Check NIC NSG inbound rules (first match by priority)
     c. Both must allow for inbound to pass
  5. Return verdict per NSG (allow/deny + matching rule name + priority)
```

### Rule Matching Logic

```python
def matches_rule(rule, port, protocol, src_prefix, dst_prefix):
    """Check if a single NSG rule matches the given traffic parameters."""
    # Protocol: * matches all, or exact match (TCP, UDP, ICMP)
    if rule.protocol != '*' and rule.protocol.upper() != protocol.upper():
        return False

    # Port range: *, single port, range (e.g. "80", "1024-65535"), comma-separated
    if not port_in_range(port, rule.destination_port_range, rule.destination_port_ranges):
        return False

    # Address prefix matching: *, CIDR, service tags
    if not prefix_matches(src_prefix, rule.source_address_prefix, rule.source_address_prefixes):
        return False
    if not prefix_matches(dst_prefix, rule.destination_address_prefix, rule.destination_address_prefixes):
        return False

    return True
```

### Service Tag Handling
Service tags in rules (`VirtualNetwork`, `Internet`, `AzureLoadBalancer`, etc.):
- `VirtualNetwork` = VNet address space + all peered VNet address spaces + on-prem (VPN/ER)
- `Internet` = anything outside VNet address space
- `AzureLoadBalancer` = Azure health probe source IP `168.63.129.16`
- `*` = matches any address

For the path checker, map resource IPs to service tag membership based on VNet CIDR ranges.

### NSG Health Badge Scoring (D-03)
- **Red:** Asymmetric block detected (source outbound allows but destination inbound denies for common ports 22/80/443/3389, or vice versa)
- **Yellow:** Overly permissive rules (priority < 1000 with source `*` and destination port `*` and access `Allow`)
- **Green:** No issues detected

---

## 3. ARG Queries for Network Topology

### VNets with Subnets and Address Space

```kql
Resources
| where type =~ "microsoft.network/virtualnetworks"
| extend addressSpace = tostring(properties.addressSpace.addressPrefixes)
| mv-expand subnet = properties.subnets
| extend subnetName = tostring(subnet.name)
| extend subnetPrefix = tostring(subnet.properties.addressPrefix)
| extend subnetNsgId = tolower(tostring(subnet.properties.networkSecurityGroup.id))
| project subscriptionId, resourceGroup, vnetName = name, id,
          addressSpace, subnetName, subnetPrefix, subnetNsgId, location
```

### VNet Peerings (already exists in vnet_peering_service.py)

```kql
Resources
| where type =~ "microsoft.network/virtualnetworks"
| mv-expand peering = parse_json(properties).virtualNetworkPeerings
| extend peeringName = tostring(peering.name)
| extend peeringState = tostring(peering.properties.peeringState)
| extend remoteVnetId = tolower(tostring(peering.properties.remoteVirtualNetwork.id))
| project subscriptionId, resourceGroup, vnetName = name,
          peeringName, peeringState, remoteVnetId, id
```

### NSGs with Rules and Associations

```kql
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
```

### Load Balancers (already exists in lb_health_service.py)
Reuse `_LB_ARG_QUERY` from `lb_health_service.py`. Extend with frontend IP:

```kql
Resources
| where type =~ "microsoft.network/loadbalancers"
| mv-expand fip = properties.frontendIPConfigurations
| extend frontendIp = tostring(fip.properties.privateIPAddress)
| extend publicIpId = tolower(tostring(fip.properties.publicIPAddress.id))
| project subscriptionId, resourceGroup, name, id, location,
          sku_name = tostring(sku.name), frontendIp, publicIpId
```

### Private Endpoints

```kql
Resources
| where type =~ "microsoft.network/privateendpoints"
| extend subnetId = tolower(tostring(properties.subnet.id))
| mv-expand conn = properties.privateLinkServiceConnections
| extend targetResourceId = tolower(tostring(conn.properties.privateLinkServiceId))
| extend groupIds = tostring(conn.properties.groupIds)
| project subscriptionId, resourceGroup, name, id, location,
          subnetId, targetResourceId, groupIds
```

### ExpressRoute / VPN Gateways

```kql
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
```

### Public IPs (for LB/Gateway label enrichment)

```kql
Resources
| where type =~ "microsoft.network/publicipaddresses"
| extend ipAddress = tostring(properties.ipAddress)
| extend allocationMethod = tostring(properties.publicIPAllocationMethod)
| project subscriptionId, name, id = tolower(id), ipAddress, allocationMethod
```

---

## 4. Existing Backend Patterns

### Service Pattern (vnet_peering_service.py / lb_health_service.py)

Both follow identical structure:
1. **Module-level ARG query string** (`_ARG_QUERY` / `_LB_ARG_QUERY`)
2. **Classification helper** (`_compute_severity` / `_classify`)
3. **Row builder** (`_build_finding` / `_build_lb_finding`)
4. **Public scan function** (`scan_vnet_peerings` / `scan_lb_health`) — never raises, logs warnings, returns `[]` on error
5. Uses `run_arg_query(credential, subscription_ids, kql)` from `arg_helper.py`
6. Accepts `credential` parameter from `get_credential_for_subscriptions` dependency

### Endpoint Pattern (vnet_peering_endpoints.py / lb_health_endpoints.py)

1. `APIRouter(prefix="/api/v1/network/...", tags=[...])`
2. `Depends(verify_token)` for auth
3. `resolve_subscription_ids(subscription_id, request)` for federation
4. `start_time = time.monotonic()` + duration logging
5. Optional query params for filtering
6. Returns dict or list directly (no Pydantic response model on most endpoints)

### Proxy Route Pattern (Next.js)

Located in `services/web-ui/app/api/proxy/network/`. Each route:
- Imports `getApiGatewayUrl()` + `buildUpstreamHeaders(request)`
- Uses `AbortSignal.timeout(15000)` for 15s timeout
- Passes through query params to upstream

### Key Observation: No arg_cache

**Important:** The existing `vnet_peering_service.py` and `lb_health_service.py` do NOT use `arg_cache.get_cached()`. They call `run_arg_query` directly on every request. The CLAUDE.md dashboard rules say to use `arg_cache.get_cached()` with 900s TTL for resource inventory.

Need to check if `arg_cache` module exists:

- File `services/api-gateway/app/shared/arg_cache.py` — **does not exist** in the globbed path
- The caching is likely not yet implemented or uses a different pattern

**Decision for Phase 103:** Follow the direct `run_arg_query` pattern used by existing network services. Add in-memory TTL cache (dict with timestamp) in the service module itself, matching the 900s TTL from CLAUDE.md rules, since `arg_cache` module doesn't exist at the expected path.

---

## 5. Phase 22 Backend — Existing Topology

### What Exists (topology.py + topology_endpoints.py)

Phase 22 built a **resource-level adjacency graph** in Cosmos DB:

- **TopologyClient** — manages Cosmos `topology` container, ARG bootstrap, 15-min sync
- **Endpoints:**
  - `GET /api/v1/topology/blast-radius?resource_id=X&max_depth=3` — BFS traversal
  - `GET /api/v1/topology/path?source=X&target=Y` — path between two resources
  - `GET /api/v1/topology/snapshot?resource_id=X` — single node properties
  - `POST /api/v1/topology/bootstrap` — manual full sync

- **Resource types indexed:** VMs, NICs, VNets, subnets, public IPs, NSGs, LBs, disks, storage accounts, key vaults, AKS, web apps, SQL, Redis, Event Hubs, Service Bus, VNet peerings, private endpoints, ExpressRoute circuits

### Reuse Assessment

| Phase 22 Feature | Reuse for Phase 103? |
|---|---|
| ARG resource type list | Yes — confirms scope is already defined |
| BFS blast-radius | No — Phase 103 needs visual graph, not incident blast radius |
| Path query | Partial — could inform path-check routing, but NSG rule evaluation is new |
| Cosmos adjacency list | No — Phase 103 queries ARG directly (D-05, 15m TTL) |
| ARG bootstrap queries | Yes — reuse `_TOPOLOGY_RESOURCE_TYPES` and ARG query patterns |

**Conclusion:** Phase 22 provides the resource relationship model but Phase 103 needs purpose-built ARG queries for network-specific properties (NSG rules, subnet associations, gateway types). The topology graph in Cosmos is useful for blast-radius but the network topology map should query ARG directly for freshness.

---

## 6. Implementation Architecture Summary

### Backend Files

| File | Purpose |
|------|---------|
| `network_topology_service.py` | 6 ARG queries (VNets+subnets, NSGs+rules, LBs, PEs, gateways, public IPs), graph assembly, NSG health scoring, path-check evaluation |
| `network_topology_endpoints.py` | `GET /api/v1/network-topology` (full graph), `POST /api/v1/network-topology/path-check` |

### Frontend Files

| File | Purpose |
|------|---------|
| `NetworkTopologyTab.tsx` | React Flow canvas, custom node components, ELK layout, path checker side panel (shadcn Sheet) |
| `app/api/proxy/network/topology/route.ts` | GET proxy |
| `app/api/proxy/network/topology/path-check/route.ts` | POST proxy |

### Node Types for React Flow

| Node Type | Visual | Data |
|-----------|--------|------|
| `vnetNode` | Blue rounded rect, address space label | VNet name, CIDR, subscription |
| `subnetNode` | Lighter nested rect inside VNet | Subnet name, CIDR, NSG association |
| `nsgNode` | Shield icon + health badge (green/yellow/red) | NSG name, rule count, health status |
| `lbNode` | Scale icon + SKU label | LB name, SKU, frontend IP |
| `peNode` | Lock icon + target service label | PE name, target resource |
| `gatewayNode` | Globe/VPN icon + type label | Gateway name, type (ER/VPN), SKU |

### Edge Types

| Edge | Style | Meaning |
|------|-------|---------|
| Peering | Animated smoothstep, blue | VNet-to-VNet peering (green=connected, red=disconnected) |
| Subnet-NSG | Dashed, gray | NSG association |
| Subnet-LB | Solid, gray | LB backend pool membership |
| Subnet-PE | Dotted, purple | Private endpoint in subnet |
| Subnet-Gateway | Solid, orange | Gateway subnet |
| Asymmetry issue | Red dashed, animated | Auto-detected NSG block (D-04) |

### Path Check Request/Response

```typescript
// Request
POST /api/v1/network-topology/path-check
{
  "source_resource_id": "/subscriptions/.../Microsoft.Compute/virtualMachines/vm1",
  "destination_resource_id": "/subscriptions/.../Microsoft.Compute/virtualMachines/vm2",
  "port": 443,
  "protocol": "TCP"
}

// Response
{
  "verdict": "blocked",
  "steps": [
    {
      "nsg_id": "/subscriptions/.../nsg-web",
      "nsg_name": "nsg-web",
      "direction": "Outbound",
      "level": "subnet",
      "result": "Allow",
      "matching_rule": "AllowHTTPS",
      "priority": 200
    },
    {
      "nsg_id": "/subscriptions/.../nsg-db",
      "nsg_name": "nsg-db",
      "direction": "Inbound",
      "level": "subnet",
      "result": "Deny",
      "matching_rule": "DenyAllInBound",
      "priority": 65500
    }
  ],
  "blocking_nsg_id": "/subscriptions/.../nsg-db",
  "source_ip": "10.0.1.4",
  "destination_ip": "10.0.2.5"
}
```

---

## 7. Key Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| ARG query latency (6 parallel queries) | Run all 6 ARG queries concurrently with `asyncio.gather`; cache results 900s |
| NSG default rules not in `securityRules` | Query `defaultSecurityRules` separately or hardcode the 3 well-known defaults (65000, 65001, 65500) |
| Service tag resolution complexity | For MVP, map `VirtualNetwork` to VNet CIDRs and `*` to any; defer full service tag DB |
| React Flow performance with large graphs | Limit to ~500 nodes; paginate by subscription if needed |
| NIC-level NSG association requires NIC query | Add a 7th ARG query for NICs with NSG associations |

### Additional ARG Query Needed: NICs with NSG

```kql
Resources
| where type =~ "microsoft.network/networkinterfaces"
| extend subnetId = tolower(tostring(properties.ipConfigurations[0].properties.subnet.id))
| extend nsgId = tolower(tostring(properties.networkSecurityGroup.id))
| extend privateIp = tostring(properties.ipConfigurations[0].properties.privateIPAddress)
| where isnotempty(nsgId)
| project subscriptionId, resourceGroup, name, id = tolower(id),
          subnetId, nsgId, privateIp
```

---

## 8. Dependencies & Package Additions

### Python (api-gateway)
- No new packages needed — uses existing `azure-mgmt-resourcegraph` + `arg_helper.py`

### Node.js (web-ui)
- `@xyflow/react` — React Flow v12
- `elkjs` — ELK.js layout engine

Install: `npm install @xyflow/react elkjs`

---

*Research complete. Ready for planning.*
