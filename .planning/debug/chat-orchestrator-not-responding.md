# Debug: Chat Orchestrator Not Responding

## Symptoms
- Chat shows "Agent response timed out" or spins indefinitely
- Container app logs: GET /api/v1/chat/{thread}/result returns 200 but run stays `in_progress`
- Sometimes completes on Foundry side but UI doesn't show it
- Auth is currently disabled (API_GATEWAY_AUTH_MODE=disabled)

## Architecture Flow
```
Browser → POST /api/proxy/chat → API Gateway POST /api/v1/chat → Foundry (create thread + run)
Browser → EventSource /api/stream?thread_id=...&run_id=...&type=token
  └→ Server polls GET /api/v1/chat/{thread}/result (directly to API gateway)
     └→ get_chat_result() → Foundry runs.get() → check status
        └→ If requires_action/submit_tool_outputs → handle function tool calls
        └→ If requires_action/submit_tool_approval → auto-approve connected-agent handoff
        └→ If completed → return reply
```

## Investigation Plan

### Phase 1: Direct Foundry Test (no gateway/UI)
- [x] Create a thread + run directly via Python SDK
- [x] Poll the run — does it complete? How long? What statuses does it go through?
- [x] Does it hit requires_action? What type? submit_tool_outputs or submit_tool_approval?

### Phase 2: Check the submit_tool_approval Gap
- [x] The get_chat_result() only handles `submit_tool_outputs`, NOT `submit_tool_approval`
- [x] If orchestrator delegates to connected_agent which uses MCP, the connected_agent's
      sub-run may need submit_tool_approval — but that's internal to Foundry
- [x] The ORCHESTRATOR's run may also hit requires_action with type we don't handle

### Phase 3: Trace the Full Stack
- [x] Test API gateway endpoint directly (curl)
- [x] Test the SSE stream route
- [x] Test in Playwright

### Phase 4: Fix and Deploy
- [x] Implement fix
- [ ] Deploy to Container Apps
- [ ] Verify in browser via Playwright

## Root Cause Analysis (2026-04-01)

### PRIMARY: Missing `submit_tool_approval` handler

When the orchestrator delegates to a connected agent (e.g., compute domain agent),
Foundry puts the **orchestrator's own run** into `requires_action` with type
`submit_tool_approval`. This is distinct from `submit_tool_outputs` (which is for
function tool calls like `classify_incident_domain`).

**Before fix:** `get_chat_result()` (chat.py L372-378) only checked for
`required_action.type == "submit_tool_outputs"`. When the type was
`submit_tool_approval`, no action was taken. The run stayed in `requires_action`
forever. The SSE polling loop saw this as non-terminal and kept polling for 2
minutes, then emitted "Agent response timed out."

**After fix:** Added an `elif action_type == "submit_tool_approval"` branch that
auto-approves the connected-agent handoff via the REST API (using the existing
`_submit_mcp_approval()` helper). If the REST approval fails, it logs a warning
and returns — the next poll cycle will retry.

### SECONDARY: SSE timeout too tight for multi-agent chains

The SSE polling timeout was 2 minutes (`POLL_TIMEOUT_MS = 120_000`). In a
multi-agent chain (orchestrator → domain agent → MCP tool calls), the total
round-trip can exceed 2 minutes if there are approval gates, MCP tool execution,
and LLM reasoning at each step.

**Fix:** Increased to 3 minutes (`POLL_TIMEOUT_MS = 180_000`).

## Files Changed

1. `services/api-gateway/chat.py` — Added `submit_tool_approval` handler in
   `get_chat_result()` alongside the existing `submit_tool_outputs` handler
2. `services/web-ui/app/api/stream/route.ts` — Increased POLL_TIMEOUT_MS from
   120s to 180s
3. `services/api-gateway/tests/test_chat_endpoint.py` — Added 5 tests for the
   new approval handling

## Deployment Checklist

- [ ] Rebuild API gateway container (`docker build -t ca-api-gateway-prod ...`)
- [ ] Push to ACR and update Container App revision
- [ ] Rebuild web-ui container (timeout change)
- [ ] Verify COMPUTE_AGENT_ID env var is set on the API gateway Container App
- [ ] Verify AZURE_PROJECT_ENDPOINT env var is set
- [ ] Smoke test: "Show my virtual machines" in chat UI
