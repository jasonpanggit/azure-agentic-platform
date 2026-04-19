# Phase 108 Research — Network Topology: Full Issue Detection, Explanations, Remediation & One-Click Fix

**Date:** 2026-04-19  
**Phase:** 108  
**Depends on:** Phase 103 (Network Topology Map)

---

## 1. Baseline Analysis — What Exists Today

### 1.1 Current Issue Detection

The existing `_detect_asymmetries()` function in `network_topology_service.py` is the **only** issue generator today. Here is exactly what it does:

- **What it detects:** NSG asymmetry — when Subnet A's NSG allows outbound TCP on a port AND Subnet B's NSG denies inbound TCP on the same port. This is a "silent packet drop" scenario.
- **Ports checked:** Only 4 hardcoded common ports: `[22, 80, 443, 3389]` (constant `_COMMON_PORTS`).
- **Scope:** Only checks **subnet-level NSGs** from `subnet_nsg_map` (built from `subnetNsgId` in the VNet/subnet query). **NIC-level NSGs are completely excluded** from asymmetry detection — even though the code fetches and renders NIC-level NSG edges (`nic-nsg` edge type). This is a known gap.
- **Issue object schema today:**
  ```python
  {
      "source_nsg_id": str,   # ARM resource ID (lowercased)
      "dest_nsg_id":   str,   # ARM resource ID (lowercased)
      "port":          int,   # TCP port number
      "description":   str,   # Human-readable one-liner
  }
  ```

### 1.2 Health Signals Computed But NOT Surfaced in `issues`

The following health signals are computed and stored in node `data` fields but **never appear in the `issues` array**:

| Signal | Where Computed | Current Effect |
|--------|---------------|----------------|
| NSG yellow (any-to-any allow rule at priority < 1000) | `_score_nsg_health()` | Node border turns yellow in graph |
| NSG red (asymmetry participant) | `_detect_asymmetries()` | Node border turns red, asymmetry edges added |
| PE non-Approved connection state | PE node construction | Node `health = "red"` — but no issue entry |
| Firewall ThreatIntel = "Off" | Firewall node construction | Node `health = "yellow"` — but no issue entry |
| Firewall provisioning Failed | `_score_resource_health()` | Node `health = "red"` — but no issue entry |
| Gateway provisioning Failed | `_score_resource_health()` | Node `health = "red"` — but no issue entry |
| VNet peering-disconnected edges | Peering edge assembly | Red dashed edge — but no issue entry |
| AKS provisioning Failed | `_score_resource_health()` | Node `health = "red"` — but no issue entry |

**These are quick wins** — they require no new ARG queries, just issue object generation from existing data.

### 1.3 Frontend Issues Drawer — Current State

The `issuesOpen` Sheet in `NetworkTopologyTab.tsx` currently:
- Renders issues as a flat list of red cards
- Displays: `Port {N}/TCP blocked`, `description`, `source_nsg_id` (name only), `dest_nsg_id` (name only)
- Has a "Focus in graph" button (`focusIssue()`) that highlights the two NSG nodes + their subnets
- Has a focused-issue banner at the bottom of the screen
- The `focusIssue` function uses `issue.source_nsg_id` and `issue.dest_nsg_id` — hardwired to the NSG asymmetry schema
- **No severity classification**, **no remediation steps**, **no portal links**, **no action buttons**

The issues pill in the summary bar shows `🚫 Issues: N — click to view` with a red badge.

---

## 2. Issue Catalog — All 17 Issues

For each issue: data available in current ARG queries? ARG query needed? Severity? Auto-remediable?

### Category A: NSG Security Issues

#### A1 — Port 22/3389 Open to Internet (NSG rule)
- **Data available:** Yes — `_NSG_RULES_QUERY` returns all rules with `sourcePrefix`, `destPortRange`, `access`, `direction`
- **Detection logic:** Find Inbound Allow rules where `sourcePrefix == "*"` (or `"Internet"`) AND `destPortRange` covers 22 or 3389
- **New ARG query needed:** No
- **Severity:** 🔴 Critical
- **Auto-remediable:** Yes, with HITL (delete/modify the offending rule via `azure-mgmt-network`)
- **Portal deep-link:** `https://portal.azure.com/#resource/{nsg_id}/securityRules`

#### A2 — Any-to-Any Allow Rule (NSG)
- **Data available:** Yes — already detected for yellow health score (`source="*"`, `port="*"`, priority < 1000)
- **Detection logic:** Extend `_score_nsg_health()` result into an issue; expand beyond priority < 1000 to catch all any-to-any
- **New ARG query needed:** No
- **Severity:** 🟠 High
- **Auto-remediable:** No (risk too high — could break connectivity; needs operator review)
- **Portal deep-link:** `https://portal.azure.com/#resource/{nsg_id}/securityRules`

#### A3 — Subnet with No NSG
- **Data available:** Yes — `_VNET_SUBNET_QUERY` returns `subnetNsgId`; if empty, no NSG attached
- **Detection logic:** Iterate VNet rows; if `subnetNsgId` is empty for a non-gateway subnet
- **New ARG query needed:** No (but need to filter out GatewaySubnet, AzureBastionSubnet, AzureFirewallSubnet, AzureFirewallManagementSubnet — these legitimately have no NSG)
- **Severity:** 🟠 High
- **Auto-remediable:** No (need operator to choose/create NSG)
- **Portal deep-link:** `https://portal.azure.com/#resource/{subnet_resource_id}/networksecurity`

#### A4 — NSG Rule Shadowed by Higher-Priority Rule
- **Data available:** Yes — full rule list per NSG in `_NSG_RULES_QUERY`
- **Detection logic:** For each NSG, sort rules by priority. For each pair of rules in same direction: if rule B's port/source/dest is a subset of rule A's and they have opposite `access`, B is shadowed by A
- **New ARG query needed:** No
- **Severity:** 🟡 Medium
- **Auto-remediable:** No (deleting the shadowed rule changes intent; needs review)
- **Portal deep-link:** `https://portal.azure.com/#resource/{nsg_id}/securityRules`

#### A5 — NSG Asymmetry (existing — upgrade to richer schema)
- **Data available:** Yes — existing `_detect_asymmetries()` 
- **Enhancement:** Add to unified issue catalog with severity, explanation, remediation steps
- **Severity:** 🟠 High
- **Auto-remediable:** No (safe fix is to add inbound Allow rule — but destination port/source scope needs operator decision)

### Category B: Connectivity Issues

#### B1 — VNet Peering Disconnected
- **Data available:** Yes — `peering-disconnected` edge type already created in `_assemble_graph()`
- **Detection logic:** Iterate edges where `type == "peering-disconnected"`; emit issue per disconnected peering
- **New ARG query needed:** No
- **Severity:** 🔴 Critical
- **Auto-remediable:** No (peering must be re-initiated from both sides; often a manual fix)
- **Portal deep-link:** `https://portal.azure.com/#resource/{vnet_id}/peerings`

#### B2 — VPN Gateway BGP Not Enabled
- **Data available:** Yes — `_GATEWAY_QUERY` returns `bgp_enabled` field; stored in gateway node `data.bgpEnabled`
- **Detection logic:** Gateway node where `gatewayType == "Vpn"` AND `bgpEnabled == False`
- **New ARG query needed:** No
- **Severity:** 🟡 Medium
- **Auto-remediable:** No (BGP toggle requires gateway reset — service-interrupting)
- **Portal deep-link:** `https://portal.azure.com/#resource/{gateway_id}/configuration`

#### B3 — Gateway Not Zone-Redundant (SKU check)
- **Data available:** Yes — `_GATEWAY_QUERY` returns `sku_name`; zone-redundant SKUs are `*AZ` variants (`VpnGw1AZ`, `ErGw1AZ`, etc.)
- **Detection logic:** Gateway where `sku_name` does NOT end in `AZ` (or is not `UltraPerformance`)
- **New ARG query needed:** No
- **Severity:** 🟡 Medium
- **Auto-remediable:** No (SKU upgrade requires gateway recreation)
- **Portal deep-link:** `https://portal.azure.com/#resource/{gateway_id}/configuration`

#### B4 — Private Endpoint in Non-Approved State
- **Data available:** Yes — PE nodes have `health` field; `connectionState != "Approved"` is already computed
- **Detection logic:** PE node where `health == "red"` (connectionState not Approved)
- **New ARG query needed:** No
- **Severity:** 🔴 Critical
- **Auto-remediable:** Yes, with HITL (approve the connection via `azure-mgmt-network` NetworkManagementClient `private_link_services.update_private_endpoint_connection`)
- **Portal deep-link:** `https://portal.azure.com/#resource/{pe_id}/overview`

### Category C: Configuration Issues

#### C1 — VM with Public IP Directly Attached
- **Data available:** Partially. `_NIC_SUBNET_QUERY` does NOT return the public IP attached to a NIC. The `_PUBLIC_IP_QUERY` fetches all public IPs but doesn't link them to VMs (only to LBs, gateways, firewalls, AppGWs via other queries).
- **New ARG query needed:** Yes — need a NIC-level public IP query:
  ```kql
  Resources
  | where type =~ "microsoft.network/networkinterfaces"
  | mv-expand ipc = properties.ipConfigurations
  | extend publicIpId = tolower(tostring(ipc.properties.publicIPAddress.id))
  | where isnotempty(publicIpId)
  | project nicId = tolower(id), publicIpId
  ```
  Then join to VM→NIC mapping.
- **Severity:** 🔴 Critical
- **Auto-remediable:** No (disassociating a public IP requires the VM to have another path to internet; too risky)
- **Portal deep-link:** `https://portal.azure.com/#resource/{vm_id}/networking`

#### C2 — Load Balancer Empty Backend Pool
- **Data available:** Partially. `_LB_BACKEND_QUERY` returns LB→NIC mappings only when backend pools have IP configs. An LB with an empty backend pool simply produces no rows.
- **Detection logic:** LBs that appear in `_LB_QUERY` but produce 0 rows in `_LB_BACKEND_QUERY` have empty backend pools.
- **New ARG query needed:** A simpler query to get backend pool member count per LB:
  ```kql
  Resources
  | where type == "microsoft.network/loadbalancers"
  | extend poolCount = array_length(properties.backendAddressPools)
  | mv-expand pool = properties.backendAddressPools
  | extend memberCount = array_length(pool.properties.backendIPConfigurations)
  | where memberCount == 0 or isnull(memberCount)
  | project lbId = tolower(id), lbName = name, emptyPool = tostring(pool.name)
  ```
- **Severity:** 🟠 High
- **Auto-remediable:** No (need operator to add backend members)
- **Portal deep-link:** `https://portal.azure.com/#resource/{lb_id}/backendpools`

#### C3 — LB Standard + Basic Public IP SKU Mismatch
- **Data available:** Yes — `_LB_QUERY` returns `sku_name` (Standard/Basic), `_PUBLIC_IP_QUERY` returns `sku_name` per public IP ID. LB node already stores `publicIpId`.
- **Detection logic:** For each LB with `publicIpId`, look up the public IP's SKU. If LB SKU is "Standard" and PIP SKU is "Basic" (or vice versa), flag it.
- **New ARG query needed:** No (public IP data already fetched; just need cross-reference)
- **Severity:** 🟠 High (will cause deployment failures)
- **Auto-remediable:** No (SKU change requires recreation)
- **Portal deep-link:** `https://portal.azure.com/#resource/{lb_id}/overview`

#### C4 — Firewall with No Policy Attached
- **Data available:** Yes — `_FIREWALL_QUERY` returns `firewallPolicyId`; if empty, no policy
- **Detection logic:** Firewall node where `firewallPolicyId` is empty/null
- **New ARG query needed:** No
- **Severity:** 🔴 Critical
- **Auto-remediable:** No (need operator to create/assign a firewall policy)
- **Portal deep-link:** `https://portal.azure.com/#resource/{fw_id}/overview`

#### C5 — Firewall Threat Intelligence Disabled
- **Data available:** Yes — `_FIREWALL_QUERY` returns `threatIntelMode`; already causes `health = "yellow"`
- **Detection logic:** Firewall node where `threatIntelMode == "Off"` or empty
- **New ARG query needed:** No
- **Severity:** 🟠 High
- **Auto-remediable:** Yes, safe (enable threat intel via `azure-mgmt-network` `AzureFirewalls.begin_create_or_update` with `threatIntelMode = "Alert"`)
- **Portal deep-link:** `https://portal.azure.com/#resource/{fw_id}/threatIntelligence`

#### C6 — AKS API Server Not Private
- **Data available:** No — `_AKS_QUERY` does not fetch `enablePrivateCluster` property
- **New ARG query needed:** Extend `_AKS_QUERY` or add separate query:
  ```kql
  Resources
  | where type =~ "microsoft.containerservice/managedclusters"
  | extend isPrivate = tobool(properties.apiServerAccessProfile.enablePrivateCluster)
  | project aksId = tolower(id), aksName = name, isPrivate
  ```
- **Severity:** 🟠 High
- **Auto-remediable:** No (converting to private cluster requires cluster recreation in most cases)
- **Portal deep-link:** `https://portal.azure.com/#resource/{aks_id}/networking`

### Category D: Routing Issues

#### D1 — Route Table with 0.0.0.0/0 → Internet (Firewall Bypass)
- **Data available:** No — `_ROUTE_TABLE_QUERY` only returns route count, not individual routes
- **New ARG query needed:** Yes:
  ```kql
  Resources
  | where type == "microsoft.network/routetables"
  | mv-expand route = properties.routes
  | extend addressPrefix = tostring(route.properties.addressPrefix)
  | extend nextHopType = tostring(route.properties.nextHopType)
  | where addressPrefix == "0.0.0.0/0" and nextHopType == "Internet"
  | project rtId = tolower(id), rtName = name, routeName = tostring(route.name)
  ```
- **Severity:** 🟠 High (bypasses Azure Firewall)
- **Auto-remediable:** No (need to redirect next hop to Firewall private IP)
- **Portal deep-link:** `https://portal.azure.com/#resource/{rt_id}/routes`

#### D2 — Subnet Address Space Overlap
- **Data available:** Yes — `_VNET_SUBNET_QUERY` returns `subnetPrefix` for all subnets
- **Detection logic:** Parse CIDRs; check if any two subnet CIDRs overlap (using Python `ipaddress.ip_network` overlap check). Only meaningful across different VNets (within same VNet, Azure prevents overlap).
- **New ARG query needed:** No
- **Severity:** 🟠 High (causes routing ambiguity in peered VNets)
- **Auto-remediable:** No (subnet resizing is destructive)
- **Portal deep-link:** `https://portal.azure.com/#resource/{vnet_id}/subnets`

#### D3 — Missing Hub-Spoke Peering Pairs
- **Data available:** Yes — peering edges already built; VNet nodes available
- **Detection logic:** A hub-spoke topology has one VNet peered to N spokes. If only one direction of a peering exists (peering-disconnected), or if spoke VNets are not peered to the detected hub, flag it. Detection: VNets with 3+ peerings = likely hub. Check if any spoke has a peering back to hub.
- **New ARG query needed:** No
- **Severity:** 🟡 Medium
- **Auto-remediable:** No (requires new peering creation)
- **Portal deep-link:** `https://portal.azure.com/#resource/{vnet_id}/peerings`

---

## 3. Remediation Architecture

### 3.1 Azure SDK for Remediation

The `azure-mgmt-network` SDK package is **NOT currently in `requirements.txt`**. It must be added. All other required packages are already present (`azure-mgmt-compute>=37.0.0`).

```
azure-mgmt-network>=25.0.0
```

**Safe automated operations per issue type:**

| Issue | SDK Operation | Risk Level |
|-------|--------------|-----------|
| A5 NSG asymmetry — add missing inbound rule | `NetworkManagementClient.security_rules.begin_create_or_update()` | Low — additive only |
| B4 PE not approved | `NetworkManagementClient.private_endpoint_connections.update()` | Low — approve connection |
| C5 Firewall ThreatIntel off → Alert | `NetworkManagementClient.azure_firewalls.begin_create_or_update()` (patch threatIntelMode) | Low — security hardening |

**Operations requiring HITL (too destructive/risky to auto-execute):**

| Issue | Why HITL required |
|-------|------------------|
| A1 Port 22/3389 open — delete/modify rule | Could break operator SSH/RDP access |
| A2 Any-to-any allow — delete rule | Could break application connectivity |
| A4 Delete shadowed rule | Changes security intent |
| C4 Assign firewall policy | Need operator to select/create correct policy |
| D1 Change route next hop | Incorrect firewall IP would black-hole all traffic |

### 3.2 HITL Approval Queue Integration (Phase 107 / existing `approvals.py`)

The existing `approvals.py` and `remediation_executor.py` implement a full HITL approval flow:
- `create_approval()` stores a pending approval record in Cosmos `approvals` container
- `approve_action()` / `reject_action()` process the decision
- The `remediation_executor.py` has `SAFE_ARM_ACTIONS` dict and WAL-based execution

**Integration approach for Phase 108:**
- Reuse the existing `create_approval()` function from `approvals.py` for HITL operations
- For safe auto-fix operations: execute directly via Azure SDK with a `remediation_audit` WAL entry
- The `ApprovalQueueCard` in the Observability tab will automatically surface pending network remediation approvals (same Cosmos container)

### 3.3 Authentication for SDK calls

The existing `get_credential_for_subscriptions` dependency in `network_topology_endpoints.py` provides `DefaultAzureCredential`. This is passed to `fetch_network_topology()`. The same credential can be used for `NetworkManagementClient` instantiation — no new auth infrastructure needed.

---

## 4. Frontend Architecture

### 4.1 Issues Drawer Redesign

**Current issues drawer schema hardwires** `issue.source_nsg_id` and `issue.dest_nsg_id` — every display reference uses these fields. The redesign must use a **unified issue schema**.

**Proposed unified issue schema:**
```typescript
interface NetworkIssue {
  id: string                    // unique issue ID (type + resource ID hash)
  type: string                  // "nsg_asymmetry" | "port_open_internet" | etc.
  severity: "critical" | "high" | "medium" | "low"
  title: string                 // Short title: "Port 22 Open to Internet"
  explanation: string           // Plain-English 2-3 sentence explanation
  impact: string                // What can go wrong: "Attackers can brute-force SSH..."
  affected_resource_id: string  // Primary ARM resource ID
  affected_resource_name: string
  related_resource_ids: string[] // Secondary affected resources
  remediation_steps: RemediationStep[]
  portal_link: string           // Azure Portal deep-link
  auto_fix_available: boolean   // Is one-click safe fix available?
  auto_fix_label: string        // "Enable Threat Intelligence" | null
  // Legacy fields for backward compat with focusIssue()
  source_nsg_id?: string
  dest_nsg_id?: string
  port?: number
  description?: string
}

interface RemediationStep {
  step: number
  action: string    // What to do
  cli?: string      // Optional: az CLI command
}
```

### 4.2 Issues Drawer UI Components

**Severity badges** — using existing CSS token pattern:
```tsx
const SEVERITY_COLOR = {
  critical: "var(--accent-red)",
  high:     "var(--accent-orange)",
  medium:   "var(--accent-yellow)",
  low:      "var(--accent-blue)",
}
```

**Issue card sections:**
1. Header: severity badge + title + affected resource name
2. Explanation: plain-English what + why (collapsible)
3. Impact: what bad thing happens
4. Remediation steps: numbered list
5. Portal link: "Open in Azure Portal" button (external link)
6. One-click fix button (when `auto_fix_available = true`) or HITL button ("Request Approval")
7. "Focus in graph" button (existing behavior, updated to use `affected_resource_id`)

### 4.3 Updated `focusIssue()` Function

The `focusIssue()` function currently hardwires `issue.source_nsg_id` and `issue.dest_nsg_id`. The redesign should:
- Use `issue.affected_resource_id` + `issue.related_resource_ids` for highlighting
- Support any resource type (not just NSG pairs)
- Clear highlighting when the sheet closes or another issue is focused

### 4.4 Issues Summary Pill

Currently shows `🚫 Issues: N`. Upgrade to show severity breakdown:
```
🔴 3 Critical  🟠 4 High  🟡 2 Medium
```
Each count is clickable and filters the issues drawer to that severity.

### 4.5 One-Click Remediation Flow (Frontend)

1. User clicks "Fix Now" button on an issue card
2. A confirmation dialog appears: "This will {action description}. Proceed?"
3. On confirm: `POST /api/v1/network-topology/remediate` with `{ issue_id, subscription_id }`
4. Loading spinner on button while request in flight
5. On success: toast notification "Fix applied. Refreshing topology..."
6. Auto-refresh topology after 3 seconds
7. On failure: error message inline on the card

**For HITL actions** ("Request Approval" button):
1. User clicks "Request Approval"
2. Dialog shows description of what will be done + risk level
3. `POST /api/v1/network-topology/remediate` with `{ require_approval: true }`
4. Backend creates Cosmos approval record (reusing `create_approval()`)
5. Toast: "Approval requested. Check the Approval Queue."

---

## 5. API Design

### 5.1 Updated `GET /api/v1/network-topology`

The existing endpoint already returns `{ nodes, edges, issues }`. The `issues` array schema changes from NSG-asymmetry-only to unified `NetworkIssue` objects.

**Breaking change mitigation:** The frontend `focusIssue()` uses `issue.source_nsg_id` and `issue.dest_nsg_id`. These fields must be retained as optional fields on NSG asymmetry issues for backward compat, while all new issue types use the unified schema.

### 5.2 New `POST /api/v1/network-topology/remediate`

```python
class RemediateRequest(BaseModel):
    issue_id: str                    # From unified issue schema
    subscription_id: Optional[str]
    require_approval: bool = False   # True = HITL, False = auto-execute if safe
    
class RemediateResponse(BaseModel):
    status: str                      # "executed" | "approval_pending" | "error"
    message: str
    approval_id: Optional[str]       # Set when status="approval_pending"
    execution_id: Optional[str]      # Set when status="executed"
```

**Endpoint logic:**
1. Look up the issue from the current topology cache (by `issue_id`)
2. Check if `auto_fix_available` and not `require_approval`
3. If safe auto-fix: execute SDK call + write WAL via `remediation_executor` pattern
4. If HITL needed: call `create_approval()` from `approvals.py`
5. Invalidate the topology cache after successful execution
6. Return structured response

### 5.3 Proxy Route (Next.js)

New file: `app/api/proxy/network/topology/remediate/route.ts`

Pattern follows existing proxy routes: `getApiGatewayUrl()` + `buildUpstreamHeaders(request)` + `AbortSignal.timeout(15000)`.

---

## 6. Issue Explanation Framework

### 6.1 Template Structure (Modeled on Azure Security Center + AWS Security Hub)

```
Title:       [Short, specific, action-oriented] — "SSH Port Open to Internet"
What:        [One sentence: what the issue IS] — "NSG rule allows inbound TCP on port 22 from any source (0.0.0.0/0)."
Why it matters: [One sentence: what can happen] — "Attackers can launch automated brute-force attacks against any VM in this subnet."
Impact:      [Who is affected + consequence] — "All VMs in subnet 'snet-compute' are exposed. A successful attack gives full OS-level access."
Fix:         [Numbered steps, specific to this issue type]
  1. Open the NSG in the Azure Portal
  2. Find the rule allowing inbound TCP 22 from *
  3. Change the source from * to your corporate IP range (e.g., 10.0.0.0/8)
  4. Or delete the rule if SSH access is not needed
  az cli: az network nsg rule update --nsg-name {nsg} -g {rg} --name {rule} --source-address-prefixes '10.0.0.0/8'
```

### 6.2 Key Principles (from Azure Security Center / AWS Security Hub research)

- **Plain English, no jargon** — say "open to internet" not "inbound allow from 0.0.0.0/0"
- **Specific, not generic** — reference the actual resource name, actual port, actual rule name
- **Impact over mechanism** — lead with "attackers can..." not "the NSG has..."
- **Numbered steps** — operators follow checklists, not paragraphs
- **Include CLI commands** — reduces context switching; operators can fix from terminal
- **Portal deep-link to the exact blade** — not just the resource overview

---

## 7. Implementation Order — Recommended Sequence

### Plan 108-1: Backend — New ARG Queries + Unified Issue Schema (Backend Only)
**Quick wins first; no new ARG queries needed for most issues.**

1. Define the unified `NetworkIssue` Python dataclass / TypedDict in `network_topology_service.py`
2. Implement issue generators for issues that need **no new ARG queries** (8 issues):
   - A2 Any-to-any allow (from existing NSG health yellow)
   - A3 Subnet with no NSG (from VNet rows)
   - A5 NSG asymmetry (upgrade existing, richer schema)
   - B1 VNet peering disconnected (from existing peering-disconnected edges)
   - B2 VPN BGP not enabled (from gateway nodes)
   - B3 Gateway not zone-redundant (from gateway nodes)
   - B4 PE non-Approved (from PE nodes)
   - C4 Firewall no policy (from firewall nodes)
   - C5 Firewall ThreatIntel off (from firewall nodes)
3. Add new ARG queries for remaining issues (4 new queries):
   - A1 (Port 22/3389 to internet — needs internet-source detection from existing NSG rules data — actually available, no new query)
   - A4 (NSG rule shadowing — from existing rules, no new query)
   - C1 (VM public IP via NIC — 1 new query)
   - C2 (LB empty backend pool — 1 new query)
   - C6 (AKS not private — extend existing AKS query)
   - D1 (Route 0.0.0.0/0 → Internet — 1 new query)
   - D2 (Subnet overlap — from existing data, no new query; uses Python `ipaddress`)
   - D3 (Missing hub-spoke pairs — from existing peering data)

**Deliverables:** Updated `network_topology_service.py` with 17-issue detection. Existing frontend continues to work (unified schema is backward-compatible with legacy fields).

**Tests:** Unit tests for each issue generator function. ~30 new test cases.

### Plan 108-2: Frontend — Issues Drawer Redesign
1. Update `TopologyData.issues` TypeScript type to `NetworkIssue[]`
2. Redesign issues drawer: severity badges, explanation sections, remediation steps, portal links
3. Update `focusIssue()` to use unified `affected_resource_id` + `related_resource_ids`
4. Upgrade issues summary pill with severity breakdown
5. No backend changes needed (Plan 108-1 already done)

**Deliverables:** Full issues drawer UI with 17 issue types displayed correctly.

### Plan 108-3: Remediation Endpoint + One-Click Fix
1. Add `azure-mgmt-network>=25.0.0` to `requirements.txt`
2. Implement `POST /api/v1/network-topology/remediate` endpoint
3. Implement safe auto-fix for C5 (Firewall ThreatIntel) and B4 (PE approval)
4. Wire HITL path via existing `create_approval()` for dangerous fixes
5. Add Next.js proxy route `app/api/proxy/network/topology/remediate/route.ts`
6. Add "Fix Now" and "Request Approval" buttons to issue cards in frontend
7. Add confirmation dialog + toast feedback

**Deliverables:** Full one-click fix flow. ~10 new API gateway tests.

---

## 8. Risk & Constraints

### 8.1 Technical Risks

| Risk | Mitigation |
|------|-----------|
| `azure-mgmt-network` adds 30–60MB to Docker image | Accept; image already has `azure-mgmt-compute` and similar |
| New ARG queries (4) add ~800ms to topology load time | Run all queries in parallel (already using `_safe_query` pattern); new queries added to parallel batch |
| Subnet overlap detection using Python `ipaddress` is O(n²) subnets | Cap at 500 subnets per call; log warning if exceeded |
| NSG rule shadowing algorithm is O(n²) rules per NSG | Cap at 200 rules per NSG; virtually all real NSGs have <50 rules |
| Firewall ThreatIntel auto-fix requires full firewall PUT (not PATCH) | Read current config → merge → PUT; risk of overwriting concurrent changes |
| Unified issue schema breaks `focusIssue()` which reads `issue.source_nsg_id` | Retain `source_nsg_id` / `dest_nsg_id` on asymmetry issues as backward-compat optional fields |

### 8.2 Data Quality Risks

| Risk | Mitigation |
|------|-----------|
| AKS private cluster detection requires `apiServerAccessProfile` — may be null for old clusters | Default to `isPrivate = false` when field absent; emit issue for any cluster missing the field |
| D3 Hub-spoke detection is heuristic (VNets with ≥3 peerings = hub) | Low-confidence issues get `severity: "low"` + note "This is a heuristic detection" |
| C2 LB empty backend pool — some LBs use IP-based backends (not NIC) | Add check for `backendIPConfigurations` AND `loadBalancerBackendAddresses` |

### 8.3 Scope Constraints

- **One-click remediation only for 2 safe operations** in Phase 108 (C5 Firewall ThreatIntel, B4 PE approval). All others use HITL.
- **No real-time re-scan after fix** — topology cache TTL is 15 minutes. The UI triggers a manual refresh call after fix execution.
- **Subnet overlap detection across VNets only** — within a VNet, Azure prevents overlap by design.
- Phase 108 does **not** cover ExpressRoute health, Application Gateway WAF status, or DNS configuration — deferred to Phase 109.

### 8.4 ARG Limitations

- `_NIC_NSG_QUERY` filters to NICs with NSGs (`where isnotempty(nsgId)`). For A1 (VM public IP via NIC), a separate query without the NSG filter is needed.
- ARG does not return real-time route effective routes — only configured routes. Effective routing (BGP, system routes) requires Network Watcher, which is not ARG-queryable.

---

## RESEARCH COMPLETE
