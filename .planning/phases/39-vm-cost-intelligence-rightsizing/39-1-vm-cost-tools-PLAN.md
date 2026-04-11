---
plan_id: "39-1"
phase: 39
wave: 1
title: "VM Cost Intelligence & Rightsizing Tools"
goal: "Implement 3 new cost intelligence tools (Advisor rightsizing, Cost Management 7-day spend, HITL SKU downsize), register in agent.py, add API gateway endpoint, build CostTab web UI, add SOP, write 15 unit tests, and wire Terraform Cost Management Reader RBAC."
---

# Plan 39-1: VM Cost Intelligence & Rightsizing Tools

## Goal

Surface wasteful Azure VM spend and enable operators to act on it through the existing HITL approval workflow. Adds:
- 3 `@ai_function` tools to `agents/compute/tools.py`
- Tool registration in `agents/compute/agent.py` (4 locations)
- 2 new packages in `agents/compute/requirements.txt`
- `GET /api/v1/vms/cost-summary` endpoint in the API gateway
- `CostTab.tsx` component + proxy route + `DashboardPanel.tsx` wiring
- `sops/compute/vm-low-cpu-rightsizing.md` SOP
- 15 unit tests in `agents/tests/compute/test_compute_cost.py`
- `Cost Management Reader` RBAC in `terraform/modules/rbac/main.tf`

## Context

### Key files
- `agents/compute/tools.py` — add 3 tools after the existing Phase 37 performance tools (around line 1093+)
- `agents/compute/agent.py` — 4 locations: import block, `COMPUTE_AGENT_SYSTEM_PROMPT` allowed tools list, `ChatAgent(tools=[...])`, `PromptAgentDefinition(tools=[...])`
- `agents/compute/requirements.txt` — currently 6 packages; add 2 more
- `agents/tests/compute/test_compute_performance.py` — test pattern to follow exactly
- `agents/tests/compute/test_compute_agent_registration.py` — agent registration test to update (tool count from 27 → 30)
- `services/api-gateway/main.py` — router imports at lines 97–119, `include_router` at lines 478–487
- `services/api-gateway/eol_endpoints.py` — pattern for a new router module
- `services/web-ui/components/DashboardPanel.tsx` — add 'cost' to TabId union + TABS array + panel div
- `services/web-ui/components/PatchTab.tsx` — UI pattern to follow
- `services/web-ui/app/api/proxy/patch/assessment/route.ts` — proxy route pattern
- `terraform/modules/rbac/main.tf` — add Cost Management Reader block inside `role_assignments` merge

### Existing HITL pattern (CRITICAL — copy exactly)
`propose_vm_restart` at lines 960–1024 is the canonical reference. Key fields:
- `container=None` — approval manager resolves its own Cosmos container
- `risk_level="medium"` for downsize (NOT "high" — that's reserved for resize)
- `incident_id=""` — cost proposals may have no incident context; pass empty string
- Return: `{"status": "pending_approval", "approval_id": ..., "message": ..., "duration_ms": ...}`

### Lazy import pattern (CRITICAL — copy exactly)
```python
try:
    from azure.mgmt.advisor import AdvisorManagementClient
except ImportError:
    AdvisorManagementClient = None  # type: ignore[assignment,misc]
```

### Tool function skeleton (CRITICAL — copy exactly)
```python
@ai_function
def my_tool(param: str, thread_id: str) -> Dict[str, Any]:
    """Docstring."""
    start_time = time.monotonic()
    agent_id = get_agent_identity()
    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="my_tool",
        tool_parameters={"param": param},
        correlation_id=param,
        thread_id=thread_id,
    ):
        try:
            # ... implementation ...
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {"query_status": "success", ..., "duration_ms": duration_ms}
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("my_tool error: %s", exc)
            return {"error": str(exc), "duration_ms": duration_ms}
```

---

## Tasks

### Task 1: Add lazy imports for new Azure SDK clients in tools.py

**File:** `agents/compute/tools.py`
**Action:** modify — add 2 new lazy import blocks after the existing lazy imports (around line 80, before `from shared.approval_manager import create_approval_record`)

Add these two blocks in sequence, following the exact pattern of existing lazy imports:

```python
# Lazy import — azure-mgmt-advisor may not be installed in all envs
try:
    from azure.mgmt.advisor import AdvisorManagementClient
    from azure.mgmt.advisor.models import ResourceRecommendationBase
except ImportError:
    AdvisorManagementClient = None  # type: ignore[assignment,misc]
    ResourceRecommendationBase = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-costmanagement may not be installed in all envs
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
```

---

### Task 2: Implement `query_advisor_rightsizing_recommendations` in tools.py

**File:** `agents/compute/tools.py`
**Action:** modify — append after the last tool in the file (after `propose_vm_redeploy` and any other Phase 32/37 tools, keeping the Phase 39 section clearly separated with a section comment)

Add section header comment:
```python
# ---------------------------------------------------------------------------
# Phase 39 — VM Cost Intelligence tools
# ---------------------------------------------------------------------------
```

Then implement the tool:

```python
@ai_function
def query_advisor_rightsizing_recommendations(
    vm_name: str,
    subscription_id: str,
    resource_group: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query Azure Advisor Cost recommendations for a specific VM.

    Returns rightsizing recommendations including target SKU and estimated
    monthly savings. Use this tool BEFORE proposing a SKU downsize to confirm
    Advisor has flagged the VM as underutilized.

    NOTE: Azure Advisor recommendations are refreshed every 24 hours.
    If no recommendations appear, the VM may not yet be assessed.

    Returns:
        Dict with recommendation_count, recommendations list, and duration_ms.
        Each recommendation contains: target_sku, estimated_monthly_savings,
        savings_currency, impact, description, extended_properties (raw dict).
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_advisor_rightsizing_recommendations",
        tool_parameters={"vm_name": vm_name, "subscription_id": subscription_id},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            if AdvisorManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-mgmt-advisor not installed",
                    "duration_ms": duration_ms,
                }

            credential = get_credential()
            client = AdvisorManagementClient(credential, subscription_id)

            recommendations = []
            for rec in client.recommendations.list():
                # Filter: Cost category only
                if rec.category != "Cost":
                    continue
                # Filter: virtualMachines resource type
                if not rec.impacted_field or "virtualmachines" not in rec.impacted_field.lower():
                    continue
                # Filter: matches this VM name (check impacted_value and resource_metadata)
                impacted_value = (rec.impacted_value or "").lower()
                resource_id_str = ""
                if rec.resource_metadata and rec.resource_metadata.resource_id:
                    resource_id_str = rec.resource_metadata.resource_id.lower()

                if vm_name.lower() not in impacted_value and vm_name.lower() not in resource_id_str:
                    continue
                # Also filter by resource_group if provided
                if resource_group and resource_group.lower() not in resource_id_str:
                    continue

                ext = rec.extended_properties or {}
                recommendations.append({
                    "recommendation_id": rec.id or "",
                    "target_sku": ext.get("recommendedSkuName", ""),
                    "estimated_monthly_savings": float(ext.get("savingsAmount", 0) or 0),
                    "annual_savings": float(ext.get("annualSavingsAmount", 0) or 0),
                    "savings_currency": ext.get("savingsCurrency", "USD"),
                    "impact": rec.impact or "Medium",
                    "description": (rec.short_description.solution if rec.short_description else ""),
                    "impacted_value": rec.impacted_value or "",
                    "last_updated": rec.last_updated.isoformat() if rec.last_updated else "",
                    "extended_properties": dict(ext),
                })

            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "query_status": "success",
                "vm_name": vm_name,
                "subscription_id": subscription_id,
                "recommendation_count": len(recommendations),
                "recommendations": recommendations,
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_advisor_rightsizing_recommendations error: %s", exc)
            return {"error": str(exc), "duration_ms": duration_ms}
```

---

### Task 3: Implement `query_vm_cost_7day` in tools.py

**File:** `agents/compute/tools.py`
**Action:** modify — append after `query_advisor_rightsizing_recommendations`

```python
@ai_function
def query_vm_cost_7day(
    resource_id: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query Azure Cost Management for a VM's actual cost over the last 7 days.

    Returns daily cost breakdown and 7-day total spend for the specified VM.

    IMPORTANT: Azure Cost Management data has a 24-48 hour lag. Today's cost
    may not yet be reflected. Use this for trend analysis, not real-time spend.

    Requires 'Cost Management Reader' role on the subscription scope (Terraform
    RBAC must be applied before this tool will succeed in production).

    Returns:
        Dict with total_cost_7d, currency, daily_costs list [{date, cost}],
        data_lag_note, and duration_ms.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_vm_cost_7day",
        tool_parameters={"resource_id": resource_id, "subscription_id": subscription_id},
        correlation_id=resource_id,
        thread_id=thread_id,
    ):
        try:
            if CostManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-mgmt-costmanagement not installed",
                    "duration_ms": duration_ms,
                }

            from datetime import datetime, timedelta, timezone

            credential = get_credential()
            client = CostManagementClient(credential)

            # 7-day window (yesterday - 7 days to yesterday to account for 24-48h lag)
            to_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            from_dt = to_dt - timedelta(days=7)

            scope = f"/subscriptions/{subscription_id}"

            query = QueryDefinition(
                type="ActualCost",
                timeframe=TimeframeType.CUSTOM,
                time_period=QueryTimePeriod(
                    from_property=from_dt,
                    to=to_dt,
                ),
                dataset=QueryDataset(
                    granularity=GranularityType.DAILY,
                    aggregation={
                        "totalCost": QueryAggregation(name="Cost", function="Sum")
                    },
                    grouping=[
                        QueryGrouping(type="Dimension", name="ResourceId"),
                    ],
                    filter={
                        "dimensions": {
                            "name": "ResourceId",
                            "operator": "In",
                            "values": [resource_id],
                        }
                    },
                ),
            )

            result = client.query.usage(scope=scope, parameters=query)

            # Parse columns to determine index positions
            columns = [col.name.lower() if hasattr(col, "name") else col.get("name", "").lower()
                       for col in (result.columns or [])]

            cost_idx = next((i for i, c in enumerate(columns) if "cost" in c), 0)
            date_idx = next((i for i, c in enumerate(columns) if "date" in c or "usage" in c.lower()), 1)
            currency_idx = next((i for i, c in enumerate(columns) if "currency" in c), None)

            daily_costs: List[Dict[str, Any]] = []
            total_cost = 0.0
            currency = "USD"
            for row in (result.rows or []):
                cost_val = float(row[cost_idx]) if len(row) > cost_idx else 0.0
                date_val = str(row[date_idx]) if len(row) > date_idx else ""
                if currency_idx is not None and len(row) > currency_idx:
                    currency = str(row[currency_idx])
                total_cost += cost_val
                daily_costs.append({"date": date_val, "cost": round(cost_val, 4)})

            # Sort daily_costs ascending by date
            daily_costs.sort(key=lambda x: x["date"])

            duration_ms = int((time.monotonic() - start_time) * 1000)
            return {
                "query_status": "success",
                "resource_id": resource_id,
                "subscription_id": subscription_id,
                "total_cost_7d": round(total_cost, 4),
                "currency": currency,
                "daily_costs": daily_costs,
                "period_from": from_dt.strftime("%Y-%m-%d"),
                "period_to": to_dt.strftime("%Y-%m-%d"),
                "data_lag_note": "Azure Cost Management data has a 24-48 hour lag. Recent costs may not be reflected.",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_vm_cost_7day error: %s", exc)
            return {"error": str(exc), "duration_ms": duration_ms}
```

---

### Task 4: Implement `propose_vm_sku_downsize` in tools.py

**File:** `agents/compute/tools.py`
**Action:** modify — append after `query_vm_cost_7day`

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
    """Propose a VM SKU downsize — creates HITL ApprovalRecord (no ARM call).

    Call query_advisor_rightsizing_recommendations and query_vm_cost_7day
    BEFORE calling this tool to confirm the downsize is warranted.

    REMEDI-001: This tool ONLY creates an approval record. The SKU change
    is executed by RemediationExecutor AFTER human approval.

    Use this tool when:
    - Azure Advisor has flagged the VM as underutilized (target_sku from Advisor)
    - CPU utilization is consistently below 5% over the last 7 days
    - Estimated monthly savings exceed $20

    Returns:
        Dict with status="pending_approval", approval_id, message, and duration_ms.
    """
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
                incident_id="",  # Cost proposals may have no incident context
                agent_name="compute-agent",
                proposal=proposal,
                resource_snapshot={"vm_name": vm_name, "target_sku": target_sku},
                risk_level="medium",  # Downsize = medium (same risk class as restart)
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

---

### Task 5: Update requirements.txt

**File:** `agents/compute/requirements.txt`
**Action:** modify — add 2 new lines

Current file ends after `azure-cosmos>=4.0.0`. Append:
```
azure-mgmt-advisor>=9.0.0
azure-mgmt-costmanagement>=4.0.0
```

Final file should be:
```
# Compute agent — Azure SDK dependencies for diagnostic tools.
azure-mgmt-resourcegraph>=8.0.1
azure-mgmt-monitor>=6.0.0
azure-monitor-query>=1.3.0
azure-mgmt-resourcehealth==1.0.0b6
azure-mgmt-compute>=30.0.0
azure-cosmos>=4.0.0
azure-mgmt-advisor>=9.0.0
azure-mgmt-costmanagement>=4.0.0
```

---

### Task 6: Register 3 new tools in agent.py — 4 locations

**File:** `agents/compute/agent.py`
**Action:** modify — 4 locations

**Location 1: Import block (lines 31–60)**

Add 3 new imports to the existing `from compute.tools import (...)` block:
```python
from compute.tools import (
    ...existing imports...
    query_advisor_rightsizing_recommendations,  # Phase 39
    query_vm_cost_7day,                         # Phase 39
    propose_vm_sku_downsize,                    # Phase 39
)
```

**Location 2: COMPUTE_AGENT_SYSTEM_PROMPT — `## VM Cost Intelligence Tools` section**

Add a new section to `COMPUTE_AGENT_SYSTEM_PROMPT` (in the `.format(allowed_tools=...)` call, the tools list is auto-generated from the `ALLOWED_MCP_TOOLS` list concatenation). The tools will appear in the formatted list automatically once added to the format call. Add a VM Cost Intelligence section to the PROMPT text before the `.format(...)` call:

In the multi-line string `COMPUTE_AGENT_SYSTEM_PROMPT`, after the `## Safety Constraints` section, add:

```
## VM Cost Intelligence Tools

Use these tools together for cost rightsizing investigations:

1. Call `query_advisor_rightsizing_recommendations` to check if Azure Advisor has flagged
   the VM as underutilized. Note the recommended target_sku and estimated monthly savings.
2. Call `query_vm_cost_7day` to confirm actual 7-day spend for the VM.
3. Only call `propose_vm_sku_downsize` when ALL of the following are true:
   - Advisor has a cost recommendation with a specific target_sku
   - Average CPU utilization is consistently below 5% (verify with query_monitor_metrics)
   - Estimated monthly savings exceed $20
   - The VM is not tagged as 'protected'
```

**Location 3: `ChatAgent(tools=[...])` list**

Add 3 tools to the `tools=[...]` list in `create_compute_agent()`. Place them at the end of the list, before the closing `]`:
```python
tools=[
    ...existing 27 tools...
    query_advisor_rightsizing_recommendations,
    query_vm_cost_7day,
    propose_vm_sku_downsize,
],
```

**Location 4: `PromptAgentDefinition(tools=[...])` list**

Add the same 3 tools to the `tools=[...]` list in `create_compute_agent_version()`:
```python
tools=[
    ...existing 27 tools...
    query_advisor_rightsizing_recommendations,
    query_vm_cost_7day,
    propose_vm_sku_downsize,
],
```

Also add the 3 new tool names to the allowed_tools format argument so they appear in the system prompt:
```python
COMPUTE_AGENT_SYSTEM_PROMPT = """...""".format(allowed_tools="\n".join(f"- `{t}`" for t in ALLOWED_MCP_TOOLS + [
    ...existing tool names...
    "query_advisor_rightsizing_recommendations",  # Phase 39
    "query_vm_cost_7day",                         # Phase 39
    "propose_vm_sku_downsize",                    # Phase 39
]))
```

---

### Task 7: Create API gateway cost endpoint module

**File:** `services/api-gateway/vm_cost.py`
**Action:** create

```python
"""VM cost summary endpoint.

GET /api/v1/vms/cost-summary — returns top-N underutilized VMs by cost with
Azure Advisor rightsizing recommendations for display in the CostTab.

Design notes:
- Queries Azure Advisor for all Cost category recommendations in all in-scope subscriptions
- Returns the top-N VMs sorted by highest estimated monthly savings opportunity
- 24-48h data lag for Cost Management data is documented in response
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential

# Lazy import — may not be available in all environments
try:
    from azure.mgmt.advisor import AdvisorManagementClient
except ImportError:
    AdvisorManagementClient = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vms", tags=["vm-cost"])


@router.get("/cost-summary")
async def get_vm_cost_summary(
    subscription_id: str = Query(..., description="Azure subscription ID to query"),
    top: int = Query(10, ge=1, le=50, description="Maximum number of VMs to return"),
    _token: str = Depends(verify_token),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return top-N underutilized VMs by estimated savings from Azure Advisor.

    Queries Azure Advisor Cost recommendations for the subscription and returns
    the VMs with the highest rightsizing savings opportunity, sorted descending
    by estimated monthly savings.

    Returns:
        {
          "subscription_id": str,
          "total_recommendations": int,
          "vms": [{
            "vm_name": str,
            "resource_group": str,
            "resource_id": str,
            "current_sku": str,          # from extended_properties if available
            "target_sku": str,
            "estimated_monthly_savings": float,
            "annual_savings": float,
            "savings_currency": str,
            "impact": str,               # "High" | "Medium" | "Low"
            "description": str,
            "last_updated": str,
          }],
          "data_lag_note": str
        }
    """
    if AdvisorManagementClient is None:
        return {
            "error": "azure-mgmt-advisor not installed",
            "vms": [],
            "total_recommendations": 0,
        }

    try:
        client = AdvisorManagementClient(credential, subscription_id)

        vms: List[Dict[str, Any]] = []
        for rec in client.recommendations.list():
            if rec.category != "Cost":
                continue
            if not rec.impacted_field or "virtualmachines" not in rec.impacted_field.lower():
                continue

            ext = rec.extended_properties or {}
            resource_id = ""
            resource_group = ""
            if rec.resource_metadata and rec.resource_metadata.resource_id:
                resource_id = rec.resource_metadata.resource_id
                # Extract resource group from ARM resource ID
                parts = resource_id.split("/")
                try:
                    rg_idx = [p.lower() for p in parts].index("resourcegroups")
                    resource_group = parts[rg_idx + 1]
                except (ValueError, IndexError):
                    pass

            vms.append({
                "vm_name": rec.impacted_value or "",
                "resource_group": resource_group,
                "resource_id": resource_id,
                "current_sku": ext.get("currentSku", ext.get("currentSkuName", "")),
                "target_sku": ext.get("recommendedSkuName", ""),
                "estimated_monthly_savings": float(ext.get("savingsAmount", 0) or 0),
                "annual_savings": float(ext.get("annualSavingsAmount", 0) or 0),
                "savings_currency": ext.get("savingsCurrency", "USD"),
                "impact": rec.impact or "Medium",
                "description": (rec.short_description.solution if rec.short_description else ""),
                "last_updated": rec.last_updated.isoformat() if rec.last_updated else "",
            })

        # Sort by highest monthly savings, take top-N
        vms.sort(key=lambda v: v["estimated_monthly_savings"], reverse=True)
        vms = vms[:top]

        return {
            "subscription_id": subscription_id,
            "total_recommendations": len(vms),
            "vms": vms,
            "data_lag_note": "Advisor recommendations are refreshed every 24 hours.",
        }

    except Exception as exc:
        logger.warning("get_vm_cost_summary error: %s", exc)
        return {
            "error": str(exc),
            "vms": [],
            "total_recommendations": 0,
            "subscription_id": subscription_id,
        }
```

---

### Task 8: Register vm_cost router in main.py

**File:** `services/api-gateway/main.py`
**Action:** modify — 2 changes

**Change 1 — Import block** (after line 119, where `eol_router` is imported):
```python
from services.api_gateway.vm_cost import router as vm_cost_router
```

**Change 2 — `include_router` calls** (after `app.include_router(eol_router)` at line 487):
```python
app.include_router(vm_cost_router)
```

Also add `azure-mgmt-advisor>=9.0.0` to the API gateway requirements if it's not already there.

**File:** `services/api-gateway/requirements.txt` (or wherever gateway packages are listed)
**Action:** verify/modify — check if `azure-mgmt-advisor` is present; if not, add it.

---

### Task 9: Create CostTab component

**File:** `services/web-ui/components/CostTab.tsx`
**Action:** create

```tsx
'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { TrendingDown, RefreshCw, DollarSign } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CostVM {
  vm_name: string;
  resource_group: string;
  resource_id: string;
  current_sku: string;
  target_sku: string;
  estimated_monthly_savings: number;
  annual_savings: number;
  savings_currency: string;
  impact: 'High' | 'Medium' | 'Low';
  description: string;
  last_updated: string;
}

interface CostSummaryResponse {
  subscription_id: string;
  total_recommendations: number;
  vms: CostVM[];
  data_lag_note?: string;
  error?: string;
}

interface CostTabProps {
  subscriptions: string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function impactBadgeStyle(impact: string): React.CSSProperties {
  switch (impact) {
    case 'High':
      return { background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)', color: 'var(--accent-red)' };
    case 'Medium':
      return { background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)', color: 'var(--accent-orange)' };
    default:
      return { background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)', color: 'var(--accent-blue)' };
  }
}

function formatCurrency(amount: number, currency: string): string {
  return `${currency} ${amount.toFixed(2)}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CostTab({ subscriptions }: CostTabProps) {
  const [vms, setVMs] = useState<CostVM[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dataLagNote, setDataLagNote] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchCostData = useCallback(async () => {
    if (subscriptions.length === 0) {
      setVMs([]);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Fetch for first selected subscription (expand to multi-sub in future)
      const subscriptionId = subscriptions[0];
      const res = await fetch(
        `/api/proxy/vms/cost-summary?subscription_id=${encodeURIComponent(subscriptionId)}&top=10`,
        { signal: AbortSignal.timeout(15000) }
      );

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error ?? `HTTP ${res.status}`);
      }

      const data: CostSummaryResponse = await res.json();
      if (data.error) {
        throw new Error(data.error);
      }

      setVMs(data.vms ?? []);
      setDataLagNote(data.data_lag_note ?? null);
      setLastRefresh(new Date());
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(`Failed to load cost data: ${message}`);
      setVMs([]);
    } finally {
      setLoading(false);
    }
  }, [subscriptions]);

  useEffect(() => {
    fetchCostData();
  }, [fetchCostData]);

  // ---------------------------------------------------------------------------
  // Render states
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="p-6 space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (subscriptions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3" style={{ color: 'var(--text-secondary)' }}>
        <TrendingDown className="h-10 w-10 opacity-30" />
        <p className="text-sm">Select a subscription to view cost recommendations.</p>
      </div>
    );
  }

  if (vms.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3" style={{ color: 'var(--text-secondary)' }}>
        <DollarSign className="h-10 w-10 opacity-30" />
        <p className="text-sm">No rightsizing recommendations found.</p>
        <p className="text-xs opacity-60">Azure Advisor refreshes recommendations every 24 hours.</p>
      </div>
    );
  }

  // Calculate total potential savings
  const totalMonthlySavings = vms.reduce((sum, vm) => sum + vm.estimated_monthly_savings, 0);
  const currency = vms[0]?.savings_currency ?? 'USD';

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2">
          <TrendingDown className="h-4 w-4" style={{ color: 'var(--accent-blue)' }} />
          <span className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
            Top Rightsizing Opportunities
          </span>
          <Badge variant="outline" className="text-[11px]">
            {vms.length} VMs
          </Badge>
          <span
            className="text-[12px] px-2 py-0.5 rounded"
            style={{
              background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
              color: 'var(--accent-green)',
              fontWeight: 600,
            }}
          >
            {formatCurrency(totalMonthlySavings, currency)}/mo potential
          </span>
        </div>
        <div className="flex items-center gap-2">
          {lastRefresh && (
            <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
              Last updated: {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={fetchCostData}
            disabled={loading}
            className="h-7 px-2 gap-1 text-[12px]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Data lag note */}
      {dataLagNote && (
        <div
          className="px-4 py-2 text-[11px]"
          style={{ color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' }}
        >
          ⏱ {dataLagNote}
        </div>
      )}

      {/* Table */}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-[12px]">VM Name</TableHead>
            <TableHead className="text-[12px]">Resource Group</TableHead>
            <TableHead className="text-[12px]">Current SKU</TableHead>
            <TableHead className="text-[12px]">Recommended SKU</TableHead>
            <TableHead className="text-[12px]">Monthly Savings</TableHead>
            <TableHead className="text-[12px]">Impact</TableHead>
            <TableHead className="text-[12px]">Description</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {vms.map((vm) => (
            <TableRow key={vm.resource_id || vm.vm_name}>
              <TableCell className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
                {vm.vm_name || '—'}
              </TableCell>
              <TableCell className="text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                {vm.resource_group || '—'}
              </TableCell>
              <TableCell className="text-[12px] font-mono" style={{ color: 'var(--text-secondary)' }}>
                {vm.current_sku || '—'}
              </TableCell>
              <TableCell className="text-[12px] font-mono" style={{ color: 'var(--accent-blue)' }}>
                {vm.target_sku || '—'}
              </TableCell>
              <TableCell className="text-[12px] font-semibold" style={{ color: 'var(--accent-green)' }}>
                {vm.estimated_monthly_savings > 0
                  ? formatCurrency(vm.estimated_monthly_savings, vm.savings_currency)
                  : '—'}
              </TableCell>
              <TableCell>
                <span
                  className="text-[11px] px-2 py-0.5 rounded font-medium"
                  style={impactBadgeStyle(vm.impact)}
                >
                  {vm.impact}
                </span>
              </TableCell>
              <TableCell
                className="text-[12px] max-w-[250px] truncate"
                style={{ color: 'var(--text-secondary)' }}
                title={vm.description}
              >
                {vm.description || '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
```

---

### Task 10: Create proxy route for cost-summary

**File:** `services/web-ui/app/api/proxy/vms/cost-summary/route.ts`
**Action:** create

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/vms/cost-summary' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/vms/cost-summary
 *
 * Proxies VM cost summary requests to the API gateway.
 * Query params forwarded as-is (subscription_id, top).
 *
 * Returns top-N underutilized VMs with Azure Advisor rightsizing
 * recommendations sorted by estimated monthly savings.
 *
 * On failure returns empty vms array gracefully.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();
    log.info('proxy request', { method: 'GET', query });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/vms/cost-summary${query ? `?${query}` : ''}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}`, vms: [], total_recommendations: 0 },
        { status: res.status }
      );
    }

    log.debug('proxy response', { vm_count: data?.total_recommendations ?? 0 });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, vms: [], total_recommendations: 0 },
      { status: 502 }
    );
  }
}
```

---

### Task 11: Wire CostTab into DashboardPanel.tsx

**File:** `services/web-ui/components/DashboardPanel.tsx`
**Action:** modify — 4 changes

**Change 1 — Add import for TrendingDown icon** (modify existing lucide-react import line):
```tsx
import { Bell, ClipboardList, Network, Server, Activity, ShieldCheck, Monitor, TrendingDown } from 'lucide-react'
```

**Change 2 — Add CostTab import** (after the VMDetailPanel import):
```tsx
import { CostTab } from './CostTab'
```

**Change 3 — Add 'cost' to TabId union type**:
```tsx
type TabId = 'alerts' | 'audit' | 'topology' | 'resources' | 'vms' | 'cost' | 'observability' | 'patch'
```

**Change 4 — Add cost entry to TABS array** (insert after 'vms', before 'observability'):
```tsx
const TABS: { id: TabId; label: string; Icon: React.FC<{ className?: string }> }[] = [
  { id: 'alerts',        label: 'Alerts',        Icon: Bell },
  { id: 'audit',         label: 'Audit',         Icon: ClipboardList },
  { id: 'topology',      label: 'Topology',      Icon: Network },
  { id: 'resources',     label: 'Resources',     Icon: Server },
  { id: 'vms',           label: 'VMs',           Icon: Monitor },
  { id: 'cost',          label: 'Cost',          Icon: TrendingDown },   // Phase 39
  { id: 'observability', label: 'Observability', Icon: Activity },
  { id: 'patch',         label: 'Patch',         Icon: ShieldCheck },
]
```

**Change 5 — Add cost tab panel div** (insert after the `tabpanel-vms` div, before `tabpanel-observability`):
```tsx
<div id="tabpanel-cost" role="tabpanel" aria-labelledby="tab-cost" hidden={activeTab !== 'cost'}>
  <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
    <CostTab subscriptions={selectedSubscriptions} />
  </div>
</div>
```

---

### Task 12: Create SOP — vm-low-cpu-rightsizing.md

**File:** `sops/compute/vm-low-cpu-rightsizing.md`
**Action:** create

```markdown
---
title: "Azure VM — Rightsizing via Low CPU Utilization (<5%)"
version: "1.0"
domain: compute
scenario_tags:
  - cost
  - rightsizing
  - low-cpu
  - advisor
  - vm-sku
severity_threshold: P4
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where sustained CPU utilization is below 5% over a
7-day window, indicating the VM is oversized for its workload. Azure Advisor
has flagged the VM with a Cost recommendation suggesting a smaller SKU to
reduce monthly spend.

## Pre-conditions
- Resource type is Microsoft.Compute/virtualMachines
- Average CPU utilization < 5% over the past 7 days (confirmed via query_monitor_metrics)
- Azure Advisor has an active Cost recommendation with a specific target_sku
- VM is NOT tagged as 'protected'

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_advisor_rightsizing_recommendations` for the VM.
   - *Expected signal:* One or more Cost recommendations with a target_sku and estimated monthly savings.
   - *Abnormal signal:* No recommendations → VM not yet assessed by Advisor; wait 24h and retry.
   - *Key output:* `target_sku`, `estimated_monthly_savings`, `savings_currency`

2. **[DIAGNOSTIC]** Call `query_vm_cost_7day` to confirm actual spend.
   - *Expected signal:* Consistent daily cost matching the SKU's list price.
   - *Abnormal signal:* Zero cost → VM may already be deallocated; no action needed.
   - *Key output:* `total_cost_7d`, `currency`, `daily_costs`

3. **[DIAGNOSTIC]** Call `query_monitor_metrics` for CPU utilization (last 7 days, 1-hour granularity).
   - *Expected signal:* P95 CPU < 5%, confirming the VM is idle/underutilized.
   - *Abnormal signal:* CPU spikes > 20% at any point → do NOT downsize; workload is bursty.

4. **[DIAGNOSTIC]** Call `query_activity_log` (48h look-back) to confirm no recent deployments
   that might explain temporary low utilization.
   - *Expected signal:* No activity in the past 48 hours.
   - *Abnormal signal:* Recent deployment → wait for workload stabilisation before downsizing.

5. **[NOTIFY]** Alert operator of rightsizing opportunity:
   > "VM '{vm_name}' has averaged <5% CPU over 7 days. Azure Advisor recommends
   >  downsizing to {target_sku} with estimated savings of {savings}/month.
   >  Awaiting approval to proceed."
   - *Channels:* teams
   - *Severity:* informational

6. **[DECISION]** Evaluate whether to propose downsize:
   - Proceed if: Advisor recommendation exists + CPU < 5% confirmed + no recent deployments
     + estimated savings > $20/month
   - Defer if: Bursty workload pattern detected (CPU spikes) or recent deployment activity
   - Skip if: VM is tagged 'protected' or in a change-freeze window

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** Propose VM SKU downsize via `propose_vm_sku_downsize`.
   - Use `target_sku` from Advisor recommendation (Step 1)
   - Set `justification`: "CPU utilization <5% for 7 days. Advisor recommends {target_sku}
     with ${savings}/month savings."
   - *Reversibility:* reversible (resize back to original SKU via propose_vm_resize)
   - *Estimated impact:* ~5-10 min downtime (deallocate/resize/start)
   - *Approval message:* "Approve downsizing {vm_name} from {current_sku} to {target_sku}?
     Estimated savings: {savings_currency} {savings}/month."

## Escalation
- If VM is tagged 'protected': do not propose remediation; log and close as informational
- If CPU has any spikes > 20%: escalate for workload pattern review before downsizing
- If Advisor shows no recommendations after 48h: escalate to FinOps team for manual review

## Rollback
- Resize back to original SKU via `propose_vm_resize` with the original SKU
- Original SKU is preserved in the ApprovalRecord `resource_snapshot` field

## References
- Azure Advisor rightsizing recommendations: https://learn.microsoft.com/en-us/azure/advisor/advisor-cost-recommendations
- Azure VM sizes: https://learn.microsoft.com/en-us/azure/virtual-machines/sizes
- Related SOPs: vm-high-cpu.md, sre-cost-optimisation.md
```

---

### Task 13: Write unit tests

**File:** `agents/tests/compute/test_compute_cost.py`
**Action:** create

Follow the exact pattern from `agents/tests/compute/test_compute_performance.py`:
- `_instrument_mock()` helper at the top
- One class per tool
- 5 tests per tool = 15 tests total
- `@patch("agents.compute.tools.instrument_tool_call")`
- `@patch("agents.compute.tools.get_agent_identity", return_value="id-test")`
- `@patch("agents.compute.tools.XxxClient")` for the relevant client
- `@patch("agents.compute.tools.get_credential")`

```python
"""Tests for Phase 39 VM cost intelligence tool functions.

Covers: query_advisor_rightsizing_recommendations, query_vm_cost_7day,
        propose_vm_sku_downsize.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _instrument_mock():
    """Return a context-manager-compatible MagicMock."""
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


# ---------------------------------------------------------------------------
# TestQueryAdvisorRightsizingRecommendations
# ---------------------------------------------------------------------------


class TestQueryAdvisorRightsizingRecommendations:
    _VM_NAME = "vm-prod-01"
    _SUB_ID = "sub-test-1"
    _RG = "rg-prod"

    def _make_rec(self, category="Cost", impacted_field="Microsoft.Compute/virtualMachines",
                  impacted_value="vm-prod-01", resource_id=None, ext=None):
        """Build a mock Advisor recommendation."""
        rec = MagicMock()
        rec.category = category
        rec.impacted_field = impacted_field
        rec.impacted_value = impacted_value
        rec.impact = "High"
        rec.short_description = MagicMock()
        rec.short_description.solution = "Downsize to Standard_B2s"
        rec.last_updated = None
        rec.id = "rec-id-1"
        rec.resource_metadata = MagicMock()
        rec.resource_metadata.resource_id = resource_id or (
            f"/subscriptions/{self._SUB_ID}/resourceGroups/{self._RG}"
            f"/providers/Microsoft.Compute/virtualMachines/{self._VM_NAME}"
        )
        rec.extended_properties = ext or {
            "recommendedSkuName": "Standard_B2s",
            "savingsAmount": "45.50",
            "annualSavingsAmount": "546.00",
            "savingsCurrency": "USD",
        }
        return rec

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.AdvisorManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_success_with_cost_recommendations(
        self, mock_cred, mock_advisor_cls, mock_identity, mock_instr,
    ):
        """Returns recommendation list when Advisor has Cost recs for the VM."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_advisor_cls.return_value = mock_client
        mock_client.recommendations.list.return_value = [self._make_rec()]

        from agents.compute.tools import query_advisor_rightsizing_recommendations

        result = query_advisor_rightsizing_recommendations(
            vm_name=self._VM_NAME,
            subscription_id=self._SUB_ID,
            resource_group=self._RG,
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["recommendation_count"] == 1
        assert result["recommendations"][0]["target_sku"] == "Standard_B2s"
        assert result["recommendations"][0]["estimated_monthly_savings"] == 45.50
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.AdvisorManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_success_no_recommendations(
        self, mock_cred, mock_advisor_cls, mock_identity, mock_instr,
    ):
        """Returns empty list when no Cost recommendations exist for the VM."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_advisor_cls.return_value = mock_client
        mock_client.recommendations.list.return_value = []

        from agents.compute.tools import query_advisor_rightsizing_recommendations

        result = query_advisor_rightsizing_recommendations(
            vm_name=self._VM_NAME,
            subscription_id=self._SUB_ID,
            resource_group=self._RG,
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["recommendation_count"] == 0
        assert result["recommendations"] == []

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.AdvisorManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_filters_non_cost_and_non_vm_recommendations(
        self, mock_cred, mock_advisor_cls, mock_identity, mock_instr,
    ):
        """Filters out non-Cost and non-VM recommendations."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_advisor_cls.return_value = mock_client
        # One HA rec (wrong category), one storage rec (wrong type), one valid cost/VM rec
        mock_client.recommendations.list.return_value = [
            self._make_rec(category="HighAvailability"),
            self._make_rec(impacted_field="Microsoft.Storage/storageAccounts"),
            self._make_rec(),  # valid
        ]

        from agents.compute.tools import query_advisor_rightsizing_recommendations

        result = query_advisor_rightsizing_recommendations(
            vm_name=self._VM_NAME,
            subscription_id=self._SUB_ID,
            resource_group=self._RG,
            thread_id="thread-1",
        )

        assert result["recommendation_count"] == 1
        assert result["recommendations"][0]["target_sku"] == "Standard_B2s"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.AdvisorManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_sdk_raises_exception_returns_error_dict(
        self, mock_cred, mock_advisor_cls, mock_identity, mock_instr,
    ):
        """SDK error returns error dict without re-raising."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_advisor_cls.return_value = mock_client
        mock_client.recommendations.list.side_effect = Exception("Advisor API error")

        from agents.compute.tools import query_advisor_rightsizing_recommendations

        result = query_advisor_rightsizing_recommendations(
            vm_name=self._VM_NAME,
            subscription_id=self._SUB_ID,
            resource_group=self._RG,
            thread_id="thread-1",
        )

        assert "error" in result
        assert "Advisor API error" in result["error"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.get_credential")
    def test_sdk_unavailable_returns_error_dict(
        self, mock_cred, mock_identity, mock_instr,
    ):
        """When AdvisorManagementClient is None (not installed), returns error dict."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute import tools as tools_mod
        original = tools_mod.AdvisorManagementClient
        tools_mod.AdvisorManagementClient = None

        try:
            from agents.compute.tools import query_advisor_rightsizing_recommendations

            result = query_advisor_rightsizing_recommendations(
                vm_name=self._VM_NAME,
                subscription_id=self._SUB_ID,
                resource_group=self._RG,
                thread_id="thread-1",
            )

            assert "error" in result
            assert "not installed" in result["error"]
        finally:
            tools_mod.AdvisorManagementClient = original


# ---------------------------------------------------------------------------
# TestQueryVmCost7day
# ---------------------------------------------------------------------------


class TestQueryVmCost7day:
    _RESOURCE_ID = (
        "/subscriptions/sub-1/resourceGroups/rg1"
        "/providers/Microsoft.Compute/virtualMachines/vm-prod-01"
    )
    _SUB_ID = "sub-1"

    def _make_cost_result(self, rows=None, columns=None):
        """Build a mock Cost Management query result."""
        result = MagicMock()
        result.columns = [
            MagicMock(name="Cost"),
            MagicMock(name="UsageDate"),
            MagicMock(name="Currency"),
        ]
        result.rows = rows or [
            [12.50, "20260404", "USD"],
            [11.80, "20260405", "USD"],
            [13.20, "20260406", "USD"],
        ]
        return result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.CostManagementClient")
    @patch("agents.compute.tools.QueryDefinition")
    @patch("agents.compute.tools.get_credential")
    def test_success_returns_daily_costs(
        self, mock_cred, mock_qd, mock_cost_cls, mock_identity, mock_instr,
    ):
        """Returns daily cost breakdown and total."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_cost_cls.return_value = mock_client
        mock_client.query.usage.return_value = self._make_cost_result()

        from agents.compute.tools import query_vm_cost_7day

        result = query_vm_cost_7day(
            resource_id=self._RESOURCE_ID,
            subscription_id=self._SUB_ID,
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["total_cost_7d"] == pytest.approx(37.50)
        assert len(result["daily_costs"]) == 3
        assert result["currency"] == "USD"
        assert "data_lag_note" in result
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.CostManagementClient")
    @patch("agents.compute.tools.QueryDefinition")
    @patch("agents.compute.tools.get_credential")
    def test_success_no_rows_returns_zero_cost(
        self, mock_cred, mock_qd, mock_cost_cls, mock_identity, mock_instr,
    ):
        """Returns zero cost and empty daily_costs when no rows returned."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_cost_cls.return_value = mock_client
        mock_client.query.usage.return_value = self._make_cost_result(rows=[])

        from agents.compute.tools import query_vm_cost_7day

        result = query_vm_cost_7day(
            resource_id=self._RESOURCE_ID,
            subscription_id=self._SUB_ID,
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["total_cost_7d"] == 0.0
        assert result["daily_costs"] == []

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.CostManagementClient")
    @patch("agents.compute.tools.QueryDefinition")
    @patch("agents.compute.tools.get_credential")
    def test_sdk_raises_exception_returns_error_dict(
        self, mock_cred, mock_qd, mock_cost_cls, mock_identity, mock_instr,
    ):
        """SDK error returns error dict without re-raising."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_cost_cls.return_value = mock_client
        mock_client.query.usage.side_effect = Exception("Cost Management 403 Forbidden")

        from agents.compute.tools import query_vm_cost_7day

        result = query_vm_cost_7day(
            resource_id=self._RESOURCE_ID,
            subscription_id=self._SUB_ID,
            thread_id="thread-1",
        )

        assert "error" in result
        assert "403 Forbidden" in result["error"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.get_credential")
    def test_sdk_unavailable_returns_error_dict(
        self, mock_cred, mock_identity, mock_instr,
    ):
        """When CostManagementClient is None, returns error dict."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute import tools as tools_mod
        original = tools_mod.CostManagementClient
        tools_mod.CostManagementClient = None

        try:
            from agents.compute.tools import query_vm_cost_7day

            result = query_vm_cost_7day(
                resource_id=self._RESOURCE_ID,
                subscription_id=self._SUB_ID,
                thread_id="thread-1",
            )

            assert "error" in result
            assert "not installed" in result["error"]
        finally:
            tools_mod.CostManagementClient = original

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.CostManagementClient")
    @patch("agents.compute.tools.QueryDefinition")
    @patch("agents.compute.tools.get_credential")
    def test_daily_costs_sorted_ascending_by_date(
        self, mock_cred, mock_qd, mock_cost_cls, mock_identity, mock_instr,
    ):
        """Daily costs are sorted ascending by date regardless of API response order."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_cost_cls.return_value = mock_client
        # Deliberately out of order
        mock_client.query.usage.return_value = self._make_cost_result(rows=[
            [5.0, "20260407", "USD"],
            [3.0, "20260405", "USD"],
            [4.0, "20260406", "USD"],
        ])

        from agents.compute.tools import query_vm_cost_7day

        result = query_vm_cost_7day(
            resource_id=self._RESOURCE_ID,
            subscription_id=self._SUB_ID,
            thread_id="thread-1",
        )

        dates = [d["date"] for d in result["daily_costs"]]
        assert dates == sorted(dates), "daily_costs should be sorted ascending by date"


# ---------------------------------------------------------------------------
# TestProposeVmSkuDownsize
# ---------------------------------------------------------------------------


class TestProposeVmSkuDownsize:
    _RESOURCE_ID = (
        "/subscriptions/sub-1/resourceGroups/rg1"
        "/providers/Microsoft.Compute/virtualMachines/vm-prod-01"
    )

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record")
    def test_success_returns_pending_approval(
        self, mock_approval, mock_identity, mock_instr,
    ):
        """Returns pending_approval status with approval_id."""
        mock_instr.return_value = _instrument_mock()
        mock_approval.return_value = {"id": "approval-uuid-123"}

        from agents.compute.tools import propose_vm_sku_downsize

        result = propose_vm_sku_downsize(
            resource_id=self._RESOURCE_ID,
            resource_group="rg1",
            vm_name="vm-prod-01",
            subscription_id="sub-1",
            target_sku="Standard_B2s",
            justification="CPU <5% for 7 days; Advisor recommends Standard_B2s",
            thread_id="thread-1",
        )

        assert result["status"] == "pending_approval"
        assert result["approval_id"] == "approval-uuid-123"
        assert "vm-prod-01" in result["message"]
        assert "Standard_B2s" in result["message"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record")
    def test_approval_record_uses_medium_risk(
        self, mock_approval, mock_identity, mock_instr,
    ):
        """Approval record uses risk_level='medium' (not 'high')."""
        mock_instr.return_value = _instrument_mock()
        mock_approval.return_value = {"id": "approval-456"}

        from agents.compute.tools import propose_vm_sku_downsize

        propose_vm_sku_downsize(
            resource_id=self._RESOURCE_ID,
            resource_group="rg1",
            vm_name="vm-prod-01",
            subscription_id="sub-1",
            target_sku="Standard_B2s",
            justification="test",
            thread_id="thread-1",
        )

        call_kwargs = mock_approval.call_args[1]
        assert call_kwargs["risk_level"] == "medium"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record")
    def test_approval_record_uses_empty_incident_id(
        self, mock_approval, mock_identity, mock_instr,
    ):
        """Approval record uses incident_id='' (cost proposal has no incident context)."""
        mock_instr.return_value = _instrument_mock()
        mock_approval.return_value = {"id": "approval-789"}

        from agents.compute.tools import propose_vm_sku_downsize

        propose_vm_sku_downsize(
            resource_id=self._RESOURCE_ID,
            resource_group="rg1",
            vm_name="vm-prod-01",
            subscription_id="sub-1",
            target_sku="Standard_B2s",
            justification="test",
            thread_id="thread-1",
        )

        call_kwargs = mock_approval.call_args[1]
        assert call_kwargs["incident_id"] == ""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record")
    def test_approval_record_raises_returns_error_dict(
        self, mock_approval, mock_identity, mock_instr,
    ):
        """If create_approval_record raises, returns error dict without re-raising."""
        mock_instr.return_value = _instrument_mock()
        mock_approval.side_effect = Exception("Cosmos DB unavailable")

        from agents.compute.tools import propose_vm_sku_downsize

        result = propose_vm_sku_downsize(
            resource_id=self._RESOURCE_ID,
            resource_group="rg1",
            vm_name="vm-prod-01",
            subscription_id="sub-1",
            target_sku="Standard_B2s",
            justification="test",
            thread_id="thread-1",
        )

        assert result["status"] == "error"
        assert "Cosmos DB unavailable" in result["message"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record")
    def test_proposal_never_makes_arm_calls(
        self, mock_approval, mock_identity, mock_instr,
    ):
        """No Azure SDK clients are instantiated — only create_approval_record is called."""
        mock_instr.return_value = _instrument_mock()
        mock_approval.return_value = {"id": "approval-abc"}

        from agents.compute.tools import propose_vm_sku_downsize

        # With no ComputeManagementClient or AdvisorManagementClient mock patches,
        # the test passes only if the tool never calls them.
        with patch("agents.compute.tools.ComputeManagementClient") as mock_compute:
            with patch("agents.compute.tools.AdvisorManagementClient") as mock_advisor:
                propose_vm_sku_downsize(
                    resource_id=self._RESOURCE_ID,
                    resource_group="rg1",
                    vm_name="vm-prod-01",
                    subscription_id="sub-1",
                    target_sku="Standard_B2s",
                    justification="test",
                    thread_id="thread-1",
                )
                mock_compute.assert_not_called()
                mock_advisor.assert_not_called()
```

---

### Task 14: Update agent registration test for new tool count

**File:** `agents/tests/compute/test_compute_agent_registration.py`
**Action:** modify

1. Add the 3 new tool names to `_TOOL_NAMES` list:
```python
_TOOL_NAMES = [
    ...existing 20 names...
    "execute_run_command",
    "parse_boot_diagnostics_serial_log",
    "query_vm_guest_health",
    "query_ama_guest_metrics",
    "get_vm_forecast",
    "query_vm_performance_baseline",
    "detect_performance_drift",
    "query_advisor_rightsizing_recommendations",  # Phase 39
    "query_vm_cost_7day",                         # Phase 39
    "propose_vm_sku_downsize",                    # Phase 39
]
```

2. Update the count assertion from 27 → 30:
```python
def test_exactly_27_tools_registered(self):
    # UPDATE: was 27 before Phase 39; now 30
    _, registered = _load_compute_tools_and_agent()
    assert len(registered) == 30, f"Expected 30 tools, got {len(registered)}"
```
(Also rename the test method to `test_exactly_30_tools_registered` to reflect the new count.)

---

### Task 15: Add Terraform Cost Management Reader RBAC

**File:** `terraform/modules/rbac/main.tf`
**Action:** modify — add new block inside the `role_assignments = merge(...)` call

Add a new entry for the Compute Agent's Cost Management Reader role. Insert it after the existing compute agent block (after the `"compute-monreader-compute"` entry, still within the same object braces for the Compute Agent):

```hcl
# Compute Agent: Cost Management Reader on compute sub + platform sub
# Required for query_vm_cost_7day tool (Phase 39)
{
  "compute-costmgmtreader-compute" = {
    principal_id         = var.agent_principal_ids["compute"]
    role_definition_name = "Cost Management Reader"
    scope                = "/subscriptions/${local.compute_sub}"
  }
  "compute-costmgmtreader-platform" = {
    principal_id         = var.agent_principal_ids["compute"]
    role_definition_name = "Cost Management Reader"
    scope                = "/subscriptions/${var.platform_subscription_id}"
  }
},
```

Insert this block after the existing compute agent block:
```hcl
# BEFORE (existing):
{
  "compute-vmcontributor-compute" = { ... }
  "compute-monreader-platform" = { ... }
  "compute-monreader-compute" = { ... }
},

# AFTER (add new block):
{
  "compute-costmgmtreader-compute" = {
    principal_id         = var.agent_principal_ids["compute"]
    role_definition_name = "Cost Management Reader"
    scope                = "/subscriptions/${local.compute_sub}"
  }
  "compute-costmgmtreader-platform" = {
    principal_id         = var.agent_principal_ids["compute"]
    role_definition_name = "Cost Management Reader"
    scope                = "/subscriptions/${var.platform_subscription_id}"
  }
},
```

---

### Task 16: Verify API gateway requirements include advisor package

**File:** `services/api-gateway/requirements.txt`
**Action:** check and modify if needed

Search for `azure-mgmt-advisor` in `services/api-gateway/requirements.txt`. If not present, add:
```
azure-mgmt-advisor>=9.0.0
```

The `vm_cost.py` gateway module uses `AdvisorManagementClient` which requires this package in the gateway container image.

---

## Verification

- [ ] `cd agents && python -m pytest tests/compute/test_compute_cost.py -v` — all 15 tests pass
- [ ] `cd agents && python -m pytest tests/compute/test_compute_agent_registration.py -v` — updated count test passes (30 tools)
- [ ] `cd agents && python -m pytest tests/compute/ -v --tb=short` — no regressions in existing test suite
- [ ] `cd services/web-ui && npx tsc --noEmit` — exits 0 (CostTab typechecks clean)
- [ ] `cd services/web-ui && npm run build` — exits 0 (no build errors)
- [ ] `terraform fmt -check terraform/modules/rbac/main.tf` — passes
- [ ] Import check: `python -c "from agents.compute.tools import query_advisor_rightsizing_recommendations, query_vm_cost_7day, propose_vm_sku_downsize; print('OK')"` from repo root
- [ ] Import check: `python -c "from agents.compute.agent import create_compute_agent; print('OK')"` with mocked azure deps
- [ ] `sops/compute/vm-low-cpu-rightsizing.md` exists and follows the SOP schema
- [ ] `services/web-ui/app/api/proxy/vms/cost-summary/route.ts` exists
- [ ] `services/api-gateway/vm_cost.py` exists and `GET /api/v1/vms/cost-summary` route is wired in `main.py`
- [ ] `DashboardPanel.tsx` has 8 tabs in TABS array (added 'cost' between 'vms' and 'observability')
- [ ] `TabId` union includes `'cost'`

## Implementation Order

Execute tasks in this order to minimize integration issues:

1. **Task 1** — lazy imports in tools.py (foundation for Tasks 2-4)
2. **Task 2** — `query_advisor_rightsizing_recommendations`
3. **Task 3** — `query_vm_cost_7day`
4. **Task 4** — `propose_vm_sku_downsize`
5. **Task 5** — requirements.txt (enables local testing)
6. **Task 6** — agent.py registration (4 locations)
7. **Task 13** — unit tests (validate tools work before moving to backend/UI)
8. **Task 14** — update agent registration test count
9. **Task 7** — vm_cost.py gateway module
10. **Task 16** — verify gateway requirements.txt
11. **Task 8** — register vm_cost router in main.py
12. **Task 9** — CostTab.tsx component
13. **Task 10** — proxy route
14. **Task 11** — DashboardPanel.tsx wiring
15. **Task 12** — SOP file
16. **Task 15** — Terraform RBAC

## Risk Mitigations

| Risk | Mitigation |
|---|---|
| `extended_properties` field names vary | All `.get()` calls use safe defaults; raw `extended_properties` dict returned for agent inspection |
| Cost Management 24-48h data lag | Documented in tool docstring, return value `data_lag_note`, and SOP |
| `propose_vm_sku_downsize` with no `incident_id` | Pass `incident_id=""` — verified in test_approval_record_uses_empty_incident_id |
| `CostManagementClient` API auth/scope | `query_vm_cost_7day` catches all exceptions and returns structured error dict |
| Advisor `list()` returns all subscription recs | Filter triple: `category=="Cost"` + `"virtualmachines" in impacted_field.lower()` + vm_name in impacted_value/resource_id |
| DashboardPanel keyboard nav broken | TABS array order preserved; `handleTabKeyDown` uses `TABS.length` dynamically |
| TypeScript type gap for 'cost' tab | `TabId` union extended; `tabpanel-cost` div added with correct aria attributes |
