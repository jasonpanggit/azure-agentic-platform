#!/usr/bin/env bash
# Phase 19 Plan 5 — Task 5: Package Teams App Manifest
#
# Creates a deployable .zip from services/teams-bot/appPackage/
# after substituting ${{BOT_ID}} and ${{CONTAINER_APP_FQDN}} placeholders.
#
# Prerequisites:
#   - BOT_ID env var set (Entra app client ID for the bot: d5b074fc-7ca6-4354-8938-046e034d80da)
#   - CONTAINER_APP_FQDN env var set (FQDN of ca-teams-bot-prod)
#   - zip installed
#
# Usage:
#   export BOT_ID="d5b074fc-7ca6-4354-8938-046e034d80da"
#   export CONTAINER_APP_FQDN="ca-teams-bot-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
#   bash scripts/ops/19-5-package-manifest.sh
#
# Output:
#   services/teams-bot/appPackage/aap-teams-bot.zip

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST_DIR="${REPO_ROOT}/services/teams-bot/appPackage"
OUTPUT_ZIP="${MANIFEST_DIR}/aap-teams-bot.zip"

echo "=== Phase 19 Plan 5: Package Teams App Manifest ==="
echo ""

# ---------------------------------------------------------------------------
# Resolve BOT_ID (from env var or az CLI)
# ---------------------------------------------------------------------------
if [[ -z "${BOT_ID:-}" ]]; then
  echo "INFO: BOT_ID not set. Attempting to retrieve from Azure..."
  BOT_ID=$(az bot show \
    --name aap-teams-bot-prod \
    --resource-group rg-aap-prod \
    --query "properties.msaAppId" -o tsv 2>/dev/null || echo "")
  if [[ -z "${BOT_ID}" ]]; then
    echo "ERROR: BOT_ID not found. Set it explicitly:"
    echo "  export BOT_ID=\"d5b074fc-7ca6-4354-8938-046e034d80da\""
    exit 1
  fi
  echo "OK: BOT_ID retrieved from Azure: ${BOT_ID}"
fi

# ---------------------------------------------------------------------------
# Resolve CONTAINER_APP_FQDN (from env var or az CLI)
# ---------------------------------------------------------------------------
if [[ -z "${CONTAINER_APP_FQDN:-}" ]]; then
  echo "INFO: CONTAINER_APP_FQDN not set. Attempting to retrieve from Azure..."
  CONTAINER_APP_FQDN=$(az containerapp show \
    --name ca-teams-bot-prod \
    --resource-group rg-aap-prod \
    --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || echo "")
  if [[ -z "${CONTAINER_APP_FQDN}" ]]; then
    echo "ERROR: CONTAINER_APP_FQDN not found. Set it explicitly:"
    echo "  export CONTAINER_APP_FQDN=\"ca-teams-bot-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io\""
    exit 1
  fi
  echo "OK: CONTAINER_APP_FQDN retrieved from Azure: ${CONTAINER_APP_FQDN}"
fi

echo ""
echo "BOT_ID:            ${BOT_ID}"
echo "CONTAINER_APP_FQDN: ${CONTAINER_APP_FQDN}"
echo ""

# ---------------------------------------------------------------------------
# Create a temporary working directory with substituted manifest
# ---------------------------------------------------------------------------
WORK_DIR=$(mktemp -d)
trap 'rm -rf "${WORK_DIR}"' EXIT

echo "--- Substituting placeholders in manifest.json ---"
sed \
  -e "s|\\\${{BOT_ID}}|${BOT_ID}|g" \
  -e "s|\\\${{CONTAINER_APP_FQDN}}|${CONTAINER_APP_FQDN}|g" \
  "${MANIFEST_DIR}/manifest.json" > "${WORK_DIR}/manifest.json"

# Verify placeholders were all replaced
REMAINING_PLACEHOLDERS=$(grep -o '\${{[^}]*}}' "${WORK_DIR}/manifest.json" 2>/dev/null || true)
if [[ -n "${REMAINING_PLACEHOLDERS}" ]]; then
  echo "WARNING: Unreplaced placeholders found in manifest.json:"
  echo "${REMAINING_PLACEHOLDERS}"
  echo "Set the corresponding environment variables and re-run."
fi

echo "OK: Placeholders substituted."

# ---------------------------------------------------------------------------
# Copy icon files into work dir
# ---------------------------------------------------------------------------
if [[ -f "${MANIFEST_DIR}/outline.png" ]]; then
  cp "${MANIFEST_DIR}/outline.png" "${WORK_DIR}/outline.png"
else
  echo "WARNING: outline.png not found in ${MANIFEST_DIR}. Teams manifest requires it."
fi

if [[ -f "${MANIFEST_DIR}/color.png" ]]; then
  cp "${MANIFEST_DIR}/color.png" "${WORK_DIR}/color.png"
else
  echo "WARNING: color.png not found in ${MANIFEST_DIR}. Teams manifest requires it."
fi

# ---------------------------------------------------------------------------
# Build the zip package
# ---------------------------------------------------------------------------
echo "--- Building ${OUTPUT_ZIP} ---"
rm -f "${OUTPUT_ZIP}"
(cd "${WORK_DIR}" && zip -j "${OUTPUT_ZIP}" manifest.json outline.png color.png 2>/dev/null || \
  zip -j "${OUTPUT_ZIP}" manifest.json $(ls *.png 2>/dev/null || true))

echo "OK: Package created: ${OUTPUT_ZIP}"
echo ""
echo "=== Teams App Installation Instructions ==="
echo ""
echo "1. Open Microsoft Teams"
echo "2. Go to Apps → Manage your apps → Upload an app → Upload a custom app"
echo "3. Select: ${OUTPUT_ZIP}"
echo "4. Click 'Add to team' and choose your target team (e.g., Azure Ops)"
echo "5. Select the channel to install to (e.g., #azure-ops-alerts)"
echo "6. Confirm installation"
echo ""
echo "After installation:"
echo "  - The bot fires onInstallationUpdate → ConversationReference is captured"
echo "  - Check bot logs: az containerapp logs show --name ca-teams-bot-prod \\"
echo "      --resource-group rg-aap-prod --tail 20"
echo "  - Look for: '[proactive] ConversationReference captured for channel:'"
echo ""
echo "=== Capture Channel ID (Task 6) ==="
echo ""
echo "Option A — from Teams admin center:"
echo "  Teams admin center → Teams → select team → Channels → channel options → Get link"
echo "  Extract channelId parameter from URL"
echo ""
echo "Option B — from bot logs after installation:"
echo "  az containerapp logs show --name ca-teams-bot-prod \\"
echo "    --resource-group rg-aap-prod --tail 50 | grep -i 'channelId\\|channel'"
echo ""
echo "Option C — Graph API:"
echo "  TEAM_ID=\$(az rest --method GET \\"
echo "    --url 'https://graph.microsoft.com/v1.0/me/joinedTeams' \\"
echo "    --query \"value[?displayName=='<your-team-name>'].id\" -o tsv)"
echo "  az rest --method GET \\"
echo "    --url \"https://graph.microsoft.com/v1.0/teams/\${TEAM_ID}/channels\" \\"
echo "    --query \"value[?displayName=='<channel-name>'].id\" -o tsv"
echo ""
echo "Once you have the channel ID, set it:"
echo "  TEAMS_CHANNEL_ID=\"<channel-id>\""
echo "  az containerapp update \\"
echo "    --name ca-teams-bot-prod \\"
echo "    --resource-group rg-aap-prod \\"
echo "    --set-env-vars \"TEAMS_CHANNEL_ID=\${TEAMS_CHANNEL_ID}\""
echo ""
echo "  Then update terraform.tfvars:"
echo "    teams_channel_id = \"\${TEAMS_CHANNEL_ID}\""
echo ""
echo "  Then run: cd terraform/envs/prod && terraform apply -var-file=credentials.tfvars"
