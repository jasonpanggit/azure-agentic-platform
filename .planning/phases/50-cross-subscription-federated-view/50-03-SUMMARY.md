---
phase: 50-cross-subscription-federated-view
plan: "03"
status: complete
commit: 55e29a0
---

# 50-03 Summary: Cross-Subscription Topology Edges

## What Was Done

Extended `services/api-gateway/topology.py` with cross-subscription network topology edges and added a full unit test suite for the new extraction logic.

## Changes

### `services/api-gateway/topology.py`
- **`_TOPOLOGY_RESOURCE_TYPES`**: Extended from 17 to 20 types by adding:
  - `microsoft.network/virtualnetworkpeerings`
  - `microsoft.network/privateendpoints`
  - `microsoft.network/expressroutecircuits`
- **`TopologyRelationship.rel_type` description**: Updated to include `vnet_peering | private_endpoint_target` alongside existing types.
- **`_extract_relationships()`**: Added two new extraction blocks:
  - **VNet Peering block**: Derives parent VNet ID by stripping `/virtualNetworkPeerings/{name}` suffix from resource ID → always emits `vnet_of` edge; emits `vnet_peering` edge to remote VNet only when `peeringState == "Connected"` (Connected peerings may span subscription boundaries).
  - **Private Endpoint block**: Emits `subnet_of` from `properties.subnet.id`; emits `private_endpoint_target` for each `privateLinkServiceConnections[*].properties.privateLinkServiceId` (target may be in a different subscription).

### `services/api-gateway/tests/test_topology_cross_sub.py` (new, 13 tests)
- **`TestVNetPeeringEdges`** (8 tests):
  - Connected peering → `vnet_peering` edge with correct cross-sub target ID
  - Disconnected peering → no `vnet_peering` edge
  - Initiated peering → no `vnet_peering` edge
  - Both Connected and Disconnected → always emit `vnet_of` to parent VNet
  - Empty remote VNet ID → no `vnet_peering` edge
  - `resource_group_member` edge always emitted
  - Cross-sub target ID contains `sub-b`
- **`TestPrivateEndpointEdges`** (5 tests):
  - `private_endpoint_target` edge with correct cross-sub target
  - `subnet_of` edge from `properties.subnet.id`
  - Cross-sub target ID verified (`sub-b`)
  - Multiple `privateLinkServiceConnections` → multiple `private_endpoint_target` edges
  - Missing subnet → no `subnet_of` edge emitted

## Verification

```
85 topology tests pass (0 regressions)
13 new cross-sub tests: 13 passed, 0 failed
_TOPOLOGY_RESOURCE_TYPES: 20 entries (17 original + 3 new)
```

## Acceptance Criteria

- [x] `_TOPOLOGY_RESOURCE_TYPES` contains `microsoft.network/virtualnetworkpeerings`, `microsoft.network/privateendpoints`, `microsoft.network/expressroutecircuits`
- [x] `_extract_relationships()` handles `virtualnetworkpeerings`: `vnet_peering` for Connected, `vnet_of` to parent VNet always
- [x] `_extract_relationships()` handles `privateendpoints`: `private_endpoint_target` + `subnet_of`
- [x] Disconnected/Initiated peerings produce NO `vnet_peering` edge
- [x] `TopologyRelationship.rel_type` description updated with new types
- [x] 13 cross-sub unit tests all pass
- [x] All existing topology tests pass (no regressions)
