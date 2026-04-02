#!/usr/bin/env bash
# validate-staging-auth.sh — Plan 19-2 Task 8: Staging end-to-end auth validation
#
# Usage:
#   export TOKEN=$(az account get-access-token --resource "api://505df1d3-3bd3-4151-ae87-6e5974b72a44" --query accessToken -o tsv)
#   ./scripts/auth-validation/validate-staging-auth.sh
#
# Prerequisites:
#   - az CLI authenticated (az login)
#   - API_GATEWAY_AUTH_MODE=entra set on ca-api-gateway-staging
#   - TOKEN env var set (see usage above)
#
# Expected outcomes:
#   - /health          → 200 (no auth required)
#   - /health/ready    → 200 or 503 (no auth required, may be not_ready if agent IDs unset)
#   - /api/v1/incidents without token → 401
#   - /api/v1/incidents with valid token → 200 or 404

set -euo pipefail

STAGING_DOMAIN="${STAGING_DOMAIN:-ca-api-gateway-staging.wittypebble-0144adc3.eastus2.azurecontainerapps.io}"
BASE_URL="https://${STAGING_DOMAIN}"

PASS=0
FAIL=0

check() {
  local desc="$1"
  local expected="$2"
  local actual="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  PASS: $desc (HTTP $actual)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc — expected HTTP $expected, got HTTP $actual"
    FAIL=$((FAIL + 1))
  fi
}

echo ""
echo "=== Plan 19-2 Staging Auth Validation ==="
echo "Base URL: $BASE_URL"
echo ""

# 1. Health liveness — must return 200 without auth
echo "--- Check 1: /health (liveness, no auth required) ---"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/health")
check "/health returns 200" "200" "$STATUS"

# 2. Health readiness — must return 200 or 503 without auth
echo "--- Check 2: /health/ready (readiness, no auth required) ---"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/health/ready")
if [ "$STATUS" = "200" ] || [ "$STATUS" = "503" ]; then
  echo "  PASS: /health/ready returns $STATUS (auth not required)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: /health/ready — expected 200 or 503, got $STATUS"
  FAIL=$((FAIL + 1))
fi

# 3. Incidents endpoint WITHOUT token — must reject with 401
echo "--- Check 3: GET /api/v1/incidents without token → 401 ---"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/v1/incidents")
check "/api/v1/incidents without token returns 401" "401" "$STATUS"

# 4. Incidents endpoint WITH valid token — must accept (200 or 404)
if [ -z "${TOKEN:-}" ]; then
  echo "--- Check 4: GET /api/v1/incidents with token → SKIPPED (TOKEN not set) ---"
  echo "  INFO: Set TOKEN env var to run authenticated check."
  echo "  Run: export TOKEN=\$(az account get-access-token --resource \"api://505df1d3-3bd3-4151-ae87-6e5974b72a44\" --query accessToken -o tsv)"
else
  echo "--- Check 4: GET /api/v1/incidents with token → 200 or 404 ---"
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${BASE_URL}/api/v1/incidents")
  if [ "$STATUS" = "200" ] || [ "$STATUS" = "404" ]; then
    echo "  PASS: /api/v1/incidents with token returns $STATUS (auth accepted)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: /api/v1/incidents with token — expected 200 or 404, got $STATUS"
    FAIL=$((FAIL + 1))
  fi
fi

echo ""
echo "=== Results ==="
echo "PASS: $PASS"
echo "FAIL: $FAIL"
echo ""

if [ $FAIL -gt 0 ]; then
  echo "STAGING AUTH VALIDATION FAILED — do NOT proceed to prod."
  echo ""
  echo "Rollback: az containerapp update --name ca-api-gateway-staging --resource-group rg-aap-staging \\"
  echo "          --set-env-vars 'API_GATEWAY_AUTH_MODE=disabled'"
  exit 1
else
  echo "STAGING AUTH VALIDATION PASSED — safe to apply auth changes to prod."
fi
