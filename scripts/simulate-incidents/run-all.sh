#!/usr/bin/env bash
set -euo pipefail

# Phase 8: Incident Simulation Orchestrator
# Runs all 7 scenarios sequentially with backoff between scenarios.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SCENARIOS=(
    "scenario_compute.py"
    "scenario_network.py"
    "scenario_storage.py"
    "scenario_security.py"
    "scenario_arc.py"
    "scenario_sre.py"
    "scenario_cross.py"
)

PASSED=0
FAILED=0
TOTAL=${#SCENARIOS[@]}

echo "============================================"
echo " Phase 8: Incident Simulation Suite"
echo " Scenarios: $TOTAL"
echo " API Gateway: ${API_GATEWAY_URL:-https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io}"
echo "============================================"
echo ""

for scenario in "${SCENARIOS[@]}"; do
    echo "--- Running: $scenario ---"
    if python3 "$scenario"; then
        echo "  PASS: $scenario"
        PASSED=$((PASSED + 1))
    else
        echo "  FAIL: $scenario"
        FAILED=$((FAILED + 1))
    fi
    echo ""

    # Backoff between scenarios to avoid Foundry rate limits
    # Note: using index arithmetic for bash 3.2 compatibility (macOS ships bash 3.2)
    if [ "$scenario" != "${SCENARIOS[$((TOTAL-1))]}" ]; then
        echo "  (waiting 5s before next scenario...)"
        sleep 5
    fi
done

echo "============================================"
echo " Results: $PASSED/$TOTAL passed, $FAILED failed"
echo "============================================"

if [ "$FAILED" -gt 0 ]; then
    echo "SIMULATION SUITE: FAIL"
    exit 1
else
    echo "SIMULATION SUITE: PASS"
    exit 0
fi
