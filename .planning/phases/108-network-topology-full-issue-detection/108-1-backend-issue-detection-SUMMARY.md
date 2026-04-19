---
plan: "108-1"
title: "Backend — Unified Issue Schema + 17 Detectors"
status: "complete"
commit: "ce371106b860b77078d9dfa6ce0e07f111baed40"
---

# Summary: Plan 108-1 — Backend Issue Detection

## What Was Done

All 8 tasks completed and delivered in commit `ce37110`.

### Task 1.1 — Unified `NetworkIssue` TypedDict ✅
- `NetworkIssue` TypedDict defined in `network_topology_service.py` with all 17+ fields
- `_make_issue_id()` returns deterministic 16-char hex from `sha256(type:resource_id)[:16]`
- `_portal_link()` returns `https://portal.azure.com/#resource{id}/{blade}`
- `_ISSUE_TYPES` dict maps all 17 type strings to default severity + title

### Task 1.2 — `_detect_asymmetries()` Upgraded ✅
- Returns `list[NetworkIssue]` with all unified fields populated
- Backward-compat fields (`source_nsg_id`, `dest_nsg_id`, `port`, `description`) retained
- NIC-level NSGs now included in asymmetry detection via `nic_nsg_map` merge

### Task 1.3 — Quick-Win Detectors (10 functions) ✅
All implemented as pure functions returning `list[NetworkIssue]`:
- `_detect_port_open_internet` — A1: ports 22, 3389, 1433, 3306, 5432 from */Internet (critical)
- `_detect_any_to_any_allow` — A2: source=* destPort=* Allow Inbound (high)
- `_detect_subnet_no_nsg` — A3: excludes 4 system subnet names (high)
- `_detect_nsg_rule_shadowing` — A4: higher-priority rule with opposite access (medium)
- `_detect_peering_disconnected` — B1: type=peering-disconnected edges (critical)
- `_detect_vpn_bgp_disabled` — B2: VPN gateway bgpEnabled=False (medium)
- `_detect_gateway_not_zone_redundant` — B3: SKU not ending in AZ (medium)
- `_detect_pe_not_approved` — B4: PE health=red, auto_fix_available=True (critical)
- `_detect_firewall_no_policy` — C4: no firewallPolicyId (critical)
- `_detect_firewall_threatintel_off` — C5: threatIntelMode=Off, auto_fix_available=True (high)

### Task 1.4 — 4 New ARG Query Constants ✅
- `_NIC_PUBLIC_IP_QUERY` — NIC→publicIp join for VM public IP detection
- `_LB_EMPTY_BACKEND_QUERY` — LBs with empty backend pools
- `_AKS_PRIVATE_QUERY` — AKS clusters with `isPrivate != true`
- `_ROUTE_DEFAULT_INTERNET_QUERY` — route tables with 0.0.0.0/0 → Internet
All 4 added to parallel `_safe_query` dispatch in `fetch_network_topology()`.

### Task 1.5 — 7 Additional Detectors ✅
- `_detect_vm_public_ip` — C1: VM→NIC→publicIp join (critical)
- `_detect_lb_empty_backend` — C2: from `_LB_EMPTY_BACKEND_QUERY` rows (high)
- `_detect_lb_pip_sku_mismatch` — C3: cross-refs LB SKU vs PIP SKU (high)
- `_detect_aks_not_private` — C6: from `_AKS_PRIVATE_QUERY` rows (high)
- `_detect_route_default_internet` — D1: from `_ROUTE_DEFAULT_INTERNET_QUERY` rows (high)
- `_detect_subnet_overlap` — D2: `ipaddress.ip_network.overlaps()`, capped at 500 (high)
- `_detect_missing_hub_spoke` — D3: heuristic ≥3-peering hub, severity=low

### Task 1.6 — All Detectors Wired ✅
All 17 detectors called sequentially in `fetch_network_topology()` after `_assemble_graph()`.
Issues sorted critical→high→medium→low, de-duplicated by `id`, cached at 900s TTL.
Return dict shape unchanged: `{nodes, edges, issues, _nsg_rules_map, _nic_subnet_map}`.

### Task 1.7 — Unit Tests ✅
89 tests total (up from ~54). All pass. Edge cases covered:
- A1: port range "22-25" triggers detection
- A3: GatewaySubnet excluded
- A4: same-access rules not flagged as shadowed
- B3: VpnGw2AZ not flagged; VpnGw2 flagged
- C1: NIC with PIP but no VM → not flagged
- C3: both Standard SKU → no mismatch
- D2: same VNet subnets → not flagged; >500 subnets → warning + continues
- D3: exactly 2 peerings → not detected as hub

### Task 1.8 — Integration Smoke Test ✅
`TestFetchTopologyCacheCountAfterPhase108` verifies 24 queries total (20 original + 4 new), cache works correctly on second call.

## Tests

```
89 passed in 0.35s
```

## Files Modified

- `services/api-gateway/network_topology_service.py` — unified schema, 17 detectors, 4 new ARG queries, wired in fetch function
- `services/api-gateway/tests/test_network_topology_service.py` — 89 unit tests
