# Phase 13: Dependency Hygiene Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate unpinned dependency versions and version duplication that can silently break builds.

**Architecture:** Three independent tasks with no interdependencies — all can be implemented in parallel by different engineers if desired. Task 13-01 pins Python package versions. Task 13-02 makes the `@azure/mcp` version a single source of truth. Task 13-03 adds a CI step logging installed versions after each build.

**Tech Stack:** Python requirements files, Bash scripts, GitHub Actions YAML, Docker

---

## File Structure

### Modified files
- `agents/requirements-base.txt` — pin `azure-ai-agentserver-core` and `azure-ai-agentserver-agentframework` versions
- `scripts/deploy-azure-mcp-server.sh` — read version from Dockerfile instead of hardcoding
- `.github/workflows/base-image.yml` — add post-build version logging step

---

## Chunk 1: Pin Agentserver Packages (Task 13-01)

### Task 13-01: Pin `azure-ai-agentserver-agentframework` and `azure-ai-agentserver-core`

**Files:**
- Modify: `agents/requirements-base.txt`

**Context:** Lines 12-13 of `requirements-base.txt`:
```
azure-ai-agentserver-core
azure-ai-agentserver-agentframework
```
Both have no version specifier. Every Docker build installs the latest available version, meaning a breaking RC release from Microsoft silently breaks all agent builds. We need to pin to the currently installed version.

**Note:** This task requires running a Docker build (or using an existing image from ACR) to determine the current installed version before pinning. The steps below show both paths.

- [ ] **Step 1: Determine the currently installed version**

**Option A — Build a temporary Docker image locally:**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
# Build the base image locally (--no-cache ensures fresh install)
docker build -f agents/Dockerfile.base -t aap-base-temp:version-check . --no-cache
# Check installed versions
docker run --rm aap-base-temp:version-check pip show azure-ai-agentserver-core azure-ai-agentserver-agentframework
```

Expected output format:
```
Name: azure-ai-agentserver-core
Version: X.Y.Z
...
Name: azure-ai-agentserver-agentframework
Version: A.B.C
...
```

Record the versions: `AGENTSERVER_CORE_VERSION=<X.Y.Z>`, `AGENTSERVER_FRAMEWORK_VERSION=<A.B.C>`

**Option B — Pull the latest ACR base image (if Docker login to ACR is available):**

```bash
# Login to ACR
az acr login --name <ACR_LOGIN_SERVER>
# Pull the latest base image
docker pull <ACR_LOGIN_SERVER>/agents/base:latest
# Check versions
docker run --rm <ACR_LOGIN_SERVER>/agents/base:latest \
  pip show azure-ai-agentserver-core azure-ai-agentserver-agentframework
```

- [ ] **Step 2: Verify `agents/requirements-base.txt` current state**

```bash
cat agents/requirements-base.txt
```

Confirm lines 12-13 are indeed unpinned (no `==` version specifier).

- [ ] **Step 3: Pin the versions in `requirements-base.txt`**

Edit `agents/requirements-base.txt` — replace the two unpinned lines:

```
# Before:
azure-ai-agentserver-core
azure-ai-agentserver-agentframework

# After (substitute actual versions from Step 1):
azure-ai-agentserver-core==<X.Y.Z>  # Pinned to current version — verify against agent-framework RC before upgrading
azure-ai-agentserver-agentframework==<A.B.C>  # Pinned to current version — verify against agent-framework RC before upgrading
```

Example (if version is 0.1.0):
```
azure-ai-agentserver-core==0.1.0  # Pinned to current version — verify against agent-framework RC before upgrading
azure-ai-agentserver-agentframework==0.1.0  # Pinned to current version — verify against agent-framework RC before upgrading
```

- [ ] **Step 4: Validate that `pip install -r requirements-base.txt` succeeds with pins**

```bash
# Create a temporary virtualenv to test
python -m venv /tmp/aap-pin-test
source /tmp/aap-pin-test/bin/activate
pip install -r agents/requirements-base.txt 2>&1 | tail -10
pip show azure-ai-agentserver-core azure-ai-agentserver-agentframework 2>&1 | grep -E "Name:|Version:"
deactivate
rm -rf /tmp/aap-pin-test
```

Expected: Both packages install at exactly the pinned versions.

- [ ] **Step 5: Build the Docker base image to confirm the pins work in Docker**

```bash
docker build -f agents/Dockerfile.base -t aap-base-pinned-test:latest . 2>&1 | tail -20
```

Expected: Build succeeds. No version resolution errors.

- [ ] **Step 6: Commit**

```bash
git add agents/requirements-base.txt
git commit -m "fix(deps): pin azure-ai-agentserver-core and azure-ai-agentserver-agentframework to exact versions (CONCERNS 6.3)"
```

---

## Chunk 2: Single Source of Truth for `@azure/mcp` Version (Task 13-02)

### Task 13-02: Remove Hardcoded `@azure/mcp` Version from Deploy Script

**Files:**
- Modify: `scripts/deploy-azure-mcp-server.sh`

**Context:** `services/azure-mcp-server/Dockerfile` already has `ARG AZURE_MCP_VERSION=2.0.0-beta.34` — this is the correct source of truth. `scripts/deploy-azure-mcp-server.sh` has `AZURE_MCP_VERSION="2.0.0-beta.34"` hardcoded at line 21. When the Dockerfile version is bumped, the deploy script lags behind silently.

- [ ] **Step 1: Read the current deploy script**

```bash
cat scripts/deploy-azure-mcp-server.sh
```

Identify:
- Line with `AZURE_MCP_VERSION="2.0.0-beta.34"` (approximately line 21)
- How `AZURE_MCP_VERSION` is used in the script (likely in a `docker build` `--build-arg` or `npx @azure/mcp@${AZURE_MCP_VERSION}` call)

- [ ] **Step 2: Read the Dockerfile to confirm `ARG AZURE_MCP_VERSION`**

```bash
grep -n "ARG AZURE_MCP_VERSION" services/azure-mcp-server/Dockerfile
```

Expected: `ARG AZURE_MCP_VERSION=2.0.0-beta.34`

- [ ] **Step 3: Verify no other hardcoded version references**

```bash
grep -rn "2\.0\.0-beta\.34" . --include="*.sh" --include="*.yml" --include="*.yaml" --include="Dockerfile*"
```

Record all locations where the version is hardcoded.

- [ ] **Step 4: Update `deploy-azure-mcp-server.sh` to read version from Dockerfile**

Find the line:
```bash
AZURE_MCP_VERSION="2.0.0-beta.34"
```

Replace with:
```bash
# Read @azure/mcp version from Dockerfile (single source of truth)
AZURE_MCP_VERSION=$(grep 'ARG AZURE_MCP_VERSION=' services/azure-mcp-server/Dockerfile | cut -d= -f2)
if [ -z "$AZURE_MCP_VERSION" ]; then
  echo "ERROR: Could not read AZURE_MCP_VERSION from services/azure-mcp-server/Dockerfile" >&2
  exit 1
fi
echo "Using @azure/mcp version: ${AZURE_MCP_VERSION}"
```

- [ ] **Step 5: Test the version extraction logic**

```bash
# Test the extraction without running the full deploy script
AZURE_MCP_VERSION=$(grep 'ARG AZURE_MCP_VERSION=' services/azure-mcp-server/Dockerfile | cut -d= -f2)
echo "Extracted version: ${AZURE_MCP_VERSION}"
```

Expected: `Extracted version: 2.0.0-beta.34`

- [ ] **Step 6: Verify no hardcoded version string remains in the deploy script**

```bash
grep "2\.0\.0-beta\.34" scripts/deploy-azure-mcp-server.sh
```

Expected: No matches.

- [ ] **Step 7: Run shellcheck on the script (if available)**

```bash
shellcheck scripts/deploy-azure-mcp-server.sh 2>&1 | head -20
```

Expected: No errors (or only pre-existing warnings).

- [ ] **Step 8: Commit**

```bash
git add scripts/deploy-azure-mcp-server.sh
git commit -m "fix(scripts): read @azure/mcp version from Dockerfile instead of hardcoding (CONCERNS 8.2)"
```

---

## Chunk 3: CI Build Version Logging (Task 13-03)

### Task 13-03: Log Installed Agent Package Versions After Base Image Build

**Files:**
- Modify: `.github/workflows/base-image.yml`

**Context:** After the base image is built and pushed to ACR, there's no record of which exact package versions were installed. We add a new `log-versions` job in `base-image.yml` that runs after `build-base` completes.

**CRITICAL STRUCTURAL NOTE:** The `build-base` job uses `uses: ./.github/workflows/docker-push.yml` (a reusable workflow). You CANNOT add `steps:` to a `uses:`-based job — it has no `steps:` array. The version logger MUST be a separate job with `needs: build-base` and its own `steps:` block. This new job also requires an ACR login step before running `docker run` (the job starts from a fresh runner with no docker credentials).

- [ ] **Step 1: Read the current `base-image.yml` to confirm structure**

```bash
cat .github/workflows/base-image.yml
```

Confirm:
- `build-base` is `uses: ./.github/workflows/docker-push.yml` (reusable workflow — no steps to add to)
- `vars.ACR_LOGIN_SERVER` is the ACR login server variable name
- Other jobs after `build-base` use `needs: build-base` — the new job follows this pattern

- [ ] **Step 2: Add `log-versions` job to `base-image.yml`**

After the `build-base` job block and before `build-orchestrator`, add a new top-level job:

```yaml
  log-versions:
    name: Log installed agent package versions
    if: ${{ github.event_name != 'pull_request' && github.ref == 'refs/heads/main' }}
    needs: build-base
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - name: Azure login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Docker login to ACR
        run: az acr login --name ${{ vars.ACR_LOGIN_SERVER }}

      - name: Log installed agent package versions to job summary
        run: |
          docker run --rm ${{ vars.ACR_LOGIN_SERVER }}/agents/base:${{ github.sha }} \
            pip show \
              agent-framework \
              azure-ai-agentserver-core \
              azure-ai-agentserver-agentframework \
              azure-ai-projects \
              azure-ai-agents \
            >> "$GITHUB_STEP_SUMMARY"
```

**Note:** `continue-on-error: true` is on the job-level (not step-level) so any step failure (including docker login or pull failure) does not fail the workflow.

- [ ] **Step 3: Validate the YAML syntax**

```bash
python3 -c "
import yaml
with open('.github/workflows/base-image.yml') as f:
    yaml.safe_load(f)
print('YAML syntax valid')
"
```

Expected: `YAML syntax valid`

- [ ] **Step 4: Verify the new job is correctly structured**

```bash
grep -A5 "log-versions:" .github/workflows/base-image.yml
```

Expected: Shows `needs: build-base`, `continue-on-error: true`, and `steps:`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/base-image.yml
git commit -m "ci(base-image): add separate log-versions job after build-base to log installed package versions to Actions summary (CONCERNS 6.3)"
```

---

## Verification Checklist

- [ ] `grep "azure-ai-agentserver-core" agents/requirements-base.txt` — shows `==X.Y.Z` version pin
- [ ] `grep "azure-ai-agentserver-agentframework" agents/requirements-base.txt` — shows `==X.Y.Z` version pin
- [ ] `grep "2\.0\.0-beta\.34" scripts/deploy-azure-mcp-server.sh` — zero matches
- [ ] `bash -c 'AZURE_MCP_VERSION=$(grep "ARG AZURE_MCP_VERSION=" services/azure-mcp-server/Dockerfile | cut -d= -f2); echo $AZURE_MCP_VERSION'` — prints version from Dockerfile
- [ ] `grep "continue-on-error" .github/workflows/base-image.yml` — shows `true` on logging step
- [ ] `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/base-image.yml'))"` — no errors
- [ ] `pip install -r agents/requirements-base.txt` — installs at pinned versions deterministically
