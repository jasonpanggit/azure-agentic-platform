# Summary: Redeploy Web UI and API Gateway

**ID:** 260405-0rp
**Status:** COMPLETE
**Date:** 2026-04-05

---

## What Was Done

Triggered GitHub Actions workflows to build and deploy both the Web UI and API Gateway services from current `main` HEAD (`ac92180fc047d4f6a280d15a3a9a4fa927199d1f`) to production Azure Container Apps.

## Workflow Runs

| Service | Workflow | Run ID | Duration | Result |
|---|---|---|---|---|
| **Web UI** | `web-ui-build.yml` | [23983032681](https://github.com/jasonpanggit/azure-agentic-platform/actions/runs/23983032681) | ~7m | SUCCESS |
| **API Gateway** | `api-gateway-build.yml` | [23983033460](https://github.com/jasonpanggit/azure-agentic-platform/actions/runs/23983033460) | ~4m | SUCCESS |

## Deployment Details

| Service | Container App | Revision | Health Check | Image Tag |
|---|---|---|---|---|
| **Web UI** | `ca-web-ui-prod` | `ca-web-ui-prod--0000065` | `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/` | `ac92180f...` |
| **API Gateway** | `ca-api-gateway-prod` | `ca-api-gateway-prod--0000084` | `https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/health` | `ac92180f...` |

## Pipeline Breakdown

### Web UI (7 min total)
1. **Validate Web UI Build Vars** (4s) -- NEXT_PUBLIC_* vars validated
2. **Build & Push via ACR Tasks** (5m21s) -- `az acr build --agent-pool aap-builder-prod`
3. **Image Size Check** -- passed
4. **Deploy new revision** -- `az containerapp update --image ...`
5. **Wait for active** -- revision `ca-web-ui-prod--0000065` active
6. **Health check** -- `GET /` returned 200

### API Gateway (4 min total)
1. **Build & Push via ACR Tasks** (2m31s) -- `az acr build --agent-pool aap-builder-prod`
2. **Image Size Check** -- passed
3. **Deploy new revision** -- `az containerapp update --image ...`
4. **Wait for active** -- revision `ca-api-gateway-prod--0000084` active
5. **Health check** -- `GET /health` returned 200

## Changes Deployed

These builds deploy current `main` HEAD which includes:
- VMDetailPanel improvements (Phase 16/17 work)
- `vm_inventory.py` OS normalization fixes
- API gateway RBAC additions (Reader + Monitoring Reader roles)
- All Phase 19-28 code-complete work

## Task Checklist

- [x] Trigger `web-ui-build.yml` via `gh workflow run` on `main`
- [x] Trigger `api-gateway-build.yml` via `gh workflow run` on `main`
- [x] Monitor both workflow runs for completion
- [x] Confirm `ca-web-ui-prod` new revision is active and healthy
- [x] Confirm `ca-api-gateway-prod` new revision is active and `/health` returns 200
- [x] Both workflow runs complete successfully (green checkmarks)
- [x] `ca-web-ui-prod` serving latest commit SHA image
- [x] `ca-api-gateway-prod` serving latest commit SHA image with `/health` returning 200

## Notes

- Previous runs from branch `quick/260404-vm9-api-gateway-rbac` built images but skipped deploy (deploy gate: `github.ref == 'refs/heads/main'`)
- Both builds used ACR agent pool `aap-builder-prod` (VNet-injected, private ACR endpoint)
- Auth mode: client-secret (not OIDC) -- SP credentials from GitHub secrets
- No code changes were needed -- this was a pure ops task
