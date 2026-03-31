# Plan: Fix Broken API Gateway Image — ModuleNotFoundError for `agents`

**Task ID:** 260331-krz
**Date:** 2026-03-31
**Status:** READY

---

## Root Cause (Confirmed)

Two co-dependent problems:

**Problem 1 — `agents.shared` not in build context:**
`chat.py` line 16 imports `from agents.shared.routing import classify_query_text`.
The Docker build context for `api-gateway` is `services/api-gateway/` in both:
- `.github/workflows/api-gateway-build.yml` (`build_context: services/api-gateway/`)
- `.github/workflows/deploy-all-images.yml` (`build_context: services/api-gateway/`)

The `agents/` directory lives at the repo root — entirely outside this build context. Docker never sees it, so the image has no `agents/` package. Container crashes at import time with `ModuleNotFoundError: No module named 'agents'`.

**Problem 2 — `services/__init__.py` missing from image:**
The Dockerfile does `COPY . ./services/api_gateway/` which copies gateway source files to the right place, but the `services/` parent directory inside the container has no `__init__.py`. The uvicorn CMD is `services.api_gateway.main:app` — Python needs `services/__init__.py` to exist as a package root.

**The fix:** Expand the build context to the repo root for `api-gateway` only, then update COPY instructions in the Dockerfile to pull from the correct paths. No other service needs this change (other services don't import from `agents.shared`).

---

## Tasks

### Task 1 — Fix `services/api-gateway/Dockerfile` COPY instructions

**File:** `services/api-gateway/Dockerfile`

Change the build context assumption from `services/api-gateway/` to repo root (`.`). The Dockerfile must:
1. Copy `requirements.txt` from the gateway's own directory
2. Copy `services/__init__.py` (creates the `services` package)
3. Copy `services/api-gateway/` as `services/api_gateway/` (note: hyphen → underscore, Python package name)
4. Copy `agents/` to provide `agents.shared.*` and all sibling agent packages that may be imported

New COPY block:
```dockerfile
# Install Python dependencies
COPY services/api-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy package roots so Python can resolve `services.api_gateway.*` and `agents.shared.*`
COPY services/__init__.py ./services/__init__.py
COPY services/api-gateway/ ./services/api_gateway/
COPY agents/ ./agents/
```

Remove the old `COPY . ./services/api_gateway/` line.

**Working directory stays `/app`; CMD stays `uvicorn services.api_gateway.main:app ...`** — no change needed there.

### Task 2 — Fix build context in both CI workflows

Both workflows pass `build_context: services/api-gateway/` which scopes Docker's filesystem to just that subdirectory. Must change to the repo root.

**File:** `.github/workflows/api-gateway-build.yml`
Change:
```yaml
build_context: services/api-gateway/
```
To:
```yaml
build_context: .
```

**File:** `.github/workflows/deploy-all-images.yml`
The `build-api-gateway` job (line ~278):
```yaml
build_context: services/api-gateway/
```
To:
```yaml
build_context: .
```

> Note: `dockerfile_path: services/api-gateway/Dockerfile` remains correct in both — the Dockerfile path is relative to the repo root checkout, not the build context.

### Task 3 — Rebuild, push to ACR, and update `ca-api-gateway-prod`

This is an operator-only task requiring live Azure credentials. Document exact commands.

**3a. Verify fix locally (no Azure needed):**
```bash
cd /path/to/repo
docker build \
  --platform linux/amd64 \
  -f services/api-gateway/Dockerfile \
  -t api-gateway:test \
  .
# Should complete without error. Confirm with:
docker run --rm api-gateway:test python -c "from services.api_gateway.chat import create_chat_thread; print('OK')"
```

**3b. Build and push to ACR:**
```bash
ACR=aapcrprodjgmjti.azurecr.io
TAG=$(git rev-parse --short HEAD)

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

**3c. Update `ca-api-gateway-prod` to new image:**
```bash
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --image $ACR/services/api-gateway:$TAG
```

**3d. Verify startup:**
```bash
# Watch logs for 30s — should NOT see ModuleNotFoundError
az containerapp logs show \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --follow \
  --tail 50

# Health check
curl https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/health
# Expected: {"status":"ok","version":"1.0.0"}
```

---

## Verification Criteria

- [ ] `docker build` from repo root with new Dockerfile completes without error
- [ ] `docker run` smoke import of `services.api_gateway.chat` succeeds (no ModuleNotFoundError)
- [ ] New image pushed to `aapcrprodjgmjti.azurecr.io/services/api-gateway`
- [ ] `ca-api-gateway-prod` updated and healthy (new revision active)
- [ ] `/health` returns `{"status":"ok","version":"1.0.0"}`
- [ ] Logs show no `ModuleNotFoundError` on startup

---

## Notes

- **No other Dockerfiles need changing** — all other `services/` images (teams-bot, web-ui, arc-mcp-server, azure-mcp-server) do not import from `agents.shared.*`. Only `api-gateway/chat.py` crosses this boundary.
- **CI path trigger** in `api-gateway-build.yml` does NOT need updating — it already watches `services/api-gateway/**` which is the right signal.
- **Larger image size** — including all of `agents/` adds ~2-4MB of Python source. Well within the 1500MB CI limit.
- **`agents/__pycache__` and `agents/*/tests/`** will be included but are harmless. A `.dockerignore` at repo root could exclude them in a follow-up.
- Alternative considered: install `agents` as an editable package via `pip install -e .` — rejected because `pyproject.toml` uses `pythonpath=["."]` for pytest only, not a proper installable package. Build context expansion is the simpler, more direct fix.
