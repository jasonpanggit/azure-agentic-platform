# Research: ARG OS Version Fields for Arc-Enabled Servers + EOL Mapping

**Date:** 2026-04-01
**Task:** Can ARG return OS version details for Arc-enabled servers for EOL determination?
**TL;DR:** Yes — and it's **already implemented** in `agents/eol/tools.py`. The compute agent (`agents/compute/tools.py`) is the only place that's missing OS version details.

---

## 1. ARG Schema for `Microsoft.HybridCompute/machines`

ARG exposes the following OS fields for Arc-enabled servers under `properties.*`:

| Field | ARG path | Example value | Notes |
|---|---|---|---|
| `osName` | `properties.osName` | `"Ubuntu 22.04.3 LTS"` / `"Windows Server 2019 Datacenter"` | Human-readable display name. Best for EOL slug matching. |
| `osVersion` | `properties.osVersion` | `"5.15.0-113-generic"` (Linux kernel) / `"10.0.17763.6659"` (Windows build) | **Kernel/build version, not distro version.** For Linux this is the kernel string, not the distro cycle. |
| `osType` | `properties.osType` | `"linux"` / `"windows"` | Case varies; normalize to lowercase. |
| `osSku` | `properties.osSku` | `"22.04"` / `"2019-datacenter"` | **Most reliable for EOL cycle extraction.** Ubuntu gives `"22.04"`, RHEL gives `"8.9"`, Windows gives the SKU slug. |
| `status` | `properties.status` | `"Connected"` / `"Disconnected"` | Agent connectivity — not OS version, but useful for filtering. |

### Key distinction: `osVersion` vs `osSku`

- **`osVersion` for Linux** = kernel version string (e.g., `"5.15.0-113-generic"`). **Not suitable for EOL mapping** directly — you'd need to extract the distro version separately.
- **`osName` for Linux** = full distro name including version (e.g., `"Ubuntu 22.04.3 LTS"`). Parse `"22.04"` from this for the endoflife.date cycle.
- **`osSku` for Linux** = the distro version cycle directly (e.g., `"22.04"` for Ubuntu, `"8.9"` for RHEL). **Best field for EOL cycle**.
- **`osVersion` for Windows** = full build string (e.g., `"10.0.17763.6659"`). Parse major.minor for MS Lifecycle matching.
- **`osName` for Windows** = `"Windows Server 2019 Datacenter"`. Direct MS Lifecycle product name — best for Windows EOL lookup.

### For Azure VMs (`Microsoft.Compute/virtualMachines`)

ARG requires `instanceView` to be populated (only available if the VM has been running and the Compute RP has refreshed). The fields are under `properties.extended.instanceView`:

| Field | ARG path | Notes |
|---|---|---|
| `osName` | `properties.extended.instanceView.osName` | Same format as Arc |
| `osVersion` | `properties.extended.instanceView.osVersion` | Same kernel/build string caveat |
| Image fallback | `properties.storageProfile.imageReference.{publisher,offer,sku}` | Always present; `sku` gives e.g. `"22_04-lts-gen2"` or `"2019-Datacenter"` |

---

## 2. Existing ARG Query Pattern in the Codebase

The `eol/tools.py` `query_os_inventory` tool (lines 400–511) **already implements the correct pattern** for both resource types:

```python
# Arc-enabled servers — the correct fields to project:
arc_kql = (
    "resources\n"
    '| where type == "microsoft.hybridcompute/machines"\n'
    "| extend osName = tostring(properties.osName),\n"
    "         osVersion = tostring(properties.osVersion),\n"
    "         osType = tostring(properties.osType),\n"
    "         osSku = tostring(properties.osSku),\n"
    "         status = tostring(properties.status)\n"
    "| project id, name, resourceGroup, subscriptionId, osName, osVersion,\n"
    "          osType, osSku, status"
)
```

The `scan_estate_eol` tool (lines 1074–1263) then uses `osName` or `osSku` as the primary product identifier for EOL lookup, falling back through `normalize_product_slug` → endoflife.date or MS Lifecycle.

**Pattern to follow:** `ResourceGraphClient` + `QueryRequest` + pagination via `skip_token`. Credentials via `get_credential()`. All of this is already established.

---

## 3. EOL Mapping Feasibility

### What ARG returns and what EOL APIs need

| OS | ARG field to use | EOL API | Cycle format |
|---|---|---|---|
| Ubuntu 22.04 | `osSku` = `"22.04"` or parse `osName` | endoflife.date `/api/ubuntu/22.04.json` | `"22.04"` |
| RHEL 8.9 | `osSku` = `"8.9"` → extract `"8"` | endoflife.date `/api/rhel/8.json` | `"8"` (major only) |
| Windows Server 2019 | `osName` = `"Windows Server 2019 Datacenter"` | MS Lifecycle `products?$filter=contains(productName,'Windows Server 2019')` | product name string |
| Windows Server 2022 | same pattern | MS Lifecycle | same |

### EOL date sources (already implemented in `eol/tools.py`)

1. **endoflife.date API** (`https://endoflife.date/api/{product}/{version}.json`) — covers Ubuntu, RHEL, Python, Node.js, PostgreSQL, MySQL, Kubernetes. Free, no auth, ~200 products. **Already implemented** with PostgreSQL 24h cache.
2. **Microsoft Product Lifecycle API** (`https://learn.microsoft.com/api/lifecycle/products`) — covers Windows Server, SQL Server, .NET. No auth, 1 req/s limit. **Already implemented** with fallback to endoflife.date.

### Normalization logic

`normalize_product_slug()` in `eol/tools.py` handles the string → (source, slug, cycle) mapping. Key patterns:
- `"ubuntu"` + `"22.04"` → `("endoflife.date", "ubuntu", "22.04")`
- `"windows server 2019"` → `("ms-lifecycle", "windows-server-2019", "")`
- `"rhel"` + `"8.9"` → `("endoflife.date", "rhel", "8")` ← **Note:** needs major-only extraction for RHEL cycles

---

## 4. What the Compute Agent Is Missing

The current `compute/tools.py` returns **zero OS version detail**. The agent's triage tools (`query_activity_log`, `query_log_analytics`, `query_resource_health`, `query_monitor_metrics`) deal exclusively with operational signals, not inventory.

There is no ARG query in `compute/tools.py` at all. The compute agent currently cannot answer "what OS version is this VM running?" from its own tools — it would need to use MCP `compute.get_vm` to get that from the ARM layer.

---

## 5. Implementation Approach

### Recommendation: **No change needed to `compute/tools.py`**

The EOL agent already owns OS version inventory via `query_os_inventory`. The architecture is correct:

- **EOL agent** = OS version discovery + EOL status → `query_os_inventory` + `scan_estate_eol`
- **Compute agent** = operational triage → CPU/memory/disk/network signals

If the task is to surface EOL information in compute triage, the cleanest path is:

**Option A (preferred): Orchestrator handoff**
When compute triage identifies a VM, the orchestrator can fan out to the EOL agent in parallel to check if the OS is near EOL. No changes to compute tools needed. This is already supported by the `needs_cross_domain` / `suspected_domain` fields in the compute agent's triage response format.

**Option B: Add `query_os_version` to compute tools**
If the compute agent needs to self-answer OS version questions (e.g., "Is this VM running an EOL OS?"), add a minimal ARG tool:

```python
@ai_function
def query_os_version(
    resource_ids: List[str],
    subscription_ids: List[str],
) -> Dict[str, Any]:
    """Query ARG for OS version details for the given resource IDs.

    Returns osName, osVersion, osType, osSku for each resource.
    Covers both microsoft.compute/virtualmachines (instanceView) and
    microsoft.hybridcompute/machines (properties.osName/osSku).
    """
```

This would be a ~50-line addition mirroring the pattern in `eol/tools.py` lines 438–511. The key fields to return per resource:
- `osName` — human-readable, good for display
- `osSku` — best for EOL cycle extraction (Arc servers)
- `osType` — `"linux"` or `"windows"`
- `imageReference.sku` — VM image SKU fallback

**Option C: Extend `query_resource_health` return**
Not recommended. Resource Health is a different API (`/providers/Microsoft.ResourceHealth/availabilityStatuses`). Mixing OS version inventory into a health check creates confusing tool semantics.

---

## Summary

| Question | Answer |
|---|---|
| Can ARG return OS version for Arc servers? | ✅ Yes — `properties.osName`, `properties.osSku`, `properties.osVersion` |
| Best field for EOL cycle extraction? | `properties.osSku` for Arc (gives `"22.04"`, `"8.9"`); `properties.osName` for Windows |
| Is `osVersion` a semver? | ❌ No — it's the kernel string (Linux) or build number (Windows). Not directly usable for EOL lookup. |
| Is this already implemented somewhere? | ✅ Yes — `agents/eol/tools.py` `query_os_inventory` has the exact queries. |
| EOL date API? | ✅ endoflife.date + MS Lifecycle, both already integrated with PostgreSQL cache. |
| What needs to change in `compute/tools.py`? | Nothing unless compute agent needs to self-answer EOL questions. If so, add Option B above (~50 lines). |
| Right architecture? | Orchestrator fans out to EOL agent. Compute agent sets `needs_cross_domain=True, suspected_domain="eol"`. |
