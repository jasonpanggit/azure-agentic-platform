# Phase 68-1 Plan: Subscription Management Tab

## Goal
Give operators a dedicated UI tab to manage all Azure subscriptions under monitoring: view discovery status, label subscriptions, toggle monitoring per subscription, and inspect per-subscription health stats.

## Requirements
- List all discovered subscriptions with enriched metadata
- Allow inline label editing
- Toggle monitoring_enabled per subscription
- Environment tagging (prod/staging/dev)
- Per-subscription stats: incident counts, resource counts
- Trigger on-demand re-sync of ARG discovery

## Implementation
- Backend: `subscription_endpoints.py` with 4 endpoints
- Frontend: `SubscriptionManagementTab.tsx` with filtering, inline editing, stats dialog
- Proxy routes: 4 routes under `/api/proxy/subscriptions/`
- DashboardPanel: Globe icon tab in Config group

## Tests
14 tests in `test_subscription_endpoints.py`
