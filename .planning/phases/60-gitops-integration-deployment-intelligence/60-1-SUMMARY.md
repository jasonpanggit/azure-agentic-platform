# Phase 60-1: GitOps Integration + Deployment Intelligence — Summary

## What Was Built

Phase 60 connects the Azure Agentic Platform to GitHub Actions (and Azure DevOps) to
correlate infrastructure incidents with the deployment that triggered them.

## Files Created / Modified

| File | Change |
|------|--------|
| `services/api-gateway/deployment_tracker.py` | **New** — DeploymentEvent model, DeploymentTracker (ingest/list/correlate), GitHub webhook parser |
| `services/api-gateway/deployment_endpoints.py` | **New** — FastAPI router: POST/GET /api/v1/deployments, GET /api/v1/deployments/correlate |
| `services/api-gateway/main.py` | **Modified** — added deployment_router import + `app.include_router(deployment_router)` |
| `agents/sre/tools.py` | **Modified** — added `get_recent_deployments` @ai_function tool (httpx, lazy import guard) |
| `services/web-ui/components/DeploymentBadge.tsx` | **New** — compact inline badge showing deploy→incident causation |
| `services/web-ui/components/DeploymentTab.tsx` | **New** — deployments table with status/time filters + correlated incidents panel |
| `services/web-ui/app/api/proxy/deployments/route.ts` | **New** — GET + POST proxy to API gateway |
| `services/web-ui/app/api/proxy/deployments/correlate/route.ts` | **New** — GET correlation proxy |
| `services/web-ui/components/DashboardPanel.tsx` | **Modified** — added 'deployments' TabId, GitPullRequest icon, DeploymentTab import + panel |
| `services/api-gateway/tests/test_deployment_tracker.py` | **New** — 12 tests (all passing) |

## Architecture Decisions

- **Correlation window**: -30min before / +5min after incident timestamp — configurable via env vars `DEPLOYMENT_CORRELATION_BEFORE_MIN` / `DEPLOYMENT_CORRELATION_AFTER_MIN`
- **Cosmos partition key**: `resource_group` — enables efficient scoped queries; falls back to `"unknown"` when empty
- **GitHub webhook**: dual-mode ingestion — detects `X-GitHub-Event` header for GitHub payloads, falls back to direct DeploymentEvent JSON
- **SRE agent tool**: uses httpx (lazy import guard) to query `/api/v1/deployments` — enables the agent to automatically surface deployment context during incident triage
- **CSS tokens**: all status badges use `color-mix(in srgb, var(--accent-*) 15%, transparent)` — no hardcoded Tailwind colors

## Test Results

```
12 passed in 0.04s
```

## GitHub Webhook Setup

To receive GitHub Actions deployment events, add a webhook in GitHub repository settings:
- **Payload URL**: `https://<your-gateway>/api/v1/deployments`
- **Content type**: `application/json`
- **Events**: `Deployment`, `Deployment status`
