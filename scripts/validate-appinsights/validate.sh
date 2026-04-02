#!/usr/bin/env bash
# validate.sh — Validate App Insights telemetry for all 12 AAP containers
#
# Uses `az monitor app-insights query` to run the heartbeat KQL query
# and compares results against the 12 expected cloud_RoleName values.
#
# Usage:
#   ./validate.sh                                    # auto-detect from rg-aap-prod
#   ./validate.sh --app <app-insights-resource-id>   # explicit resource ID
#   ./validate.sh --app-name appi-aap-prod --rg rg-aap-prod
#
# Requirements:
#   - Azure CLI (`az`) installed and authenticated
#   - `jq` installed (JSON parsing)
#
# Exit codes:
#   0 — All 12 containers are sending telemetry
#   1 — One or more containers are silent

set -euo pipefail

# ─── Expected containers ──────────────────────────────────────────────────────
EXPECTED_CONTAINERS=(
  "aiops-orchestrator-agent"
  "aiops-compute-agent"
  "aiops-network-agent"
  "aiops-storage-agent"
  "aiops-security-agent"
  "aiops-arc-agent"
  "aiops-sre-agent"
  "aiops-patch-agent"
  "aiops-eol-agent"
  "api-gateway"
  "teams-bot"
  "arc-mcp-server"
)

# ─── Container App name mapping (for remediation hints) ──────────────────────
declare -A CONTAINER_APP_MAP=(
  ["aiops-orchestrator-agent"]="ca-orchestrator-prod"
  ["aiops-compute-agent"]="ca-compute-prod"
  ["aiops-network-agent"]="ca-network-prod"
  ["aiops-storage-agent"]="ca-storage-prod"
  ["aiops-security-agent"]="ca-security-prod"
  ["aiops-arc-agent"]="ca-arc-prod"
  ["aiops-sre-agent"]="ca-sre-prod"
  ["aiops-patch-agent"]="ca-patch-prod"
  ["aiops-eol-agent"]="ca-eol-prod"
  ["api-gateway"]="ca-api-gateway-prod"
  ["teams-bot"]="ca-teams-bot-prod"
  ["arc-mcp-server"]="ca-arc-mcp-server-prod"
)

# ─── Defaults ─────────────────────────────────────────────────────────────────
APP_ID=""
APP_NAME=""
RESOURCE_GROUP="rg-aap-prod"

# ─── Parse arguments ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app)
      APP_ID="$2"
      shift 2
      ;;
    --app-name)
      APP_NAME="$2"
      shift 2
      ;;
    --rg)
      RESOURCE_GROUP="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--app <resource-id>] [--app-name <name> --rg <resource-group>]"
      echo ""
      echo "Options:"
      echo "  --app        Full App Insights resource ID"
      echo "  --app-name   App Insights resource name (used with --rg)"
      echo "  --rg         Resource group (default: rg-aap-prod)"
      echo "  -h, --help   Show this help"
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# ─── Resolve App Insights resource ID ────────────────────────────────────────
if [[ -z "$APP_ID" ]]; then
  echo "Resolving App Insights resource..."

  if [[ -n "$APP_NAME" ]]; then
    APP_ID=$(az monitor app-insights component show \
      --app "$APP_NAME" \
      -g "$RESOURCE_GROUP" \
      --query "appId" -o tsv 2>/dev/null || true)
  else
    # Auto-detect: find the first App Insights resource in the resource group
    APP_ID=$(az monitor app-insights component show \
      -g "$RESOURCE_GROUP" \
      --query "[0].appId" -o tsv 2>/dev/null || true)
    APP_NAME=$(az monitor app-insights component show \
      -g "$RESOURCE_GROUP" \
      --query "[0].name" -o tsv 2>/dev/null || true)
  fi

  if [[ -z "$APP_ID" ]]; then
    echo "ERROR: Could not resolve App Insights resource in resource group '$RESOURCE_GROUP'." >&2
    echo "Use --app <resource-id> or --app-name <name> --rg <resource-group>." >&2
    exit 1
  fi
  echo "Found: ${APP_NAME:-$APP_ID}"
fi

# ─── Run heartbeat KQL query ─────────────────────────────────────────────────
KQL_QUERY="union traces, requests, dependencies, exceptions, customMetrics
| where timestamp > ago(24h)
| summarize LastSeen=max(timestamp), TelemetryCount=count() by cloud_RoleName
| order by cloud_RoleName asc"

echo ""
echo "Running heartbeat query against App Insights (last 24h)..."
echo ""

QUERY_RESULT=$(az monitor app-insights query \
  --app "$APP_ID" \
  --analytics-query "$KQL_QUERY" \
  -o json 2>/dev/null)

if [[ -z "$QUERY_RESULT" ]] || ! echo "$QUERY_RESULT" | jq empty 2>/dev/null; then
  echo "ERROR: Failed to run KQL query or received invalid JSON." >&2
  echo "Check that 'az' is authenticated and the App Insights resource is accessible." >&2
  exit 1
fi

# ─── Parse results into associative arrays ────────────────────────────────────
# Extract rows from the query result (App Insights returns nested tables/columns/rows)
declare -A FOUND_ROLES
declare -A ROLE_LAST_SEEN
declare -A ROLE_COUNT

# Parse the tables[0].rows array: each row is [cloud_RoleName, LastSeen, TelemetryCount]
ROWS=$(echo "$QUERY_RESULT" | jq -r '.tables[0].rows[]? | @tsv' 2>/dev/null || true)

while IFS=$'\t' read -r role_name last_seen count; do
  if [[ -n "$role_name" && "$role_name" != "null" ]]; then
    FOUND_ROLES["$role_name"]=1
    ROLE_LAST_SEEN["$role_name"]="$last_seen"
    ROLE_COUNT["$role_name"]="$count"
  fi
done <<< "$ROWS"

# ─── Print results table ─────────────────────────────────────────────────────
PASS_COUNT=0
FAIL_COUNT=0
SILENT_CONTAINERS=()

# Header
printf "%-30s %-8s %-24s %10s\n" "Container" "Status" "Last Seen" "Count"
printf "%s\n" "$(printf '%.0s-' {1..76})"

for container in "${EXPECTED_CONTAINERS[@]}"; do
  if [[ -n "${FOUND_ROLES[$container]:-}" ]]; then
    status_str="PASS"
    last_seen="${ROLE_LAST_SEEN[$container]:-unknown}"
    count="${ROLE_COUNT[$container]:-0}"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    status_str="FAIL"
    last_seen="(no telemetry)"
    count="0"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    SILENT_CONTAINERS+=("$container")
  fi
  printf "%-30s %-8s %-24s %10s\n" "$container" "$status_str" "$last_seen" "$count"
done

# Also show unexpected roles (containers not in the expected list)
UNEXPECTED_COUNT=0
for role_name in "${!FOUND_ROLES[@]}"; do
  is_expected=false
  for expected in "${EXPECTED_CONTAINERS[@]}"; do
    if [[ "$role_name" == "$expected" ]]; then
      is_expected=true
      break
    fi
  done
  if ! $is_expected; then
    if [[ $UNEXPECTED_COUNT -eq 0 ]]; then
      echo ""
      printf "%-30s %-8s %-24s %10s\n" "--- Unexpected Roles ---" "" "" ""
    fi
    printf "%-30s %-8s %-24s %10s\n" "$role_name" "EXTRA" "${ROLE_LAST_SEEN[$role_name]:-}" "${ROLE_COUNT[$role_name]:-}"
    UNEXPECTED_COUNT=$((UNEXPECTED_COUNT + 1))
  fi
done

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Summary: ${PASS_COUNT}/12 containers sending telemetry, ${FAIL_COUNT}/12 silent"

if [[ $UNEXPECTED_COUNT -gt 0 ]]; then
  echo "         ${UNEXPECTED_COUNT} unexpected cloud_RoleName value(s) detected (review above)"
fi

# ─── Remediation hints for silent containers ──────────────────────────────────
if [[ ${#SILENT_CONTAINERS[@]} -gt 0 ]]; then
  echo ""
  echo "Remediation hints for silent containers:"
  echo ""
  for container in "${SILENT_CONTAINERS[@]}"; do
    ca_name="${CONTAINER_APP_MAP[$container]:-unknown}"
    echo "  $container ($ca_name):"
    echo "    1. Check APPLICATIONINSIGHTS_CONNECTION_STRING env var:"
    echo "       az containerapp show -n $ca_name -g $RESOURCE_GROUP --query 'properties.template.containers[0].env[?name==\`APPLICATIONINSIGHTS_CONNECTION_STRING\`]' -o table"
    echo "    2. Check container is running (not crashed/scaled to 0):"
    echo "       az containerapp revision list -n $ca_name -g $RESOURCE_GROUP --query '[].{name:name, active:properties.active, replicas:properties.replicas, health:properties.healthState}' -o table"
    echo "    3. Check container logs for OTel init:"
    echo "       az containerapp logs show -n $ca_name -g $RESOURCE_GROUP --type console --tail 50"
    echo "    4. Verify container image includes OTel SDK (rebuild + push if needed)"
    echo ""
  done

  echo "RESULT: FAIL"
  exit 1
fi

echo ""
echo "RESULT: PASS"
exit 0
