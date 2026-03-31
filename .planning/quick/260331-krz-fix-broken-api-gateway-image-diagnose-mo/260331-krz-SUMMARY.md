# Summary: Fix Broken API Gateway Image — ModuleNotFoundError

**Task ID:** 260331-krz
**Date:** 2026-03-31
**Commit:** 13f2b78
**Status:** CODE FIXES COMPLETE — operator rebuild + deploy required

---

## What Was Fixed

### Root Cause
Two co-dependent bugs caused `ca-api-gateway-prod` to crash at startup with `ModuleNotFoundError: No module named 'agents'`:

1. **Build context too narrow** — Both CI workflows passed `build_context: services/api-gateway/`, so Docker's filesystem was scoped to that subdirectory. The `agents/` directory at the repo root was never included in the image.

2. **Missing `services/__init__.py`** — The old `COPY . ./services/api_gateway/` only copied gateway source files. Python couldn't resolve `services.api_gateway` as a package because the `services/` parent lacked an `__init__.py`.

### Files Changed (commit 13f2b78)

| File | Change |
|------|--------|
| `services/api-gateway/Dockerfile` | Replace single `COPY . ./services/api_gateway/` with three targeted COPYs from repo root; also fix `requirements.txt` path |
| `.github/workflows/api-gateway-build.yml` | `build_context: services/api-gateway/` → `build_context: .` |
| `.github/workflows/deploy-all-images.yml` | `build_context: services/api-gateway/` → `build_context: .` (build-api-gateway job) |

### New Dockerfile COPY block

```dockerfile
# Install Python dependencies
COPY services/api-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy package roots so Python can resolve `services.api_gateway.*` and `agents.shared.*`
COPY services/__init__.py ./services/__init__.py
COPY services/api-gateway/ ./services/api_gateway/
COPY agents/ ./agents/
```

`dockerfile_path: services/api-gateway/Dockerfile` was **not changed** in either workflow — the Dockerfile path is always relative to the repo root checkout, not the build context.

---

## Operator Steps to Deploy the Fix

> These steps require live Azure credentials. Run them after the commit is on main
> (or from the current branch).

### Step 1 — Verify the build locally (no Azure needed)

```bash
cd /path/to/azure-agentic-platform

docker build \
  --platform linux/amd64 \
  -f services/api-gateway/Dockerfile \
  -t api-gateway:test \
  .

# Smoke-test the import — must print "OK" with no ModuleNotFoundError
docker run --rm api-gateway:test \
  python -c "from services.api_gateway.chat import create_chat_thread; print('OK')"
```

### Step 2 — Build and push to ACR

```bash
ACR=aapcrprodjgmjti.azurecr.io
TAG=$(git rev-parse --short HEAD)   # e.g. 13f2b78

az acr login --name aapcrprodjgmjti

docker build \
  --platform linux/amd64 \
  -f services/api-gateway/Dockerfile \
  -t $ACR/services/api-gateway:$TAG \
  -t $ACR/services/api-gateway:latest \
  .

docker push $ACR/services/api-gateway:$TAG
docker push $ACR/services/api-gateway:latest
```

### Step 3 — Update ca-api-gateway-prod

```bash
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --image $ACR/services/api-gateway:$TAG
```

### Step 4 — Verify startup

```bash
# Watch logs — must NOT contain ModuleNotFoundError
az containerapp logs show \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --follow \
  --tail 50

# Health check — expected: {"status":"ok","version":"1.0.0"}
curl https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/health
```

> **CI path:** Once this commit reaches `main`, the `Build API Gateway` workflow
> (`api-gateway-build.yml`) will trigger automatically on push (watches
> `services/api-gateway/**`) and run the new build + deploy to prod.

---

## Verification Criteria

| # | Criterion | Automatable? |
|---|-----------|-------------|
| 1 | `docker build` from repo root completes without error | Local |
| 2 | Smoke import of `services.api_gateway.chat` succeeds (no ModuleNotFoundError) | Local |
| 3 | New image pushed to `aapcrprodjgmjti.azurecr.io/services/api-gateway` | Operator |
| 4 | `ca-api-gateway-prod` updated and new revision active | Operator |
| 5 | `/health` returns `{"status":"ok","version":"1.0.0"}` | Operator |
| 6 | Startup logs show no `ModuleNotFoundError` | Operator |

---

## Notes

- No other Dockerfiles need this treatment. Only `api-gateway/chat.py` crosses into `agents.shared.*`.
- The `agents/` directory adds ~2–4 MB to the image. Well within limits.
- `agents/__pycache__` and `agents/*/tests/` are included but harmless. A repo-root `.dockerignore` can exclude them as a follow-up if desired.
