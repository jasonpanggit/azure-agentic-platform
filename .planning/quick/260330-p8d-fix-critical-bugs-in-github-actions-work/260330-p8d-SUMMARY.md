# Quick Task Summary: Fix Critical Bugs in GitHub Actions Workflows

**ID:** 260330-p8d
**Status:** COMPLETE
**Branch:** `fix/gh-actions-workflow-bugs`
**Date:** 2026-03-30

---

## Commits

| # | Commit | Message |
|---|--------|---------|
| 1 | `a304b17` | `fix(ci): fix deploy-all-images service builds missing secret and image tag` |
| 2 | `a35c58d` | `fix(ci): add PGSSLMODE=require and ON_ERROR_STOP to terraform-apply psql steps` |
| 3 | `3758e75` | `fix(ci): replace non-deterministic npm install with npm ci in e2e workflow` |

---

## Task 1: Fix `deploy-all-images.yml`

**Files changed:** `.github/workflows/deploy-all-images.yml`

### 1a. Missing `AZURE_CLIENT_SECRET` on `build-azure-mcp-server`

The `build-azure-mcp-server` job only passed 3 secrets while all other build jobs passed 4. The reusable `docker-push.yml` workflow uses `AZURE_CLIENT_SECRET` for auth mode detection -- without it, the job always falls through to OIDC even when client-secret auth is configured.

**Fix:** Added `AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}` to the secrets block.

### 1b. Inconsistent image tagging on service builds

All 5 service build jobs (`build-api-gateway`, `build-arc-mcp-server`, `build-teams-bot`, `build-web-ui`, `build-azure-mcp-server`) passed `image_tag: ${{ inputs.image_tag }}` directly. When `inputs.image_tag` is empty (the default), this passes an empty string to `docker-push.yml` which then independently resolves to `github.sha`. This worked but was fragile and inconsistent with agent builds which use the resolved tag from `build-agent-base.outputs.image_tag`.

**Fix:** Added `needs: build-agent-base` to all 5 service build jobs and changed `image_tag` to `${{ needs.build-agent-base.outputs.image_tag }}`. All 13 images (8 agent + 5 service) are now tagged from a single resolution point.

---

## Task 2: Fix `terraform-apply.yml`

**Files changed:** `.github/workflows/terraform-apply.yml`

Three "Create pgvector Extension" steps (dev, staging, prod) were missing:

1. **`PGSSLMODE: require`** in the `env:` block -- Azure PostgreSQL Flexible Server requires SSL; without this the connection may fail or use an insecure channel.
2. **`-v ON_ERROR_STOP=1`** flag on psql -- without this, SQL errors are silently swallowed and the step reports success.

**Fix:** Added both `PGSSLMODE: require` and `-v ON_ERROR_STOP=1` to all 3 steps, matching the pattern already used in `prod-db-setup.yml`.

---

## Task 3: Fix `staging-e2e-simulation.yml`

**Files changed:** `.github/workflows/staging-e2e-simulation.yml`

The e2e job ran `npm init -y` (overwriting the committed `e2e/package.json`) then `npm install` with unpinned packages at whatever latest versions resolved. The `e2e/` directory already has a committed `package.json` and `package-lock.json`.

**Fix:**
- Replaced `npm init -y` + `npm install ...` with `npm ci` (uses lockfile for deterministic installs)
- Added `cache: npm` and `cache-dependency-path: e2e/package-lock.json` to `actions/setup-node@v4` for faster CI runs

**Note on `@azure/monitor-query`:** The old workflow installed this package but it is NOT imported in any e2e test file (confirmed via grep). It was not added to `e2e/package.json` -- no action needed.

---

## Verification

- [x] All 13 build jobs in `deploy-all-images.yml` now have consistent 4-secret passing
- [x] All 5 service builds depend on `build-agent-base` and use resolved tag
- [x] All 3 psql steps in `terraform-apply.yml` have `PGSSLMODE: require` and `-v ON_ERROR_STOP=1`
- [x] `staging-e2e-simulation.yml` uses deterministic `npm ci` with lockfile caching
- [x] `@azure/monitor-query` confirmed not imported in e2e tests -- no package.json change needed
- [x] YAML syntax verified via `git diff` review of all changes
