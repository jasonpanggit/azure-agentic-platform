#!/usr/bin/env bash
# setup_spn.sh — Grant required Azure RBAC roles to a Service Principal
# and optionally onboard it to the AAP monitoring platform.
#
# Usage:
#   ./setup_spn.sh --subscription-id <uuid> --client-id <uuid> --tenant-id <uuid> [options]
#
# Options:
#   --subscription-id   Required. Azure subscription GUID
#   --client-id         Required. App Registration (SPN) client ID
#   --tenant-id         Required. Entra tenant ID
#   --sp-name           Optional. Label (default: aap-monitor-<sub-short>)
#   --onboard           Flag. Call platform onboard API after role assignments
#   --api-url           Required if --onboard. API gateway base URL
#   --skip-reader       Flag. Skip Reader assignment (already granted)
#   --dry-run           Flag. Print commands without executing
#   --help              Show this message

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
SUBSCRIPTION_ID=""
CLIENT_ID=""
TENANT_ID=""
SP_NAME=""
ONBOARD=false
API_URL=""
SKIP_READER=false
DRY_RUN=false

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription-id) SUBSCRIPTION_ID="$2"; shift 2 ;;
    --client-id)       CLIENT_ID="$2"; shift 2 ;;
    --tenant-id)       TENANT_ID="$2"; shift 2 ;;
    --sp-name)         SP_NAME="$2"; shift 2 ;;
    --onboard)         ONBOARD=true; shift ;;
    --api-url)         API_URL="$2"; shift 2 ;;
    --skip-reader)     SKIP_READER=true; shift ;;
    --dry-run)         DRY_RUN=true; shift ;;
    --help|-h)
      sed -n '/^# Usage/,/^$/p' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── Validate required args ────────────────────────────────────────────────────
if [[ -z "$SUBSCRIPTION_ID" || -z "$CLIENT_ID" || -z "$TENANT_ID" ]]; then
  echo "ERROR: --subscription-id, --client-id, and --tenant-id are required." >&2
  echo "Run with --help for usage." >&2
  exit 1
fi

if [[ "$ONBOARD" == true && -z "$API_URL" ]]; then
  echo "ERROR: --api-url is required when --onboard is set." >&2
  exit 1
fi

SP_NAME="${SP_NAME:-aap-monitor-${SUBSCRIPTION_ID:0:8}}"

# ── Helper ────────────────────────────────────────────────────────────────────
run() {
  if [[ "$DRY_RUN" == true ]]; then
    echo "[DRY-RUN] $*"
  else
    "$@"
  fi
}

check_mark() { echo "✅ $1"; }
warn_mark()  { echo "⚠️  $1"; }
fail_mark()  { echo "❌ $1"; }

# ── Verify subscription access ────────────────────────────────────────────────
echo ""
echo "Verifying subscription access..."
if ! az account show --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  echo "ERROR: Cannot access subscription $SUBSCRIPTION_ID. Run 'az login' first." >&2
  exit 1
fi
check_mark "Subscription $SUBSCRIPTION_ID accessible"

# ── Role assignments ──────────────────────────────────────────────────────────
echo ""
echo "Assigning required roles to SPN $CLIENT_ID on subscription $SUBSCRIPTION_ID..."
echo ""

SCOPE="/subscriptions/$SUBSCRIPTION_ID"

declare -a ROLES=(
  "Monitoring Reader"
  "Security Reader"
  "Cost Management Reader"
  "Virtual Machine Contributor"
  "Azure Kubernetes Service Contributor Role"
  "Container Apps Contributor"
)

if [[ "$SKIP_READER" == false ]]; then
  ROLES=("Reader" "${ROLES[@]}")
fi

for ROLE in "${ROLES[@]}"; do
  if run az role assignment create \
      --assignee "$CLIENT_ID" \
      --role "$ROLE" \
      --scope "$SCOPE" \
      --output none 2>/dev/null; then
    check_mark "$(printf '%-42s' "$ROLE") assigned"
  else
    warn_mark "$(printf '%-42s' "$ROLE") already assigned or assignment failed — check manually"
  fi
done

# ── Onboard to platform ───────────────────────────────────────────────────────
if [[ "$ONBOARD" == true ]]; then
  echo ""
  echo "Onboarding subscription to AAP..."
  echo ""

  # Secure secret input — never on command line, never in history
  echo -n "Enter client secret (input hidden): "
  read -rs CLIENT_SECRET
  echo ""

  # Optional: display name and expiry
  echo -n "Display name for this subscription (press Enter to skip): "
  read DISPLAY_NAME
  echo -n "Secret expiry date ISO-8601 e.g. 2027-01-01T00:00:00Z (press Enter to skip): "
  read SECRET_EXPIRES_AT

  # Build JSON body (secret passed via stdin heredoc — never in process args)
  BODY=$(cat <<EOF
{
  "subscription_id": "$SUBSCRIPTION_ID",
  "display_name": "$DISPLAY_NAME",
  "tenant_id": "$TENANT_ID",
  "client_id": "$CLIENT_ID",
  "client_secret": "$CLIENT_SECRET",
  "secret_expires_at": "$SECRET_EXPIRES_AT",
  "environment": "prod"
}
EOF
)

  echo "Calling $API_URL/api/v1/subscriptions/onboard ..."

  # Validate AAP_TOKEN is set before calling auth-gated API
  if [[ -z "${AAP_TOKEN:-}" ]]; then
    echo "WARNING: AAP_TOKEN environment variable is not set."
    echo "The onboard endpoint requires an Entra ID Bearer token."
    echo "Set it with: export AAP_TOKEN=\$(az account get-access-token --query accessToken -o tsv)"
    echo ""
    echo "Skipping API onboard call — run manually with:"
    echo "  curl -X POST $API_URL/api/v1/subscriptions/onboard -H 'Authorization: Bearer <token>' -d '<body>'"
    exit 1
  fi

  RESPONSE=$(echo "$BODY" | curl -s -X POST \
    "$API_URL/api/v1/subscriptions/onboard" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${AAP_TOKEN}" \
    -d @- 2>&1) || true

  echo ""
  echo "Platform response:"
  echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"

  # Parse and display permission_status
  if echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); [print('  ✅' if v=='granted' else '  ⚠️ ', k, '-', v) for k,v in d.get('permission_status',{}).items()]" 2>/dev/null; then
    echo ""
    echo "Note: permissions showing 'missing' may still be propagating (2-5 min). Re-validate in the UI."
  fi
fi

echo ""
echo "Done. If any roles show warnings, verify in Azure Portal > Subscriptions > Access control (IAM)."
