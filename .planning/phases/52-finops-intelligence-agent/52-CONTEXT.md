# Phase 52: FinOps Intelligence Agent - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure/backend phase)

<domain>
## Phase Boundary

Build a dedicated FinOps agent (`ca-finops-prod`) that reasons over Azure Cost Management data to surface wasteful spend, forecast monthly bills, and propose cost-saving actions through the existing HITL workflow. Includes a FinOps tab in the Web UI with cost breakdown charts, waste list, and savings proposals.

Scope:
- New Python agent service: `agents/finops/`
- FinOps-specific tool functions via Azure Cost Management SDK
- Container App: `ca-finops-prod` registered with Foundry
- API gateway route additions
- Frontend FinOps tab in Next.js UI
- Orchestrator routing updates for FinOps intent

Out of scope: multi-tenant cost isolation (Phase 64), RI purchasing flows.

</domain>

<decisions>
## Implementation Decisions

### Agent Architecture
- Follow the established compute/network/SRE agent pattern exactly: `agents/finops/` directory with `main.py`, `tools.py`, `agent.py`
- Use `@ai_function` decorator pattern for all tool functions
- SDK availability guard pattern: `try: from azure.mgmt.costmanagement import CostManagementClient except ImportError: CostManagementClient = None`
- Tool functions never raise — return structured error dicts on failure
- `start_time = time.monotonic()` + `duration_ms` in both try and except blocks

### Cost Management Tools
- `get_subscription_cost_breakdown(subscription_id, days, group_by)` — Cost Management query API: group by ResourceGroup, ResourceType, or Tag
- `get_resource_cost(subscription_id, resource_id, days)` — per-resource amortized spend
- `identify_idle_resources(subscription_id, threshold_cpu_pct, hours)` — cross-references Monitor metrics for CPU <2% + network ~0 for 72h; generates HITL `propose_deallocate` actions
- `get_reserved_instance_utilisation(subscription_id)` — RI/savings plan utilisation from Cost Management Benefits API
- `get_cost_forecast(subscription_id, budget_name)` — Azure native forecast vs budget; burn rate calculation
- `get_top_cost_drivers(subscription_id, n, days)` — ranked list of top N cost drivers by resource type

### HITL Integration
- Idle resource deallocation proposals use existing `RemediationAction` model and `/api/v1/remediation/approve|reject` endpoints
- Proposals include estimated monthly savings in USD
- Severity = LOW for savings proposals (no operational risk)

### Frontend FinOps Tab
- New "FinOps" tab (7th tab) in the dashboard alongside existing Alerts/Audit/Topology/Resources/Observability/Patch tabs
- Cost breakdown: bar chart showing top-10 resource groups by spend (use Recharts — already in project)
- Waste list: table of idle resources with monthly cost + HITL approve/reject buttons
- Savings proposals: card list of AI-suggested savings actions
- Budget gauge: current month spend vs budget with burn rate indicator
- Follow CSS semantic token system: `var(--accent-blue)`, `var(--bg-canvas)`, etc.

### Infrastructure
- Container App `ca-finops-prod`: same pattern as existing agents (internal ingress only)
- Azure Cost Management API requires `Cost Management Reader` role on subscription scope
- Add to Foundry connected agents; update orchestrator routing table

### Claude's Discretion
- Specific chart color palette and layout details
- Exact KQL/API query parameters for idle resource detection thresholds
- Error message copy for missing budget configurations

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agents/compute/tools.py` — canonical tool function pattern with SDK guard + timing
- `agents/sre/tools.py` — cross-domain correlation pattern
- `agents/shared/` — shared utilities, auth, response models
- `services/api-gateway/main.py` — existing agent routing (connected_agents pattern)
- `app/components/ui/` — shadcn/ui components (button, card, badge, table, tabs)
- Recharts already used in VM performance tab (Phase 37)
- `app/(dashboard)/layout.tsx` — tab navigation pattern to extend

### Established Patterns
- Tool function: `start_time = time.monotonic()` → try → except returns error dict
- API gateway: thin router, no business logic, `connected_agent_query` pattern  
- Container App deployment: `terraform/modules/container_apps/agent.tf` module
- HITL: existing `RemediationAction` model in `services/api-gateway/models.py`
- Agent registration: `AzureAIAgentClient` with `project_endpoint` + `DefaultAzureCredential`

### Integration Points
- `services/api-gateway/routers/` — add `finops.py` router
- `agents/finops/` — new directory following compute agent structure
- `app/app/(dashboard)/` — add finops tab route
- `terraform/modules/container_apps/` — add finops agent CA resource
- Orchestrator intent routing: add `finops` and `cost` intent keywords

</code_context>

<specifics>
## Specific Ideas

- The FinOps tab should make cost transparency immediate — show current month total spend prominently at the top
- Idle resource detection should be conservative (72h window, <2% CPU AND <1MB/s network) to avoid false positives
- HITL proposals for cost savings should always show the estimated monthly saving in dollars to make the business case clear
- Budget burn rate alert threshold: flag if projected spend >110% of budget

</specifics>

<deferred>
## Deferred Ideas

- RI purchasing recommendations (requires marketplace integration)
- Multi-tenant cost allocation / chargeback (Phase 64)
- Cost anomaly email digest (could be added later)
- Tag governance enforcement (separate phase concern)

</deferred>
