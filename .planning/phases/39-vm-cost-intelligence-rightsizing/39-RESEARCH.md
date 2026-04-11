# Phase 39: VM Cost Intelligence & Rightsizing — Research

> Date: 2026-04-11
> Purpose: Answer "What do I need to know to PLAN this phase well?"

---

## 1. Azure Advisor SDK — Rightsizing Recommendations

### Package
`azure-mgmt-advisor` — **NOT currently in `agents/compute/requirements.txt`**. Must be added.

```
azure-mgmt-advisor>=9.0.0
```

### Key Classes & Methods

```python
from azure.mgmt.advisor import AdvisorManagementClient
from azure.mgmt.advisor.models import ResourceRecommendationBase

client = AdvisorManagementClient(credential, subscription_id)

# List ALL recommendations
recs = client.recommendations.list()

# Filter in Python for:
#   category == "Cost"
#   impactedField containing "virtualMachines" (case-insensitive)
#   impactedValue == vm_name  (or partial match on resource_group/vm_name)
```

### Response Shape (ResourceRecommendationBase)
```python
rec.id                             # ARM resource ID of the recommendation
rec.category                       # "Cost" | "HighAvailability" | "Security" | etc.
rec.impact                         # "High" | "Medium" | "Low"
rec.impacted_field                 # e.g. "Microsoft.Compute/virtualMachines"
rec.impacted_value                 # e.g. "vm-prod-01" (the VM name)
rec.short_description.solution     # Human-readable solution text
rec.extended_properties            # dict: may contain "recommendedSkuName",
                                   #   "savingsAmount", "savingsCurrency", etc.
rec.resource_metadata.resource_id  # Full ARM resource ID of the affected VM
rec.last_updated                   # datetime
```

### Filtering Strategy for a Specific VM
```python
# Advisor does not have a per-VM filter on the API itself.
# You must:
#   1. Call client.recommendations.list()
#   2. Filter: rec.category == "Cost"
#   3. Filter: vm_name in (rec.impacted_value or rec.resource_metadata.resource_id)
#   4. Optionally filter: resource_group in rec.resource_metadata.resource_id
```

### Savings Estimation
The `extended_properties` dict may include:
- `"annualSavingsAmount"` (float)
- `"savingsAmount"` (float, monthly)
- `"savingsCurrency"` (e.g. "USD")
- `"recommendedSkuName"` — the suggested downsized SKU

**Important:** These fields are not guaranteed — always use `.get()` with a default.

### Confidence: HIGH — azure-mgmt-advisor is the standard package; well-documented.

---

## 2. Azure Cost Management SDK — Per-VM 7-Day Spend

### Package
`azure-mgmt-costmanagement` — **NOT currently in `agents/compute/requirements.txt`**. Must be added.

```
azure-mgmt-costmanagement>=4.0.0
```

### Key Classes & Methods

```python
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    QueryDefinition, QueryTimePeriod, QueryDataset,
    QueryAggregation, QueryGrouping, GranularityType,
    TimeframeType,
)

client = CostManagementClient(credential)

scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"

# Query: last 7 days, grouped by resource (to isolate the VM)
query = QueryDefinition(
    type="ActualCost",
    timeframe=TimeframeType.CUSTOM,
    time_period=QueryTimePeriod(from_property=from_dt, to=to_dt),
    dataset=QueryDataset(
        granularity=GranularityType.DAILY,
        aggregation={
            "totalCost": QueryAggregation(name="Cost", function="Sum")
        },
        grouping=[
            QueryGrouping(type="Dimension", name="ResourceId"),
            QueryGrouping(type="Dimension", name="ResourceType"),
        ],
        filter={...}  # optional: filter by ResourceId == vm resource_id
    ),
)

result = client.query.usage(scope=scope, parameters=query)
```

### Response Shape
`result.rows` — each row is a list:
- `[cost_value, date, resource_id, resource_type, currency]` (column order depends on `aggregation` + `grouping` order)

Use `result.columns` to determine column indices by name.

### Recommended Approach for Per-VM Query
1. Scope to `subscription_id` (not RG) — simpler, no RG-level scoping quirks.
2. Use `ResourceId` filter to narrow to the specific VM's resource ID.
3. 7-day window = `TimeframeType.CUSTOM` with `from_property = now - 7 days`.
4. Return: `total_cost_7d`, `currency`, `daily_costs: [{date, cost}]`.

### Important Caveats
- **Cost data lag:** Azure Cost Management data typically has a 24-48h lag. Document this in tool response.
- **Permissions:** Requires `Cost Management Reader` role on the subscription scope. Must be added to Terraform RBAC.
- **Scope quirks:** RG-level scoping requires `resources` endpoint, not `query`; sub-level with ResourceId filter is cleaner.

### Confidence: HIGH — azure-mgmt-costmanagement is GA and well-documented.

---

## 3. HITL Pattern — Exact `create_approval_record` Usage

### Source: `agents/compute/tools.py` lines 961–1092 (`propose_vm_restart`, `propose_vm_resize`)

### Pattern Template (copy verbatim, adjust fields):

```python
@ai_function
def propose_vm_sku_downsize(
    resource_id: str,
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    target_sku: str,
    justification: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Propose a VM SKU downsize — creates HITL ApprovalRecord (no ARM call)."""
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="propose_vm_sku_downsize",
        tool_parameters={"vm_name": vm_name, "target_sku": target_sku},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            proposal = {
                "action": "vm_sku_downsize",
                "resource_id": resource_id,
                "resource_group": resource_group,
                "vm_name": vm_name,
                "subscription_id": subscription_id,
                "target_sku": target_sku,
                "justification": justification,
                "description": f"Downsize VM '{vm_name}' to {target_sku}: {justification}",
                "target_resources": [resource_id],
                "estimated_impact": "~5-10 min downtime (deallocate/resize/start)",
                "reversible": True,
            }

            record = create_approval_record(
                container=None,
                thread_id=thread_id,
                incident_id="",           # no incident context required for cost proposals
                agent_name="compute-agent",
                proposal=proposal,
                resource_snapshot={"vm_name": vm_name, "target_sku": target_sku},
                risk_level="medium",      # downsize = medium (same as restart)
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "status": "pending_approval",
                "approval_id": record.get("id") if isinstance(record, dict) else getattr(record, "id", ""),
                "message": f"SKU downsize proposal created for '{vm_name}' → {target_sku}. Awaiting human approval.",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("propose_vm_sku_downsize error: %s", exc)
            return {"status": "error", "message": str(exc), "duration_ms": duration_ms}
```

### Key HITL Rules (from codebase):
- `container=None` — approval manager resolves its own Cosmos container
- `risk_level="medium"` for downsize (same risk class as restart; `propose_vm_resize` uses `"high"`)
- Tool NEVER calls ARM — RemediationExecutor handles execution after approval
- Function signature MUST NOT include `incident_id` as required param — cost proposals may lack one. Pass `incident_id=""` internally.
- Return shape: `{"status": "pending_approval", "approval_id": ..., "message": ..., "duration_ms": ...}`

---

## 4. Web UI — Fleet Cost Dashboard Tab

### Existing Tab Registration Pattern (DashboardPanel.tsx lines 24–32):

```tsx
const TABS: { id: TabId; label: string; Icon: React.FC<{ className?: string }> }[] = [
  { id: 'alerts',       label: 'Alerts',       Icon: Bell },
  { id: 'audit',        label: 'Audit',        Icon: ClipboardList },
  { id: 'topology',     label: 'Topology',     Icon: Network },
  { id: 'resources',    label: 'Resources',    Icon: Server },
  { id: 'vms',          label: 'VMs',          Icon: Monitor },
  { id: 'observability',label: 'Observability',Icon: Activity },
  { id: 'patch',        label: 'Patch',        Icon: ShieldCheck },
]
```

### To Add a "Cost" Tab:
1. Add `{ id: 'cost', label: 'Cost', Icon: TrendingDown }` to `TABS` array (after `'vms'`, before `'observability'`)
2. Add `'cost'` to the `TabId` union type (line ~16)
3. Add `import { CostTab } from './CostTab'` at top
4. Add panel div: `<div id="tabpanel-cost" hidden={activeTab !== 'cost'}>...</div>`
5. Create `services/web-ui/components/CostTab.tsx`
6. Create `services/web-ui/app/api/proxy/cost/route.ts` (proxy to api-gateway)

### Tab Panel Pattern (from existing PatchTab/VMTab wiring):
```tsx
<div id="tabpanel-cost" role="tabpanel" aria-labelledby="tab-cost" hidden={activeTab !== 'cost'}>
  <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
    <CostTab subscriptions={selectedSubscriptions} />
  </div>
</div>
```

### CostTab Deliverable — Top-10 Underutilized VMs
- Columns: VM Name, Resource Group, Current SKU, Avg CPU (7d), Estimated Monthly Spend, Advisor Recommendation, Monthly Savings
- Data source: new `GET /api/v1/vms/cost-summary` gateway endpoint
- Gateway endpoint queries Advisor (all recs, filter Category=Cost) + Cost Management
- Lucide icon: `TrendingDown` (cost reduction theme)

### CSS Token Pattern (dark-mode safe):
```tsx
// Badges: color-mix(in srgb, var(--accent-green) 15%, transparent)
// Never: bg-green-100 text-green-700
```

---

## 5. SOP Location and Pattern

### Location: `sops/compute/` directory

Existing compute SOPs:
```
sops/compute/
  compute-generic.md
  vm-boot-failure.md
  vm-disk-exhaustion.md
  vm-high-cpu.md
  vm-memory-pressure.md
  vm-network-unreachable.md
  vm-unavailable.md
```

### New SOP: `sops/compute/vm-low-cpu-rightsizing.md`

### SOP Schema (from `sops/_schema/`):

```yaml
id: SOP-COMPUTE-008
title: "VM Rightsizing — Low CPU Utilization (<5%)"
domain: compute
version: "1.0"
severity: low
tags: [cost, rightsizing, vm, advisor]
steps:
  - id: "1"
    action: DIAGNOSE
    description: "Query Advisor rightsizing recommendations for the VM"
    tool: query_advisor_rightsizing_recommendations
  - id: "2"
    action: DIAGNOSE
    description: "Query 7-day cost spend for the VM"
    tool: query_vm_cost_7day
  - id: "3"
    action: REMEDIATION
    description: "Propose SKU downsize if savings > $20/month and CPU < 5%"
    tool: propose_vm_sku_downsize
    requires_approval: true
```

### SOP Upload: After creating the file, run `scripts/seed-runbooks/seed.py` to re-seed (or the SOP upload script from Phase 30).

---

## 6. Agent Registration in `agents/compute/agent.py`

### Current import block (lines 31–60 of agent.py) shows the pattern:

```python
from compute.tools import (
    ALLOWED_MCP_TOOLS,
    detect_performance_drift,
    get_vm_forecast,
    propose_vm_restart,
    propose_vm_resize,
    query_activity_log,
    ...
)
```

### Three new tools to add to imports + `tools` list in `ChatAgent(...)`:
```python
from compute.tools import (
    ...
    query_advisor_rightsizing_recommendations,   # new Phase 39
    query_vm_cost_7day,                          # new Phase 39
    propose_vm_sku_downsize,                     # new Phase 39
)
```

### ChatAgent tools list: The `ChatAgent` constructor accepts `tools=[...]`. Add the 3 new functions there.

---

## 7. Required Package Additions

### `agents/compute/requirements.txt` — add:
```
azure-mgmt-advisor>=9.0.0
azure-mgmt-costmanagement>=4.0.0
```

### Terraform RBAC — add to compute agent managed identity:
- `Cost Management Reader` — scope: all in-scope subscriptions
  - Role definition ID: `72fafed3-4f88-40d7-8a8c-5b7f1b4bb8d3`
- No additional Advisor role needed — `Reader` already covers Advisor read

---

## 8. Test Pattern

### Source: `agents/tests/compute/test_compute_performance.py`

### Pattern Summary:
```python
class TestQueryAdvisorRightsizingRecommendations:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.AdvisorManagementClient")   # new lazy import
    @patch("agents.compute.tools.get_credential")
    def test_success_with_cost_recommendations(self, ...):
        ...
        assert result["query_status"] == "success"
        assert result["recommendation_count"] >= 1
        assert "duration_ms" in result
```

### Required test cases per tool (follow Phase 37 pattern: 5 tests per tool):
1. Success — SDK returns recommendations/data
2. Success — no recommendations found (empty result)
3. SDK unavailable (`XxxClient = None`) → graceful error dict
4. SDK raises exception → error dict, no re-raise
5. Missing required env/param → skipped/error dict

---

## 9. Gateway Endpoint Design

### New endpoint: `GET /api/v1/vms/cost-summary`

```python
# services/api-gateway/main.py or routers/vms.py
@router.get("/api/v1/vms/cost-summary")
async def get_vm_cost_summary(subscription_id: str, top: int = 10):
    """Return top-N underutilized VMs by cost with Advisor recommendations."""
    # 1. Query Advisor for all Cost category recommendations in subscription
    # 2. Query Cost Management for top-N VMs by spend (7d)
    # 3. Join on resource_id
    # 4. Return sorted list: highest savings opportunity first
```

### Proxy route: `services/web-ui/app/api/proxy/cost/route.ts`
- Follows existing pattern: `getApiGatewayUrl()` + `buildUpstreamHeaders(request)` + `AbortSignal.timeout(15000)`

---

## 10. Implementation Order (for plan breakdown)

Recommended single-plan approach (Phase 39 is self-contained):

**39-1: Cost Intelligence Tools + UI + SOP**

1. Add lazy imports for `AdvisorManagementClient` + `CostManagementClient` in `tools.py`
2. Implement `query_advisor_rightsizing_recommendations` in `tools.py`
3. Implement `query_vm_cost_7day` in `tools.py`
4. Implement `propose_vm_sku_downsize` in `tools.py` (HITL, no ARM)
5. Update `requirements.txt` (2 new packages)
6. Register 3 tools in `agent.py` (imports + `tools=` list)
7. Add `GET /api/v1/vms/cost-summary` endpoint in api-gateway
8. Create `CostTab.tsx` — top-10 underutilized VMs table
9. Add proxy route `app/api/proxy/cost/route.ts`
10. Wire `CostTab` into `DashboardPanel.tsx`
11. Create `sops/compute/vm-low-cpu-rightsizing.md`
12. Write unit tests (15 tests: 5 per tool × 3 tools)
13. Terraform: add `Cost Management Reader` RBAC to compute agent MI

---

## 11. Key Risk / Gotchas

| Risk | Mitigation |
|---|---|
| Advisor `extended_properties` field names vary by recommendation type | Use `.get()` with defaults; return raw `extended_properties` dict so agent can inspect |
| Cost Management data has 24-48h lag | Document in tool docstring and return value |
| `propose_vm_sku_downsize` may not have an `incident_id` (cost-driven, not alert-driven) | Pass `incident_id=""` to `create_approval_record`; verify approval manager tolerates empty string |
| `CostManagementClient` API version quirks | Use `azure-mgmt-costmanagement>=4.0.0` which targets stable API versions |
| `Cost Management Reader` RBAC not yet in Terraform | Add to `terraform/modules/agent-apps/rbac.tf` alongside existing Reader role |
| `advisor.list_recommendations` returns recs for ALL resource types | Filter `category == "Cost"` AND `"virtualmachines" in impacted_field.lower()` |

---

## RESEARCH COMPLETE
