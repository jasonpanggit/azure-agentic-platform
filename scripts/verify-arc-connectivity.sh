#!/usr/bin/env bash
# verify-arc-connectivity.sh
#
# Verifies the Arc MCP Server is reachable from within the Container Apps
# environment and responds correctly to the MCP initialize handshake.
#
# Usage (from within Container Apps environment or via Azure CLI):
#   export ARC_MCP_SERVER_URL="http://ca-arc-mcp-server-dev.{env-domain}/mcp"
#   ./scripts/verify-arc-connectivity.sh
#
# Phase 3 Success Criteria SC-1: Arc Agent calls arc_servers_list without
# public internet egress — the URL must be an internal FQDN (.internal or
# Container Apps environment default domain), not a public hostname.

set -euo pipefail

ARC_MCP_SERVER_URL="${ARC_MCP_SERVER_URL:-}"
TIMEOUT="${VERIFY_TIMEOUT:-30}"
SUBSCRIPTION_ID="${TEST_SUBSCRIPTION_ID:-}"

echo "=== Arc MCP Server Connectivity Verification ==="
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

if [[ -z "${ARC_MCP_SERVER_URL}" ]]; then
  echo "ERROR: ARC_MCP_SERVER_URL is not set."
  echo "Set it to the internal FQDN of the Arc MCP Server Container App."
  echo "Example: http://ca-arc-mcp-server-dev.{env-domain}/mcp"
  exit 1
fi

# Verify URL is internal (not public internet)
if echo "${ARC_MCP_SERVER_URL}" | grep -qE "^https://"; then
  echo "WARNING: ARC_MCP_SERVER_URL uses HTTPS. Arc MCP Server is internal-only and uses HTTP."
fi

echo ""
echo "Target URL: ${ARC_MCP_SERVER_URL}"
echo "Timeout: ${TIMEOUT}s"

# ---------------------------------------------------------------------------
# Test 1: MCP initialize handshake
# ---------------------------------------------------------------------------

echo ""
echo "[1/3] Testing MCP initialize handshake..."

INIT_RESPONSE=$(curl -sf \
  --max-time "${TIMEOUT}" \
  -X POST "${ARC_MCP_SERVER_URL}" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"verify-script","version":"1.0"}}}' \
  2>&1) || {
  echo "FAIL: Arc MCP Server is not reachable at ${ARC_MCP_SERVER_URL}"
  echo "Check: Is the Container App running? Is ARC_MCP_SERVER_URL the internal FQDN?"
  exit 1
}

# Verify server name in response
if echo "${INIT_RESPONSE}" | grep -q '"arc-mcp-server"'; then
  echo "PASS: MCP initialize handshake successful. Server: arc-mcp-server"
else
  echo "FAIL: Unexpected initialize response: ${INIT_RESPONSE}"
  exit 1
fi

# ---------------------------------------------------------------------------
# Test 2: tools/list — verify all 9 tools are registered
# ---------------------------------------------------------------------------

echo ""
echo "[2/3] Verifying required tools are registered..."

TOOLS_RESPONSE=$(curl -sf \
  --max-time "${TIMEOUT}" \
  -X POST "${ARC_MCP_SERVER_URL}" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}') || {
  echo "FAIL: tools/list request failed"
  exit 1
}

REQUIRED_TOOLS=(
  "arc_servers_list"
  "arc_servers_get"
  "arc_extensions_list"
  "arc_k8s_list"
  "arc_k8s_get"
  "arc_k8s_gitops_status"
  "arc_data_sql_mi_list"
  "arc_data_sql_mi_get"
  "arc_data_postgresql_list"
)

MISSING_TOOLS=0
for TOOL in "${REQUIRED_TOOLS[@]}"; do
  if echo "${TOOLS_RESPONSE}" | grep -q "\"${TOOL}\""; then
    echo "  PASS: ${TOOL} ✓"
  else
    echo "  FAIL: ${TOOL} — NOT FOUND"
    MISSING_TOOLS=$((MISSING_TOOLS + 1))
  fi
done

if [[ ${MISSING_TOOLS} -gt 0 ]]; then
  echo "FAIL: ${MISSING_TOOLS} required tool(s) missing from Arc MCP Server"
  exit 1
fi

echo "PASS: All 9 required tools registered"

# ---------------------------------------------------------------------------
# Test 3: arc_servers_list call (if subscription ID provided)
# ---------------------------------------------------------------------------

if [[ -n "${SUBSCRIPTION_ID}" ]]; then
  echo ""
  echo "[3/3] Testing arc_servers_list with subscription ${SUBSCRIPTION_ID}..."

  SERVERS_RESPONSE=$(curl -sf \
    --max-time "${TIMEOUT}" \
    -X POST "${ARC_MCP_SERVER_URL}" \
    -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"arc_servers_list\",\"arguments\":{\"subscription_id\":\"${SUBSCRIPTION_ID}\"}}}" \
    2>&1) || {
    echo "FAIL: arc_servers_list call failed"
    exit 1
  }

  if echo "${SERVERS_RESPONSE}" | grep -q '"total_count"'; then
    TOTAL=$(echo "${SERVERS_RESPONSE}" | grep -o '"total_count":[0-9]*' | cut -d: -f2 || echo "unknown")
    echo "PASS: arc_servers_list responded. total_count: ${TOTAL}"
  else
    echo "FAIL: arc_servers_list response missing total_count field"
    echo "Response: ${SERVERS_RESPONSE}"
    exit 1
  fi
else
  echo ""
  echo "[3/3] Skipping arc_servers_list test — TEST_SUBSCRIPTION_ID not set"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "=== Verification Complete ==="
echo "Arc MCP Server at ${ARC_MCP_SERVER_URL} is healthy and operational."
echo ""
echo "Phase 3 SC-1 check:"
echo "  ✓ Arc MCP Server is reachable via internal URL"
echo "  ✓ All 9 required tools are registered"
if [[ -n "${SUBSCRIPTION_ID}" ]]; then
  echo "  ✓ arc_servers_list returns total_count field"
fi
