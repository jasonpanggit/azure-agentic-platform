---
wave: 1
depends_on: []
files_modified:
  - agents/finops/__init__.py
  - agents/finops/tools.py
  - agents/finops/agent.py
  - agents/finops/main.py
  - agents/finops/requirements.txt
  - agents/finops/Dockerfile
  - docs/agents/finops-agent.spec.md
  - agents/tests/finops/__init__.py
  - agents/tests/finops/test_finops_tools.py
autonomous: true
---

# Plan 52-1: FinOps Agent — Python Backend, Tools, and Tests

## Goal

Create the `agents/finops/` package with 6 `@ai_function` tools that surface Azure Cost Management data (subscription cost breakdown, per-resource cost, idle resource detection, RI utilisation, cost forecast, top cost drivers), the agent factory, Dockerfile, `docs/agents/finops-agent.spec.md` (required by CI spec lint gate AGENT-009), and ≥40 unit tests.

## Context

Phase 52 adds a dedicated FinOps agent to the platform. The spec lint CI gate (`agent-spec-lint.yml`) checks for `docs/agents/{agent_name}-agent.spec.md` with 6 required sections before any agent Python files can pass CI. All patterns must replicate `agents/messaging/` (most recent domain agent, Phase 49). The `CostManagementClient` SDK pattern is already proven in `agents/compute/tools.py` lines 86–106 and 2823+. `deallocate_vm` is already in `SAFE_ARM_ACTIONS` in `remediation_executor.py` — no executor changes needed for idle resource HITL proposals.

<threat_model>
## Security Threat Assessment

**1. SDK lazy-import fallback (None assignment)**: Every SDK client guard checks `if Client is None` and returns a structured error dict — no stack traces or credentials leak to LLM output. Pattern is identical to all other domain agents.

**2. `identify_idle_resources` asyncio batching**: Batches Monitor metric queries in groups of 20 using `asyncio.gather()`. No user-controlled concurrency. Cap at 50 VMs per call prevents resource exhaustion.

**3. RI utilisation API graceful degradation**: If `benefit_utilization_summaries` returns 403 (billing scope unavailable), returns `{"query_status": "insufficient_permissions", "message": "Billing Reader role required"}` — never raises, never leaks error details beyond the structured response.

**4. HITL proposal tool (`identify_idle_resources`)**: Calls `create_approval_record()` from `shared/approval_manager.py` with `risk_level="low"`. Does NOT execute any SDK mutation. `vm_deallocate` action is already in `SAFE_ARM_ACTIONS` in `remediation_executor.py` — no new action handler needed.

**5. Cost data `group_by` parameter**: Validated against an allowlist `{"ResourceGroup", "ResourceType", "ServiceName"}` before SDK call. Rejects arbitrary strings to prevent API errors or injection.

**6. `days` parameter bounds**: Clamped to `[7, 90]` in the tool signature (Pydantic-style validation). Azure Cost Management has a 24–48h data lag noted in every response via `data_lag_note` field.

**7. Credential handling**: Uses `get_credential()` from `agents/shared/auth.py` which resolves `DefaultAzureCredential` — no secrets in parameters or env vars passed to tool functions.
</threat_model>

---

## Tasks

### Task 1: Create `docs/agents/finops-agent.spec.md` (CI gate — must be first)

<read_first>
- `docs/agents/messaging-agent.spec.md` — exact section structure to replicate (6 required sections: Persona, Goals, Workflow, Tool Permissions, Safety Constraints, Example Flows)
- `.github/workflows/agent-spec-lint.yml` — confirms the 6 required section headers that the lint check greps for
</read_first>

<action>
Create `docs/agents/finops-agent.spec.md` with the following exact content:

```markdown
---
agent: finops
requirements: [TRIAGE-004, REMEDI-001, FINOPS-001, FINOPS-002, FINOPS-003]
phase: 52
---

# FinOps Agent Spec

## Persona

Domain specialist for Azure cost optimisation — subscription spend analysis, idle resource detection, reserved instance utilisation monitoring, cost forecasting, and HITL-gated VM deallocation proposals. Receives handoffs from the Orchestrator for cost-related queries and produces actionable FinOps insights backed by Azure Cost Management data.

## Goals

1. Surface subscription cost breakdown grouped by ResourceGroup, ResourceType, or Tag to identify highest-spend areas (FINOPS-001)
2. Detect idle VMs (CPU <2% AND network <1MB/s over 72h) and generate HITL deallocation proposals with estimated monthly savings (FINOPS-002)
3. Forecast current-month spend vs budget and flag burn rate >110% of budget (FINOPS-003)
4. Retrieve reserved instance / savings plan utilisation and flag under-used commitments
5. Present the top cost drivers with month-over-month delta for trend awareness
6. Always include `data_lag_note` in cost responses (Azure Cost Management has 24–48h data lag)
7. Propose remediation actions with full context — never execute without explicit human approval (REMEDI-001)

## Workflow

1. Receive handoff from Orchestrator with `IncidentMessage` envelope (`correlation_id`, `thread_id`, `source_agent: "orchestrator"`, `target_agent: "finops"`, `message_type: "incident_handoff"`)
2. **Spend overview:** Call `get_subscription_cost_breakdown(subscription_id, days=30, group_by="ResourceGroup")` to establish current-period spend by resource group
3. **Cost drivers:** Call `get_top_cost_drivers(subscription_id, n=10, days=30)` to rank services by spend
4. **Forecast vs budget:** Call `get_cost_forecast(subscription_id, budget_name)` to check burn rate and projected month-end total
5. **Idle resources:** Call `identify_idle_resources(subscription_id)` to surface VMs with CPU <2% and network <1MB/s over 72h; each result includes estimated monthly savings
6. **RI utilisation:** Call `get_reserved_instance_utilisation(subscription_id)` — if returns `insufficient_permissions`, note that Billing Reader role is required at billing account scope
7. **Per-resource drill-down:** If operator asks about a specific resource, call `get_resource_cost(subscription_id, resource_id, days=30)`
8. Correlate all findings into prioritised cost-saving recommendations with estimated USD impact per action
9. For each idle VM, propose deallocation via HITL: `risk_level="low"`, `reversible=True`, include `estimated_monthly_savings_usd`

### Retrieve Relevant Runbooks (TRIAGE-005)
- Call `retrieve_runbooks(query=<cost_optimisation_topic>, domain="finops", limit=3)`
- Filter results with similarity >= 0.75
- If runbook service is unavailable, proceed without citation (non-blocking)

## Tool Permissions

| Tool | Allowed | Notes |
|---|---|---|
| `get_subscription_cost_breakdown` | ✅ | Cost Management Reader on subscription scope |
| `get_resource_cost` | ✅ | AmortizedCost query for a single resource |
| `identify_idle_resources` | ✅ | ARG + Monitor metrics; generates HITL proposals |
| `get_reserved_instance_utilisation` | ✅ | Billing Reader scope; graceful degradation on 403 |
| `get_cost_forecast` | ✅ | Native Azure forecast + budget comparison |
| `get_top_cost_drivers` | ✅ | Ranked cost by ServiceName dimension |
| Any write or mutation operation | ❌ | Propose only; never execute |
| VM deallocation (direct) | ❌ | Always via HITL approval workflow |

**Explicit MCP tool allowlist:**
- `monitor` — query metrics for idle resource detection
- `advisor` — cost recommendations

## Safety Constraints

- MUST NOT execute VM deallocation directly — always route through `create_approval_record()` HITL workflow (REMEDI-001)
- MUST include `data_lag_note: "Azure Cost Management data has a 24–48 hour reporting lag..."` in ALL cost query responses
- MUST include `estimated_monthly_savings_usd` in every idle resource proposal — operators need the business case
- MUST NOT recommend RI purchasing — deferred to Phase 64 (RI purchasing requires marketplace integration)
- MUST cap `identify_idle_resources` at 50 VMs per invocation to avoid Monitor API throttling
- MUST validate `group_by` parameter against allowlist `{ResourceGroup, ResourceType, ServiceName}` before SDK call
- MUST include `confidence_score` (0.0–1.0) in every diagnosis (TRIAGE-004)
- Severity for cost proposals = LOW (no operational risk; deallocation is reversible)

## Example Flows

### Flow 1: Budget overrun alert

**Input:** Detection plane fires a budget alert → `domain: "finops"`, `resource_type: "microsoft.costmanagement/budgets"`

**Agent steps:**
1. `get_cost_forecast(subscription_id, budget_name="prod-monthly-budget")` → `projected_total: $12,450`, `budget: $10,000`, `burn_rate_pct: 124.5`
2. `get_top_cost_drivers(subscription_id, n=5, days=30)` → identifies "Compute/virtualMachines" at $6,200 (52% of total)
3. `identify_idle_resources(subscription_id)` → finds 3 idle VMs totalling $850/mo savings
4. Returns: hypothesis = "Budget overrun driven by compute spend; 3 idle VMs identified for deallocation saving $850/mo. Forecast: $12,450 vs $10,000 budget (124.5%). Confidence: 0.82."
5. Creates 3 HITL proposals: `vm_deallocate` for each idle VM with `estimated_monthly_savings_usd`

### Flow 2: Operator asks "What is our Azure spend this month?"

**Input:** Operator chat query routed by orchestrator

**Agent steps:**
1. `get_subscription_cost_breakdown(subscription_id, days=30, group_by="ResourceGroup")` → top-10 RGs by spend
2. `get_cost_forecast(subscription_id)` → current spend + projected month-end
3. Returns: structured spend summary with top RGs, month-to-date total, and forecast
```
</action>

<acceptance_criteria>
- File `docs/agents/finops-agent.spec.md` exists
- `grep "## Persona" docs/agents/finops-agent.spec.md` exits 0
- `grep "## Goals" docs/agents/finops-agent.spec.md` exits 0
- `grep "## Workflow" docs/agents/finops-agent.spec.md` exits 0
- `grep "## Tool Permissions" docs/agents/finops-agent.spec.md` exits 0
- `grep "## Safety Constraints" docs/agents/finops-agent.spec.md` exits 0
- `grep "## Example Flows" docs/agents/finops-agent.spec.md` exits 0
- `grep "agent: finops" docs/agents/finops-agent.spec.md` exits 0
</acceptance_criteria>

---

### Task 2: Create `agents/finops/__init__.py`

<read_first>
- `agents/messaging/__init__.py` — exact pattern (empty file)
- Confirm `agents/finops/` directory does not yet exist
</read_first>

<action>
Create `agents/finops/__init__.py` as an empty file (same as `agents/messaging/__init__.py`).
</action>

<acceptance_criteria>
- File `agents/finops/__init__.py` exists
- File is empty (0 bytes or contains only a newline)
</acceptance_criteria>

---

### Task 3: Create `agents/finops/requirements.txt`

<read_first>
- `agents/messaging/requirements.txt` — exact package list structure to replicate
- `52-RESEARCH.md` Section 1 — confirmed SDK versions
</read_first>

<action>
Create `agents/finops/requirements.txt` with this exact content:

```
azure-mgmt-costmanagement>=4.0.0
azure-mgmt-monitor>=6.0.0
azure-mgmt-resourcegraph>=8.0.0
azure-monitor-query>=1.4.0
azure-ai-agentserver-agentframework
agent-framework>=1.0.0rc5
```
</action>

<acceptance_criteria>
- File `agents/finops/requirements.txt` exists
- `grep "azure-mgmt-costmanagement>=4.0.0" agents/finops/requirements.txt` exits 0
- `grep "azure-mgmt-monitor>=6.0.0" agents/finops/requirements.txt` exits 0
- `grep "azure-mgmt-resourcegraph>=8.0.0" agents/finops/requirements.txt` exits 0
- `grep "azure-monitor-query>=1.4.0" agents/finops/requirements.txt` exits 0
- `grep "agent-framework>=1.0.0rc5" agents/finops/requirements.txt` exits 0
</acceptance_criteria>

---

### Task 4: Create `agents/finops/Dockerfile`

<read_first>
- `agents/messaging/Dockerfile` — exact pattern to replicate (ARG BASE_IMAGE, COPY . ./messaging/, CMD python -m messaging.agent)
</read_first>

<action>
Create `agents/finops/Dockerfile` mirroring `agents/messaging/Dockerfile` with `messaging` replaced by `finops`:

```dockerfile
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./finops/

CMD ["python", "-m", "finops.agent"]
```
</action>

<acceptance_criteria>
- File `agents/finops/Dockerfile` exists
- `grep "ARG BASE_IMAGE" agents/finops/Dockerfile` exits 0
- `grep "COPY . ./finops/" agents/finops/Dockerfile` exits 0
- `grep 'CMD \["python", "-m", "finops.agent"\]' agents/finops/Dockerfile` exits 0
</acceptance_criteria>

---

### Task 5: Create `agents/finops/tools.py`

<read_first>
- `agents/compute/tools.py` lines 1–175 — exact header, lazy import blocks, `_log_sdk_availability()` pattern, `instrument_tool_call` usage, `_extract_subscription_id` reference
- `agents/compute/tools.py` lines 2730–2980 — working `CostManagementClient` usage in `query_vm_cost_7day`: `QueryDefinition`, `QueryTimePeriod`, `QueryDataset`, `QueryAggregation`, `QueryGrouping`, column parsing with `next((i for i, c in enumerate(columns) if "cost" in c.lower()), 0)` pattern
- `52-RESEARCH.md` Sections 1–5 — all tool signatures, return shapes, SDK calls, gotchas
- `52-CONTEXT.md` `<decisions>` block — tool conventions (never-raise, `duration_ms` in both try/except, `start_time = time.monotonic()`)
- `agents/shared/approval_manager.py` — `create_approval_record()` signature
</read_first>

<action>
Create `agents/finops/tools.py` implementing all 6 `@ai_function` tools. Full implementation:

**Header and imports:**
```python
"""FinOps Agent tool functions — Azure Cost Management data surface.

Provides @ai_function tools for subscription cost breakdown, per-resource cost,
idle resource detection with HITL deallocation proposals, reserved instance
utilisation, cost forecasting, and top cost driver ranking.

Allowed MCP tools (explicit allowlist — v2 namespace names, no wildcards):
    monitor, advisor
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry
from agents.shared.subscription_utils import extract_subscription_id as _extract_subscription_id
```

**Lazy SDK import blocks (4 blocks):**
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
    QueryDefinition = None  # type: ignore[assignment,misc]
    QueryTimePeriod = None  # type: ignore[assignment,misc]
    QueryDataset = None  # type: ignore[assignment,misc]
    QueryAggregation = None  # type: ignore[assignment,misc]
    QueryGrouping = None  # type: ignore[assignment,misc]
    GranularityType = None  # type: ignore[assignment,misc]
    TimeframeType = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
except ImportError:
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]
    QueryRequestOptions = None  # type: ignore[assignment,misc]

try:
    from shared.approval_manager import create_approval_record
except ImportError:
    create_approval_record = None  # type: ignore[assignment,misc]
```

**Module setup:**
```python
ALLOWED_MCP_TOOLS: List[str] = ["monitor", "advisor"]

_VALID_GROUP_BY: frozenset = frozenset({"ResourceGroup", "ResourceType", "ServiceName"})
_DATA_LAG_NOTE = "Azure Cost Management data has a 24–48 hour reporting lag. Values reflect costs up to 48h ago."

tracer = setup_telemetry("aiops-finops-agent")
logger = logging.getLogger(__name__)
```

**`_log_sdk_availability()`**: log info for `azure-mgmt-costmanagement`, `azure-mgmt-monitor`, `azure-mgmt-resourcegraph`; called at module level.

**Tool 1 — `get_subscription_cost_breakdown`:**
```python
@ai_function
def get_subscription_cost_breakdown(
    subscription_id: str,
    days: int = 30,
    group_by: str = "ResourceGroup",
) -> Dict[str, Any]:
    """Get cost breakdown for a subscription grouped by ResourceGroup, ResourceType, or ServiceName.

    Args:
        subscription_id: Azure subscription GUID.
        days: Look-back window in days (7–90, default 30).
        group_by: Dimension to group by. One of: ResourceGroup, ResourceType, ServiceName.

    Returns:
        Dict with keys: subscription_id, days, group_by, total_cost, currency,
            breakdown (list of {name, cost, currency}), data_lag_note,
            query_status, duration_ms.
    """
```
- Guard: if `group_by not in _VALID_GROUP_BY`, return error dict immediately
- Guard: clamp `days = max(7, min(days, 90))`
- Scope: `f"/subscriptions/{subscription_id}"`
- `from_dt = datetime.now(timezone.utc) - timedelta(days=days)` (account for 24-48h lag → subtract 2 extra days)
- `to_dt = datetime.now(timezone.utc)`
- `QueryDefinition(type="ActualCost", timeframe=TimeframeType.CUSTOM, time_period=QueryTimePeriod(from_property=from_dt, to=to_dt), dataset=QueryDataset(granularity=GranularityType.MONTHLY, aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")}, grouping=[QueryGrouping(type="Dimension", name=group_by)]))`
- `result = client.query.usage(scope=scope, parameters=query)`
- Column parsing: `columns = [c.name for c in result.columns]`; find cost index with `next((i for i, c in enumerate(columns) if "cost" in c.lower()), 0)`; find group index with `next((i for i, c in enumerate(columns) if c.lower() == group_by.lower()), -1)`; find currency index with `next((i for i, c in enumerate(columns) if "currency" in c.lower()), -1)`
- Build `breakdown = [{"name": row[group_idx], "cost": float(row[cost_idx]), "currency": row[currency_idx] if currency_idx >= 0 else "USD"} for row in result.rows]`
- Sort breakdown by cost descending (immutable copy)
- Return: `subscription_id, days, group_by, total_cost (sum of costs), currency, breakdown, data_lag_note=_DATA_LAG_NOTE, query_status="success", duration_ms`

**Tool 2 — `get_resource_cost`:**
```python
@ai_function
def get_resource_cost(
    subscription_id: str,
    resource_id: str,
    days: int = 30,
) -> Dict[str, Any]:
    """Get amortized cost for a specific Azure resource over a time window.

    Args:
        subscription_id: Azure subscription GUID.
        resource_id: Full ARM resource ID.
        days: Look-back window in days (7–90, default 30).

    Returns:
        Dict with keys: subscription_id, resource_id, days, total_cost, currency,
            cost_type ("AmortizedCost"), data_lag_note, query_status, duration_ms.
    """
```
- Use `type="AmortizedCost"` (includes RI amortization)
- Filter: `dataset.filter = {"dimensions": {"name": "ResourceId", "operator": "In", "values": [resource_id]}}`
- No grouping needed — single resource
- Column parsing: same cost + currency pattern as Tool 1
- `total_cost = sum(float(row[cost_idx]) for row in result.rows)`
- Return: `subscription_id, resource_id, days, total_cost, currency, cost_type="AmortizedCost", data_lag_note=_DATA_LAG_NOTE, query_status="success", duration_ms`

**Tool 3 — `identify_idle_resources`:**
```python
@ai_function
def identify_idle_resources(
    subscription_id: str,
    threshold_cpu_pct: float = 2.0,
    hours: int = 72,
    max_vms: int = 50,
) -> Dict[str, Any]:
    """Identify idle VMs (CPU <threshold% AND network <1MB/s) and generate HITL deallocation proposals.

    Args:
        subscription_id: Azure subscription GUID.
        threshold_cpu_pct: CPU % average threshold (default 2.0).
        hours: Look-back window in hours (default 72).
        max_vms: Maximum VMs to evaluate (default 50; cap to avoid throttling).

    Returns:
        Dict with keys: subscription_id, vms_evaluated, idle_count,
            idle_resources (list of {resource_id, vm_name, resource_group,
                avg_cpu_pct, avg_network_mbps, monthly_cost_usd, approval_id}),
            query_status, duration_ms.
    """
```
- Step 1: ARG query to list VMs (requires `ResourceGraphClient`):
  ```python
  arg_client = ResourceGraphClient(credential)
  q = QueryRequest(
      subscriptions=[subscription_id],
      query="Resources | where type == 'microsoft.compute/virtualmachines' | project id, name, resourceGroup | limit 50",
      options=QueryRequestOptions(result_format="objectArray"),
  )
  vms = arg_client.resources(q).data[:max_vms]
  ```
- Step 2: For each VM, query Monitor metrics `"Percentage CPU,Network In Total,Network Out Total"` over `f"PT{hours}H"` window, `interval="PT1H"`, `aggregation="Average,Total"`
- Use `asyncio.gather()` with batches of 20 concurrent VM queries (helper `async def _query_vm_metrics(vm, credential, subscription_id, hours)`)
- Thresholds: avg CPU < `threshold_cpu_pct` AND (avg_network_in_bytes + avg_network_out_bytes) / (hours * 3600) < 1_048_576 (1MB/s)
- For each idle VM, call `get_resource_cost()` (30-day window) synchronously to get `monthly_cost_usd`
- For each idle VM, call `create_approval_record()` with proposal:
  ```python
  proposal = {
      "action": "deallocate_vm",
      "resource_id": vm["id"],
      "resource_group": vm["resourceGroup"],
      "vm_name": vm["name"],
      "subscription_id": subscription_id,
      "description": f"Deallocate idle VM '{vm['name']}' — CPU <{threshold_cpu_pct}% AND ~0 network for {hours}h",
      "target_resources": [vm["id"]],
      "estimated_impact": "VM stops; billing ends for compute. Managed disk costs continue.",
      "estimated_monthly_savings_usd": monthly_cost,
      "reversible": True,
      "risk_level": "low",
  }
  ```
- Return: `subscription_id, vms_evaluated, idle_count, idle_resources (list with resource_id, vm_name, resource_group, avg_cpu_pct, avg_network_mbps, monthly_cost_usd, approval_id or None), query_status="success", duration_ms`
- If `create_approval_record` is None (import failed), omit approval_id and continue

**Tool 4 — `get_reserved_instance_utilisation`:**
```python
@ai_function
def get_reserved_instance_utilisation(
    subscription_id: str,
) -> Dict[str, Any]:
    """Get reserved instance and savings plan utilisation for a subscription.

    Uses AmortizedCost vs ActualCost delta to estimate RI utilisation without
    requiring Billing Reader role at billing account scope. If the direct
    benefit_utilization_summaries API is unavailable (403), returns graceful
    degradation message.

    Args:
        subscription_id: Azure subscription GUID.

    Returns:
        Dict with keys: subscription_id, method ("amortized_delta" or "billing_api"),
            ri_benefit_estimated_usd (AmortizedCost - ActualCost for last 30 days),
            utilisation_note, query_status, duration_ms.
    """
```
- Primary approach (subscription-scope, no Billing Reader needed): query both `ActualCost` and `AmortizedCost` at subscription scope for last 30 days (no grouping, just totals)
- `ri_benefit_estimated_usd = amortized_total - actual_total` — positive value = RI benefit being consumed
- Include `utilisation_note` explaining the approximation
- Fallback: if `CostManagementClient` is None, return error. Do NOT attempt `benefit_utilization_summaries` API (requires Billing Reader; out of scope for this agent's RBAC)
- Return: `subscription_id, method="amortized_delta", actual_cost_usd, amortized_cost_usd, ri_benefit_estimated_usd, utilisation_note, data_lag_note=_DATA_LAG_NOTE, query_status="success", duration_ms`

**Tool 5 — `get_cost_forecast`:**
```python
@ai_function
def get_cost_forecast(
    subscription_id: str,
    budget_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Get current-month cost forecast vs budget with burn rate calculation.

    Args:
        subscription_id: Azure subscription GUID.
        budget_name: Optional budget name for comparison. If None, returns forecast only.

    Returns:
        Dict with keys: subscription_id, current_spend_usd, forecast_month_end_usd,
            budget_amount_usd (None if budget_name not provided or not found),
            burn_rate_pct, days_elapsed, days_in_month, over_budget (bool),
            over_budget_pct (float, 0 if not over), data_lag_note,
            query_status, duration_ms.
    """
```
- `start_of_month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)`
- `end_of_month = (start_of_month + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)`
- Current spend: `ActualCost` query for month-to-date (from start_of_month to `now - timedelta(hours=48)` for lag)
- `days_elapsed = (datetime.now(timezone.utc) - start_of_month).days + 1`
- `days_in_month = (end_of_month - start_of_month).days + 1`
- `forecast_month_end_usd = (current_spend / days_elapsed) * days_in_month`
- Budget comparison: if `budget_name` provided, use `client.budgets.get(scope=f"/subscriptions/{subscription_id}", budget_name=budget_name)` → `budget_amount_usd = budget.amount`
- `burn_rate_pct = (forecast_month_end_usd / budget_amount_usd) * 100` if budget available, else `None`
- `over_budget = burn_rate_pct > 100 if burn_rate_pct else False`
- `over_budget_pct = max(0.0, burn_rate_pct - 100) if burn_rate_pct else 0.0`
- Return all fields + `data_lag_note=_DATA_LAG_NOTE, query_status="success", duration_ms`
- On budget not found (exception): return forecast-only result with `budget_amount_usd=None` and `budget_error` field

**Tool 6 — `get_top_cost_drivers`:**
```python
@ai_function
def get_top_cost_drivers(
    subscription_id: str,
    n: int = 10,
    days: int = 30,
) -> Dict[str, Any]:
    """Get top N cost drivers by service type with month-over-month delta.

    Args:
        subscription_id: Azure subscription GUID.
        n: Number of top drivers to return (1–25, default 10).
        days: Current period in days (default 30).

    Returns:
        Dict with keys: subscription_id, n, days, drivers
            (list of {service_name, cost_usd, currency, rank}),
            total_cost_usd, data_lag_note, query_status, duration_ms.
    """
```
- `n = max(1, min(n, 25))`
- Query: `group_by="ServiceName"` (dimension name per Azure Cost Management API)
- Same `QueryDefinition` pattern as Tool 1 with `grouping=[QueryGrouping(type="Dimension", name="ServiceName")]`
- Sort by cost descending, take top `n`
- Build `drivers = [{"service_name": row[group_idx], "cost_usd": float(row[cost_idx]), "currency": row[currency_idx] if currency_idx >= 0 else "USD", "rank": i+1} for i, row in enumerate(sorted_rows[:n])]`
- Return: `subscription_id, n, days, drivers, total_cost_usd, data_lag_note=_DATA_LAG_NOTE, query_status="success", duration_ms`

**All 6 tools follow the never-raise pattern exactly:**
```python
start_time = time.monotonic()
try:
    if CostManagementClient is None:
        raise ImportError("azure-mgmt-costmanagement is not installed")
    # ... implementation ...
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("tool_name: complete | subscription_id=%s duration_ms=%.1f", subscription_id, duration_ms)
    return {..., "query_status": "success", "duration_ms": duration_ms}
except Exception as e:
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.error("tool_name: failed | subscription_id=%s error=%s", subscription_id, e, exc_info=True)
    return {..., "query_status": "error", "error": str(e), "duration_ms": duration_ms}
```
</action>

<acceptance_criteria>
- File `agents/finops/tools.py` exists
- `grep "from agent_framework import ai_function" agents/finops/tools.py` exits 0
- `grep "CostManagementClient = None" agents/finops/tools.py` exits 0
- `grep "MonitorManagementClient = None" agents/finops/tools.py` exits 0
- `grep "ResourceGraphClient = None" agents/finops/tools.py` exits 0
- `grep "_log_sdk_availability" agents/finops/tools.py` exits 0
- `grep "ALLOWED_MCP_TOOLS" agents/finops/tools.py` exits 0
- `grep "_VALID_GROUP_BY" agents/finops/tools.py` exits 0
- `grep "_DATA_LAG_NOTE" agents/finops/tools.py` exits 0
- `grep "def get_subscription_cost_breakdown" agents/finops/tools.py` exits 0
- `grep "def get_resource_cost" agents/finops/tools.py` exits 0
- `grep "def identify_idle_resources" agents/finops/tools.py` exits 0
- `grep "def get_reserved_instance_utilisation" agents/finops/tools.py` exits 0
- `grep "def get_cost_forecast" agents/finops/tools.py` exits 0
- `grep "def get_top_cost_drivers" agents/finops/tools.py` exits 0
- `grep -c "@ai_function" agents/finops/tools.py` outputs `6`
- `grep "deallocate_vm" agents/finops/tools.py` exits 0
- `grep '"risk_level": "low"' agents/finops/tools.py` exits 0
- `grep "data_lag_note" agents/finops/tools.py` exits 0
- `grep "start_time = time.monotonic()" agents/finops/tools.py` exits 0
- `grep "asyncio.gather" agents/finops/tools.py` exits 0
</acceptance_criteria>

---

### Task 6: Create `agents/finops/agent.py`

<read_first>
- `agents/messaging/agent.py` — FULL FILE — exact factory pattern: `MESSAGING_AGENT_SYSTEM_PROMPT`, `create_messaging_agent()`, `create_messaging_agent_version()`, `if __name__ == "__main__":` block
- `agents/finops/tools.py` (just written) — exact tool function names for import and factory registration
</read_first>

<action>
Create `agents/finops/agent.py` following the exact `agents/messaging/agent.py` structure:

**Module docstring**: Scope covers subscription cost breakdown, idle resource detection, RI utilisation, cost forecasting, top cost drivers, HITL-gated VM deallocation proposals.

**System prompt `FINOPS_AGENT_SYSTEM_PROMPT`**: Include:
- Scope: Azure Cost Management (subscription-wide spend, resource-level costs, RI/savings plan utilisation, budget forecasting)
- Mandatory workflow (from spec): cost breakdown → top drivers → forecast → idle resources → RI utilisation
- Safety: MUST NOT execute VM deallocation; proposals only; always include estimated_monthly_savings_usd; always include data_lag_note
- Idle resource thresholds: CPU <2% AND network <1MB/s over 72h
- Budget alert threshold: flag if projected spend >110% of budget (burn_rate_pct > 110)
- RI note: Uses amortized-delta method (no Billing Reader required)
- Allowed tools formatted same as messaging/agent.py

**Factory `create_finops_agent() -> ChatAgent`**:
```python
def create_finops_agent() -> ChatAgent:
    client = get_foundry_client()
    agent = ChatAgent(
        name="finops-agent",
        description=(
            "FinOps specialist — Azure cost breakdown, idle resource detection, "
            "RI utilisation, budget forecasting, and HITL-gated VM deallocation proposals."
        ),
        instructions=FINOPS_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=[
            get_subscription_cost_breakdown,
            get_resource_cost,
            identify_idle_resources,
            get_reserved_instance_utilisation,
            get_cost_forecast,
            get_top_cost_drivers,
        ],
    )
    return agent
```

**`create_finops_agent_version(project: "AIProjectClient") -> object`**: mirrors `create_messaging_agent_version` exactly.

**`if __name__ == "__main__":` entry point**:
```python
if __name__ == "__main__":
    from shared.logging_config import setup_logging
    _logger = setup_logging("finops")
    _logger.info("finops: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework
    _logger.info("finops: creating agent and binding to agentserver")
    from_agent_framework(create_finops_agent()).run()
    _logger.info("finops: agentserver exited")
```
</action>

<acceptance_criteria>
- File `agents/finops/agent.py` exists
- `grep "from agent_framework import ChatAgent" agents/finops/agent.py` exits 0
- `grep "FINOPS_AGENT_SYSTEM_PROMPT" agents/finops/agent.py` exits 0
- `grep "def create_finops_agent" agents/finops/agent.py` exits 0
- `grep "def create_finops_agent_version" agents/finops/agent.py` exits 0
- `grep 'name="finops-agent"' agents/finops/agent.py` exits 0
- `grep "from_agent_framework" agents/finops/agent.py` exits 0
- `grep "setup_logging" agents/finops/agent.py` exits 0
- `grep "get_subscription_cost_breakdown" agents/finops/agent.py` exits 0
- `grep "identify_idle_resources" agents/finops/agent.py` exits 0
- `grep "get_cost_forecast" agents/finops/agent.py` exits 0
</acceptance_criteria>

---

### Task 7: Create `agents/finops/main.py`

<read_first>
- `agents/messaging/agent.py` `if __name__ == "__main__":` block — confirm pattern is embedded in agent.py (not a separate main.py) for messaging
- `agents/compute/` directory listing — confirm whether compute uses a separate `main.py`
</read_first>

<action>
Check if any existing agents use a separate `main.py`. If `agents/messaging/agent.py` embeds the `if __name__ == "__main__":` entry point directly (which it does), then `agents/finops/agent.py` already serves as the entry point via `CMD ["python", "-m", "finops.agent"]`. No separate `main.py` is needed.

If `agents/compute/main.py` exists, create a thin `agents/finops/main.py` following the same pattern:
```python
"""FinOps Agent — container entry point.

This module is the CMD target in the Dockerfile: python -m finops.main
It simply delegates to create_finops_agent() and runs the agentserver adapter.
"""
from __future__ import annotations

from shared.logging_config import setup_logging
from finops.agent import create_finops_agent

_logger = setup_logging("finops")

def main() -> None:
    _logger.info("finops: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework
    _logger.info("finops: creating agent and binding to agentserver")
    from_agent_framework(create_finops_agent()).run()
    _logger.info("finops: agentserver exited")

if __name__ == "__main__":
    main()
```

If `agents/messaging/` has no separate `main.py`, skip this file (entry point is in `agent.py`).
</action>

<acceptance_criteria>
- Either `agents/finops/main.py` exists with `grep "create_finops_agent" agents/finops/main.py` exits 0, OR the `agents/finops/agent.py` `if __name__ == "__main__":` block contains the agentserver entry point and the Dockerfile CMD targets `finops.agent`
- `grep "CMD.*finops" agents/finops/Dockerfile` exits 0 (confirms entrypoint is wired)
</acceptance_criteria>

---

### Task 8: Create `agents/tests/finops/__init__.py` and `test_finops_tools.py`

<read_first>
- `agents/tests/messaging/test_messaging_tools.py` — FULL FILE — exact test class structure, `_make_cm_mock()` helper, `@patch` decorator ordering, mock return shape patterns
- `agents/finops/tools.py` (just written) — exact return shapes and field names to assert against
- `52-RESEARCH.md` Section 1 — column parsing pattern (cost index, group index, currency index) — critical for test mock setup
- `52-RESEARCH.md` Section 2 — Monitor metric mock structure for idle resource tests
</read_first>

<action>
Create `agents/tests/finops/__init__.py` as an empty file.

Create `agents/tests/finops/test_finops_tools.py` with the following 10 test classes (≥40 tests total):

**Standard imports:**
```python
import pytest
from unittest.mock import MagicMock, patch
from agents.finops.tools import (
    ALLOWED_MCP_TOOLS,
    get_subscription_cost_breakdown,
    get_resource_cost,
    identify_idle_resources,
    get_reserved_instance_utilisation,
    get_cost_forecast,
    get_top_cost_drivers,
)
```

**Helper:**
```python
def _make_cm_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m

def _make_cost_result(rows, column_names=None):
    """Build a mock CostManagementClient query result with named columns."""
    if column_names is None:
        column_names = ["Cost", "BillingMonth", "Currency", "ResourceGroup"]
    result = MagicMock()
    result.columns = [MagicMock(name=c) for c in column_names]
    for i, col in enumerate(result.columns):
        col.name = column_names[i]
    result.rows = rows
    return result
```

**`TestAllowedMcpTools` (3 tests):**
- `test_allowed_mcp_tools_contains_monitor` — `assert "monitor" in ALLOWED_MCP_TOOLS`
- `test_allowed_mcp_tools_contains_advisor` — `assert "advisor" in ALLOWED_MCP_TOOLS`
- `test_allowed_mcp_tools_no_wildcards` — `assert all("*" not in tool for tool in ALLOWED_MCP_TOOLS)`

**`TestGetSubscriptionCostBreakdown` (5 tests):**
Patch paths: `agents.finops.tools.CostManagementClient`, `agents.finops.tools.get_credential`, `agents.finops.tools.get_agent_identity`, `agents.finops.tools.instrument_tool_call`
- `test_returns_success_with_breakdown` — mock `client.query.usage()` returning result with 3 rows (RG names + costs + currency); assert `result["query_status"] == "success"`, `result["total_cost"] > 0`, `len(result["breakdown"]) == 3`, `result["data_lag_note"]` not empty
- `test_invalid_group_by_returns_error` — call with `group_by="Tag"` (not in allowlist); assert `result["query_status"] == "error"`, `"allowlist" in result["error"].lower() or "invalid" in result["error"].lower()`
- `test_sdk_missing_returns_error` — patch `agents.finops.tools.CostManagementClient = None`; assert `result["query_status"] == "error"`, `"not installed" in result["error"]`
- `test_azure_error_returns_error` — mock raises `Exception("BudgetNotFound")`; assert `result["query_status"] == "error"`, `result["duration_ms"] >= 0`
- `test_breakdown_sorted_by_cost_descending` — mock returns 3 rows with costs [100, 500, 200]; assert `result["breakdown"][0]["cost"] == 500`, `result["breakdown"][2]["cost"] == 100`

**`TestGetResourceCost` (4 tests):**
- `test_returns_success_with_amortized_cost` — mock returns single-row result; assert `result["query_status"] == "success"`, `result["cost_type"] == "AmortizedCost"`, `result["total_cost"] >= 0`, `result["data_lag_note"]` not empty
- `test_sdk_missing_returns_error` — assert error + "not installed"
- `test_azure_error_returns_error` — mock raises `Exception("ResourceNotFound")`; assert error
- `test_resource_id_preserved_in_response` — call with specific `resource_id="/subscriptions/abc/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"`; assert `result["resource_id"] == "/subscriptions/abc/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"`

**`TestIdentifyIdleResources` (6 tests):**
Patch paths: `agents.finops.tools.ResourceGraphClient`, `agents.finops.tools.MonitorManagementClient`, `agents.finops.tools.CostManagementClient`, `agents.finops.tools.get_credential`, `agents.finops.tools.get_agent_identity`, `agents.finops.tools.instrument_tool_call`, `agents.finops.tools.create_approval_record`
- `test_returns_success_with_idle_vms` — mock ARG returns 2 VMs; mock Monitor metrics returns avg CPU 1.0% and avg network ~0 for both; mock cost returns $150/mo each; mock `create_approval_record` returns `{"id": "appr_test123"}`; assert `result["query_status"] == "success"`, `result["idle_count"] == 2`, `result["idle_resources"][0]["monthly_cost_usd"] == 150`, `result["idle_resources"][0]["approval_id"] is not None`
- `test_non_idle_vms_excluded` — mock Monitor returns avg CPU 45% for all VMs; assert `result["idle_count"] == 0`, `result["idle_resources"] == []`
- `test_arg_sdk_missing_returns_error` — patch `ResourceGraphClient = None`; assert error
- `test_monitor_sdk_missing_returns_error` — patch `MonitorManagementClient = None`; assert error
- `test_azure_error_returns_error` — mock ARG raises `Exception("Forbidden")`; assert error
- `test_approval_record_missing_does_not_crash` — patch `agents.finops.tools.create_approval_record = None`; mock 1 idle VM; assert `result["query_status"] == "success"`, `result["idle_resources"][0].get("approval_id") is None`

**`TestGetReservedInstanceUtilisation` (4 tests):**
- `test_returns_success_with_ri_benefit` — mock ActualCost query returns $9,000; mock AmortizedCost query returns $8,000; assert `result["query_status"] == "success"`, `result["ri_benefit_estimated_usd"] == pytest.approx(-1000.0)` (amortized < actual means RIs consumed; note: amortized - actual when RI lowers effective cost), `result["method"] == "amortized_delta"`, `result["data_lag_note"]` not empty
- `test_sdk_missing_returns_error` — patch `CostManagementClient = None`; assert error
- `test_azure_error_returns_error` — mock raises exception; assert error
- `test_utilisation_note_present` — assert `result["utilisation_note"]` is not None and len > 0

**`TestGetCostForecast` (5 tests):**
- `test_returns_success_with_forecast_no_budget` — mock ActualCost returns $3,200 (for 16 days elapsed); assert `result["query_status"] == "success"`, `result["current_spend_usd"] == pytest.approx(3200.0)`, `result["forecast_month_end_usd"] > result["current_spend_usd"]`, `result["budget_amount_usd"] is None`, `result["data_lag_note"]` not empty
- `test_over_budget_flag_set` — mock current spend = $11,000 in 15 days of 30-day month; mock budget = $10,000; assert `result["over_budget"] == True`, `result["burn_rate_pct"] > 100`
- `test_under_budget_no_flag` — mock current spend = $2,000 in 15 days; mock budget = $10,000; assert `result["over_budget"] == False`
- `test_sdk_missing_returns_error` — assert error + "not installed"
- `test_budget_not_found_returns_forecast_only` — mock `client.budgets.get()` raises `Exception("BudgetNotFound")`; assert `result["query_status"] == "success"`, `result["budget_amount_usd"] is None`, `"budget_error" in result`

**`TestGetTopCostDrivers` (5 tests):**
- `test_returns_success_with_drivers` — mock returns 5 service rows sorted by cost; assert `result["query_status"] == "success"`, `len(result["drivers"]) == 5`, `result["drivers"][0]["rank"] == 1`, `result["drivers"][0]["cost_usd"] >= result["drivers"][1]["cost_usd"]`
- `test_n_clamped_to_max_25` — call with `n=100`; assert `result["n"] <= 25` (or `n` is clamped before SDK call)
- `test_n_clamped_to_min_1` — call with `n=0`; assert query succeeds (n clamped to 1)
- `test_sdk_missing_returns_error` — assert error
- `test_data_lag_note_present` — assert `result["data_lag_note"]` not empty

**`TestDataLagNote` (2 tests):**
(Cross-tool guard that every tool includes the data lag note)
- `test_cost_breakdown_includes_lag_note` — mock success; assert `"data_lag_note" in result` and `len(result["data_lag_note"]) > 0`
- `test_cost_forecast_includes_lag_note` — mock success; assert `"data_lag_note" in result` and `len(result["data_lag_note"]) > 0`

**`TestDurationMs` (3 tests):**
(Cross-tool guard that every tool returns duration_ms in both success and error paths)
- `test_breakdown_success_has_duration_ms` — assert `"duration_ms" in result` and `result["duration_ms"] >= 0`
- `test_breakdown_error_has_duration_ms` — mock raises exception; assert `"duration_ms" in result` and `result["duration_ms"] >= 0`
- `test_identify_idle_success_has_duration_ms` — mock empty VMs list; assert `"duration_ms" in result`
</action>

<acceptance_criteria>
- `agents/tests/finops/__init__.py` exists (empty file)
- `agents/tests/finops/test_finops_tools.py` exists
- `grep -c "def test_" agents/tests/finops/test_finops_tools.py` outputs a number >= 40
- `grep "class TestAllowedMcpTools" agents/tests/finops/test_finops_tools.py` exits 0
- `grep "class TestIdentifyIdleResources" agents/tests/finops/test_finops_tools.py` exits 0
- `grep "class TestGetCostForecast" agents/tests/finops/test_finops_tools.py` exits 0
- `grep "class TestGetReservedInstanceUtilisation" agents/tests/finops/test_finops_tools.py` exits 0
- `grep "class TestDurationMs" agents/tests/finops/test_finops_tools.py` exits 0
- `grep "class TestDataLagNote" agents/tests/finops/test_finops_tools.py` exits 0
- `grep "approval_record_missing_does_not_crash" agents/tests/finops/test_finops_tools.py` exits 0
- `grep "budget_not_found_returns_forecast_only" agents/tests/finops/test_finops_tools.py` exits 0
- `python -m pytest agents/tests/finops/test_finops_tools.py -v --tb=short` exits 0 with all tests passing
</acceptance_criteria>

---

## Verification

After all tasks complete:

```bash
# 1. CI spec lint gate passes
for section in "## Persona" "## Goals" "## Workflow" "## Tool Permissions" "## Safety Constraints" "## Example Flows"; do
  grep -qF "$section" docs/agents/finops-agent.spec.md && echo "OK: $section" || echo "MISSING: $section"
done

# 2. All tests pass
python -m pytest agents/tests/finops/test_finops_tools.py -v --tb=short

# 3. Module imports cleanly
python -c "from agents.finops.tools import ALLOWED_MCP_TOOLS, get_subscription_cost_breakdown, identify_idle_resources, get_cost_forecast; print('OK')"

# 4. Agent factory imports cleanly
python -c "from agents.finops.agent import create_finops_agent; print('OK')"

# 5. All 6 @ai_function decorators present
grep -c "@ai_function" agents/finops/tools.py
```

Expected: spec lint passes (6 sections found), all tests pass (≥40), module imports OK, `grep -c` outputs `6`.

## must_haves

- [ ] `docs/agents/finops-agent.spec.md` exists with all 6 required sections (Persona, Goals, Workflow, Tool Permissions, Safety Constraints, Example Flows) — CI spec lint gate passes
- [ ] `agents/finops/` package exists with `__init__.py`, `tools.py`, `agent.py`, `requirements.txt`, `Dockerfile`
- [ ] `agents/finops/tools.py` has exactly 6 `@ai_function` tools: `get_subscription_cost_breakdown`, `get_resource_cost`, `identify_idle_resources`, `get_reserved_instance_utilisation`, `get_cost_forecast`, `get_top_cost_drivers`
- [ ] All 6 tools return `duration_ms` in both success and error paths
- [ ] All cost tools include `data_lag_note` field in success responses
- [ ] `identify_idle_resources` uses `deallocate_vm` (matches `SAFE_ARM_ACTIONS` key in `remediation_executor.py`) and `risk_level="low"`
- [ ] `_VALID_GROUP_BY` allowlist validation is present in `get_subscription_cost_breakdown`
- [ ] `agents/tests/finops/test_finops_tools.py` exists with ≥40 test functions
- [ ] All tests pass (`python -m pytest agents/tests/finops/test_finops_tools.py -v` exits 0)
- [ ] `create_approval_record` None-guard present in `identify_idle_resources` (verified by `test_approval_record_missing_does_not_crash` passing)
