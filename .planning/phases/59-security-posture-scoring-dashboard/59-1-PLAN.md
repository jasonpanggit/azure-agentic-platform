# Phase 59-1: Security Posture Scoring Dashboard — Plan

## Goal
Surface a unified, continuously updated security posture score across all monitored subscriptions — aggregating Defender secure score, policy compliance, and exposure management.

## Deliverables

### Backend
- [ ] `services/api-gateway/security_posture.py` — SecurityPostureClient service class
- [ ] `services/api-gateway/security_posture_endpoints.py` — FastAPI router with 2 endpoints
- [ ] Register router in `services/api-gateway/main.py`

### Frontend
- [ ] `services/web-ui/components/SecurityPostureTab.tsx` — full UI component
- [ ] `services/web-ui/app/api/proxy/security/posture/route.ts` — proxy route
- [ ] `services/web-ui/app/api/proxy/security/findings/route.ts` — proxy route
- [ ] Register tab in `services/web-ui/components/DashboardPanel.tsx`

### Tests
- [ ] `services/api-gateway/tests/test_security_posture.py` — ≥8 tests

## Architecture Decisions

### Composite Score Formula
- 50% Defender Secure Score (via `azure-mgmt-security` SecurityCenter client)
- 30% Policy Compliance % (via `azure-mgmt-policyinsights`)
- 20% Custom Controls (placeholder → None → contributes 0, flagged in warnings)

### Cosmos TTL
- Documents stored in `security_posture` container with `ttl: 3600` (1 hour)
- ID keyed by `{subscription_id}:posture:{YYYY-MM-DDTHH}` for hourly dedup

### Score Color Thresholds
- ≥75 → green, ≥50 → yellow, <50 → red

### SDK Safety
- All Azure SDK imports wrapped in `try/except ImportError` with `None` fallback
- Tool functions never raise — return structured error dicts

### Frontend
- CSS semantic tokens only (`var(--accent-*)`, `var(--bg-*)`, `var(--text-*)`)
- recharts `LineChart` for 30-day trend
- "Remediate via agent" button per finding calls `onOpenChat` prop with pre-filled context
- Loading skeletons + empty states

## API Endpoints

```
GET /api/v1/security/posture?subscription_id=
  → { composite_score, color, sub_scores, trend, warnings, ... }

GET /api/v1/security/findings?subscription_id=&limit=25
  → { findings: [...], total, ... }
```

## Proxy Routes
```
GET /api/proxy/security/posture → /api/v1/security/posture
GET /api/proxy/security/findings → /api/v1/security/findings
```
