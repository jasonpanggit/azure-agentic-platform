---
phase: "108-1"
title: "Backend — Unified Issue Schema + 17 Detectors"
depends_on: ["Phase 103"]
estimated_effort: "L"
wave: 1
files_to_modify:
  - services/api-gateway/network_topology_service.py
  - services/api-gateway/tests/test_network_topology_service.py
files_to_create: []
---

# Plan 108-1: Backend — Unified Issue Schema + 17 Issue Detectors

## Goal

Replace the 4-field asymmetry-only issue schema with a unified `NetworkIssue` schema and implement 17 issue detectors across 4 categories (security, connectivity, configuration, routing). All detectors run inside `fetch_network_topology()` and populate the existing `issues` array — no API signature changes, no new endpoints.

---

## Task 1.1 — Define Unified `NetworkIssue` TypedDict

<read_first>
- `services/api-gateway/network_topology_service.py` lines 1-30 (imports + constants)
- `services/api-gateway/network_topology_service.py` lines 464-499 (`_detect_asymmetries`)
- `.planning/phases/108-network-topology-full-issue-detection/108-RESEARCH.md` § 4.1 (unified schema)
</read_first>

<action>
1. At module top (after imports), define a `NetworkIssue` TypedDict with fields:
   - `id: str` — deterministic hash of `(type, affected_resource_id)`
   - `type: str` — one of 17 enum values (e.g. `"nsg_asymmetry"`, `"port_open_internet"`, `"any_to_any_allow"`, `"subnet_no_nsg"`, `"nsg_rule_shadowed"`, `"vnet_peering_disconnected"`, `"vpn_bgp_disabled"`, `"gateway_not_zone_redundant"`, `"pe_not_approved"`, `"vm_public_ip"`, `"lb_empty_backend"`, `"lb_pip_sku_mismatch"`, `"firewall_no_policy"`, `"firewall_threatintel_off"`, `"aks_not_private"`, `"route_default_internet"`, `"subnet_overlap"`)
   - `severity: str` — `"critical" | "high" | "medium" | "low"`
   - `title: str`
   - `explanation: str`
   - `impact: str`
   - `affected_resource_id: str`
   - `affected_resource_name: str`
   - `related_resource_ids: list[str]`
   - `remediation_steps: list[dict]` — each `{"step": int, "action": str, "cli": str | None}`
   - `portal_link: str`
   - `auto_fix_available: bool`
   - `auto_fix_label: str | None`
   - `source_nsg_id: str | None` — backward compat for `focusIssue()`
   - `dest_nsg_id: str | None` — backward compat
   - `port: int | None` — backward compat
   - `description: str | None` — backward compat
2. Add a helper `_make_issue_id(issue_type: str, resource_id: str) -> str` that returns `hashlib.sha256(f"{issue_type}:{resource_id}".encode()).hexdigest()[:16]`.
3. Add a constant `_ISSUE_TYPES` dict mapping each type string to its default severity, title template, and portal link template.
4. Add a helper `_portal_link(resource_id: str, blade: str = "overview") -> str` that returns `f"https://portal.azure.com/#resource{resource_id}/{blade}"`.
</action>

<acceptance_criteria>
- `NetworkIssue` TypedDict importable and mypy-clean
- `_make_issue_id("nsg_asymmetry", "/subscriptions/.../nsg1")` returns a 16-char hex string
- `_portal_link("/subscriptions/.../nsg1", "securityRules")` returns correct URL
- All 17 type strings listed in `_ISSUE_TYPES`
</acceptance_criteria>

---

## Task 1.2 — Upgrade `_detect_asymmetries()` to Unified Schema

<read_first>
- `services/api-gateway/network_topology_service.py` lines 464-499 (`_detect_asymmetries`)
- `services/api-gateway/network_topology_service.py` lines 336-349 (`_score_nsg_health`)
</read_first>

<action>
1. Refactor `_detect_asymmetries()` to return `list[NetworkIssue]` instead of the legacy 4-field dicts.
2. Each issue must populate ALL unified fields: `id`, `type="nsg_asymmetry"`, `severity="high"`, `title`, `explanation` (plain-English), `impact`, `affected_resource_id` (dest NSG), `affected_resource_name`, `related_resource_ids=[source_nsg_id]`, `remediation_steps` (3 steps: open NSG → find deny rule → add matching allow rule), `portal_link` to dest NSG securityRules blade, `auto_fix_available=False`.
3. Retain `source_nsg_id`, `dest_nsg_id`, `port`, `description` as backward-compat fields on every asymmetry issue.
4. Include NIC-level NSGs in asymmetry detection (currently excluded). Build a `nic_nsg_map` from `nic_nsg_rows` and merge into the subnet-level check.
</action>

<acceptance_criteria>
- Asymmetry issues have all 17+ fields of `NetworkIssue`
- Legacy fields `source_nsg_id`, `dest_nsg_id`, `port`, `description` still present
- NIC-level NSGs participate in asymmetry detection
- Existing unit tests updated and passing
</acceptance_criteria>

---

## Task 1.3 — Implement Quick-Win Detectors (No New ARG Queries)

<read_first>
- `services/api-gateway/network_topology_service.py` lines 336-364 (`_score_nsg_health`, `_score_resource_health`)
- `services/api-gateway/network_topology_service.py` lines 547-1146 (`_assemble_graph` — PE nodes, firewall nodes, gateway nodes, peering edges)
- `.planning/phases/108-network-topology-full-issue-detection/108-RESEARCH.md` § 2 (issue catalog)
</read_first>

<action>
Implement 8 detector functions (each returns `list[NetworkIssue]`):

1. **`_detect_any_to_any_allow(nsg_rules_map)`** — A2: Find NSG rules where `source="*"`, `destPort="*"`, `access="Allow"`, `direction="Inbound"`. Severity: high.
2. **`_detect_subnet_no_nsg(vnet_rows)`** — A3: Subnets where `subnetNsgId` is empty. Exclude system subnets: `GatewaySubnet`, `AzureBastionSubnet`, `AzureFirewallSubnet`, `AzureFirewallManagementSubnet`. Severity: high.
3. **`_detect_port_open_internet(nsg_rules_map)`** — A1: Inbound Allow rules where source is `"*"` or `"Internet"` and dest port covers 22, 3389, 1433, 3306, 5432. Severity: critical.
4. **`_detect_nsg_rule_shadowing(nsg_rules_map)`** — A4: For each NSG, sort by priority; detect when a lower-priority rule is completely shadowed by a higher-priority rule with opposite access. Severity: medium.
5. **`_detect_peering_disconnected(edges)`** — B1: Edges where `type == "peering-disconnected"`. Severity: critical.
6. **`_detect_vpn_bgp_disabled(gateway_nodes)`** — B2: VPN gateway where `bgpEnabled == False`. Severity: medium.
7. **`_detect_gateway_not_zone_redundant(gateway_nodes)`** — B3: Gateway SKU does not end in `"AZ"`. Severity: medium.
8. **`_detect_pe_not_approved(pe_nodes)`** — B4: PE node where `connectionState != "Approved"`. Severity: critical. `auto_fix_available=True`, `auto_fix_label="Approve Connection"`.
9. **`_detect_firewall_no_policy(firewall_nodes)`** — C4: Firewall where `firewallPolicyId` is empty. Severity: critical.
10. **`_detect_firewall_threatintel_off(firewall_nodes)`** — C5: Firewall where `threatIntelMode == "Off"`. Severity: high. `auto_fix_available=True`, `auto_fix_label="Enable Threat Intelligence"`.

Each function is pure (takes data, returns issues). No side effects. All issues use `_make_issue_id()` and `_portal_link()`.
</action>

<acceptance_criteria>
- 10 new detector functions defined (A1-A5, B1-B4, C4, C5)
- Each returns `list[NetworkIssue]` with all unified fields populated
- `_detect_port_open_internet` catches ports 22, 3389, 1433, 3306, 5432
- `_detect_subnet_no_nsg` excludes 4 system subnet names
- `_detect_nsg_rule_shadowing` correctly identifies shadowed rules (same direction, subset port/source, opposite access)
- PE and Firewall ThreatIntel detectors set `auto_fix_available=True`
</acceptance_criteria>

---

## Task 1.4 — Add New ARG Queries

<read_first>
- `services/api-gateway/network_topology_service.py` lines 40-120 (existing ARG query constants)
- `services/api-gateway/network_topology_service.py` lines 1154-1250 (`fetch_network_topology` — parallel query dispatch)
- `.planning/phases/108-network-topology-full-issue-detection/108-RESEARCH.md` § 2 (C1, C2, C6, D1 queries)
</read_first>

<action>
Add 4 new ARG query constants and include them in the parallel `_safe_query` dispatch inside `fetch_network_topology()`:

1. **`_NIC_PUBLIC_IP_QUERY`** — For C1 (VM with public IP):
   ```kql
   Resources
   | where type =~ "microsoft.network/networkinterfaces"
   | mv-expand ipc = properties.ipConfigurations
   | extend publicIpId = tolower(tostring(ipc.properties.publicIPAddress.id))
   | where isnotempty(publicIpId)
   | project nicId = tolower(id), publicIpId
   ```

2. **`_LB_EMPTY_BACKEND_QUERY`** — For C2 (LB empty backend pool):
   ```kql
   Resources
   | where type == "microsoft.network/loadbalancers"
   | mv-expand pool = properties.backendAddressPools
   | extend memberCount = array_length(pool.properties.backendIPConfigurations)
   | extend addrCount = array_length(pool.properties.loadBalancerBackendAddresses)
   | where (memberCount == 0 or isnull(memberCount)) and (addrCount == 0 or isnull(addrCount))
   | project lbId = tolower(id), lbName = name, emptyPool = tostring(pool.name)
   ```

3. **`_AKS_PRIVATE_QUERY`** — For C6 (AKS not private):
   ```kql
   Resources
   | where type =~ "microsoft.containerservice/managedclusters"
   | extend isPrivate = tobool(properties.apiServerAccessProfile.enablePrivateCluster)
   | where isPrivate != true
   | project aksId = tolower(id), aksName = name
   ```

4. **`_ROUTE_DEFAULT_INTERNET_QUERY`** — For D1 (route 0.0.0.0/0 → Internet):
   ```kql
   Resources
   | where type == "microsoft.network/routetables"
   | mv-expand route = properties.routes
   | extend addressPrefix = tostring(route.properties.addressPrefix)
   | extend nextHopType = tostring(route.properties.nextHopType)
   | where addressPrefix == "0.0.0.0/0" and nextHopType == "Internet"
   | project rtId = tolower(id), rtName = name, routeName = tostring(route.name)
   ```

Add these 4 queries to the existing parallel `asyncio.gather` / `_safe_query` batch in `fetch_network_topology()`.
</action>

<acceptance_criteria>
- 4 new query constants defined at module level
- All 4 included in the parallel query dispatch (same `_safe_query` pattern as existing queries)
- Query results stored in named variables for use by detector functions
- No increase in sequential query rounds (all run in existing parallel batch)
</acceptance_criteria>

---

## Task 1.5 — Implement Remaining Detectors (New Query Data)

<read_first>
- `.planning/phases/108-network-topology-full-issue-detection/108-RESEARCH.md` § 2 (C1, C2, C3, C6, D1, D2, D3)
</read_first>

<action>
Implement 7 additional detector functions:

1. **`_detect_vm_public_ip(nic_public_ip_rows, vm_nic_map)`** — C1: VMs with public IP directly on NIC. Join NIC→public IP rows with VM→NIC mapping. Severity: critical. `auto_fix_available=False`.
2. **`_detect_lb_empty_backend(lb_empty_rows)`** — C2: LBs with empty backend pools. Severity: high.
3. **`_detect_lb_pip_sku_mismatch(lb_nodes, public_ip_map)`** — C3: LB Standard + Basic PIP (or vice versa). Cross-reference existing LB and PIP data. Severity: high.
4. **`_detect_aks_not_private(aks_private_rows)`** — C6: AKS clusters without private API server. Severity: high.
5. **`_detect_route_default_internet(route_default_rows)`** — D1: Route tables with 0.0.0.0/0 → Internet. Severity: high.
6. **`_detect_subnet_overlap(vnet_rows)`** — D2: Cross-VNet subnet CIDR overlap using `ipaddress.ip_network`. Only compare subnets across different VNets. Cap at 500 subnets with log warning. Severity: high.
7. **`_detect_missing_hub_spoke(vnet_nodes, peering_edges)`** — D3: Heuristic — VNets with 3+ peerings are hubs; check spoke VNets have peering back. Severity: low (heuristic). Add note in `explanation`.

All functions are pure, return `list[NetworkIssue]`.
</action>

<acceptance_criteria>
- 7 new detector functions defined (C1-C3, C6, D1-D3)
- `_detect_subnet_overlap` uses `ipaddress.ip_network(cidr, strict=False)` and `overlaps()` method
- `_detect_subnet_overlap` caps at 500 subnets with `logger.warning` if exceeded
- `_detect_missing_hub_spoke` marks issues as `severity="low"` with heuristic disclaimer
- `_detect_lb_pip_sku_mismatch` correctly cross-references LB SKU against PIP SKU
</acceptance_criteria>

---

## Task 1.6 — Wire All Detectors into `fetch_network_topology()`

<read_first>
- `services/api-gateway/network_topology_service.py` lines 1154-1364 (`fetch_network_topology`)
</read_first>

<action>
1. After `_assemble_graph()` returns and `_detect_asymmetries()` runs, call all 17 detector functions.
2. Collect results into a single `issues: list[NetworkIssue]` list.
3. Sort issues by severity: critical → high → medium → low.
4. De-duplicate by `id` (same issue shouldn't appear twice).
5. Replace the current `issues` key in the return dict with the unified list.
6. Extract node/edge data needed by detectors from the assembled graph (gateway_nodes, pe_nodes, firewall_nodes, peering edges, etc.) — pass as arguments to each detector.
7. Ensure the in-memory LRU cache (900s TTL) caches the full unified issues list.
</action>

<acceptance_criteria>
- `fetch_network_topology()` returns unified `issues` array with all 17 issue types
- Issues sorted by severity (critical first)
- No duplicate issues (de-duped by `id`)
- Cache stores and returns unified issues
- Return dict shape unchanged: `{nodes, edges, issues, _nsg_rules_map, _nic_subnet_map}`
</acceptance_criteria>

---

## Task 1.7 — Unit Tests for All Detectors

<read_first>
- `services/api-gateway/tests/test_network_topology_service.py` (existing test structure)
</read_first>

<action>
Add ~30 unit tests covering all 17 detectors:

**For each detector function, test:**
1. Happy path — input data triggers the issue → verify issue returned with correct fields
2. Negative path — input data does NOT trigger → verify empty list returned
3. Edge cases specific to each detector (documented below)

**Edge case tests:**
- A1: Rule with `destPortRange="22-25"` (range covering 22) should trigger
- A3: `GatewaySubnet` excluded even if no NSG
- A4: Two rules same direction, same port, same access → NOT shadowed (same access)
- A4: Two rules same direction, superset port, opposite access → shadowed
- B3: SKU `VpnGw2AZ` should NOT trigger; `VpnGw2` should trigger
- C1: NIC with public IP but not attached to any VM → NOT triggered (no VM link)
- C3: Both Standard SKU → no mismatch
- D2: Two subnets in SAME VNet → NOT flagged; across VNets → flagged
- D2: More than 500 subnets → warning logged, processing continues
- D3: VNet with exactly 2 peerings → NOT detected as hub

**Test structure:** Use `pytest.mark.parametrize` where multiple scenarios apply to same detector.
</action>

<acceptance_criteria>
- ≥30 new test cases across all 17 detectors
- All tests pass
- Edge cases for A1 (port range), A3 (system subnets), A4 (same-access not shadowed), D2 (same-VNet excluded, 500+ cap) covered
- Tests use pure function calls with mock data (no API calls)
</acceptance_criteria>

---

## Task 1.8 — Integration Smoke Test

<read_first>
- `services/api-gateway/network_topology_endpoints.py` lines 1-50 (GET endpoint)
</read_first>

<action>
1. Add an integration test that calls `GET /api/v1/network-topology` with mocked ARG responses containing trigger data for at least 5 different issue types.
2. Assert the response `issues` array contains unified `NetworkIssue` objects with correct `type`, `severity`, `title`, `affected_resource_id`, and `portal_link` fields.
3. Assert backward-compat fields (`source_nsg_id`, `dest_nsg_id`, `port`) present on asymmetry issues.
4. Assert issues are sorted by severity (critical before high before medium).
</action>

<acceptance_criteria>
- Integration test passes with mocked ARG data
- Response issues array contains ≥5 different issue types
- Asymmetry issues retain backward-compat fields
- Issues sorted by severity
- No changes to the `GET` endpoint signature or HTTP response code
</acceptance_criteria>
