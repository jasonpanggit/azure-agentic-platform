#!/usr/bin/env bash
# scripts/ops/24-3-noise-reduction-test.sh
#
# INTEL-001 Alert Noise Reduction Simulation Test
#
# Validates INTEL-001: Alert noise reduction >=80% on correlated alert storm simulations.
#
# Sends 1 root-cause incident followed by 9 cascade incidents from the same topology
# cluster, waits for background processing, then asserts that the noise_reduction_pct
# reported by GET /api/v1/incidents/stats is >= REQUIRED_NOISE_REDUCTION (default: 80%).
#
# Usage:
#   # Local dev (no auth):
#   API_BASE=http://localhost:8080 bash scripts/ops/24-3-noise-reduction-test.sh
#
#   # Against deployed Container App:
#   TOKEN=$(az account get-access-token --resource api://aap-api-gateway --query accessToken -o tsv)
#   API_BASE=https://ca-api-gateway-prod.azurecontainerapps.io \
#   TOKEN="${TOKEN}" \
#   bash scripts/ops/24-3-noise-reduction-test.sh
#
#   # With Entra client credentials (CI):
#   E2E_CLIENT_ID=<app-id> \
#   E2E_CLIENT_SECRET=<secret> \
#   E2E_API_AUDIENCE=api://aap-api-gateway \
#   API_URL=https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io \
#   bash scripts/ops/24-3-noise-reduction-test.sh
#
# Required env vars:
#   API_URL                  — overrides API_BASE (matches deployment convention)
#
# Optional env vars:
#   API_BASE                 — base URL of the API gateway (default: http://localhost:8080)
#   TOKEN                    — Entra Bearer token (acquired via az cli if not set)
#   E2E_CLIENT_ID            — App registration client ID for client-credentials token flow
#   E2E_CLIENT_SECRET        — Client secret for client-credentials token flow
#   E2E_API_AUDIENCE         — API audience for token request (default: api://aap-api-gateway)
#   REQUIRED_NOISE_REDUCTION — Minimum noise reduction % to pass INTEL-001 (default: 80)
#   WINDOW_HOURS             — Stats window in hours (default: 1)
#
# Exit codes:
#   0 — INTEL-001 PASS (noise_reduction_pct >= REQUIRED_NOISE_REDUCTION)
#   1 — INTEL-001 FAIL (noise_reduction_pct < REQUIRED_NOISE_REDUCTION or error)

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# API_URL takes precedence over API_BASE (aligns with deployment env var convention).
API_BASE="${API_URL:-${API_BASE:-http://localhost:8080}}"
TOKEN="${TOKEN:-}"
WINDOW_HOURS="${WINDOW_HOURS:-1}"
REQUIRED_NOISE_REDUCTION="${REQUIRED_NOISE_REDUCTION:-80}"

# Entra client-credentials flow (CI use case)
E2E_CLIENT_ID="${E2E_CLIENT_ID:-}"
E2E_CLIENT_SECRET="${E2E_CLIENT_SECRET:-}"
E2E_API_AUDIENCE="${E2E_API_AUDIENCE:-api://aap-api-gateway}"

# Shared topology cluster — resource IDs that form a real blast-radius neighborhood.
# All cascade incidents reference resources from this same cluster so that
# check_causal_suppression and check_temporal_topological_correlation can fire.
SUBSCRIPTION_ID="00000000-test-0000-0000-000000000001"
ROOT_RESOURCE_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/virtualMachines/vm-root-001"

# ---------------------------------------------------------------------------
# Pre-flight: verify required tools
# ---------------------------------------------------------------------------

if ! command -v curl &>/dev/null; then
    echo "ERROR: curl is required but not found in PATH"
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 is required but not found in PATH"
    exit 1
fi

# ---------------------------------------------------------------------------
# Token acquisition
# ---------------------------------------------------------------------------

# Option 1: Client-credentials token flow (CI — E2E_CLIENT_ID + E2E_CLIENT_SECRET)
if [[ -z "${TOKEN}" && -n "${E2E_CLIENT_ID}" && -n "${E2E_CLIENT_SECRET}" ]]; then
    echo "[intel-001] Acquiring token via client-credentials flow..."
    # Resolve tenant from az cli if available
    TENANT_ID=$(az account show --query tenantId -o tsv 2>/dev/null || true)
    if [[ -n "${TENANT_ID}" ]]; then
        TOKEN_RESPONSE=$(curl -sf -X POST \
            "https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token" \
            -d "client_id=${E2E_CLIENT_ID}" \
            -d "client_secret=${E2E_CLIENT_SECRET}" \
            -d "scope=${E2E_API_AUDIENCE}/.default" \
            -d "grant_type=client_credentials" 2>/dev/null || true)
        TOKEN=$(echo "${TOKEN_RESPONSE}" | python3 -c \
            "import sys, json; d=json.load(sys.stdin); print(d.get('access_token',''))" \
            2>/dev/null || true)
        if [[ -n "${TOKEN}" ]]; then
            echo "[intel-001] Token acquired via client-credentials flow."
        else
            echo "[intel-001] WARNING: client-credentials token request failed."
        fi
    else
        echo "[intel-001] WARNING: Could not resolve tenant ID — skipping client-credentials flow."
    fi
fi

# Option 2: az cli token (developer workstations)
if [[ -z "${TOKEN}" ]]; then
    echo "[intel-001] Attempting token acquisition via az cli..."
    TOKEN=$(az account get-access-token \
        --resource "${E2E_API_AUDIENCE}" \
        --query accessToken \
        -o tsv 2>/dev/null || true)
    if [[ -n "${TOKEN}" ]]; then
        echo "[intel-001] Token acquired via az cli."
    else
        echo "[intel-001] WARNING: Could not acquire token via az cli."
        echo "[intel-001] Set TOKEN env var or ensure 'az login' is complete."
        echo "[intel-001] Proceeding without auth (will work if auth is disabled in dev)."
    fi
fi

AUTH_HEADER=""
if [[ -n "${TOKEN}" ]]; then
    AUTH_HEADER="Authorization: Bearer ${TOKEN}"
fi

# ---------------------------------------------------------------------------
# Helper: send_incident
#
# Arguments:
#   $1 — incident_id
#   $2 — resource_id
#   $3 — severity   (default: Sev2)
#   $4 — domain     (default: compute)
#   $5 — title
#
# Outputs the raw curl response including "HTTP_STATUS:<code>" trailer.
# ---------------------------------------------------------------------------

send_incident() {
    local incident_id="$1"
    local resource_id="$2"
    local severity="${3:-Sev2}"
    local domain="${4:-compute}"
    local title="$5"

    local payload
    payload=$(python3 -c "
import json
print(json.dumps({
    'incident_id': '${incident_id}',
    'severity': '${severity}',
    'domain': '${domain}',
    'title': '''${title}''',
    'detection_rule': 'INTEL001_StormTest',
    'affected_resources': [{
        'resource_id': '''${resource_id}''',
        'subscription_id': '${SUBSCRIPTION_ID}',
        'resource_type': 'Microsoft.Compute/virtualMachines',
    }],
    'kql_evidence': 'INTEL-001 simulation - noise reduction test',
}))
" 2>/dev/null || echo "PAYLOAD_ERROR")

    if [[ "${payload}" == "PAYLOAD_ERROR" ]]; then
        echo "CURL_ERROR"
        return
    fi

    local response
    if [[ -n "${AUTH_HEADER}" ]]; then
        response=$(curl -s -X POST \
            "${API_BASE}/api/v1/incidents" \
            -H "Content-Type: application/json" \
            -H "${AUTH_HEADER}" \
            -d "${payload}" \
            -w "\nHTTP_STATUS:%{http_code}" 2>&1 || echo "CURL_ERROR")
    else
        response=$(curl -s -X POST \
            "${API_BASE}/api/v1/incidents" \
            -H "Content-Type: application/json" \
            -d "${payload}" \
            -w "\nHTTP_STATUS:%{http_code}" 2>&1 || echo "CURL_ERROR")
    fi

    echo "${response}"
}

# ---------------------------------------------------------------------------
# Helper: query_stats
#
# Arguments:
#   $1 — window_hours (default: 1)
#
# Outputs the raw curl response including "HTTP_STATUS:<code>" trailer.
# ---------------------------------------------------------------------------

query_stats() {
    local window_h="${1:-1}"
    local response

    if [[ -n "${AUTH_HEADER}" ]]; then
        response=$(curl -s \
            "${API_BASE}/api/v1/incidents/stats?window_hours=${window_h}" \
            -H "${AUTH_HEADER}" \
            -w "\nHTTP_STATUS:%{http_code}" 2>&1 || echo "CURL_ERROR")
    else
        response=$(curl -s \
            "${API_BASE}/api/v1/incidents/stats?window_hours=${window_h}" \
            -w "\nHTTP_STATUS:%{http_code}" 2>&1 || echo "CURL_ERROR")
    fi

    echo "${response}"
}

# ---------------------------------------------------------------------------
# Helper: extract_json_field
#
# Extracts a numeric field from a JSON string using python3.
# Returns "0" on failure (non-blocking).
# ---------------------------------------------------------------------------

extract_json_field() {
    local json="$1"
    local field="$2"
    python3 -c "
import sys, json
try:
    d = json.loads('''${json}''')
    print(d.get('${field}', 0))
except Exception:
    print(0)
" 2>/dev/null || echo "0"
}

# ---------------------------------------------------------------------------
# Main test body
# ---------------------------------------------------------------------------

echo ""
echo "============================================================"
echo " INTEL-001: Alert Noise Reduction Simulation Test"
echo " API: ${API_BASE}"
echo " Threshold: >= ${REQUIRED_NOISE_REDUCTION}% noise reduction"
echo " Window: ${WINDOW_HOURS}h"
echo "============================================================"
echo ""

# --- Pre-test baseline ---
echo "[intel-001] Recording pre-test baseline..."
BASELINE_STATS=$(query_stats "${WINDOW_HOURS}")
BASELINE_BODY=$(echo "${BASELINE_STATS}" | grep -v "HTTP_STATUS:")
BASELINE_HTTP=$(echo "${BASELINE_STATS}" | grep "HTTP_STATUS:" | sed 's/HTTP_STATUS://')

if [[ "${BASELINE_BODY}" == "CURL_ERROR" ]]; then
    echo "[intel-001] ERROR: Cannot reach API at ${API_BASE}"
    echo "[intel-001] Verify API_BASE/API_URL is correct and the gateway is running."
    exit 1
fi

BASELINE_TOTAL=$(extract_json_field "${BASELINE_BODY}" "total")
echo "[intel-001] Baseline total incidents in window: ${BASELINE_TOTAL} (HTTP ${BASELINE_HTTP})"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Send root-cause incident
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "[intel-001] ─────────────────────────────────────────────"
echo "[intel-001] Step 1: Sending root-cause incident..."
ROOT_INCIDENT_ID="intel001-root-$(date +%s)"
ROOT_RESPONSE=$(send_incident \
    "${ROOT_INCIDENT_ID}" \
    "${ROOT_RESOURCE_ID}" \
    "Sev1" \
    "compute" \
    "INTEL-001 Root Cause: vm-root-001 high CPU - storm test")

ROOT_STATUS=$(echo "${ROOT_RESPONSE}" | grep "HTTP_STATUS:" | sed 's/HTTP_STATUS://')
ROOT_BODY=$(echo "${ROOT_RESPONSE}" | grep -v "HTTP_STATUS:" | head -1)

echo "[intel-001] Root incident ID  : ${ROOT_INCIDENT_ID}"
echo "[intel-001] Root HTTP status  : ${ROOT_STATUS}"

if [[ "${ROOT_RESPONSE}" == "CURL_ERROR" ]]; then
    echo "[intel-001] ERROR: Failed to send root incident (curl error)."
    echo "[intel-001] Verify API_BASE is correct and the gateway is reachable."
    exit 1
fi

# Wait briefly for topology blast_radius to propagate to the root incident document.
# The causal suppression algorithm reads blast_radius_summary from this document.
echo "[intel-001] Waiting 2s for blast_radius propagation..."
sleep 2

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Send 9 cascade incidents from the same topology cluster
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "[intel-001] ─────────────────────────────────────────────"
echo "[intel-001] Step 2: Sending 9 cascade incidents from topology cluster..."

# Resource IDs in the same topology cluster as ROOT_RESOURCE_ID.
# These simulate downstream resources in the blast radius that should be
# suppressed or correlated against the root-cause incident.
CASCADE_RESOURCES=(
    "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-intel001-test/providers/Microsoft.Network/networkInterfaces/nic-root-001"
    "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/disks/disk-root-001"
    "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-intel001-test/providers/Microsoft.Network/virtualNetworks/vnet-prod-001"
    "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/virtualMachines/vm-cascade-001"
    "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/virtualMachines/vm-cascade-002"
    "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/virtualMachines/vm-cascade-003"
    "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-intel001-test/providers/Microsoft.Network/networkInterfaces/nic-cascade-001"
    "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-intel001-test/providers/Microsoft.Network/networkInterfaces/nic-cascade-002"
    "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-intel001-test/providers/Microsoft.Compute/disks/disk-cascade-001"
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
        "INTEL-001 Cascade $((i + 1)): downstream alert from topology cluster")
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

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: Allow background tasks to complete
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "[intel-001] ─────────────────────────────────────────────"
echo "[intel-001] Step 3: Waiting 3s for background processing..."
echo "[intel-001] (topology sync, change correlator, blast_radius updates)"
sleep 3

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: Query noise reduction stats
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "[intel-001] ─────────────────────────────────────────────"
echo "[intel-001] Step 4: Querying noise reduction stats (window=${WINDOW_HOURS}h)..."
STATS_RESPONSE=$(query_stats "${WINDOW_HOURS}")
STATS_BODY=$(echo "${STATS_RESPONSE}" | grep -v "HTTP_STATUS:")
STATS_HTTP=$(echo "${STATS_RESPONSE}" | grep "HTTP_STATUS:" | sed 's/HTTP_STATUS://')

echo "[intel-001] Stats HTTP status: ${STATS_HTTP}"
echo "[intel-001] Stats response:"
echo "${STATS_BODY}" | python3 -m json.tool 2>/dev/null || echo "${STATS_BODY}"

if [[ "${STATS_BODY}" == "CURL_ERROR" ]]; then
    echo "[intel-001] ERROR: Failed to query stats endpoint."
    exit 1
fi

# Parse stats fields
TOTAL=$(extract_json_field "${STATS_BODY}" "total")
SUPPRESSED=$(extract_json_field "${STATS_BODY}" "suppressed")
CORRELATED=$(extract_json_field "${STATS_BODY}" "correlated")
NOISE_PCT=$(extract_json_field "${STATS_BODY}" "noise_reduction_pct")

# Net totals: subtract baseline to isolate this test run from ambient traffic
NET_TOTAL=$(( TOTAL - BASELINE_TOTAL ))

echo ""
echo "[intel-001] ─────────────────────────────────────────────"
echo "[intel-001] Results (window=${WINDOW_HOURS}h):"
echo "[intel-001]   Total in window : ${TOTAL} (baseline: ${BASELINE_TOTAL}, net: ${NET_TOTAL})"
echo "[intel-001]   Suppressed      : ${SUPPRESSED}"
echo "[intel-001]   Correlated      : ${CORRELATED}"
echo "[intel-001]   Noise reduced   : ${SUPPRESSED} + ${CORRELATED} = $(( SUPPRESSED + CORRELATED ))"
echo "[intel-001]   Noise reduction : ${NOISE_PCT}%"
echo "[intel-001] ─────────────────────────────────────────────"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: Assert INTEL-001
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "[intel-001] Step 5: Asserting INTEL-001 (>= ${REQUIRED_NOISE_REDUCTION}% noise reduction)..."

# Use python3 for reliable float comparison
PASS=$(python3 -c "
try:
    pct = float('${NOISE_PCT}')
    threshold = float('${REQUIRED_NOISE_REDUCTION}')
    print('yes' if pct >= threshold else 'no')
except Exception:
    print('no')
" 2>/dev/null || echo "no")

echo ""
if [[ "${PASS}" == "yes" ]]; then
    echo "============================================================"
    echo " INTEL-001 PASS"
    echo "     Noise reduction: ${NOISE_PCT}% >= ${REQUIRED_NOISE_REDUCTION}%"
    echo "     Suppressed: ${SUPPRESSED}  Correlated: ${CORRELATED}  Total: ${TOTAL}"
    echo "     Root incident: ${ROOT_INCIDENT_ID}"
    echo "     Cascade incidents sent: ${CASCADE_SENT}/9"
    echo "============================================================"
    exit 0
else
    echo "============================================================"
    echo " INTEL-001 FAIL"
    echo "     Noise reduction: ${NOISE_PCT}% < ${REQUIRED_NOISE_REDUCTION}%"
    echo "     Suppressed: ${SUPPRESSED}  Correlated: ${CORRELATED}  Total: ${TOTAL}"
    echo "     Root incident: ${ROOT_INCIDENT_ID}"
    echo "     Cascade incidents sent: ${CASCADE_SENT}/9"
    echo ""
    echo "     Troubleshooting checklist:"
    echo "     - Is NOISE_SUPPRESSION_ENABLED=true on the gateway?"
    echo "     - Is the topology service initialized?"
    echo "       (COSMOS_ENDPOINT + SUBSCRIPTION_IDS must be set on the Container App)"
    echo "     - Did the root incident write a blast_radius_summary to Cosmos?"
    echo "       Run: GET ${API_BASE}/api/v1/incidents/${ROOT_INCIDENT_ID}"
    echo "       and verify blast_radius_summary.affected_resources is populated."
    echo "     - Are cascade resource IDs in the topology graph for ${SUBSCRIPTION_ID}?"
    echo "     - Is the WINDOW_HOURS (${WINDOW_HOURS}h) window wide enough?"
    echo "       Try increasing it: WINDOW_HOURS=2 bash scripts/ops/24-3-noise-reduction-test.sh"
    echo "     - Is there ambient test traffic diluting noise_reduction_pct?"
    echo "       Check NET_TOTAL (${NET_TOTAL}) — if much less than 10, earlier requests failed."
    echo "============================================================"
    exit 1
fi
