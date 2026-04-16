# Phase 63 — AIOps Quality Flywheel

## Goal
Close the loop between operator decisions and model behaviour by capturing feedback signals, computing SOP effectiveness scores, and surfacing quality metrics in the UI.

## Deliverables

1. `services/api-gateway/feedback_capture.py` — FeedbackRecord model + FeedbackCaptureService
2. `services/api-gateway/quality_endpoints.py` — FastAPI router for /api/v1/quality/*
3. `services/api-gateway/migrations/007_eval_feedback.sql` — PostgreSQL migration
4. `services/web-ui/components/QualityFlywheelTab.tsx` — UI tab component
5. `services/web-ui/app/api/proxy/quality/metrics/route.ts` — Proxy route
6. `services/web-ui/app/api/proxy/quality/sop-effectiveness/route.ts` — Proxy route
7. `services/api-gateway/tests/test_feedback_capture.py` — 8+ tests
8. DashboardPanel.tsx updated with quality tab

## Architecture

```
Operator approve/reject → approvals.py → record_feedback() → eval_feedback (PostgreSQL)
                                                ↓
GET /api/v1/quality/metrics ← FeedbackCaptureService.get_quality_metrics()
GET /api/v1/quality/sop-effectiveness ← FeedbackCaptureService.compute_sop_effectiveness()
GET /api/v1/quality/feedback ← recent records
                                                ↓
Next.js proxy routes → QualityFlywheelTab
```

## Implementation Steps

- [ ] Write migration SQL
- [ ] Write feedback_capture.py (FeedbackRecord + FeedbackCaptureService)
- [ ] Write quality_endpoints.py router
- [ ] Register router in main.py
- [ ] Write proxy routes (metrics, sop-effectiveness)
- [ ] Write QualityFlywheelTab.tsx
- [ ] Register tab in DashboardPanel.tsx
- [ ] Write tests
- [ ] Verify: pytest + tsc --noEmit
