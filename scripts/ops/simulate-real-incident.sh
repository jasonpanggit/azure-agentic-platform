#!/usr/bin/env bash
# =============================================================================
# simulate-real-incident.sh — End-to-End Real Incident Simulation Walkthrough
# =============================================================================
#
# This script walks an operator through a complete AIOps incident lifecycle
# using a real Azure VM (the jumphost in aml-rg) as the target:
#
#   1. Stress the VM CPU with stress-ng to generate genuine Azure Monitor metrics
#   2. Wait for Azure Monitor to ingest the CPU spike (~2-3 minutes)
#   3. POST a crafted incident to the API gateway pointing at the jumphost
#   4. Poll the evidence endpoint until the diagnostic pipeline completes
#   5. Open the Web UI -> Alerts tab -> click the incident for VMDetailPanel
#   6. Use "Investigate with AI" for Compute agent investigation
#   7. If the agent proposes remediation, approve/reject via ProposalCard
#
# Usage:
#   bash scripts/ops/simulate-real-incident.sh [--auto]
#
#   --auto   Skip interactive pauses (CI/headless mode)
#
# =============================================================================
#
# KNOWN LIMITATIONS
# -----------------
#
# 1. APPROVAL IS AGENT-DRIVEN
#    The LLM decides whether to propose remediation. There is no deterministic
#    way to force a specific action. If the agent reports findings without
#    proposing a fix, use the fallback injection script:
#      python3 scripts/ops/inject-approval.py --incident-id <ID> --thread-id <TID>
#
# 2. NO STANDALONE APPROVALS TAB
#    Pending approvals are visible ONLY in the chat stream (ProposalCard).
#    The Observability tab shows a pending-approvals count but doesn't link
#    to individual approvals. For the demo, approvals MUST be discovered via
#    the chat flow.
#
# 3. EVIDENCE TIMING
#    - Diagnostic pipeline runs as a BackgroundTask (~15-30s after POST).
#    - Azure Monitor metrics lag ~2-3 minutes from the VM. The CPU spike must
#      be visible in Azure Monitor BEFORE the incident is posted, otherwise the
#      diagnostic pipeline will collect "normal" metrics.
#
# 4. STRESS-NG DEPENDENCY
#    stress-ng must be installed on the jumphost. Install with:
#      sudo apt-get update && sudo apt-get install -y stress-ng
#
# 5. AUTH DISABLED
#    The production API gateway has API_GATEWAY_AUTH_MODE=disabled.
#    No Bearer token is needed for any curl commands in this script.
#
# 6. COSMOS PARTITION KEY
#    The incidents container uses incident_id as partition key. The diagnostic
#    pipeline reads evidence by incident_id. All queries use cross-partition
#    where needed.
#
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_GATEWAY="https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
WEB_UI="https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
SUBSCRIPTION_ID="4c727b88-12f4-4c91-9c2b-372aab3bbae9"
RESOURCE_GROUP="aml-rg"
VM_NAME="jumphost"
RESOURCE_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Compute/virtualMachines/${VM_NAME}"
STRESS_DURATION="300"  # 5 minutes of CPU stress
EVIDENCE_POLL_INTERVAL=5
EVIDENCE_POLL_MAX_ATTEMPTS=60  # 5 minutes max wait
AUTO_MODE=false

# Parse arguments
for arg in "$@"; do
  case "$arg" in
    --auto) AUTO_MODE=true ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

# Generate a unique incident ID with timestamp
INCIDENT_ID="sim-$(date +%s)"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[1;32m[OK]\033[0m    $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $*"; }

pause() {
  if [ "$AUTO_MODE" = true ]; then
    return
  fi
  echo ""
  read -rp "  Press Enter to continue (or Ctrl+C to abort)..."
  echo ""
}

# ---------------------------------------------------------------------------
# Step 0: Prerequisites
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  AAP Real Incident Simulation"
echo "  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"
echo ""

info "Checking prerequisites..."

# Check az CLI is logged in
if ! az account show &>/dev/null; then
  error "Not logged in to Azure CLI. Run: az login"
  exit 1
fi
ok "Azure CLI authenticated"

# Verify the jumphost VM exists
VM_INFO=$(az vm show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --query "{name:name, resourceGroup:resourceGroup, vmId:vmId, powerState:instanceView.statuses[?starts_with(code,'PowerState/')].displayStatus | [0]}" \
  --show-details \
  -o json 2>/dev/null || true)

if [ -z "$VM_INFO" ] || [ "$VM_INFO" = "null" ]; then
  error "Jumphost VM not found: $VM_NAME in $RESOURCE_GROUP"
  exit 1
fi
ok "Jumphost VM found: $VM_NAME"
echo "   Resource ID: $RESOURCE_ID"
echo "   VM info: $VM_INFO"

# Check API gateway is reachable
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${API_GATEWAY}/health" 2>/dev/null || echo "000")
if [ "$HTTP_STATUS" != "200" ]; then
  error "API gateway health check failed (HTTP $HTTP_STATUS): ${API_GATEWAY}/health"
  exit 1
fi
ok "API gateway reachable (HTTP 200)"

echo ""
info "Configuration:"
echo "   Incident ID:    $INCIDENT_ID"
echo "   Target VM:      $VM_NAME ($RESOURCE_GROUP)"
echo "   Resource ID:    $RESOURCE_ID"
echo "   API Gateway:    $API_GATEWAY"
echo "   Web UI:         $WEB_UI"
echo "   Stress duration: ${STRESS_DURATION}s"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Stress the VM CPU
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Step 1: Stress the jumphost CPU"
echo "============================================================"
echo ""
info "This step SSHs into the jumphost and runs stress-ng to generate"
info "a genuine CPU spike visible in Azure Monitor."
echo ""
info "If stress-ng is not installed, it will be installed first."
echo ""

pause

# Run stress-ng on the jumphost via az vm run-command
info "Running stress-ng on $VM_NAME for ${STRESS_DURATION}s..."
info "(Using az vm run-command invoke — this takes 30-60s to submit)"

az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts "
    # Install stress-ng if not present
    if ! command -v stress-ng &>/dev/null; then
      sudo apt-get update -qq && sudo apt-get install -y -qq stress-ng
    fi
    # Run CPU stress in background so the run-command returns immediately
    nohup stress-ng --cpu \$(nproc) --timeout ${STRESS_DURATION}s &>/dev/null &
    echo \"stress-ng started: \$(nproc) CPU workers for ${STRESS_DURATION}s (PID: \$!)\"
  " \
  -o json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    msg = data.get('value', [{}])[0].get('message', 'No output')
    print(f'   VM output: {msg.strip()}')
except Exception as e:
    print(f'   (Could not parse output: {e})')
" || warn "run-command may have timed out (stress-ng still runs in background)"

ok "CPU stress initiated on $VM_NAME"
echo ""

# ---------------------------------------------------------------------------
# Step 2: Wait for Azure Monitor metrics to propagate
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Step 2: Wait for Azure Monitor metrics"
echo "============================================================"
echo ""
info "Azure Monitor ingests VM metrics every ~60s with a ~2-3 minute"
info "propagation delay. Waiting 150s for the CPU spike to be visible."
echo ""

if [ "$AUTO_MODE" = true ]; then
  info "Waiting 150 seconds..."
  sleep 150
else
  info "You can wait here, or skip ahead if you know metrics are fresh."
  info "Recommended wait: at least 2-3 minutes after stress-ng started."
  echo ""
  for i in $(seq 150 -30 0); do
    echo -ne "\r   Waiting... ${i}s remaining (press Ctrl+C then Enter to skip)  "
    sleep 30 2>/dev/null || break
  done
  echo ""
fi

ok "Wait complete — metrics should now be visible in Azure Monitor"
echo ""

# ---------------------------------------------------------------------------
# Step 3: Inject the incident
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Step 3: POST incident to API gateway"
echo "============================================================"
echo ""

info "Posting incident: $INCIDENT_ID"
echo ""

INCIDENT_RESPONSE=$(curl -s -X POST "${API_GATEWAY}/api/v1/incidents" \
  -H "Content-Type: application/json" \
  -d "{
    \"incident_id\": \"${INCIDENT_ID}\",
    \"severity\": \"Sev1\",
    \"domain\": \"compute\",
    \"title\": \"High CPU utilization on jumphost VM (stress-ng simulation)\",
    \"description\": \"CPU utilization exceeded 95% on jumphost VM. stress-ng process consuming all available CPU cores. Investigate and propose remediation.\",
    \"detection_rule\": \"HighCPUAlert\",
    \"affected_resources\": [{
      \"resource_id\": \"${RESOURCE_ID}\",
      \"subscription_id\": \"${SUBSCRIPTION_ID}\",
      \"resource_type\": \"Microsoft.Compute/virtualMachines\"
    }],
    \"kql_evidence\": \"Perf | where CounterName == '% Processor Time' | where CounterValue > 95 | where Computer == 'jumphost'\"
  }")

echo "$INCIDENT_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$INCIDENT_RESPONSE"
echo ""

# Extract thread_id from response
THREAD_ID=$(echo "$INCIDENT_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('thread_id', ''))
except:
    print('')
" 2>/dev/null)

INCIDENT_STATUS=$(echo "$INCIDENT_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('status', ''))
except:
    print('')
" 2>/dev/null)

if [ -z "$THREAD_ID" ] || [ "$THREAD_ID" = "suppressed" ]; then
  if [ "$INCIDENT_STATUS" = "suppressed_cascade" ]; then
    warn "Incident was suppressed by noise reduction (parent incident exists)."
    warn "Try a different incident_id or wait for the parent to resolve."
    exit 1
  fi
  error "Failed to get thread_id from incident response."
  error "Response: $INCIDENT_RESPONSE"
  exit 1
fi

ok "Incident created!"
echo "   Incident ID: $INCIDENT_ID"
echo "   Thread ID:   $THREAD_ID"
echo "   Status:      $INCIDENT_STATUS"
echo ""

# ---------------------------------------------------------------------------
# Step 4: Poll for evidence
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Step 4: Poll for diagnostic evidence"
echo "============================================================"
echo ""
info "The diagnostic pipeline runs as a BackgroundTask (~15-30s)."
info "Polling GET /api/v1/incidents/${INCIDENT_ID}/evidence..."
echo ""

EVIDENCE_READY=false
for attempt in $(seq 1 "$EVIDENCE_POLL_MAX_ATTEMPTS"); do
  EVIDENCE_RESPONSE=$(curl -s -w "\n%{http_code}" \
    "${API_GATEWAY}/api/v1/incidents/${INCIDENT_ID}/evidence")

  HTTP_CODE=$(echo "$EVIDENCE_RESPONSE" | tail -1)
  BODY=$(echo "$EVIDENCE_RESPONSE" | sed '$d')

  PIPELINE_STATUS=$(echo "$BODY" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('pipeline_status', 'unknown'))
except:
    print('unknown')
" 2>/dev/null)

  if [ "$HTTP_CODE" = "200" ] && [ "$PIPELINE_STATUS" != "pending" ]; then
    EVIDENCE_READY=true
    ok "Evidence ready! (attempt $attempt)"
    echo ""
    # Show a summary of collected evidence
    echo "$BODY" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print('   Evidence summary:')
    status = data.get('pipeline_status', 'unknown')
    print(f'     Pipeline status: {status}')
    sections = data.get('sections', data.get('evidence', {}))
    if isinstance(sections, dict):
        for key, val in sections.items():
            if isinstance(val, list):
                print(f'     {key}: {len(val)} items')
            elif isinstance(val, dict):
                print(f'     {key}: {len(val)} fields')
            else:
                print(f'     {key}: {str(val)[:100]}')
    collected = data.get('collected_at') or data.get('evidence_collected_at', '')
    if collected:
        print(f'     Collected at: {collected}')
except Exception as e:
    print(f'     (Could not parse evidence: {e})')
"
    break
  fi

  echo -ne "\r   Attempt $attempt/$EVIDENCE_POLL_MAX_ATTEMPTS — pipeline_status=$PIPELINE_STATUS (HTTP $HTTP_CODE)  "
  sleep "$EVIDENCE_POLL_INTERVAL"
done

echo ""

if [ "$EVIDENCE_READY" = false ]; then
  warn "Evidence did not become ready within the timeout."
  warn "The pipeline may still be running. Check the API gateway logs."
  warn "Continuing anyway — the Web UI will poll for evidence automatically."
fi

# ---------------------------------------------------------------------------
# Step 5: Open the Web UI
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Step 5: Open the Web UI"
echo "============================================================"
echo ""
info "Open the following URL in your browser:"
echo ""
echo "   ${WEB_UI}"
echo ""
info "Navigation:"
echo "   1. Click the 'Alerts' tab in the dashboard"
echo "   2. Find the incident: '${INCIDENT_ID}'"
echo "      Title: 'High CPU utilization on jumphost VM (stress-ng simulation)'"
echo "   3. Click the incident row to open VMDetailPanel"
echo "   4. VMDetailPanel shows:"
echo "      - VM health status (from Resource Health API)"
echo "      - Real-time CPU/memory/disk/network sparkline charts"
echo "      - Evidence summary (activity logs, metric anomalies)"
echo "      - Active incidents list"
echo ""

pause

# ---------------------------------------------------------------------------
# Step 6: AI Investigation via Chat
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Step 6: Investigate with AI"
echo "============================================================"
echo ""
info "In the VMDetailPanel:"
echo "   1. Click 'Investigate with AI' button"
echo "   2. The chat panel opens with an auto-generated investigation summary"
echo "   3. The Compute agent analyzes:"
echo "      - CPU/memory metrics from Azure Monitor"
echo "      - Recent ARM activity logs"
echo "      - Resource health status"
echo "      - Log Analytics workspace (if configured)"
echo "   4. The agent presents its findings in the chat"
echo ""
info "To encourage the agent to propose remediation, try typing:"
echo "   'Based on this evidence, what remediation do you recommend?'"
echo "   'Can you propose restarting the stress-ng process?'"
echo ""

pause

# ---------------------------------------------------------------------------
# Step 7: Approval Flow
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Step 7: Approval Flow"
echo "============================================================"
echo ""
info "If the agent proposes a remediation action:"
echo "   1. A ProposalCard appears in the chat with:"
echo "      - Proposed action description"
echo "      - Risk level badge"
echo "      - 30-minute countdown timer"
echo "      - 'Approve' and 'Reject' buttons"
echo "   2. Click 'Approve' to trigger execution"
echo "   3. Click 'Reject' to decline the proposal"
echo ""
warn "If no ProposalCard appears (agent-driven — see Known Limitations):"
info "   Use the fallback injection script:"
echo ""
echo "   python3 scripts/ops/inject-approval.py \\"
echo "     --incident-id ${INCIDENT_ID} \\"
echo "     --thread-id ${THREAD_ID}"
echo ""
info "   This creates a synthetic approval in Cosmos DB that will"
info "   render in the chat stream as a ProposalCard."
echo ""

pause

# ---------------------------------------------------------------------------
# Step 8: Cleanup
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Step 8: Cleanup"
echo "============================================================"
echo ""
info "To stop the CPU stress on the jumphost:"
echo ""
echo "   az vm run-command invoke \\"
echo "     --resource-group $RESOURCE_GROUP \\"
echo "     --name $VM_NAME \\"
echo "     --command-id RunShellScript \\"
echo "     --scripts 'pkill -f stress-ng || true; echo Done'"
echo ""
info "To delete the simulation incident from Cosmos DB (optional):"
echo ""
echo "   # Incidents use incident_id as partition key"
echo "   az cosmosdb sql container item delete \\"
echo "     --account-name aap-cosmos-prod \\"
echo "     --database-name aap \\"
echo "     --container-name incidents \\"
echo "     --partition-key-path '/incident_id' \\"
echo "     --id '${INCIDENT_ID}' \\"
echo "     --partition-key-value '${INCIDENT_ID}'"
echo ""

if [ "$AUTO_MODE" = false ]; then
  read -rp "  Kill stress-ng now? [y/N] " KILL_STRESS
  if [[ "$KILL_STRESS" =~ ^[Yy]$ ]]; then
    info "Killing stress-ng on $VM_NAME..."
    az vm run-command invoke \
      --resource-group "$RESOURCE_GROUP" \
      --name "$VM_NAME" \
      --command-id RunShellScript \
      --scripts "pkill -f stress-ng || true; echo 'stress-ng killed'" \
      -o json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    msg = data.get('value', [{}])[0].get('message', 'Done')
    print(f'   {msg.strip()}')
except:
    print('   Done')
" || warn "Could not kill stress-ng via run-command"
    ok "Cleanup complete"
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Simulation Summary"
echo "============================================================"
echo ""
echo "   Incident ID:  $INCIDENT_ID"
echo "   Thread ID:    $THREAD_ID"
echo "   Status:       $INCIDENT_STATUS"
echo "   Evidence:     $([ "$EVIDENCE_READY" = true ] && echo 'Ready' || echo 'Pending')"
echo ""
echo "   Web UI:       ${WEB_UI}"
echo "   API Gateway:  ${API_GATEWAY}"
echo ""
echo "   Useful API endpoints:"
echo "     GET  ${API_GATEWAY}/api/v1/incidents/${INCIDENT_ID}/evidence"
echo "     GET  ${API_GATEWAY}/api/v1/incidents?limit=5"
echo "     GET  ${API_GATEWAY}/api/v1/approvals?status=pending"
echo ""
echo "   Fallback approval injection:"
echo "     python3 scripts/ops/inject-approval.py \\"
echo "       --incident-id ${INCIDENT_ID} \\"
echo "       --thread-id ${THREAD_ID}"
echo ""
echo "============================================================"
echo "  Done!"
echo "============================================================"
