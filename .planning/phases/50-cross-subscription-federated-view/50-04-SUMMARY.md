---
phase: 50-cross-subscription-federated-view
plan: "04"
status: complete
commit: 7f533e1
---

# 50-04 Summary: UI Federation Awareness + Agent Subscription Utility DRY

## What Was Done

Two focused changes:

1. **UI federation** — Dashboard tabs no longer bail out when `selectedSubscriptions` is empty. Empty = "all subscriptions"; the backend registry handles the all-subscriptions default.
2. **Agent DRY** — `_extract_subscription_id()` was copy-pasted across 6+ agent files. Moved to `agents/shared/subscription_utils.py`; all affected agents now import via alias.

## Changes

### Task 1: UI — Remove early-return on empty subscriptions

**`services/web-ui/components/VMTab.tsx`**
- Removed `if (subscriptions.length === 0) return` early return from `fetchVMs()`
- Changed `new URLSearchParams({ subscriptions: ... })` to conditional: only sets `subscriptions` param when `subscriptions.length > 0`
- Updated empty-state message: removed "Select a subscription to view VMs" conditional; always shows "No VMs found in selected subscriptions"

**`services/web-ui/components/VMSSTab.tsx`**
- Same pattern applied to `fetchVMSS()`: removed early return, made `subscriptions` param conditional
- Empty-state message updated: "No scale sets found in selected subscriptions" (unconditional)

**`services/web-ui/components/AKSTab.tsx`**
- Same pattern applied to `fetchClusters()`: removed early return, made `subscriptions` param conditional
- Empty-state message updated: "No AKS clusters found in selected subscriptions" (unconditional)

**`services/web-ui/components/PatchTab.tsx`**
- Removed `if (subscriptions.length === 0) { ... return }` early return from `fetchData()`
- Changed hard-coded `?subscriptions=...` query string to conditional: `subsQuery` is empty string when `subscriptions.length === 0`, otherwise `?subscriptions=...`
- Removed render-level `if (subscriptions.length === 0 && !loading)` block that showed "No patch data available / Select one or more subscriptions above"

### Task 2: Create agents/shared/subscription_utils.py + update agent imports

**`agents/shared/subscription_utils.py`** (new)
- `extract_subscription_id(resource_id: str) -> str` — canonical implementation
- Raises `ValueError` with "Cannot extract subscription_id from resource_id: ..." for invalid ARM IDs
- Validates non-empty subscription segment (catches edge case of trailing slash)

**`agents/compute/tools.py`**, **`agents/network/tools.py`**, **`agents/security/tools.py`**, **`agents/sre/tools.py`**, **`agents/database/tools.py`**, **`agents/appservice/tools.py`**
- Replaced local `def _extract_subscription_id(...)` (22-line function body) with:
  ```python
  from agents.shared.subscription_utils import extract_subscription_id as _extract_subscription_id
  ```
- Zero call-site changes required anywhere — alias preserves the private `_extract_subscription_id` name

## Verification

```
TypeScript: npx tsc --noEmit → clean (0 errors)
Early return check: grep found 0 occurrences in VMTab, VMSSTab, AKSTab, PatchTab
Agent tests: 787 passed, 0 failed
subscription_utils: extract_subscription_id('/subscriptions/sub-abc/...') == 'sub-abc' ✓
Local def check: grep ^def _extract_subscription_id in 6 updated files → 0 matches ✓
api-gateway failure: pre-existing (missing azure.monitor.query — unrelated)
```

## Acceptance Criteria

- [x] `VMTab.tsx`: no `if (subscriptions.length === 0) return` early return
- [x] `VMTab.tsx`: `params.set('subscriptions', ...)` inside `if (subscriptions.length > 0)` guard
- [x] `VMTab.tsx`: empty-state message is "No VMs found in selected subscriptions" (unconditional)
- [x] `VMSSTab.tsx`: same changes applied
- [x] `AKSTab.tsx`: same changes applied
- [x] `PatchTab.tsx`: early return removed, fetch conditional, render-level empty-state removed
- [x] TypeScript compilation clean in `services/web-ui/`
- [x] `agents/shared/subscription_utils.py` exists with `extract_subscription_id()`
- [x] `extract_subscription_id` raises `ValueError` with correct message for invalid ARM IDs
- [x] `agents/compute/tools.py`: import alias replaces local definition
- [x] `agents/network/tools.py`: import alias replaces local definition
- [x] `agents/security/tools.py`: import alias replaces local definition
- [x] `agents/sre/tools.py`: import alias replaces local definition
- [x] `agents/database/tools.py`: import alias replaces local definition
- [x] `agents/appservice/tools.py`: import alias replaces local definition
- [x] No local `def _extract_subscription_id` functions remain in updated files
- [x] 787 agent tests pass — no regressions
</content>
</invoke>