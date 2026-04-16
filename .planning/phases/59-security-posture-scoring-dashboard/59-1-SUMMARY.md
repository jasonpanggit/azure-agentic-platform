# Phase 59-1: Security Posture Scoring Dashboard — Summary

## Status: ✅ Complete

## What Was Built

### Backend (Python)

**`services/api-gateway/security_posture.py`**
- `SecurityPostureClient` class following the `CapacityPlannerClient` pattern
- `_get_defender_secure_score()` — fetches from `azure-mgmt-security` SecurityCenter, normalises to 0-100
- `_get_policy_compliance_pct()` — fetches from `azure-mgmt-policyinsights`, returns compliant%
- `_get_custom_controls_score()` — placeholder returning None (future: exposure management)
- `get_composite_score()` — computes weighted composite, upserts to Cosmos with 1h TTL
- `get_posture_trend(days=30)` — queries Cosmos for historical score points
- `get_top_findings(limit=25)` — fetches Defender tasks, sorted by severity
- Pure helpers: `_clamp`, `_score_color`, `_compute_composite`

**`services/api-gateway/security_posture_endpoints.py`**
- `GET /api/v1/security/posture` — composite score + sub-scores + 30-day trend
- `GET /api/v1/security/findings` — top-N findings with recommendation and control

**`services/api-gateway/main.py`** — router registered

### Frontend (TypeScript/React)

**`services/web-ui/components/SecurityPostureTab.tsx`**
- Composite score gauge (large number + color ring)
- 3 sub-score cards: Defender Score (50%), Policy Compliance (30%), Custom Controls (20%)
- 30-day trend `LineChart` via recharts
- Findings table with severity badges and "Remediate via agent" button
- All styling via CSS semantic tokens — zero hardcoded Tailwind colors
- Loading skeletons + empty state + error alert

**Proxy routes**
- `services/web-ui/app/api/proxy/security/posture/route.ts`
- `services/web-ui/app/api/proxy/security/findings/route.ts`
- Both: `runtime='nodejs'`, `dynamic='force-dynamic'`, `AbortSignal.timeout(15000)`

**`services/web-ui/components/DashboardPanel.tsx`**
- Added `'security-posture'` to `TabId` union
- Added tab entry `{ id: 'security-posture', label: 'Security Score', Icon: ShieldCheck }` in Security & compliance group
- Added `<SecurityPostureTab>` panel with lazy render (`activeTab === 'security-posture'`)

### Tests

**`services/api-gateway/tests/test_security_posture.py`** — 22 tests, all passing
- `TestClamp` (4 tests) — boundary clamping
- `TestScoreColor` (3 tests) — green/yellow/red thresholds
- `TestComputeComposite` (8 tests) — calculation, bounds, None handling, warnings, sub-scores, color
- `TestGetCompositeScore` (3 tests) — endpoint returns score, works without Cosmos, handles exceptions
- `TestGetTopFindings` (2 tests) — returns list, empty when SDK unavailable
- `TestGetPostureTrend` (2 tests) — empty without Cosmos, queries Cosmos correctly

## Test Results
```
22 passed, 3 warnings in 0.05s
```

## TypeScript
```
0 errors (excluding pre-existing OpsTab.test.tsx unrelated issue)
```

## Key Patterns Followed
- SDK lazy imports: `try/except ImportError` with `None` fallback at module level
- Tool functions never raise — return structured error dicts
- `start_time = time.monotonic()` + `duration_ms` in all public methods
- CSS semantic tokens throughout — no hardcoded Tailwind color classes
- Proxy routes: `runtime='nodejs'`, `dynamic='force-dynamic'`, `AbortSignal.timeout(15000)`
