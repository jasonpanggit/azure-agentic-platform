# Phase 52: FinOps Intelligence Agent — Research

**Date:** 2026-04-14
**Phase:** 52 — FinOps Intelligence Agent
**Status:** Research complete

---

## 1. Azure Cost Management SDK — Exact API Calls

### Package

```
azure-mgmt-costmanagement>=4.0.0
```

Already imported in `agents/compute/tools.py` (Phase 39 VM cost work). The exact import pattern already working in production:

```python
try:
    from azure.mgmt.costmanagement import CostManagementClient
    from azure.mgmt.costmanagement.models import (
        QueryDefinition,
        QueryTimePeriod,
        QueryDataset,
        QueryAggregation,
        QueryGrouping,
        GranularityType,
        TimeframeType,
    )
except ImportError:
    CostManagementClient = None  # type: ignore[assignment,misc]
    # ... other None assignments
```

### `get_subscription_cost_breakdown` — Cost by ResourceGroup/ResourceType/Tag

Scope: `/subscriptions/{subscription_id}`

```python
client = CostManagementClient(credential)
query = QueryDefinition(
    type="ActualCost",  # or "AmortizedCost" for RI amortization
    timeframe=TimeframeType.CUSTOM,
    time_period=QueryTimePeriod(from_property=from_dt, to=to_dt),
    dataset=QueryDataset(
        granularity=GranularityType.MONTHLY,  # or DAILY for trend
        aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
        grouping=[QueryGrouping(type="Dimension", name="ResourceGroup")],  # or "ResourceType" or "TagKey"
    ),
)
result = client.query.usage(scope=scope, parameters=query)
# columns = [col.name for col in result.columns]
# rows = result.rows   # each row = [cost, date/period, currency, grouping_value]
```

- **Days param → timeframe:** 7 days = subtract `timedelta(days=7)` from today (account for 24-48h lag)
- **MoM delta:** run query twice (current month vs prior month), compute delta %
- **Group by tag:** `QueryGrouping(type="Tag", name="Environment")`
- **Group by ResourceType:** `QueryGrouping(type="Dimension", name="ServiceName")`

### `get_resource_cost` — Per-resource amortized cost

Same `client.query.usage()` but:
- `type="AmortizedCost"` to include RI amortization
- `filter` with `{"dimensions": {"name": "ResourceId", "operator": "In", "values": [resource_id]}}`

This exact pattern is **already working** in `query_vm_cost_7day` (line 2823 of `compute/tools.py`). The FinOps tool is a generalization: remove the VM-specific resource_id filter, accept any resource_id, and support 7/30/90 day windows.

### `get_cost_forecast` — Native Azure forecast

```python
from azure.mgmt.costmanagement.models import ForecastDefinition, ForecastDataset

forecast_query = ForecastDefinition(
    type="ActualCost",
    timeframe="Custom",  # current billing period
    time_period=QueryTimePeriod(from_property=start_of_month, to=end_of_month),
    dataset=ForecastDataset(
        granularity="Monthly",
        aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
    ),
    include_actual_cost=True,
    include_fresh_partial_cost=False,
)
result = client.forecast.usage(scope=scope, parameters=forecast_query)
```

- Budget comparison: use `azure-mgmt-costmanagement` `BudgetsOperations`: `client.budgets.get(scope, budget_name)` → `budget.current_spend.amount` vs `budget.amount`
- Burn rate: `current_spend / days_elapsed * days_in_month` — compare to budget
- **110% alert threshold**: if projected > budget × 1.10, flag

### `get_reserved_instance_utilisation` — RI/Savings Plan

```python
# List utilization summaries for Reservation Orders
# Requires Billing Reader or Reservations Reader
summaries = client.benefit_utilization_summaries.list_by_billing_account_id(
    billing_account_id=billing_account_id,
    grain_parameter="Monthly",
)
# OR per reservation order:
summaries = client.benefit_utilization_summaries.list_by_reservation_order(
    reservation_order_id=order_id,
    grain="Monthly",
)
```

**Important caveat:** The RI utilization API requires Billing Account scope, not subscription scope. Billing Account ID comes from `client.billing_accounts.list()`. This may require the Billing Reader role (separate from Cost Management Reader). If billing scope is unavailable, the tool should return a graceful `{"query_status": "unavailable", "reason": "Billing Reader role required"}` rather than failing hard.

**Alternative approach** (subscription-scope, simpler RBAC): query `ActualCost` vs `AmortizedCost` at subscription scope — the delta reveals RI benefit usage even without billing API access.

### RBAC Required

- **Cost Management Reader** on subscription scope → covers all cost query tools
- **Billing Reader** on billing account → needed for RI utilization API
- Idle resource detection also needs **Monitoring Reader** (for Monitor metrics) — already standard

---

## 2. Azure Monitor Metrics for Idle Resource Detection

### `identify_idle_resources` strategy

Two-step approach:
1. **List all VMs in subscription** via ARG: `Resources | where type == 'microsoft.compute/virtualmachines'`
2. **For each VM**: query Monitor metrics over 72h window

```python
from azure.mgmt.monitor import MonitorManagementClient
client = MonitorManagementClient(credential, subscription_id)

# CPU: Percentage CPU, Average, 72h window
response = client.metrics.list(
    resource_uri=resource_id,
    metricnames="Percentage CPU,Network In Total,Network Out Total",
    timespan="PT72H",
    interval="PT1H",
    aggregation="Average,Total",
)
```

**Thresholds (per 52-CONTEXT.md):**
- CPU `<2%` average over 72h: flag as idle
- Network In + Out `<1 MB/s` (= `<1_048_576 bytes/s`) average: flag as idle
- Both conditions must be true

**Scalability concern:** If subscription has 500+ VMs, per-VM metric queries will be slow/throttled. Strategy: batch with `asyncio.gather()` (max ~20 concurrent), or use ARG + Log Analytics approach:

```kql
// Alternative: ARG + AMA Perf table (requires AMA installed)
InsightsMetrics
| where TimeGenerated > ago(72h)
| where Name in ("Processor Utilization", "Network Received Bytes/sec")
| summarize AvgVal = avg(Val) by Computer, Name
| where AvgVal < 2  // for CPU
```

**Decision:** Use direct Monitor SDK metrics (per-VM) since it's the same pattern as `query_availability_metrics` in sre/tools.py. Batch with asyncio for parallelism. Cap at 50 VMs per call to avoid throttling.

### Monthly cost for idle resources

After identifying idle VMs, call `get_resource_cost()` (30-day window) for each idle VM to attach a monthly cost estimate to each idle resource finding.

### `propose_deallocate` HITL action

Uses `create_approval_record()` from `shared/approval_manager.py` with:
- `risk_level = "low"` (per 52-CONTEXT.md — deallocation is reversible)
- `proposal.action = "vm_deallocate"`
- `proposal.estimated_monthly_savings = $X` — must be included

---

## 3. Existing Agent Structure to Follow

### Directory layout (`agents/compute/` pattern)

```
agents/finops/
├── __init__.py
├── agent.py          # ChatAgent factory + system prompt
├── tools.py          # @ai_function tools
├── requirements.txt  # azure-mgmt-costmanagement, azure-mgmt-monitor
├── Dockerfile        # FROM agents/Dockerfile.base
└── finops.spec.md    # Required by CI spec lint gate (AGENT-009)
```

### `tools.py` skeleton (from compute/tools.py and messaging/tools.py patterns)

```python
"""FinOps Agent tool functions — Azure Cost Management data surface."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent_framework import ai_function
from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry

try:
    from azure.mgmt.costmanagement import CostManagementClient
    from azure.mgmt.costmanagement.models import (
        QueryDefinition, QueryTimePeriod, QueryDataset,
        QueryAggregation, QueryGrouping, GranularityType, TimeframeType,
    )
except ImportError:
    CostManagementClient = None  # type: ignore[assignment,misc]
    # ... guard each model class

try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

ALLOWED_MCP_TOOLS: List[str] = ["monitor", "advisor"]

tracer = setup_telemetry("aiops-finops-agent")
logger = logging.getLogger(__name__)

def _log_sdk_availability() -> None: ...
_log_sdk_availability()

@ai_function
def get_subscription_cost_breakdown(...) -> Dict[str, Any]: ...

@ai_function
def get_resource_cost(...) -> Dict[str, Any]: ...

@ai_function
def identify_idle_resources(...) -> Dict[str, Any]: ...

@ai_function
def get_reserved_instance_utilisation(...) -> Dict[str, Any]: ...

@ai_function
def get_cost_forecast(...) -> Dict[str, Any]: ...

@ai_function
def get_top_cost_drivers(...) -> Dict[str, Any]: ...
```

### `agent.py` skeleton (from compute/agent.py)

```python
from agent_framework import ChatAgent
from shared.auth import get_foundry_client
from shared.otel import setup_telemetry
from finops.tools import (
    get_subscription_cost_breakdown, get_resource_cost, identify_idle_resources,
    get_reserved_instance_utilisation, get_cost_forecast, get_top_cost_drivers,
)

FINOPS_SYSTEM_PROMPT = """You are the AAP FinOps Agent..."""

def create_finops_agent() -> ChatAgent:
    client = get_foundry_client()
    return ChatAgent(
        name="finops-agent",
        description="Azure FinOps specialist — cost optimization and waste detection.",
        instructions=FINOPS_SYSTEM_PROMPT,
        chat_client=client,
        tools=[get_subscription_cost_breakdown, get_resource_cost, ...],
    )

if __name__ == "__main__":
    from azure.ai.agentserver.agentframework import from_agent_framework
    from_agent_framework(create_finops_agent()).run()
```

### `main.py`

```python
# Identical pattern to compute/main.py — just the bootstrap entrypoint
from finops.agent import create_finops_agent
...
from azure.ai.agentserver.agentframework import from_agent_framework
from_agent_framework(create_finops_agent()).run()
```

### `Dockerfile`

```dockerfile
FROM aapcrprodjgmjti.azurecr.io/agents/base:latest
COPY finops/ ./finops/
COPY finops/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "-m", "finops.agent"]
```

### `requirements.txt`

```
azure-mgmt-costmanagement>=4.0.0
azure-mgmt-monitor>=6.0.0
azure-mgmt-resourcegraph>=8.0.0
azure-monitor-query>=1.4.0
azure-ai-agentserver-agentframework
agent-framework>=1.0.0rc5
```

### `finops.spec.md` (required by CI spec lint gate AGENT-009)

Must follow existing `.spec.md` format (see `agents/compute/agent.spec.md`). Contains: Persona, Goals, Workflow steps, Tool permissions, Safety constraints, Example flows.

---

## 4. Frontend Patterns

### DashboardPanel.tsx — Tab registration

Current tabs (from `DashboardPanel.tsx` line 32-46):
```typescript
type TabId = 'ops' | 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'vmss' | 'aks' | 'cost' | 'observability' | 'patch' | 'runbooks' | 'settings'
```

**A `cost` tab already exists!** It uses `CostTab.tsx` and `TrendingDown` icon. The existing `CostTab` shows Azure Advisor Cost recommendations (from Phase 28 FinOps integration + 260413-v9x quick task).

**Decision required:** Options:
1. **Extend** existing `CostTab` with FinOps data (cost breakdown chart, waste list, savings proposals, budget gauge)
2. **Replace** CostTab with a richer FinOps tab

**Recommendation:** Extend the existing `CostTab` by adding new sections (budget gauge, cost breakdown chart, idle resource waste list) alongside the existing Advisor recommendations. The tab is already registered; no `DashboardPanel.tsx` tab registration needed. But the tab label might be updated from "Cost" to "FinOps" with a new icon (`DollarSign` or `PieChart`).

### CostTab.tsx — Current structure

- Fetches from `/api/proxy/vms/cost-summary?subscription_id=...&top=10` (Azure Advisor recommendations)
- Card grid layout (2-col)
- Uses `var(--accent-green)` for savings amounts
- Uses `color-mix(in srgb, var(--accent-red) 15%, transparent)` for High impact badges
- Pattern: `useCallback` + `useEffect` + fetch + loading/error states

### Recharts usage pattern (from AgentLatencyCard.tsx)

```tsx
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';

<ResponsiveContainer width="100%" height={140}>
  <BarChart data={costData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
    <XAxis dataKey="resourceGroup" tick={{ fontSize: 10 }} />
    <YAxis tick={{ fontSize: 10 }} unit="$" />
    <Tooltip formatter={(v: unknown) => [`$${Number(v).toFixed(2)}`, 'Cost']} contentStyle={{ fontSize: 11 }} />
    <Bar dataKey="cost" fill="var(--accent-blue)" radius={[2, 2, 0, 0]} />
  </BarChart>
</ResponsiveContainer>
```

For the FinOps cost breakdown bar chart (top-10 resource groups by spend):
- X-axis: resource group name (truncated)
- Y-axis: cost in USD
- Color: `var(--accent-blue)` bars
- The `recharts` package is already installed at `^3.8.1`

### Budget gauge

No radial gauge component currently in the codebase. Options:
- Use a `<progress>` HTML element styled with Tailwind
- Use Recharts `RadialBarChart`
- Use a simple CSS-based percentage bar with `width: ${pct}%`

**Recommendation:** Simple horizontal progress bar (no extra deps) styled with semantic tokens. If burn rate >110%, color changes to `var(--accent-red)`.

### Waste list + HITL approve/reject buttons

Pattern from `PatchTab.tsx` (table + action buttons). Use `shadcn/ui` `Table` + `Button`. Approve/reject calls existing `/api/v1/remediation/approve|reject` endpoints.

### CSS semantic tokens to use

- `var(--accent-green)` — savings amounts, good burn rate
- `var(--accent-red)` — overspend, idle resources flagged
- `var(--accent-orange)` — warning burn rate (90-110%)
- `var(--accent-blue)` — chart bars, resource type badges
- `var(--bg-canvas)` — card backgrounds
- `var(--text-primary)` / `var(--text-secondary)` — text
- Badge pattern: `color-mix(in srgb, var(--accent-*) 15%, transparent)` for backgrounds

---

## 5. HITL Approval Flow for `propose_deallocate`

### How it works (from `shared/approval_manager.py`)

1. Tool calls `create_approval_record(container, thread_id, incident_id, agent_name, proposal, resource_snapshot, risk_level="low")`
2. Cosmos DB `approvals` container gets a `pending` record with `expires_at = now + 30min`
3. Tool returns `{"status": "pending_approval", "approval_id": "appr_...", "message": "..."}`
4. Agent returns this to the Foundry thread; thread becomes idle
5. Web UI ProposalCard renders approve/reject buttons polling `/api/v1/approvals/{id}`
6. Operator clicks Approve → `POST /api/v1/remediation/approve/{id}` → triggers `RemediationExecutor`
7. RemediationExecutor executes the VM deallocate via `ComputeManagementClient`

### `propose_deallocate` tool proposal dict

```python
proposal = {
    "action": "vm_deallocate",
    "resource_id": resource_id,
    "resource_group": resource_group,
    "vm_name": vm_name,
    "subscription_id": subscription_id,
    "description": f"Deallocate idle VM '{vm_name}' — CPU <2% + ~0 network for 72h",
    "target_resources": [resource_id],
    "estimated_impact": "VM stops, billing ends for compute. Disk costs continue.",
    "estimated_monthly_savings_usd": monthly_cost,  # from get_resource_cost()
    "reversible": True,
    "risk_level": "low",
}
```

### RemediationExecutor support for `vm_deallocate`

Need to verify if `vm_deallocate` is in `remediation_executor.py` already. The compute agent has `propose_vm_restart` and `propose_vm_sku_downsize`. A `vm_deallocate` action might need to be added to `remediation_executor.py`'s action dispatch. **Must check during implementation.**

### Severity = LOW for cost proposals

Per 52-CONTEXT.md: cost savings proposals use `risk_level="low"`. This bypasses the Teams Adaptive Card escalation (which fires for `high`/`critical`). Low-risk proposals appear in the Web UI ProposalCard only.

---

## 6. Orchestrator Routing — Adding FinOps Intent

### Current `DOMAIN_AGENT_MAP` (orchestrator/agent.py lines 145-158)

```python
DOMAIN_AGENT_MAP: dict = {
    "compute": "compute_agent",
    "network": "network_agent",
    # ... 10 entries
    "messaging": "messaging_agent",
}
```

Add:
```python
"finops": "finops_agent",
"cost": "finops_agent",  # alias
```

### Routing keywords to add to orchestrator system prompt

```
- Mentions "cost", "spend", "billing", "finops", "budget", "waste", "idle",
  "reserved instance", "ri utilization", "savings plan", "cost breakdown",
  "monthly bill", "cloud cost", "rightsizing", "cost optimization" → call `finops_agent`
```

### `RESOURCE_TYPE_TO_DOMAIN` — no new entry needed

FinOps doesn't map to a specific ARM resource type; it's triggered by conversational intent.

### `IncidentPayload` model domain validation

Currently: `pattern=r"^(compute|network|storage|security|arc|sre|patch|eol|messaging)$"`

Must add `"finops"` to this regex pattern. This allows detection-plane incidents with `domain: finops` to route correctly (e.g., a budget alert firing).

### `agents/shared/routing.py` — keyword routing

```python
# QUERY_DOMAIN_KEYWORDS — add finops entry
"finops": ["cost", "spend", "billing", "finops", "budget", "idle resources",
           "reserved instance", "savings plan", "waste", "rightsizing",
           "cost breakdown", "monthly bill", "burn rate"],
```

---

## 7. API Gateway Proxy Routes Pattern

### Pattern (from `app/api/proxy/patch/assessment/route.ts`)

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/finops/cost-breakdown' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/finops/cost-breakdown${query ? `?${query}` : ''}`,
      { headers: upstreamHeaders, signal: AbortSignal.timeout(15000) }
    );

    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: data?.detail ?? `Gateway error: ${res.status}` }, { status: res.status });
    }
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}
```

### FinOps proxy routes needed

```
app/api/proxy/finops/
├── cost-breakdown/route.ts          → GET /api/v1/finops/cost-breakdown
├── resource-cost/route.ts           → GET /api/v1/finops/resource-cost
├── idle-resources/route.ts          → GET /api/v1/finops/idle-resources
├── ri-utilization/route.ts          → GET /api/v1/finops/ri-utilization
├── cost-forecast/route.ts           → GET /api/v1/finops/cost-forecast
└── top-cost-drivers/route.ts        → GET /api/v1/finops/top-cost-drivers
```

### API Gateway endpoints (FastAPI)

New file: `services/api-gateway/finops_endpoints.py`

```python
from fastapi import APIRouter, Depends, Query
from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential

router = APIRouter(prefix="/api/v1/finops", tags=["finops"])

@router.get("/cost-breakdown")
async def get_cost_breakdown(
    subscription_id: str = Query(...),
    days: int = Query(30, ge=7, le=90),
    group_by: str = Query("ResourceGroup"),
    _token: str = Depends(verify_token),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]: ...
```

Register in `main.py`:
```python
from services.api_gateway.finops_endpoints import router as finops_router
app.include_router(finops_router)
```

**Note:** The existing `vm_cost.py` router uses the pattern of calling the Azure SDK directly (not delegating to the FinOps agent). The FinOps tab API gateway endpoints should follow the same pattern — direct SDK calls, not agent delegation — for fast UI response. The FinOps **agent** is for conversational queries routed through the orchestrator.

---

## 8. Container App Terraform Pattern

### `locals.agents` in `terraform/modules/agent-apps/main.tf`

Currently:
```hcl
locals {
  agents = {
    orchestrator = { ... }
    compute      = { ... }
    messaging    = { ... }  # newest agent (Phase 49)
    # ADD:
    finops       = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
  }
}
```

Adding `finops` to `locals.agents`:
- Creates `ca-finops-prod` Container App automatically via `for_each`
- SystemAssigned managed identity provisioned automatically
- All standard env vars injected (FOUNDRY_*, COSMOS_*, APPLICATIONINSIGHTS_*, etc.)
- Internal ingress only (`ingress_external = false`)
- Image path: `${var.acr_login_server}/agents/finops:${var.image_tag}`

### FINOPS_AGENT_ID env var injection pattern

Following the `messaging_agent_id` pattern:

1. **`variables.tf`:** Add `variable "finops_agent_id" { default = "" }`
2. **`main.tf`:** Add dynamic env block:
   ```hcl
   dynamic "env" {
     for_each = contains(["orchestrator", "api-gateway"], each.key) && var.finops_agent_id != "" ? [1] : []
     content {
       name  = "FINOPS_AGENT_ID"
       value = var.finops_agent_id
     }
   }
   ```
3. **`terraform/envs/prod/main.tf`:** Wire `finops_agent_id = var.finops_agent_id`
4. **`terraform/envs/prod/variables.tf`:** Declare `variable "finops_agent_id" { default = "" }`
5. **`terraform/envs/prod/terraform.tfvars`:** Add `finops_agent_id = ""` placeholder

### RBAC Terraform

In the RBAC module, add `Cost Management Reader` role assignment for the FinOps Container App's managed identity:

```hcl
# Cost Management Reader for FinOps agent
resource "azurerm_role_assignment" "finops_cost_reader" {
  for_each             = toset(var.all_subscription_ids)
  scope                = "/subscriptions/${each.value}"
  role_definition_name = "Cost Management Reader"
  principal_id         = azurerm_container_app.agents["finops"].identity[0].principal_id
}
```

---

## 9. Existing Cost-Related Code in the Codebase

### `agents/compute/tools.py` (Phase 39)

Three working cost tools already deployed:
- `query_advisor_rightsizing_recommendations` (lines 2730+) — Azure Advisor Cost recs for a specific VM
- `query_vm_cost_7day` (lines 2823+) — **THE PRIMARY REFERENCE** for Cost Management SDK usage. Full working implementation of `CostManagementClient` + `QueryDefinition` + column parsing pattern
- `propose_vm_sku_downsize` (lines 2940+) — HITL proposal for SKU resize

**Key insight:** `query_vm_cost_7day` is the exact working pattern for the FinOps tools. The FinOps tools are generalizations of this (subscription-wide, not per-VM; 30/90 day windows; grouped by RG/type/tag instead of filtered by ResourceId).

### `services/api-gateway/vm_cost.py`

The existing `GET /api/v1/vms/cost-summary` endpoint queries Azure Advisor Cost recommendations and returns top-N sorted by savings. This is what the current `CostTab.tsx` uses.

**The FinOps tab will add new endpoints** alongside this existing one. The existing `/api/v1/vms/cost-summary` endpoint stays unchanged.

### `services/api-gateway/pattern_analyzer.py`

Has a `FinOps` business tier concept (`POST /api/v1/admin/business-tiers`) from Phase 28. Not directly related to the FinOps agent tools but relevant context.

### `services/web-ui/components/CostTab.tsx`

Already exists with:
- Advisor recommendations card grid
- Impact badge coloring with semantic CSS vars
- `formatCurrency()` helper
- `cleanServiceType()` helper  
- `impactBadgeStyle()` helper

These helpers should be **reused** in the extended FinOps tab rather than duplicated.

---

## 10. Recharts Usage in Frontend

### Current usage pattern (`AgentLatencyCard.tsx`, `IncidentThroughputCard.tsx`)

```tsx
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
  // Also available:
  LineChart, Line, PieChart, Pie, Cell, AreaChart, Area,
} from 'recharts';
```

**Package version:** `recharts@^3.8.1` (in `services/web-ui/package.json`)

### Cost breakdown bar chart pattern for FinOps tab

```tsx
// Top-10 resource groups by spend
const costData = breakdown.slice(0, 10).map(b => ({
  name: b.resource_group.length > 15 ? b.resource_group.slice(0, 15) + '…' : b.resource_group,
  cost: b.total_cost,
}));

<ResponsiveContainer width="100%" height={200}>
  <BarChart data={costData} layout="vertical" margin={{ top: 4, right: 40, left: 60, bottom: 0 }}>
    <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={v => `$${Number(v).toFixed(0)}`} />
    <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={55} />
    <Tooltip
      formatter={(v: unknown) => [`$${Number(v).toFixed(2)}`, 'Cost']}
      contentStyle={{ fontSize: 11 }}
    />
    <Bar dataKey="cost" fill="var(--accent-blue)" radius={[0, 2, 2, 0]} />
  </BarChart>
</ResponsiveContainer>
```

Vertical bar chart better fits resource group names (they're long). The `AgentLatencyCard` uses horizontal bars for agent names.

### Budget gauge pattern (simple, no extra deps)

```tsx
// Burn rate gauge: horizontal progress bar
const burnPct = Math.min((currentSpend / budgetAmount) * 100, 150);
const barColor = burnPct > 110 ? 'var(--accent-red)' : burnPct > 90 ? 'var(--accent-orange)' : 'var(--accent-green)';

<div className="relative h-4 rounded-full" style={{ background: 'color-mix(in srgb, var(--border) 50%, transparent)' }}>
  <div
    className="absolute inset-y-0 left-0 rounded-full transition-all"
    style={{ width: `${Math.min(burnPct, 100)}%`, background: barColor }}
  />
</div>
<p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
  ${currentSpend.toFixed(0)} of ${budgetAmount.toFixed(0)} ({burnPct.toFixed(0)}%)
  {burnPct > 110 && <span style={{ color: 'var(--accent-red)' }}> ⚠ On track to exceed budget by {(burnPct - 100).toFixed(0)}%</span>}
</p>
```

---

## Key Implementation Risks and Watchpoints

### 1. `identify_idle_resources` scale problem
Querying Monitor metrics for every VM in a subscription serially will be slow and may hit rate limits. Must use `asyncio.gather()` batching (max 20 concurrent). For the initial implementation, cap at 50 VMs returned and document the limitation.

### 2. RI utilization requires Billing scope
`benefit_utilization_summaries` needs Billing Reader at billing account scope — this is a different auth scope than subscription. The FinOps agent's managed identity may not have this role. Implement with graceful degradation: if billing API returns 403, return `{"query_status": "insufficient_permissions", "message": "Billing Reader role required at billing account scope"}`.

### 3. Cost data 24-48h lag
Always include `data_lag_note: "Azure Cost Management data has a 24-48 hour lag..."` in all cost tool responses. Already done in `query_vm_cost_7day`.

### 4. `vm_deallocate` in RemediationExecutor
Need to verify that `services/api-gateway/remediation_executor.py` handles `action = "vm_deallocate"`. If not, the executor needs a new action handler. The `propose_vm_restart` action type is already there as a reference.

### 5. DashboardPanel TabId type
The `cost` TabId already exists. Adding FinOps data to the existing CostTab means **no DashboardPanel change** needed — we just expand CostTab's content. This is the cleaner approach.

### 6. Cost Management API column parsing
The `result.columns` from `client.query.usage()` must be parsed dynamically (column order is not guaranteed). The existing `query_vm_cost_7day` implementation handles this correctly with `next((i for i, c in enumerate(columns) if "cost" in c), 0)` pattern. **Reuse this pattern exactly.**

### 7. `finops.spec.md` required by CI lint gate
The CI workflow enforces spec files for all agent containers. Must create `agents/finops/finops.spec.md` before the Docker image build passes CI. Use the `agents/compute/compute.spec.md` as the template.

---

## Plan Breakdown Recommendation

Based on research, Phase 52 naturally splits into:

### Plan 52-1: FinOps Agent Backend (Python)
- `agents/finops/` directory: `__init__.py`, `tools.py` (6 @ai_function tools), `agent.py`, `main.py`, `requirements.txt`, `Dockerfile`, `finops.spec.md`
- All 6 tools with full SDK calls + test coverage (≥40 unit tests)
- `shared/subscription_utils.py` reuse for resource ID parsing

### Plan 52-2: API Gateway Integration
- `services/api-gateway/finops_endpoints.py` — 6 REST endpoints
- `services/api-gateway/main.py` — router registration
- `services/api-gateway/models.py` — FinOps Pydantic models if needed
- Orchestrator routing: domain keyword addition + `IncidentPayload` domain regex
- 20+ API gateway tests

### Plan 52-3: Frontend FinOps Tab
- Extend `CostTab.tsx` with: current month spend KPI, cost breakdown bar chart, budget burn rate gauge, idle resource waste list with HITL approve/reject, RI utilization card
- 6 new proxy routes under `app/api/proxy/finops/`
- TypeScript types for all FinOps API responses
- `DashboardPanel.tsx` minimal update (rename tab label from "Cost" → "FinOps" and update icon)

### Plan 52-4: Infrastructure + CI/CD
- `terraform/modules/agent-apps/main.tf` — add `finops` to `locals.agents`
- `terraform/modules/agent-apps/variables.tf` — `finops_agent_id` variable
- `terraform/modules/rbac/` — Cost Management Reader role assignment
- `terraform/envs/prod/` — wire all finops variables
- `.github/workflows/` — `build-finops.yml` + `deploy-finops.yml`
- `scripts/ops/provision-finops-agent.sh` — Foundry agent provisioning

---

## RESEARCH COMPLETE
