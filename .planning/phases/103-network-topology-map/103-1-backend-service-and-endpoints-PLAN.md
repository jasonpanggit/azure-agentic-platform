---
wave: 1
depends_on: []
files_modified:
  - services/api-gateway/network_topology_service.py
  - services/api-gateway/network_topology_endpoints.py
  - services/api-gateway/main.py
  - services/api-gateway/tests/test_network_topology_service.py
autonomous: true
---

# Plan 103-1: Backend — Network Topology Service & Endpoints

## Goal

Create `network_topology_service.py` (7 ARG queries, graph assembly, NSG health scoring, path-check evaluation) and `network_topology_endpoints.py` (GET /api/v1/network-topology + POST /api/v1/network-topology/path-check). Register router in main.py. Full test coverage.

---

## Tasks

<task id="1">
<title>Create network_topology_service.py</title>
<read_first>
  - services/api-gateway/vnet_peering_service.py
  - services/api-gateway/lb_health_service.py
  - .planning/phases/103-network-topology-map/103-RESEARCH.md
  - .planning/phases/103-network-topology-map/103-PATTERNS.md
</read_first>
<action>
Create `services/api-gateway/network_topology_service.py` with:

1. **Imports and logger** — follow vnet_peering_service.py pattern. Lazy import `run_arg_query` from `services.api_gateway.arg_helper` with try/except fallback to None.

2. **7 ARG query constants** (copy exact KQL from RESEARCH.md §3):
   - `_VNET_SUBNET_QUERY` — VNets with subnets, address space, subnet NSG associations
   - `_NSG_RULES_QUERY` — NSGs with security rules, subnet/NIC associations
   - `_LB_QUERY` — Load balancers with frontend IPs
   - `_PE_QUERY` — Private endpoints with subnet and target resource
   - `_GATEWAY_QUERY` — ExpressRoute/VPN gateways with subnet and public IP
   - `_PUBLIC_IP_QUERY` — Public IP addresses for enrichment
   - `_NIC_NSG_QUERY` — NICs with NSG associations and private IPs

3. **In-memory TTL cache** — `_cache` dict, `_cache_lock` threading.Lock, `_TOPOLOGY_TTL_SECONDS = 900`, `_get_cached_or_fetch(key, ttl, fetch_fn)` function (pattern from PATTERNS.md §1).

4. **Helper functions:**
   - `_score_nsg_health(nsg_rules: List[Dict]) -> str` — returns 'green', 'yellow', or 'red':
     - Red: any rule with access='Allow', sourcePrefix='*', destPortRange='*', priority < 1000 AND there exist deny rules in a related NSG for common ports (22,80,443,3389) — but for MVP simplify: red if asymmetry detected (set externally), yellow if any rule has source='*' AND destPortRange='*' AND access='Allow' AND priority < 1000, green otherwise.
     - Actually: `_score_nsg_health` only checks permissiveness (yellow/green). Asymmetry (red) is set by `_detect_asymmetries` which returns affected NSG IDs.
   - `_detect_asymmetries(nsg_map, subnet_nsg_map, vnet_subnets, nsg_rules_map)` — for each peered VNet pair, for common ports (22,80,443,3389) TCP, check if source subnet NSG allows outbound but destination subnet NSG denies inbound (or vice versa). Returns list of `{"source_nsg_id": ..., "dest_nsg_id": ..., "port": ..., "description": "..."}`.
   - `_matches_rule(rule, port, protocol, src_prefix, dst_prefix) -> bool` — rule matching per RESEARCH.md §2.
   - `_port_in_range(port, range_str, ranges_list) -> bool` — handles '*', single port, ranges like '1024-65535', comma-separated.
   - `_evaluate_nsg_rules(rules, port, protocol, src_prefix, dst_prefix, direction) -> Dict` — iterate rules sorted by priority ascending, return first match `{"result": "Allow"|"Deny", "matching_rule": name, "priority": N}`. If no match, return default deny (65500).
   - `_assemble_graph(vnets, nsgs, lbs, pes, gateways, public_ips, nics) -> Tuple[List[Dict], List[Dict]]` — builds nodes list and edges list. Each node: `{"id": str, "type": "vnet"|"subnet"|"nsg"|"lb"|"pe"|"gateway", "label": str, "data": {...}}`. Each edge: `{"id": str, "source": str, "target": str, "type": "peering"|"subnet-nsg"|"subnet-lb"|"subnet-pe"|"subnet-gateway"|"asymmetry", "data": {...}}`.

5. **Public functions (never raise):**
   - `fetch_network_topology(subscription_ids, credential=None) -> Dict[str, Any]` — returns `{"nodes": [...], "edges": [...], "issues": [...]}`. Uses `_get_cached_or_fetch` with key based on sorted subscription_ids. Runs 7 ARG queries, calls `_assemble_graph`, `_detect_asymmetries`, merges asymmetry issues into edges and updates NSG health to 'red' for affected NSGs.
   - `evaluate_path_check(source_resource_id, destination_resource_id, port, protocol, subscription_ids, credential=None) -> Dict[str, Any]` — returns `{"verdict": "allowed"|"blocked"|"error", "steps": [...], "blocking_nsg_id": str|None, "source_ip": str, "destination_ip": str}`. Fetches topology (cached), resolves source/dest to subnet→NSG chain, evaluates outbound then inbound per RESEARCH.md §2 algorithm.

Both public functions: `start_time = time.monotonic()` at entry, `duration_ms` in both try and except, never raise.
</action>
<acceptance_criteria>
  - grep -c "_VNET_SUBNET_QUERY" services/api-gateway/network_topology_service.py returns 1+
  - grep -c "_NSG_RULES_QUERY" services/api-gateway/network_topology_service.py returns 1+
  - grep -c "_NIC_NSG_QUERY" services/api-gateway/network_topology_service.py returns 1+
  - grep "def fetch_network_topology" services/api-gateway/network_topology_service.py
  - grep "def evaluate_path_check" services/api-gateway/network_topology_service.py
  - grep "_TOPOLOGY_TTL_SECONDS = 900" services/api-gateway/network_topology_service.py
  - grep "def _get_cached_or_fetch" services/api-gateway/network_topology_service.py
  - grep "def _score_nsg_health" services/api-gateway/network_topology_service.py
  - grep "def _detect_asymmetries" services/api-gateway/network_topology_service.py
  - grep "def _matches_rule" services/api-gateway/network_topology_service.py
  - grep "def _evaluate_nsg_rules" services/api-gateway/network_topology_service.py
  - grep "def _assemble_graph" services/api-gateway/network_topology_service.py
  - grep 'run_arg_query' services/api-gateway/network_topology_service.py
  - grep 'start_time = time.monotonic()' services/api-gateway/network_topology_service.py
  - No occurrences of "raise" in public functions (fetch_network_topology, evaluate_path_check)
</acceptance_criteria>
</task>

<task id="2">
<title>Create network_topology_endpoints.py</title>
<read_first>
  - services/api-gateway/vnet_peering_endpoints.py
  - services/api-gateway/network_topology_service.py (just created in task 1)
  - .planning/phases/103-network-topology-map/103-PATTERNS.md
</read_first>
<action>
Create `services/api-gateway/network_topology_endpoints.py` following vnet_peering_endpoints.py pattern:

1. `router = APIRouter(prefix="/api/v1/network-topology", tags=["network-topology"])`

2. `PathCheckRequest` Pydantic model:
   - `source_resource_id: str`
   - `destination_resource_id: str`
   - `port: int`
   - `protocol: str = "TCP"`

3. `GET ""` endpoint — `get_topology(request, subscription_id=Query(None), token=Depends(verify_token), credential=Depends(get_credential_for_subscriptions))`:
   - Docstring: `"""Return network topology graph queried live from ARG (15m TTL cache)."""`
   - Calls `resolve_subscription_ids`, then `fetch_network_topology`
   - Logs duration with node/edge count
   - Returns dict directly

4. `POST "/path-check"` endpoint — `path_check(body: PathCheckRequest, request, subscription_id=Query(None), token, credential)`:
   - Docstring: `"""Evaluate NSG rule chain for source->destination traffic. On-demand, not cached."""`
   - Calls `evaluate_path_check` with body fields
   - Logs verdict and duration

Import verify_token, get_credential_for_subscriptions, resolve_subscription_ids from same locations as vnet_peering_endpoints.py.
</action>
<acceptance_criteria>
  - grep 'prefix="/api/v1/network-topology"' services/api-gateway/network_topology_endpoints.py
  - grep "class PathCheckRequest" services/api-gateway/network_topology_endpoints.py
  - grep "async def get_topology" services/api-gateway/network_topology_endpoints.py
  - grep "async def path_check" services/api-gateway/network_topology_endpoints.py
  - grep "queried live from ARG" services/api-gateway/network_topology_endpoints.py
  - grep "On-demand, not cached" services/api-gateway/network_topology_endpoints.py
  - grep "fetch_network_topology" services/api-gateway/network_topology_endpoints.py
  - grep "evaluate_path_check" services/api-gateway/network_topology_endpoints.py
  - No occurrences of "/scan" in the file
</acceptance_criteria>
</task>

<task id="3">
<title>Register router in main.py</title>
<read_first>
  - services/api-gateway/main.py
  - services/api-gateway/network_topology_endpoints.py (task 2)
</read_first>
<action>
In `services/api-gateway/main.py`:

1. Add import near the other router imports (around the block that imports vnet_peering_router, lb_health_router, etc.):
   ```python
   from services.api_gateway.network_topology_endpoints import router as network_topology_router
   ```

2. Add `app.include_router(network_topology_router)` after the `app.include_router(lb_health_router)` line (around line 853).
</action>
<acceptance_criteria>
  - grep "network_topology_router" services/api-gateway/main.py
  - grep "include_router(network_topology_router)" services/api-gateway/main.py
</acceptance_criteria>
</task>

<task id="4">
<title>Create test_network_topology_service.py</title>
<read_first>
  - services/api-gateway/tests/test_vnet_peering_service.py
  - services/api-gateway/network_topology_service.py (task 1)
  - .planning/phases/103-network-topology-map/103-PATTERNS.md
</read_first>
<action>
Create `services/api-gateway/tests/test_network_topology_service.py` with comprehensive tests:

**Row factory helpers:**
- `_make_vnet_row(subscription_id="sub-1", vnet_name="vnet-1", address_space="[10.0.0.0/16]", subnet_name="subnet-1", subnet_prefix="10.0.1.0/24", subnet_nsg_id="")` — returns dict matching _VNET_SUBNET_QUERY columns
- `_make_nsg_row(nsg_name="nsg-1", nsg_id="", rule_name="AllowSSH", priority=100, direction="Inbound", access="Allow", protocol="TCP", source_prefix="*", dest_prefix="*", dest_port_range="22")` — returns dict matching _NSG_RULES_QUERY columns
- `_make_nic_row(name="nic-1", subnet_id="", nsg_id="", private_ip="10.0.1.4")` — returns dict matching _NIC_NSG_QUERY columns

**Test classes/functions (minimum 15 tests):**

1. `test_score_nsg_health_green_no_issues` — rules with specific ports and sources → 'green'
2. `test_score_nsg_health_yellow_overly_permissive` — rule with source='*', destPortRange='*', access='Allow', priority=500 → 'yellow'
3. `test_fetch_topology_empty_subscriptions` — `fetch_network_topology([])` returns `{"nodes": [], "edges": [], "issues": []}`
4. `test_fetch_topology_no_credential` — returns empty graph
5. `test_fetch_topology_arg_error_returns_empty` — mock run_arg_query to raise → returns empty graph, never raises
6. `test_fetch_topology_assembles_vnet_nodes` — mock 7 ARG queries with 2 VNets, verify nodes contain both VNets with type="vnet"
7. `test_fetch_topology_assembles_nsg_edges` — mock NSG with subnet association, verify edge with type="subnet-nsg"
8. `test_detect_asymmetries_found` — two subnets in peered VNets, source NSG allows port 443 outbound, dest NSG has no matching inbound allow → returns asymmetry issue
9. `test_detect_asymmetries_none` — both NSGs allow → empty issues list
10. `test_matches_rule_exact_port` — rule destPortRange="443", port=443 → True
11. `test_matches_rule_port_range` — rule destPortRange="1024-65535", port=8080 → True
12. `test_matches_rule_wildcard` — rule destPortRange="*", protocol="*" → True for any port/protocol
13. `test_matches_rule_no_match` — rule for port 80, check port 443 → False
14. `test_evaluate_nsg_rules_first_match_wins` — two rules: priority 100 Allow, priority 200 Deny → result is Allow
15. `test_path_check_allowed` — mock topology with allowing NSGs → verdict "allowed"
16. `test_path_check_blocked_by_dest_nsg` — mock topology where dest NSG denies → verdict "blocked", blocking_nsg_id set
17. `test_path_check_error_returns_error_verdict` — mock to raise → verdict "error", never raises
18. `test_cache_returns_cached_result` — call fetch twice, verify run_arg_query called only once within TTL

Use `@patch("services.api_gateway.network_topology_service.run_arg_query")` for mocking.

Run: `cd services/api-gateway && python -m pytest tests/test_network_topology_service.py -v` — all tests pass.
</action>
<acceptance_criteria>
  - grep -c "def test_" services/api-gateway/tests/test_network_topology_service.py returns 15+
  - grep "test_fetch_topology_empty_subscriptions" services/api-gateway/tests/test_network_topology_service.py
  - grep "test_path_check_blocked_by_dest_nsg" services/api-gateway/tests/test_network_topology_service.py
  - grep "test_matches_rule_exact_port" services/api-gateway/tests/test_network_topology_service.py
  - grep "test_cache_returns_cached_result" services/api-gateway/tests/test_network_topology_service.py
  - grep "test_detect_asymmetries_found" services/api-gateway/tests/test_network_topology_service.py
  - python -m pytest services/api-gateway/tests/test_network_topology_service.py passes
</acceptance_criteria>
</task>

---

## Verification

```bash
# All tests pass
cd services/api-gateway && python -m pytest tests/test_network_topology_service.py -v

# Service file exists with key functions
grep -c "def " services/api-gateway/network_topology_service.py  # 8+

# Endpoints registered
grep "network_topology_router" services/api-gateway/main.py

# No scan pattern violations
grep -r "scan" services/api-gateway/network_topology_endpoints.py || echo "PASS: no scan references"
grep -r "scan" services/api-gateway/network_topology_service.py || echo "PASS: no scan references"
```

## must_haves

- [ ] `GET /api/v1/network-topology` returns `{nodes, edges, issues}` from live ARG with 900s TTL cache
- [ ] `POST /api/v1/network-topology/path-check` evaluates NSG rule chain and returns verdict with blocking NSG ID
- [ ] NSG health scoring: green (clean), yellow (overly permissive), red (asymmetric block)
- [ ] Asymmetry auto-detection on common ports (22, 80, 443, 3389)
- [ ] 7 ARG queries cover VNets, subnets, NSGs, LBs, PEs, gateways, NICs
- [ ] No scan button, no Cosmos intermediary — ARG-backed with TTL cache
- [ ] 15+ tests passing, covering scoring, assembly, path check, caching, edge cases
- [ ] Router registered in main.py
