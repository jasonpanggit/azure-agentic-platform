# Plan 21-3: Pipeline Health Monitoring

---
wave: 2
depends_on:
  - 21-1-terraform-activation-PLAN.md
files_modified:
  - scripts/ops/21-3-detection-health-check.sh
requirements:
  - PROD-004
autonomous: true
---

## Objective

Create a reusable health-check script that operators can run on-demand (or schedule via cron/CI) to verify the detection pipeline is alive and flowing data. This script queries the API gateway, checks Cosmos DB for recent `det-` prefixed incidents, and validates the end-to-end path is working without simulation scripts. This is the ongoing operational assurance that PROD-004 remains satisfied.

## Tasks

<task id="21-3-01">
<title>Create detection pipeline health check script</title>
<read_first>
- scripts/ops/21-2-activate-detection-plane.sh (the activation runbook — this script is the ongoing health check companion)
- scripts/ops/19-3-register-mcp-connections.sh (style reference for Azure CLI + API validation scripts)
- services/detection-plane/models.py (IncidentRecord schema — status field values)
- services/detection-plane/payload_mapper.py (det- prefix on incident_id)
- services/api-gateway/models.py (IncidentPayload schema if needed for reference)
</read_first>
<action>
Create `scripts/ops/21-3-detection-health-check.sh` with the following structure:

```bash
#!/usr/bin/env bash
# Phase 21: Detection Pipeline Health Check
#
# Run this script periodically to verify the live detection loop is operational.
# PROD-004: Live alert detection loop operational without simulation scripts.
#
# Usage:
#   bash scripts/ops/21-3-detection-health-check.sh
#
# Optional env vars:
#   API_URL        - API gateway URL (default: https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io)
#   E2E_CLIENT_ID  - Service principal client ID for auth token
#   E2E_CLIENT_SECRET - Service principal secret
#   E2E_API_AUDIENCE  - API audience (default: api://505df1d3-3bd3-4151-ae87-6e5974b72a44)

set -euo pipefail
```

The script should have these sections:

1. **Constants and defaults**:
   - `RESOURCE_GROUP="rg-aap-prod"`
   - `API_URL="${API_URL:-https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io}"`
   - `TENANT_ID="abbdca26-d233-4a1e-9d8c-c4eebbc16e50"`
   - `PASS_COUNT=0` / `FAIL_COUNT=0` / `SKIP_COUNT=0`

2. **Helper functions**:
   - `pass_check()` — increment PASS_COUNT, echo green checkmark with message
   - `fail_check()` — increment FAIL_COUNT, echo red X with message
   - `skip_check()` — increment SKIP_COUNT, echo yellow dash with message

3. **Check 1: Fabric capacity status** — `az resource show --ids "/subscriptions/.../resourceGroups/rg-aap-prod/providers/Microsoft.Fabric/capacities/fcaapprod" --query "properties.state" -o tsv`. Pass if `Active`.

4. **Check 2: Fabric workspace exists** — `az rest --method GET --url "https://api.fabric.microsoft.com/v1/workspaces" --headers "Authorization=Bearer $(az account get-access-token --resource https://analysis.windows.net/powerbi/api --query accessToken -o tsv)" 2>/dev/null | python3 -c "import sys,json; ws=[w for w in json.load(sys.stdin).get('value',[]) if w.get('displayName')=='aap-prod']; sys.exit(0 if ws else 1)"`. Pass if workspace `aap-prod` is found in the list.

5. **Check 3: Event Hub namespace health** — `az eventhubs namespace show --name ehns-aap-prod --resource-group rg-aap-prod --query "status" -o tsv`. Pass if `Active`.

6. **Check 4: Event Hub has recent messages** — `az eventhubs eventhub show --name eh-alerts-prod --namespace-name ehns-aap-prod --resource-group rg-aap-prod --query "messageRetentionInDays" -o tsv`. Pass if > 0 (hub exists and configured).

7. **Check 5: API gateway health** — `curl -sf "${API_URL}/health" -o /dev/null`. Pass if HTTP 200.

8. **Check 6: Recent incidents with det- prefix (requires auth token)** — If `E2E_CLIENT_ID` is set, acquire token and call `GET ${API_URL}/api/v1/incidents?limit=5`, check if any incident_id starts with `det-`. Pass if at least 1 found, skip if no auth token.

9. **Check 7: Container App running** — `az containerapp show --name ca-api-gateway-prod --resource-group rg-aap-prod --query "properties.runningStatus.state" -o tsv 2>/dev/null || echo "Unknown"`. Pass if running.

10. **Summary** section at the end:
    ```
    === Detection Pipeline Health Check Summary ===
    PASSED: ${PASS_COUNT}
    FAILED: ${FAIL_COUNT}
    SKIPPED: ${SKIP_COUNT}

    PROD-004 Status: [HEALTHY | DEGRADED | UNHEALTHY]
    ```
    - HEALTHY = 0 failures
    - DEGRADED = some checks failed but API gateway is up
    - UNHEALTHY = API gateway down or Fabric capacity not Active

11. Exit with code 0 if HEALTHY, 1 if DEGRADED or UNHEALTHY.

Make the file executable: `chmod +x scripts/ops/21-3-detection-health-check.sh`
</action>
<acceptance_criteria>
- File exists at `scripts/ops/21-3-detection-health-check.sh`
- `head -1 scripts/ops/21-3-detection-health-check.sh` outputs `#!/usr/bin/env bash`
- `grep "set -euo pipefail" scripts/ops/21-3-detection-health-check.sh` returns a match
- `grep "PROD-004" scripts/ops/21-3-detection-health-check.sh` returns at least 2 matches (header + summary)
- `grep "fcaapprod" scripts/ops/21-3-detection-health-check.sh` returns at least 1 match
- `grep "ehns-aap-prod" scripts/ops/21-3-detection-health-check.sh` returns at least 1 match
- `grep "eh-alerts-prod" scripts/ops/21-3-detection-health-check.sh` returns at least 1 match
- `grep "det-" scripts/ops/21-3-detection-health-check.sh` returns at least 1 match
- `grep "HEALTHY" scripts/ops/21-3-detection-health-check.sh` returns at least 1 match
- `grep "DEGRADED" scripts/ops/21-3-detection-health-check.sh` returns at least 1 match
- `grep "PASS_COUNT" scripts/ops/21-3-detection-health-check.sh` returns at least 1 match
- `grep "FAIL_COUNT" scripts/ops/21-3-detection-health-check.sh` returns at least 1 match
- `grep "/health" scripts/ops/21-3-detection-health-check.sh` returns at least 1 match
- `test -x scripts/ops/21-3-detection-health-check.sh` exits 0 (executable)
- `bash -n scripts/ops/21-3-detection-health-check.sh` exits 0 (valid bash syntax)
</acceptance_criteria>
</task>

<task id="21-3-02">
<title>Add health check reference to operator documentation</title>
<read_first>
- docs/ops/detection-plane-activation.md (the documentation created in plan 21-2)
- scripts/ops/21-3-detection-health-check.sh (the health check script)
</read_first>
<action>
Append a new section to `docs/ops/detection-plane-activation.md` at the bottom (before any closing markers):

```markdown
## Ongoing Health Monitoring

After the detection plane is activated, use the health check script to verify the pipeline remains operational:

```bash
# Basic health check (no auth required for infrastructure checks)
bash scripts/ops/21-3-detection-health-check.sh

# Full health check including incident verification (requires auth)
export E2E_CLIENT_ID="<client-id>"
export E2E_CLIENT_SECRET="<client-secret>"
bash scripts/ops/21-3-detection-health-check.sh
```

### Health Check Coverage

| Check | What it validates | Requires auth |
|-------|-------------------|---------------|
| Fabric capacity | Capacity is Active | No |
| Fabric workspace | Workspace exists | No |
| Event Hub namespace | Namespace is Active | No |
| Event Hub messages | Hub is configured | No |
| API gateway | Health endpoint returns 200 | No |
| Recent det- incidents | Pipeline is creating incidents | Yes |
| Container App status | Gateway is running | No |

### Recommended Schedule

- **Manual**: After any Terraform apply that touches the fabric module
- **CI**: Add to staging-e2e workflow as a post-deploy check
- **Cron**: Daily at 06:00 UTC for production alerting
```
</action>
<acceptance_criteria>
- `grep "Ongoing Health Monitoring" docs/ops/detection-plane-activation.md` returns at least 1 match
- `grep "21-3-detection-health-check" docs/ops/detection-plane-activation.md` returns at least 1 match
- `grep "Recommended Schedule" docs/ops/detection-plane-activation.md` returns at least 1 match
</acceptance_criteria>
</task>

## Verification

After all tasks complete:
1. `scripts/ops/21-3-detection-health-check.sh` exists, is executable, and passes `bash -n` syntax check
2. Script has 7 numbered health checks covering Fabric, Event Hub, API gateway, and incident verification
3. Script outputs a summary with PASSED/FAILED/SKIPPED counts and a PROD-004 status
4. Operator documentation references the health check script and recommends a schedule

## must_haves

- [ ] Health check script at `scripts/ops/21-3-detection-health-check.sh` passes bash syntax check
- [ ] Script checks Fabric capacity status
- [ ] Script checks Event Hub namespace health
- [ ] Script checks API gateway health endpoint
- [ ] Script checks for `det-` prefixed incidents when auth is available
- [ ] Script outputs PROD-004 status (HEALTHY/DEGRADED/UNHEALTHY)
- [ ] Script exits with code 0 for healthy, 1 for degraded/unhealthy
- [ ] Operator documentation references the health check script
