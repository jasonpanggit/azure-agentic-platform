---
phase: "108-3"
title: "Remediation Engine — One-Click Fix + HITL Approval"
depends_on: ["108-1", "108-2"]
estimated_effort: "L"
wave: 3
files_to_modify:
  - services/api-gateway/network_topology_service.py
  - services/api-gateway/network_topology_endpoints.py
  - services/api-gateway/requirements.txt
  - services/web-ui/components/NetworkTopologyTab.tsx
files_to_create:
  - services/api-gateway/network_remediation.py
  - services/web-ui/app/api/proxy/network/topology/remediate/route.ts
---

# Plan 108-3: Remediation Engine — One-Click Fix + HITL Approval

## Goal

Implement `POST /api/v1/network-topology/remediate` with safe auto-fix for 2 issue types (Firewall ThreatIntel, PE approval) and HITL approval queue integration for all others. Wire the frontend Fix Now / Request Approval buttons, confirmation dialog, and toast feedback.

---

## Task 3.1 — Add `azure-mgmt-network` Dependency + Create `network_remediation.py`

<read_first>
- `services/api-gateway/requirements.txt`
- `services/api-gateway/remediation_executor.py` lines 1-60 (WAL pattern, SAFE_ARM_ACTIONS)
- `services/api-gateway/approvals.py` lines 1-50 (create_approval interface)
</read_first>

<action>
1. Add `azure-mgmt-network>=25.0.0` to `services/api-gateway/requirements.txt`.
2. Create `services/api-gateway/network_remediation.py` with:
   - Module-level SDK import with graceful fallback:
     ```python
     try:
         from azure.mgmt.network import NetworkManagementClient
     except ImportError:
         NetworkManagementClient = None  # type: ignore[assignment,misc]
     ```
   - `SAFE_NETWORK_ACTIONS` dict mapping issue types to their remediation functions:
     ```python
     SAFE_NETWORK_ACTIONS: dict[str, Callable] = {
         "firewall_threatintel_off": _fix_firewall_threatintel,
         "pe_not_approved": _fix_pe_approve,
     }
     ```
   - `async def execute_network_remediation(issue: NetworkIssue, subscription_id: str, credential: Any) -> dict` — main entry point:
     1. Check `issue["type"]` in `SAFE_NETWORK_ACTIONS`
     2. If safe: `start_time = time.monotonic()`, call the fix function, record `duration_ms`, return `{"status": "executed", "execution_id": ..., "message": ...}`
     3. If not safe: return `{"status": "requires_approval"}`
     4. Never raise — return structured error dict on failure
   - `async def _fix_firewall_threatintel(issue, subscription_id, credential)`:
     1. Parse resource group and firewall name from `issue["affected_resource_id"]`
     2. Instantiate `NetworkManagementClient(credential, subscription_id)`
     3. `client.azure_firewalls.get(rg, fw_name)` → read current config
     4. Set `firewall.threat_intel_mode = "Alert"`
     5. `client.azure_firewalls.begin_create_or_update(rg, fw_name, firewall)` → PUT
     6. Return success dict with `execution_id`
   - `async def _fix_pe_approve(issue, subscription_id, credential)`:
     1. Parse PE resource ID components
     2. `client.private_endpoint_connections.update(...)` with `status="Approved"`
     3. Return success dict
3. Follow the `remediation_executor.py` WAL pattern: write a pre-execution audit record, execute, write post-execution record.
</action>

<acceptance_criteria>
- `azure-mgmt-network>=25.0.0` in requirements.txt
- `network_remediation.py` created with `SAFE_NETWORK_ACTIONS` for 2 issue types
- Graceful `ImportError` handling for `NetworkManagementClient`
- Functions never raise — return structured error/success dicts
- `time.monotonic()` used for duration tracking in both try and except paths
- WAL audit records written before and after execution
</acceptance_criteria>

---

## Task 3.2 — Implement `POST /api/v1/network-topology/remediate` Endpoint

<read_first>
- `services/api-gateway/network_topology_endpoints.py` (existing router)
- `services/api-gateway/approvals.py` lines 280-370 (`create_approval` function signature)
- `services/api-gateway/arg_cache.py` lines 80-109 (`invalidate` function)
</read_first>

<action>
1. Define Pydantic models in `network_topology_endpoints.py`:
   ```python
   class RemediateRequest(BaseModel):
       issue_id: str
       subscription_id: Optional[str] = None
       require_approval: bool = False

   class RemediateResponse(BaseModel):
       status: str  # "executed" | "approval_pending" | "error"
       message: str
       approval_id: Optional[str] = None
       execution_id: Optional[str] = None
   ```
2. Add `POST /api/v1/network-topology/remediate` endpoint:
   1. Look up the issue by `issue_id` from the cached topology data (call `fetch_network_topology` or read from cache).
   2. If issue not found: return 404.
   3. If `require_approval` is True OR issue type not in `SAFE_NETWORK_ACTIONS`:
      - Call `create_approval()` from `approvals.py` with:
        - `thread_id="network-topology"`, `incident_id=issue_id`, `agent_name="network-topology"`
        - `proposal={"action": issue["auto_fix_label"] or "Manual remediation", "issue": issue}`
        - `resource_snapshot={"affected_resource_id": issue["affected_resource_id"]}`
        - `risk_level="low"` for safe types, `"high"` for others
      - Return `RemediateResponse(status="approval_pending", approval_id=..., message="Approval requested")`
   4. If safe auto-fix:
      - Call `execute_network_remediation(issue, subscription_id, credential)`
      - On success: invalidate topology cache via `arg_cache.invalidate("network_topology", ...)`
      - Return `RemediateResponse(status="executed", execution_id=..., message="Fix applied")`
   5. On any exception: return `RemediateResponse(status="error", message=str(error))`
</action>

<acceptance_criteria>
- `POST /remediate` endpoint returns 200 with `RemediateResponse` for all paths
- 404 returned for unknown `issue_id`
- Safe issues (C5, B4) execute directly when `require_approval=False`
- All other issues route through `create_approval()`
- Topology cache invalidated after successful execution
- No unhandled exceptions — all errors returned as `status="error"`
</acceptance_criteria>

---

## Task 3.3 — Next.js Proxy Route

<read_first>
- `services/web-ui/app/api/proxy/network/topology/route.ts` (existing topology proxy)
- `services/web-ui/lib/api-gateway.ts` (getApiGatewayUrl, buildUpstreamHeaders)
</read_first>

<action>
Create `services/web-ui/app/api/proxy/network/topology/remediate/route.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server"
import { getApiGatewayUrl, buildUpstreamHeaders } from "@/lib/api-gateway"

export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const body = await request.json()
    const upstream = `${getApiGatewayUrl()}/api/v1/network-topology/remediate`
    const response = await fetch(upstream, {
      method: "POST",
      headers: buildUpstreamHeaders(request),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    })
    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    return NextResponse.json(
      { status: "error", message: error instanceof Error ? error.message : "Unexpected error" },
      { status: 502 },
    )
  }
}
```
</action>

<acceptance_criteria>
- Proxy route follows existing pattern: `getApiGatewayUrl()` + `buildUpstreamHeaders(request)` + `AbortSignal.timeout(15000)`
- POST method only
- Error responses use 502 status with structured error body
- No hardcoded API gateway URL
</acceptance_criteria>

---

## Task 3.4 — Wire Frontend Fix Now / Request Approval Buttons

<read_first>
- `services/web-ui/components/NetworkTopologyTab.tsx` (issue cards from Plan 108-2, Task 2.3)
</read_first>

<action>
1. Remove `disabled` from the Fix Now / Request Approval buttons added in Plan 108-2.
2. Add state: `remediatingIssueId: string | null` (loading state per issue).
3. **Fix Now click handler:**
   1. Set `remediatingIssueId` to issue ID
   2. Show confirmation dialog: "This will {auto_fix_label}. Proceed?" with Cancel/Confirm buttons
   3. On confirm: `POST /api/proxy/network/topology/remediate` with `{ issue_id, subscription_id, require_approval: false }`
   4. On success response (`status: "executed"`):
      - Show success toast: "Fix applied. Refreshing topology..."
      - `setTimeout(() => fetchData(), 3000)` to auto-refresh
   5. On error response: show inline error message on the issue card
   6. Clear `remediatingIssueId`
4. **Request Approval click handler:**
   1. Show confirmation dialog: "This will submit a remediation request for approval. Risk level: {high/low}."
   2. On confirm: `POST /api/proxy/network/topology/remediate` with `{ issue_id, subscription_id, require_approval: true }`
   3. On success (`status: "approval_pending"`): show toast "Approval requested. Check the Approval Queue in Observability tab."
   4. On error: inline error message
5. Use existing toast infrastructure (shadcn/ui `toast` or inline notification pattern used elsewhere in the app).
</action>

<acceptance_criteria>
- Fix Now button triggers confirmation dialog → POST → toast → auto-refresh
- Request Approval button triggers confirmation dialog → POST → toast
- Loading spinner shown on the active issue card during request
- Error displayed inline on the card (not a global error)
- Auto-refresh fires 3 seconds after successful fix
- Only one remediation request at a time (button disabled while `remediatingIssueId` is set)
</acceptance_criteria>

---

## Task 3.5 — Backend Unit Tests for Remediation

<read_first>
- `services/api-gateway/tests/test_network_topology_service.py` (existing test patterns)
- `services/api-gateway/network_remediation.py` (from Task 3.1)
</read_first>

<action>
Add ~10 unit tests in a new `services/api-gateway/tests/test_network_remediation.py`:

1. **`_fix_firewall_threatintel`** — mock `NetworkManagementClient`:
   - Happy path: firewall GET returns current config → PUT called with `threat_intel_mode="Alert"` → success dict returned
   - Error path: SDK raises `HttpResponseError` → structured error dict returned (no raise)
2. **`_fix_pe_approve`** — mock `NetworkManagementClient`:
   - Happy path: connection updated to Approved → success dict
   - Error path: resource not found → error dict
3. **`execute_network_remediation`** routing:
   - Issue type `"firewall_threatintel_off"` → calls `_fix_firewall_threatintel`
   - Issue type `"subnet_no_nsg"` → returns `{"status": "requires_approval"}`
   - Unknown issue type → returns error dict
4. **POST endpoint tests** (via `TestClient`):
   - Valid issue ID, safe type → 200, `status="executed"`
   - Valid issue ID, unsafe type → 200, `status="approval_pending"`
   - Invalid issue ID → 404
   - `require_approval=True` on safe type → still routes to approval
</action>

<acceptance_criteria>
- ≥10 tests covering both remediation functions + endpoint routing
- All SDK calls mocked (no real Azure calls)
- Error paths verified: functions never raise, return structured dicts
- POST endpoint tests use FastAPI TestClient
- All tests pass
</acceptance_criteria>

---

## Task 3.6 — Cache Invalidation + End-to-End Smoke Test

<read_first>
- `services/api-gateway/arg_cache.py` (invalidate function)
</read_first>

<action>
1. Verify that `arg_cache.invalidate("network_topology", subscription_ids)` is called after successful remediation execution in the POST endpoint.
2. Write an end-to-end integration test (mocked Azure SDK, real FastAPI app):
   1. Seed the topology cache with a topology containing a `firewall_threatintel_off` issue
   2. `POST /api/v1/network-topology/remediate` with that issue ID
   3. Assert response `status="executed"`
   4. Assert `arg_cache.invalidate` was called
   5. Assert WAL audit record was written (mock the WAL store and verify call)
3. Write a second integration test for the HITL path:
   1. Seed topology with a `subnet_no_nsg` issue (not auto-fixable)
   2. `POST /remediate` with `require_approval=False`
   3. Assert response `status="approval_pending"` (forced to HITL because not in SAFE_NETWORK_ACTIONS)
   4. Assert `create_approval()` was called with correct parameters
</action>

<acceptance_criteria>
- Cache invalidated after successful auto-fix execution
- WAL audit record written for auto-fix execution
- HITL path correctly invoked for non-safe issue types even when `require_approval=False`
- Both integration tests pass with mocked dependencies
- No real Azure SDK calls in tests
</acceptance_criteria>
