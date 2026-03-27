# Quick Task Summary: Deploy Images to Container Registry

**ID:** 260328-2ir
**Status:** complete
**Branch:** `quick/260328-2ir-deploy-images`
**Date:** 2026-03-28

---

## Tasks Completed

### Task 1: Create teams-bot Docker push workflow
**Commit:** `d212743`
**File:** `.github/workflows/teams-bot-build.yml`

Created `teams-bot-build.yml` following the exact pattern of `api-gateway-build.yml` and `web-ui-build.yml`:
- Triggers on push to `main` when `services/teams-bot/**` changes
- Uses reusable `docker-push.yml` with `image_name: services/teams-bot`
- Permissions: `id-token: write`, `contents: read`

### Task 2: Create unified "Deploy All Images" workflow
**Commit:** `672af99`
**Files:** `.github/workflows/deploy-all-images.yml`, `.github/workflows/docker-push.yml`

**deploy-all-images.yml:**
- Trigger: `workflow_dispatch` only (manual operator trigger)
- Optional `image_tag` input (default: git SHA)
- Builds 12 images total:
  - **Phase 1:** Agent base image (`agents/Dockerfile.base`) — inline job that outputs `base_image` and `image_tag`
  - **Phase 2a:** 7 agent images in parallel (orchestrator, compute, network, storage, security, sre, arc) — all `needs: build-agent-base`, pass `BASE_IMAGE` build-arg via job output
  - **Phase 2b:** 4 service images in parallel (api-gateway, arc-mcp-server, teams-bot, web-ui) — no dependencies, start immediately
- Summary job lists all image statuses in `GITHUB_STEP_SUMMARY`; fails workflow if any build failed

**docker-push.yml enhancements (backward-compatible):**
- Added optional `build_args` input (default: `''`) for Docker build-arg passthrough
- Added optional `image_tag` input (default: `''`, falls back to `github.sha`) for tag override
- Added `Resolve image tag` step that uses tag input or SHA
- Updated `Build and Push` step to use resolved tag + build-args
- Updated `Image Size Check` to use resolved tag

### Task 3: Verify and fix naming conventions
**Commit:** `94d0b8b`
**Files:** `.github/workflows/arc-mcp-server-build.yml`, `terraform/modules/arc-mcp-server/main.tf`

**Naming mismatch found and fixed:**
- `arc-mcp-server-build.yml` was pushing to ACR as `arc-mcp-server:*` (no `services/` prefix)
- Terraform `arc-mcp-server/main.tf` was referencing `${acr_login_server}/arc-mcp-server:${image_tag}`
- Both corrected to `services/arc-mcp-server` to align with `agent-apps/main.tf` convention where all services use `services/<name>` prefix

**Verification results:**
| Check | Result |
|-------|--------|
| All 12 Dockerfiles exist | Pass |
| `build_context` paths align with Dockerfile COPY commands | Pass |
| `agent-apps/main.tf` image naming matches workflow `image_name` | Pass |
| Agent base image builds before dependent agents | Pass (via `needs:`) |
| `arc-mcp-server` naming aligned across workflow + Terraform | Pass (fixed) |
| YAML syntax validation (all 4 files) | Pass |

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `.github/workflows/teams-bot-build.yml` | Created | Teams bot Docker push on path change |
| `.github/workflows/deploy-all-images.yml` | Created | Unified manual deploy-all workflow |
| `.github/workflows/docker-push.yml` | Modified | Added `build_args`, `image_tag` inputs |
| `.github/workflows/arc-mcp-server-build.yml` | Modified | Fixed ACR tag to `services/arc-mcp-server` |
| `terraform/modules/arc-mcp-server/main.tf` | Modified | Fixed image ref to `services/arc-mcp-server` |

---

## Image Naming Convention (Final)

| Image | ACR Path | Terraform Reference |
|-------|----------|-------------------|
| Agent Base | `agents/base` | N/A (build-time only) |
| Orchestrator | `agents/orchestrator` | `agents/orchestrator` via `agent-apps` |
| Compute | `agents/compute` | `agents/compute` via `agent-apps` |
| Network | `agents/network` | `agents/network` via `agent-apps` |
| Storage | `agents/storage` | `agents/storage` via `agent-apps` |
| Security | `agents/security` | `agents/security` via `agent-apps` |
| SRE | `agents/sre` | `agents/sre` via `agent-apps` |
| Arc | `agents/arc` | `agents/arc` via `agent-apps` |
| API Gateway | `services/api-gateway` | `services/api-gateway` via `agent-apps` |
| Arc MCP Server | `services/arc-mcp-server` | `services/arc-mcp-server` via `arc-mcp-server` module |
| Teams Bot | `services/teams-bot` | `services/teams-bot` via `agent-apps` |
| Web UI | `services/web-ui` | `services/web-ui` via `agent-apps` |
