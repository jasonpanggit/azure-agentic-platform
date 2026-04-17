# Phase 68-1 Summary: Subscription Management Tab

## Status: ✅ Complete

## What Was Built

### Backend (`services/api-gateway/subscription_endpoints.py`)
- `GET /api/v1/subscriptions/managed` — returns all subscriptions from Cosmos with label, monitoring_enabled, environment, incident_count_24h, open_incidents, last_synced
- `PATCH /api/v1/subscriptions/{id}` — update label/monitoring_enabled/environment; upserts to Cosmos; 404 if not found
- `POST /api/v1/subscriptions/sync` — triggers ARG re-discovery via SubscriptionRegistry.full_sync()
- `GET /api/v1/subscriptions/{id}/stats` — per-subscription incident counts (24h, open, by severity), resource/VM counts from ARG

### Frontend (`services/web-ui/components/SubscriptionManagementTab.tsx`)
- Summary cards: Total, Monitoring Active, Open Incidents, Environments breakdown
- Filter bar: All/Prod/Staging/Dev env buttons + search + "Monitoring only" toggle
- Table: inline label edit, env badge+dropdown, shadcn Switch for monitoring, incident counts, relative timestamps
- Stats Dialog: fetches per-subscription stats, loading skeletons, 7 stat rows

### Proxy routes (4 files)
- `managed/route.ts`, `sync/route.ts`, `[id]/route.ts`, `[id]/stats/route.ts`

### DashboardPanel.tsx
- Added `'subscriptions'` to TabId, Globe icon, lazy render
- Placed in Config group

## Tests
14/14 passing in `test_subscription_endpoints.py`
