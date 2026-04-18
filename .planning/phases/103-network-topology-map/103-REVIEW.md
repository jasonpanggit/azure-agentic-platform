# Phase 103 — Network Topology Map: Code Review

> Reviewed: 2026-04-18  
> Depth: Standard  
> Files: 9 (backend service, endpoints, tests, proxy routes, UI components, package.json)

---

## Overall Assessment

**PASS with minor issues.** The implementation is well-structured and follows project conventions throughout. The backend is fault-tolerant (never raises), the frontend uses the correct live-load pattern with `useEffect`-on-mount + polling, and the proxy routes conform to the gateway proxy pattern. A few medium issues are noted; no critical or blocking defects found.

---

## File-by-File Findings

### `network_topology_service.py`

**Strengths**
- Never-raise contract honoured throughout — all public functions catch broadly and return empty-safe results.
- `start_time = time.monotonic()` + `duration_ms` logging on all paths (including early-return guards and error paths).
- Custom in-memory TTL cache with a thread-safe `threading.Lock` is consistent with the project's `arg_cache` pattern.
- Module-level `try/except ImportError` scaffold for `run_arg_query` is correct per project conventions.
- ARG queries are clean KQL with `tolower()` normalisation on IDs — consistent casing throughout.
- 7 parallel ARG queries per topology fetch; cache prevents redundant multi-subscription fan-out on repeat calls.

**Issues**

| Severity | Location | Description |
|----------|----------|-------------|
| MEDIUM | `evaluate_path_check` L583–598 | Path-check **re-queries NSG rules unconditionally** via a fresh `run_arg_query` call even though the topology was just fetched (and may be fresh from cache). The topology cache stores nodes/edges but not raw `nsg_rules_map`. This doubles the NSG query cost on every path-check invocation. Consider storing the raw rules in the cache alongside nodes/edges, or passing them through. |
| MEDIUM | `_resolve_resource_nsg` L678–709 | The fallback heuristic at L696–708 is O(nodes × edges) and returns **the first subnet-nsg edge found for any subnet in the same VNet** regardless of which subnet the resource belongs to. For multi-subnet VNets this will silently pick the wrong NSG, giving incorrect path-check verdicts without any warning. |
| LOW | `_get_cached_or_fetch` L123–135 | The lock is released between the read check (L126–131) and the write (L133–134), creating a **TOCTOU race** where two concurrent callers can both miss the cache and both invoke `fetch_fn()`. Consider holding the lock across the full operation or using a double-checked pattern. The current pattern is acceptable given TTL-based staleness tolerance but worth noting. |
| LOW | `_detect_asymmetries` L258–293 | Asymmetry detection uses `"*"` as both source and destination prefix when calling `_evaluate_nsg_rules`. This is a permissive approximation — it ignores rules that restrict by CIDR and may miss real blocks or report false asymmetries for NSGs with CIDR-scoped rules. Acceptable for a first pass but not production-accurate. |
| LOW | `_assemble_graph` L310+ | `public_ips` and `nics` are fetched (7 queries) but `nics` is passed to `_assemble_graph` and then **never used inside it**. `public_ips` is similarly fetched but not incorporated into any node's data (e.g., gateway or LB public IP resolution). This is dead query cost. |

---

### `network_topology_endpoints.py`

**Strengths**
- Thin router with no business logic — correct architecture.
- Both endpoints use `Depends(verify_token)` and `Depends(get_credential_for_subscriptions)` — auth and credential injection correct.
- `resolve_subscription_ids` used consistently.
- Structured `logger.info` with key metrics on every response.

**Issues**

| Severity | Location | Description |
|----------|----------|-------------|
| LOW | `PathCheckRequest` L31–37 | `port` has no validation bounds. A caller can send `port=0` or `port=99999`. Add `port: int = Field(ge=1, le=65535)` (requires `from pydantic import Field`). |

---

### `tests/test_network_topology_service.py`

**Strengths**
- Good coverage of NSG scoring, port range matching, rule evaluation, asymmetry detection, topology assembly, caching, and path-check error handling.
- `_cache.clear()` called before each test that touches the cache — correct isolation.
- Row factory helpers avoid repetition and are easy to read.

**Issues**

| Severity | Location | Description |
|----------|----------|-------------|
| MEDIUM | `TestPathCheck.test_path_check_allowed` L282–307 | Assertion is `assert result["verdict"] in ("allowed", "blocked")` — this test passes regardless of the actual verdict. It tests nothing meaningful. Should assert `== "allowed"` or explicitly document why both are acceptable. |
| MEDIUM | `TestPathCheck.test_path_check_blocked_by_dest_nsg` L309–336 | Same problem — asserts `in ("allowed", "blocked", "error")` which is vacuously true for all possible non-exception paths. The test intent (blocked by dest NSG) is not verified. |
| LOW | Coverage gap | No test for `_resolve_resource_nsg` directly. Given the heuristic is fragile (see service finding above), a dedicated unit test for the subnet resolution logic would be valuable. |
| LOW | Coverage gap | `_assemble_graph` with LBs, PEs, and gateways has no dedicated test. Only vnet/nsg assembly is tested. |

---

### `app/api/proxy/network/topology/route.ts`

**Strengths**
- Follows proxy route pattern exactly: `getApiGatewayUrl()` + `buildUpstreamHeaders()` + `AbortSignal.timeout(15000)`.
- `runtime = 'nodejs'` and `dynamic = 'force-dynamic'` set correctly.
- Structured error logging on both upstream errors and gateway-unreachable paths.

**No issues found.**

---

### `app/api/proxy/network/topology/path-check/route.ts`

**Strengths**
- Identical proxy pattern to the topology GET route.
- `Content-Type: application/json` added to headers for POST — correct.

**No issues found.**

---

### `NetworkTopologyTab.tsx`

**Strengths**
- `useEffect` fires `fetchData()` on mount with `setInterval` polling — correct live-load pattern per project rules. No scan button anywhere.
- Empty state message: "No network resources found in the current subscriptions." — correct (not "run a scan").
- ELK layout via `elkjs` — appropriate choice for hierarchical network graphs.
- Custom node types cover all 6 resource types from the API.
- All colors via CSS semantic tokens (`var(--accent-*)`, `var(--bg-surface)`, etc.) — no hardcoded Tailwind colors.
- NSG health badge uses `color-mix(in srgb, var(--accent-*) 15%, transparent)` — matches project dark-mode badge pattern.
- Path-check sheet includes step-by-step timeline with per-step rule name and priority.
- `handleClearPathCheck` restores full graph from `topologyData` — clean state reset.

**Issues**

| Severity | Location | Description |
|----------|----------|-------------|
| MEDIUM | `handlePathCheck` L531 | `catch {}` is a **silent swallow** — path-check errors are discarded with no feedback to the user. The UI should set an error state or display a toast so the operator knows the check failed. |
| MEDIUM | `resourceOptions` L552–558 | The path-check dropdowns offer `subnet`, `nsg`, and `vnet` nodes as selectable resources. The path-check API expects VM/NIC resource IDs; selecting a VNet or NSG ID will produce unreliable results from `_resolve_resource_nsg`. Either restrict to subnet/NIC IDs or update the API to handle VNet-level inputs explicitly. |
| LOW | `transformToReactFlowNodes` L371–379 | `position: { x: 0, y: 0 }` is set as the initial position for all nodes before ELK runs. This is fine, but if ELK layout fails (async) the nodes will stack at origin. There is no error handling around `computeLayout` in `fetchData`. An ELK failure would leave the graph unusable silently. |
| LOW | `NsgNode` L203 | `data.healthStatus` is read from the ReactFlow node data, but the backend returns the health field as `data.health` (not `healthStatus`). In `transformToReactFlowNodes`, `n.data` is spread directly, so the backend key `health` will be present but `healthStatus` will be `undefined`, defaulting to `"green"`. All NSGs will always appear green in the UI regardless of backend scoring. |

---

### `NetworkHubTab.tsx`

**Strengths**
- Clean sub-tab switcher; `NetworkTopologyTab` is the default sub-tab.
- `subscriptions` prop is passed through to `PrivateEndpointTab` but not to `NetworkTopologyTab` — consistent with the other sub-tabs that use their own subscription resolution.

**No issues found.**

---

### `package.json`

**Strengths**
- `@xyflow/react: ^12.10.2` and `elkjs: ^0.11.1` — both appropriate and current.
- `tailwindcss: ^4.0.0` — note this is Tailwind v4; CLAUDE.md specifies `v3.4.19`. If the project is intentionally on v4, that's fine, but worth noting the discrepancy.

---

## Summary of Issues

| Severity | Count | Items |
|----------|-------|-------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 5 | Re-query NSG in path-check; weak `_resolve_resource_nsg` heuristic; two vacuous path-check test assertions; silent path-check error catch; NSG health key mismatch (`health` vs `healthStatus`) |
| LOW | 6 | TOCTOU cache race; asymmetry detection CIDR approximation; dead `nics`/`public_ips` fetch; port validation; missing `_resolve_resource_nsg` unit test; ELK error unhandled |

---

## Required Fixes Before Ship

1. **NSG health key mismatch** (MEDIUM, `NsgNode`): `data.health` from API is mapped to `n.data.health` in ReactFlow nodes, but `NsgNode` reads `data.healthStatus`. Fix the read in `NsgNode` to use `data.health` or rename at transform time.
2. **Silent path-check error** (MEDIUM, `handlePathCheck`): Add user-visible error feedback on catch.
3. **Vacuous test assertions** (MEDIUM, tests): Tighten `test_path_check_allowed` and `test_path_check_blocked_by_dest_nsg` to assert specific expected verdicts.

## Recommended Fixes

4. **Dead `nics` fetch** (LOW): Either use NIC data in graph assembly (for NIC-level NSG resolution) or remove the query to save one ARG call per topology refresh.
5. **Port validation** (LOW): Add `Field(ge=1, le=65535)` to `PathCheckRequest.port`.
