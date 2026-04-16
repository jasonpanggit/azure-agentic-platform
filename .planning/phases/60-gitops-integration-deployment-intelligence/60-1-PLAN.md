# Phase 60-1: GitOps Integration + Deployment Intelligence — Plan

## Goal
Connect the platform to GitHub Actions to correlate infrastructure incidents with the
deployment that caused them — surfacing deployment-to-incident causation and enabling
one-click pipeline rollbacks through HITL.

## Tasks

- [x] 1. Create `services/api-gateway/deployment_tracker.py`
  - DeploymentEvent Pydantic model (deployment_id, source, repository, environment, status, commit_sha, author, pipeline_url, resource_group, started_at, completed_at)
  - DeploymentTracker class: ingest_event, list_recent, correlate
  - DeploymentCorrelator: -30min to +5min window around incident timestamp
  - parse_github_deployment_payload: GitHub Actions webhook → DeploymentEvent

- [x] 2. Create `services/api-gateway/deployment_endpoints.py`
  - POST /api/v1/deployments — ingest deployment event (GitHub webhook + direct)
  - GET  /api/v1/deployments — list recent deployments (resource_group, limit, hours_back)
  - GET  /api/v1/deployments/correlate — correlate deployments to incident

- [x] 3. Register deployment_router in `services/api-gateway/main.py`

- [x] 4. Add `get_recent_deployments` @ai_function tool to `agents/sre/tools.py`
  - HTTP call to /api/v1/deployments via httpx (lazy import guard)
  - Returns deployments list, total, query_status

- [x] 5. Create `services/web-ui/components/DeploymentBadge.tsx`
  - Compact inline badge: "Deployed Xmin before incident by @user — commit abc123"
  - CSS semantic tokens only; ExternalLink to pipeline_url

- [x] 6. Create `services/web-ui/components/DeploymentTab.tsx`
  - Recent deployments table: Time | Repository | Environment | Status | Author | Commit | Correlated Incidents
  - Status filter (all/success/failure/in_progress) + time range filter (6h/24h/48h/7d)
  - Click row → CorrelatedIncidentsPanel with DeploymentBadge per correlated event
  - Loading skeletons, empty state with webhook setup instruction
  - CSS semantic tokens only

- [x] 7. Create proxy routes
  - `services/web-ui/app/api/proxy/deployments/route.ts` — GET + POST
  - `services/web-ui/app/api/proxy/deployments/correlate/route.ts` — GET

- [x] 8. Register Deployments tab in `services/web-ui/components/DashboardPanel.tsx`
  - Added 'deployments' to TabId union
  - Added GitPullRequest icon import
  - Added to "Security & compliance" group: Deployments
  - Imported DeploymentTab and rendered in tabpanel

- [x] 9. Write tests in `services/api-gateway/tests/test_deployment_tracker.py`
  - 12 tests covering ingest, list, correlate, GitHub webhook parsing, error cases

## Verification
- Python tests: 12/12 passed
- TypeScript: no errors in new files
