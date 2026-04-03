#!/usr/bin/env bash
# scripts/ops/26-4-forecast-accuracy-test.sh
#
# INTEL-005 Accuracy Validation Script
#
# Tests that _holt_smooth + _compute_time_to_breach meet the ≥70% accuracy
# requirement (MAPE < 30%) against synthetic deterministic data.
#
# Self-contained: no Azure credentials, no Cosmos DB, no network access.
# Imports forecaster functions directly from services/api-gateway/forecaster.py.
#
# Usage:
#   bash scripts/ops/26-4-forecast-accuracy-test.sh
#
# Exit codes:
#   0 — INTEL-005 PASS (all accuracy checks satisfied)
#   1 — INTEL-005 FAIL (one or more checks failed)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=== INTEL-005: Capacity Forecast Accuracy Test ==="
echo "Repo root: ${REPO_ROOT}"
echo ""

cd "${REPO_ROOT}"

# Run accuracy validation via inline Python heredoc.
# Single-quoted delimiter (<<'PYTHON_SCRIPT') prevents shell variable expansion
# inside the Python block — all $ characters in f-strings are safe.
python3 - <<'PYTHON_SCRIPT'
import sys
import os

# ---------------------------------------------------------------------------
# 1. Import forecaster functions
#    services/api-gateway uses a hyphen (not a valid Python identifier), so
#    we add the directory itself to sys.path and import the module directly.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.getcwd(), "services", "api-gateway"))

print("1. Importing forecaster module...")
try:
    from forecaster import (
        _holt_smooth,
        _compute_mape,
        _compute_time_to_breach,
    )
    print("   OK: forecaster imported successfully")
except ImportError as e:
    print(f"   FAIL: Cannot import forecaster: {e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 2. Generate synthetic 24-point linear trend series
#    start=40, step=2/interval, threshold=90
#    Final value: 40 + 23*2 = 86
#    True remaining intervals to breach: (90 - 86) / 2 = 2
#    True time-to-breach: 2 * 5 min/interval = 10.0 minutes
# ---------------------------------------------------------------------------
print("\n2. Generating synthetic 24-point linear trend series...")
START = 40.0
STEP = 2.0
THRESHOLD = 90.0
N_POINTS = 24

values = [START + i * STEP for i in range(N_POINTS)]
print(f"   Series: start={START}, step={STEP}/interval, n={N_POINTS}")
print(f"   First 4: {values[:4]}")
print(f"   Last  4: {values[-4:]}")
print(f"   Threshold: {THRESHOLD}")

final_value = values[-1]  # 86.0
true_intervals_remaining = (THRESHOLD - final_value) / STEP  # 2.0
true_ttb_minutes = true_intervals_remaining * 5.0             # 10.0
print(f"   True time-to-breach: {true_ttb_minutes:.1f} minutes")

# ---------------------------------------------------------------------------
# 3. Hold-out MAPE test
#    Fit on first 18 points, predict next 6, assert MAPE < 30%
# ---------------------------------------------------------------------------
print("\n3. Computing hold-out MAPE (fit on 18 points, predict 6)...")
_FIT_POINTS = 18
fit_values = values[:_FIT_POINTS]
holdout_actual = values[_FIT_POINTS:]   # [76, 78, 80, 82, 84, 86]

fit_level, fit_trend = _holt_smooth(fit_values)
print(f"   Fitted level={fit_level:.4f}, trend={fit_trend:.4f}")

holdout_predicted = [
    fit_level + (i + 1) * fit_trend
    for i in range(len(holdout_actual))
]
print(f"   Holdout actual:    {[f'{v:.1f}' for v in holdout_actual]}")
print(f"   Holdout predicted: {[f'{v:.2f}' for v in holdout_predicted]}")

mape = _compute_mape(holdout_actual, holdout_predicted)
print(f"   MAPE: {mape:.2f}%")

MAPE_THRESHOLD = 30.0
if mape < MAPE_THRESHOLD:
    print(f"   [PASS] MAPE {mape:.2f}% < {MAPE_THRESHOLD}% threshold (>=70% accuracy)")
else:
    print(f"   [FAIL] MAPE {mape:.2f}% >= {MAPE_THRESHOLD}% (below 70% accuracy requirement)")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 4. Time-to-breach accuracy test on full 24-point series
#    Assert estimated TTB is within ±30% of true value (10.0 min)
# ---------------------------------------------------------------------------
print("\n4. Computing time-to-breach estimate on full 24-point series...")
level, trend = _holt_smooth(values)
print(f"   Full fit: level={level:.4f}, trend={trend:.4f}")

estimated_ttb = _compute_time_to_breach(level, trend, THRESHOLD, invert=False)
print(f"   Estimated TTB: {estimated_ttb} minutes")
print(f"   True TTB:      {true_ttb_minutes:.1f} minutes")

if estimated_ttb is None:
    print("   [FAIL] _compute_time_to_breach returned None (expected a positive value)")
    sys.exit(1)

tolerance = 0.30
lower_bound = true_ttb_minutes * (1.0 - tolerance)   # 7.0
upper_bound = true_ttb_minutes * (1.0 + tolerance)   # 13.0
print(f"   Acceptable range: [{lower_bound:.1f}, {upper_bound:.1f}] minutes (+-{tolerance*100:.0f}%)")

if lower_bound <= estimated_ttb <= upper_bound:
    pct_error = abs(estimated_ttb - true_ttb_minutes) / true_ttb_minutes * 100
    print(f"   [PASS] TTB estimate {estimated_ttb:.1f}m within +-30% of truth (error={pct_error:.1f}%)")
else:
    pct_error = abs(estimated_ttb - true_ttb_minutes) / true_ttb_minutes * 100
    print(f"   [FAIL] TTB estimate {estimated_ttb:.1f}m outside +-30% of truth (error={pct_error:.1f}%)")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 5. Edge case: inverted metric (Available Memory — breach when LOW)
#    Declining series: 80 down to 34 (step=-2/interval)
#    invert=True, threshold=10 → breach when value <= 10
# ---------------------------------------------------------------------------
print("\n5. Edge case: inverted metric (declining toward threshold)...")
declining_values = [80.0 - i * 2.0 for i in range(N_POINTS)]  # 80 .. 34
declining_level, declining_trend = _holt_smooth(declining_values)
INVERT_THRESHOLD = 10.0
inv_ttb = _compute_time_to_breach(
    declining_level, declining_trend, INVERT_THRESHOLD, invert=True
)
print(f"   Declining series: start=80.0, step=-2.0/interval, last={declining_values[-1]:.1f}")
print(f"   Level={declining_level:.2f}, trend={declining_trend:.4f}")
print(f"   Invert TTB: {inv_ttb} minutes")
if inv_ttb is not None and inv_ttb > 0:
    print("   [PASS] Inverted metric TTB computed correctly")
else:
    print("   [FAIL] Inverted metric TTB should be a positive value")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 6. Edge case: flat trend should return None
# ---------------------------------------------------------------------------
print("\n6. Edge case: flat trend should return None...")
flat_values = [50.0] * N_POINTS
flat_level, flat_trend = _holt_smooth(flat_values)
flat_ttb = _compute_time_to_breach(flat_level, flat_trend, THRESHOLD, invert=False)
print(f"   Flat series: level={flat_level:.2f}, trend={flat_trend:.6f}")
print(f"   TTB: {flat_ttb}")
if flat_ttb is None:
    print("   [PASS] Flat trend correctly returns None")
else:
    print(f"   [FAIL] Flat trend should return None, got {flat_ttb}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 7. Edge case: already-breached threshold should return None
# ---------------------------------------------------------------------------
print("\n7. Edge case: already breached threshold should return None...")
breached_values = [91.0 + i * 0.5 for i in range(N_POINTS)]
breach_level, breach_trend = _holt_smooth(breached_values)
breach_ttb = _compute_time_to_breach(
    breach_level, breach_trend, THRESHOLD, invert=False
)
print(f"   Breached series: level={breach_level:.2f} > threshold={THRESHOLD}")
print(f"   TTB: {breach_ttb}")
if breach_ttb is None:
    print("   [PASS] Already-breached metric correctly returns None")
else:
    print(f"   [FAIL] Already-breached should return None, got {breach_ttb}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 8. Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("INTEL-005 ACCURACY TEST: ALL CHECKS PASSED")
print("=" * 60)
print(f"  Hold-out MAPE:           {mape:.2f}% (threshold: <30%)")
print(f"  TTB accuracy:            within +-30% of true value")
print(f"  Inverted metric:         PASS")
print(f"  Flat trend -> None:      PASS")
print(f"  Already breached -> None: PASS")
print("")
print("INTEL-005 SATISFIED: Capacity exhaustion forecasts predict metric")
print("breaches with >=70% accuracy (MAPE < 30%).")
sys.exit(0)

PYTHON_SCRIPT

EXIT_CODE=$?

echo ""
if [ ${EXIT_CODE} -eq 0 ]; then
    echo "=== INTEL-005: PASS ==="
else
    echo "=== INTEL-005: FAIL (exit code: ${EXIT_CODE}) ==="
fi

exit ${EXIT_CODE}
