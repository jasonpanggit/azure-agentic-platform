# Plan 24-3: INTEL-001 Simulation Test

**Phase:** 24 — Alert Intelligence and Noise Reduction
**Wave:** 3 (depends on 24-1 and 24-2 — noise reducer and wiring must be complete)
**Requirement:** INTEL-001 — Alert noise reduction ≥80% on correlated alert storm simulations
**autonomous:** true

---

## Objective

Create `scripts/ops/24-3-noise-reduction-test.sh` — an executable shell script that
validates the INTEL-001 requirement end-to-end by:

1. Seeding 1 root-cause incident via `POST /api/v1/incidents`
2. Sending 9 cascade incidents from the same topology cluster
3. Querying `GET /api/v1/incidents/stats` for suppression/correlation counts
4. Asserting ≥80% of the 10 alerts were suppressed or correlated (≥8 of 10)
5. Reporting **INTEL-001 PASS** or **INTEL-001 FAIL** and exiting 0 or 1

---

## Pre-conditions

Before running this script, the following must be true:

- `services/api-gateway/noise_reducer.py` exists (Wave 1 complete)
- `services/api-gateway/main.py` has noise-reduction wiring (Wave 2 complete)
- API gateway is running and reachable (local or deployed)
- A valid Entra Bearer token is available (via `az account get-access-token`)
- `NOISE_SUPPRESSION_ENABLED=true` (default) on the running gateway

The script does NOT deploy the service or run `terraform apply`. It assumes
the gateway is already running.

---

## File to Create

| Action | Path |
|--------|------|
| CREATE | `scripts/ops/24-3-noise-reduction-test.sh` |

---

## Step 1 — Verify parent directory

Before writing the script, confirm `scripts/ops/` exists:

```bash
ls scripts/ops/
```

If it does not exist, create it:
```bash
mkdir -p scripts/ops
```

---

## Step 2 — Script specification

### File: `scripts/ops/24-3-noise-reduction-test.sh`

```
#!/usr/bin/env bash
set -euo pipefail
```

### Configuration (overridable via env vars)

```bash
API_BASE="${API_BASE:-http://localhost:8080}"
TOKEN="${TOKEN:-}"                          # Entra Bearer token; required
WINDOW_HOURS="${WINDOW_HOURS:-1}"           # Stats window for the assertion
REQUIRED_NOISE_REDUCTION="${REQUIRED_NOISE_REDUCTION:-80}"  # INTEL-001 threshold %

# Shared topology cluster — resource IDs must form a real blast-radius neighborhood.
# All cascade incidents reference resources from this same cluster so that
# check_causal_suppression and check_temporal_topological_correlation can fire.
ROOT_RESOURCE_ID="/subscriptions/00000000-test-0000-0000-000000000001/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/virtualMachines/vm-root-001"
SUBSCRIPTION_ID="00000000-test-0000-0000-000000000001"
```

### Token acquisition (if TOKEN is empty)

```bash
if [[ -z "${TOKEN}" ]]; then
    echo "[intel-001] Acquiring token via az cli..."
    TOKEN=$(az account get-access-token --resource "${API_BASE}" --query accessToken -o tsv 2>/dev/null || true)
    if [[ -z "${TOKEN}" ]]; then
        echo "[intel-001] WARNING: Could not acquire token via az cli."
        echo "[intel-001] Set TOKEN env var or ensure 'az login' is complete."
        echo "[intel-001] Proceeding without auth (will work if auth is disabled in dev)."
    fi
fi

AUTH_HEADER=""
if [[ -n "${TOKEN}" ]]; then
    AUTH_HEADER="Authorization: Bearer ${TOKEN}"
fi
```

### Helper: `send_incident`

```bash
send_incident() {
    local incident_id="$1"
    local resource_id="$2"
    local severity="${3:-Sev2}"
    local domain="${4:-compute}"
    local title="$5"

    local payload
    payload=$(cat <<EOF
{
  "incident_id": "${incident_id}",
  "severity": "${severity}",
  "domain": "${domain}",
  "title": "${title}",
  "detection_rule": "INTEL001_StormTest",
  "affected_resources": [
    {
      "resource_id": "${resource_id}",
      "subscription_id": "${SUBSCRIPTION_ID}",
      "resource_type": "Microsoft.Compute/virtualMachines"
    }
  ],
  "kql_evidence": "INTEL-001 simulation — noise reduction test"
}
EOF
)

    local response
    if [[ -n "${AUTH_HEADER}" ]]; then
        response=$(curl -sf -X POST \
            "${API_BASE}/api/v1/incidents" \
            -H "Content-Type: application/json" \
            -H "${AUTH_HEADER}" \
            -d "${payload}" \
            -w "\nHTTP_STATUS:%{http_code}" 2>&1 || echo "CURL_ERROR")
    else
        response=$(curl -sf -X POST \
            "${API_BASE}/api/v1/incidents" \
            -H "Content-Type: application/json" \
            -d "${payload}" \
            -w "\nHTTP_STATUS:%{http_code}" 2>&1 || echo "CURL_ERROR")
    fi

    echo "${response}"
}
```

### Helper: `query_stats`

```bash
query_stats() {
    local window_h="${1:-1}"
    local response
    if [[ -n "${AUTH_HEADER}" ]]; then
        response=$(curl -sf \
            "${API_BASE}/api/v1/incidents/stats?window_hours=${window_h}" \
            -H "${AUTH_HEADER}" \
            -w "\nHTTP_STATUS:%{http_code}" 2>&1 || echo "CURL_ERROR")
    else
        response=$(curl -sf \
            "${API_BASE}/api/v1/incidents/stats?window_hours=${window_h}" \
            -w "\nHTTP_STATUS:%{http_code}" 2>&1 || echo "CURL_ERROR")
    fi
    echo "${response}"
}
```

### Main test body

```bash
echo ""
echo "============================================================"
echo " INTEL-001: Alert Noise Reduction Simulation Test"
echo " API: ${API_BASE}"
echo " Threshold: >= ${REQUIRED_NOISE_REDUCTION}% noise reduction"
echo "============================================================"
echo ""

# Record baseline stats BEFORE injection to isolate test window counts.
echo "[intel-001] Recording pre-test baseline..."
BASELINE_STATS=$(query_stats "${WINDOW_HOURS}")
BASELINE_TOTAL=$(echo "${BASELINE_STATS}" | python3 -c "import sys,json; d=json.loads([l for l in sys.stdin if not l.startswith('HTTP_STATUS')][0]); print(d['total'])" 2>/dev/null || echo "0")
echo "[intel-001] Baseline total incidents in window: ${BASELINE_TOTAL}"

# --- STEP 1: Send root-cause incident ---
echo ""
echo "[intel-001] Step 1: Sending root-cause incident..."
ROOT_INCIDENT_ID="intel001-root-$(date +%s)"
ROOT_RESPONSE=$(send_incident \
    "${ROOT_INCIDENT_ID}" \
    "${ROOT_RESOURCE_ID}" \
    "Sev1" \
    "compute" \
    "INTEL-001 Root Cause: vm-root-001 high CPU")

ROOT_STATUS=$(echo "${ROOT_RESPONSE}" | grep "HTTP_STATUS:" | sed 's/HTTP_STATUS://')
echo "[intel-001] Root incident response status: ${ROOT_STATUS}"
echo "[intel-001] Root incident ID: ${ROOT_INCIDENT_ID}"

# Wait briefly for topology blast_radius to propagate to root incident doc.
sleep 2

# --- STEP 2: Send 9 cascade incidents from same topology cluster ---
echo ""
echo "[intel-001] Step 2: Sending 9 cascade incidents..."

# Resource IDs in the same topology cluster as ROOT_RESOURCE_ID.
# These simulate downstream resources in the blast radius.
CASCADE_RESOURCES=(
    "/subscriptions/00000000-test-0000-0000-000000000001/resourceGroups/rg-intel001-test/providers/Microsoft.Network/networkInterfaces/nic-root-001"
    "/subscriptions/00000000-test-0000-0000-000000000001/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/disks/disk-root-001"
    "/subscriptions/00000000-test-0000-0000-000000000001/resourceGroups/rg-intel001-test/providers/Microsoft.Network/virtualNetworks/vnet-prod-001"
    "/subscriptions/00000000-test-0000-0000-000000000001/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/virtualMachines/vm-cascade-001"
    "/subscriptions/00000000-test-0000-0000-000000000001/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/virtualMachines/vm-cascade-002"
    "/subscriptions/00000000-test-0000-0000-000000000001/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/virtualMachines/vm-cascade-003"
    "/subscriptions/00000000-test-0000-0000-000000000001/resourceGroups/rg-intel001-test/providers/Microsoft.Network/networkInterfaces/nic-cascade-001"
    "/subscriptions/00000000-test-0000-0000-000000000001/resourceGroups/rg-intel001-test/providers/Microsoft.Network/networkInterfaces/nic-cascade-002"
    "/subscriptions/00000000-test-0000-0000-000000000001/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/disks/disk-cascade-001"
)

CASCADE_SENT=0
for i in "${!CASCADE_RESOURCES[@]}"; do
    RESOURCE="${CASCADE_RESOURCES[$i]}"
    CASCADE_ID="intel001-cascade-$(date +%s)-${i}"
    RESPONSE=$(send_incident \
        "${CASCADE_ID}" \
        "${RESOURCE}" \
        "Sev2" \
        "compute" \
        "INTEL-001 Cascade $(( i + 1 )): downstream alert from topology cluster")
    HTTP_CODE=$(echo "${RESPONSE}" | grep "HTTP_STATUS:" | sed 's/HTTP_STATUS://')
    if [[ "${RESPONSE}" == "CURL_ERROR" ]]; then
        echo "[intel-001]   cascade $((i+1)): CURL_ERROR — skipping"
    else
        echo "[intel-001]   cascade $((i+1)): ID=${CASCADE_ID} HTTP=${HTTP_CODE}"
        CASCADE_SENT=$(( CASCADE_SENT + 1 ))
    fi
    # Small pause to avoid overwhelming the gateway in CI
    sleep 0.2
done
echo "[intel-001] Cascade incidents sent: ${CASCADE_SENT}/9"

# --- STEP 3: Allow background tasks to complete ---
echo ""
echo "[intel-001] Step 3: Waiting 3s for background processing..."
sleep 3

# --- STEP 4: Query stats ---
echo ""
echo "[intel-001] Step 4: Querying noise reduction stats..."
STATS_RESPONSE=$(query_stats "${WINDOW_HOURS}")
STATS_BODY=$(echo "${STATS_RESPONSE}" | grep -v "HTTP_STATUS:")
STATS_HTTP=$(echo "${STATS_RESPONSE}" | grep "HTTP_STATUS:" | sed 's/HTTP_STATUS://')

echo "[intel-001] Stats HTTP status: ${STATS_HTTP}"
echo "[intel-001] Stats response:"
echo "${STATS_BODY}" | python3 -m json.tool 2>/dev/null || echo "${STATS_BODY}"

# Parse stats
TOTAL=$(echo "${STATS_BODY}" | python3 -c "import sys,json; print(json.load(sys.stdin)['total'])" 2>/dev/null || echo "0")
SUPPRESSED=$(echo "${STATS_BODY}" | python3 -c "import sys,json; print(json.load(sys.stdin)['suppressed'])" 2>/dev/null || echo "0")
CORRELATED=$(echo "${STATS_BODY}" | python3 -c "import sys,json; print(json.load(sys.stdin)['correlated'])" 2>/dev/null || echo "0")
NOISE_PCT=$(echo "${STATS_BODY}" | python3 -c "import sys,json; print(json.load(sys.stdin)['noise_reduction_pct'])" 2>/dev/null || echo "0")

# Net counts: subtract baseline to isolate this test run
NET_TOTAL=$(( TOTAL - BASELINE_TOTAL ))
NOISE_REDUCED=$(( SUPPRESSED + CORRELATED ))

echo ""
echo "[intel-001] ─────────────────────────────────────────────"
echo "[intel-001] Results (window=${WINDOW_HOURS}h, net of baseline):"
echo "[intel-001]   Total in window : ${TOTAL} (baseline: ${BASELINE_TOTAL}, net: ${NET_TOTAL})"
echo "[intel-001]   Suppressed      : ${SUPPRESSED}"
echo "[intel-001]   Correlated      : ${CORRELATED}"
echo "[intel-001]   Noise reduction : ${NOISE_PCT}%"
echo "[intel-001] ─────────────────────────────────────────────"

# --- STEP 5: Assert INTEL-001 ---
echo ""
echo "[intel-001] Step 5: Asserting INTEL-001 (>= ${REQUIRED_NOISE_REDUCTION}% noise reduction)..."

# Use python3 for float comparison
PASS=$(python3 -c "print('yes' if float('${NOISE_PCT}') >= float('${REQUIRED_NOISE_REDUCTION}') else 'no')" 2>/dev/null || echo "no")

echo ""
if [[ "${PASS}" == "yes" ]]; then
    echo "============================================================"
    echo " ✅  INTEL-001 PASS"
    echo "     Noise reduction: ${NOISE_PCT}% >= ${REQUIRED_NOISE_REDUCTION}%"
    echo "     Suppressed: ${SUPPRESSED}  Correlated: ${CORRELATED}  Total: ${TOTAL}"
    echo "============================================================"
    exit 0
else
    echo "============================================================"
    echo " ❌  INTEL-001 FAIL"
    echo "     Noise reduction: ${NOISE_PCT}% < ${REQUIRED_NOISE_REDUCTION}%"
    echo "     Suppressed: ${SUPPRESSED}  Correlated: ${CORRELATED}  Total: ${TOTAL}"
    echo ""
    echo "     Checklist:"
    echo "     - Is NOISE_SUPPRESSION_ENABLED=true on the gateway?"
    echo "     - Is the topology service initialized (COSMOS_ENDPOINT + SUBSCRIPTION_IDS set)?"
    echo "     - Did the root incident write a blast_radius_summary to Cosmos?"
    echo "     - Are cascade resource IDs in the topology graph for this subscription?"
    echo "     - Run: GET ${API_BASE}/api/v1/incidents/{ROOT_INCIDENT_ID}"
    echo "       and verify blast_radius_summary.affected_resources is populated."
    echo "============================================================"
    exit 1
fi
```

### End of script

---

## Step 3 — Make the script executable

After writing the file:

```bash
chmod +x scripts/ops/24-3-noise-reduction-test.sh
```

Verify syntax (bash -n check):

```bash
bash -n scripts/ops/24-3-noise-reduction-test.sh
```

---

## Usage

### Local development (no auth)

```bash
# Start gateway locally
uvicorn services.api_gateway.main:app --port 8080

# Run simulation (no token needed in dev if auth is bypassed)
API_BASE=http://localhost:8080 bash scripts/ops/24-3-noise-reduction-test.sh
```

### Against deployed Container App

```bash
TOKEN=$(az account get-access-token --resource api://aap-api-gateway --query accessToken -o tsv)
API_BASE=https://ca-api-gateway-prod.azurecontainerapps.io \
TOKEN="${TOKEN}" \
bash scripts/ops/24-3-noise-reduction-test.sh
```

### CI (GitHub Actions)

```yaml
- name: INTEL-001 Noise Reduction Validation
  env:
    API_BASE: ${{ vars.API_GATEWAY_URL }}
    TOKEN: ${{ steps.get-token.outputs.token }}
    REQUIRED_NOISE_REDUCTION: "80"
  run: bash scripts/ops/24-3-noise-reduction-test.sh
```

---

## Important Caveats

### Topology dependency

The causal suppression algorithm requires that:
1. The root incident's blast-radius was computed and stored in Cosmos
   (happens synchronously in `ingest_incident` via `topology_client.get_blast_radius`)
2. The cascade resource IDs appear in that blast-radius `affected_resources` list

In a dev/test environment without a real Azure subscription, `topology_client` may
be `None` (no `SUBSCRIPTION_IDS` env var set). In that case, suppression will not
fire and the test will FAIL. This is expected — INTEL-001 requires the topology
service to be active.

**To make the test pass in an environment without real Azure topology:** the
`check_causal_suppression` function should fall back to domain+resource-group
matching. However, this is NOT in scope for Phase 24 — the simulation test
documents the requirement that topology must be operational.

### Stats window overlap

The script uses `WINDOW_HOURS=1` by default. If other tests or traffic have recently
created incidents, the noise_reduction_pct may be lower than 80% due to non-suppressed
incidents in the window. The baseline subtraction (step 4) mitigates this for the
net count, but `noise_reduction_pct` comes from the raw stats endpoint which includes
all incidents. If this causes flaky CI, increase specificity:
- Add a unique `detection_rule` to the test incidents and filter stats by it, OR
- Use a very short `WINDOW_HOURS=0` (not supported by current endpoint) — defer to
  Phase 25 if needed.

---

## Acceptance Criteria

- [ ] `scripts/ops/24-3-noise-reduction-test.sh` exists and is executable (`chmod +x`)
- [ ] `bash -n scripts/ops/24-3-noise-reduction-test.sh` passes (no syntax errors)
- [ ] Script exits 0 when `noise_reduction_pct >= 80`
- [ ] Script exits 1 when `noise_reduction_pct < 80`
- [ ] Script prints `INTEL-001 PASS` or `INTEL-001 FAIL` with metric details
- [ ] Script is usable without arguments (uses env var defaults)
- [ ] `TOKEN` env var is optional (script proceeds without auth for dev mode)
- [ ] Script sends exactly 1 root-cause + 9 cascade incidents (10 total)
- [ ] Failure output includes actionable troubleshooting checklist
- [ ] No hardcoded production URLs or secrets in the script
