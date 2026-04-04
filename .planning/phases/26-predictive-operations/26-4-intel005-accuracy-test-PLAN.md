# Plan 26-4: INTEL-005 Accuracy Validation Script

**Phase:** 26 — Predictive Operations
**Wave:** 3 (independent of 26-3; depends only on 26-2: `forecaster.py` must exist)
**Autonomous:** true
**Requirement:** INTEL-005 — validate ≥70% forecast accuracy (MAPE < 30%) against synthetic data

---

## Goal

Create `scripts/ops/26-4-forecast-accuracy-test.sh` — a self-contained accuracy validation script that proves INTEL-005 is satisfied without requiring Azure credentials, a running API, or Cosmos DB. Exits 0 on PASS, 1 on FAIL.

---

## Files to Create

| File | Change |
|---|---|
| `scripts/ops/26-4-forecast-accuracy-test.sh` | **Create** — INTEL-005 accuracy validation script |

---

## What the Script Does

1. Generates a **synthetic 24-point time series** with a known linear trend in an inline Python heredoc
2. Imports `_holt_smooth` and `_compute_time_to_breach` directly from `forecaster.py` (no API call, no Cosmos)
3. Computes Holt smoothing + time-to-breach on the synthetic series
4. Computes MAPE between forecast projections and known-future values
5. Computes true time-to-breach from the known trend and asserts the estimated TTB is within 30% of truth
6. Reports INTEL-005 PASS or FAIL with details
7. Exits 0 on PASS, exits 1 on FAIL

---

## Synthetic Test Data Design

The script uses a **linear trend series** where the true breach time is mathematically deterministic.

**Series design:**
- 24 data points, 5-minute intervals (represents 2 hours of Azure Monitor data)
- Start value: `start = 40.0`
- Increment per interval: `step = 2.0`
- Threshold: `90.0`
- Final value at t=23: `40.0 + 23 * 2.0 = 86.0`
- True remaining intervals to breach: `(90.0 - 86.0) / 2.0 = 2.0 intervals`
- True time to breach: `2.0 * 5 minutes = 10.0 minutes`

**Why this works for INTEL-005 validation:**
- The series has a clean, noise-free linear trend → Holt smoothing should fit it well
- The true breach time is known exactly → we can compare the estimate against truth
- INTEL-005 requires "≥30 minutes in advance with ≥70% accuracy"
- The 30% tolerance test (`abs(estimated - true) / true <= 0.30`) directly maps to "≥70% accuracy"
- A MAPE < 30% on the hold-out set confirms the model generalizes

**For the MAPE validation (hold-out test):**
- Fit on first 18 points (`[40.0, 42.0, ..., 74.0]`)
- Predict next 6 points using fitted level + trend
- Compare predictions against actual points `[76.0, 78.0, 80.0, 82.0, 84.0, 86.0]`
- Assert MAPE < 30.0

---

## Script Structure

```bash
#!/usr/bin/env bash
# INTEL-005 Accuracy Validation Script
# Tests that _holt_smooth + _compute_time_to_breach meet ≥70% accuracy requirement.
# Usage: bash scripts/ops/26-4-forecast-accuracy-test.sh
# Exit: 0 = PASS, 1 = FAIL

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=== INTEL-005: Capacity Forecast Accuracy Test ==="
echo "Repo root: ${REPO_ROOT}"
echo ""

cd "${REPO_ROOT}"

# Run accuracy validation via inline Python
python3 - <<'PYTHON_SCRIPT'
import sys
import os

# Add repo root to path so we can import forecaster directly
sys.path.insert(0, os.getcwd())

print("1. Importing forecaster module...")
try:
    from services.api_gateway.forecaster import (
        _holt_smooth,
        _compute_mape,
        _compute_time_to_breach,
    )
    print("   OK: forecaster imported successfully")
except ImportError as e:
    print(f"   FAIL: Cannot import forecaster: {e}")
    sys.exit(1)

# -----------------------------------------------------------------------
# 2. Generate synthetic linear trend series
# -----------------------------------------------------------------------
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

# True breach from final point
final_value = values[-1]  # 86.0
true_intervals_remaining = (THRESHOLD - final_value) / STEP  # 2.0 intervals
true_ttb_minutes = true_intervals_remaining * 5.0  # 10.0 minutes
print(f"   True time-to-breach: {true_ttb_minutes:.1f} minutes")

# -----------------------------------------------------------------------
# 3. Hold-out MAPE test (fit on first 18, predict next 6)
# -----------------------------------------------------------------------
print("\n3. Computing hold-out MAPE (fit on 18 points, predict 6)...")
_FIT_POINTS = 18
fit_values = values[:_FIT_POINTS]
holdout_actual = values[_FIT_POINTS:]  # [76, 78, 80, 82, 84, 86]

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
    print(f"   [PASS] MAPE {mape:.2f}% < {MAPE_THRESHOLD}% threshold (≥70% accuracy)")
else:
    print(f"   [FAIL] MAPE {mape:.2f}% >= {MAPE_THRESHOLD}% (below 70% accuracy requirement)")
    sys.exit(1)

# -----------------------------------------------------------------------
# 4. Time-to-breach accuracy test (fit on all 24 points)
# -----------------------------------------------------------------------
print("\n4. Computing time-to-breach estimate on full 24-point series...")
level, trend = _holt_smooth(values)
print(f"   Full fit: level={level:.4f}, trend={trend:.4f}")

estimated_ttb = _compute_time_to_breach(level, trend, THRESHOLD, invert=False)
print(f"   Estimated TTB: {estimated_ttb} minutes")
print(f"   True TTB:      {true_ttb_minutes:.1f} minutes")

if estimated_ttb is None:
    print("   [FAIL] _compute_time_to_breach returned None (expected a positive value)")
    sys.exit(1)

# Tolerance: estimated must be within 30% of true value
tolerance = 0.30
lower_bound = true_ttb_minutes * (1.0 - tolerance)
upper_bound = true_ttb_minutes * (1.0 + tolerance)
print(f"   Acceptable range: [{lower_bound:.1f}, {upper_bound:.1f}] minutes (±{tolerance*100:.0f}%)")

if lower_bound <= estimated_ttb <= upper_bound:
    pct_error = abs(estimated_ttb - true_ttb_minutes) / true_ttb_minutes * 100
    print(f"   [PASS] TTB estimate {estimated_ttb:.1f}m within ±30% of truth (error={pct_error:.1f}%)")
else:
    pct_error = abs(estimated_ttb - true_ttb_minutes) / true_ttb_minutes * 100
    print(f"   [FAIL] TTB estimate {estimated_ttb:.1f}m outside ±30% of truth (error={pct_error:.1f}%)")
    sys.exit(1)

# -----------------------------------------------------------------------
# 5. Edge case: invert=True (declining metric, e.g. Available Memory)
# -----------------------------------------------------------------------
print("\n5. Edge case: inverted metric (declining toward threshold)...")
declining_values = [80.0 - i * 2.0 for i in range(N_POINTS)]  # 80 down to 34
declining_level, declining_trend = _holt_smooth(declining_values)
INVERT_THRESHOLD = 10.0
inv_ttb = _compute_time_to_breach(declining_level, declining_trend, INVERT_THRESHOLD, invert=True)
print(f"   Declining series: start=80.0, step=-2.0/interval")
print(f"   Level={declining_level:.2f}, trend={declining_trend:.4f}")
print(f"   Invert TTB: {inv_ttb} minutes")
if inv_ttb is not None and inv_ttb > 0:
    print("   [PASS] Inverted metric TTB computed correctly")
else:
    print("   [FAIL] Inverted metric TTB should be positive")
    sys.exit(1)

# -----------------------------------------------------------------------
# 6. Edge case: flat trend → None
# -----------------------------------------------------------------------
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

# -----------------------------------------------------------------------
# 7. Edge case: already breached → None
# -----------------------------------------------------------------------
print("\n7. Edge case: already breached threshold should return None...")
breached_values = [91.0 + i * 0.5 for i in range(N_POINTS)]
breach_level, breach_trend = _holt_smooth(breached_values)
breach_ttb = _compute_time_to_breach(breach_level, breach_trend, THRESHOLD, invert=False)
print(f"   Breached series: level={breach_level:.2f} > threshold={THRESHOLD}")
print(f"   TTB: {breach_ttb}")
if breach_ttb is None:
    print("   [PASS] Already-breached metric correctly returns None")
else:
    print(f"   [FAIL] Already-breached should return None, got {breach_ttb}")
    sys.exit(1)

# -----------------------------------------------------------------------
# 8. Summary
# -----------------------------------------------------------------------
print("\n" + "="*60)
print("INTEL-005 ACCURACY TEST: ALL CHECKS PASSED")
print("="*60)
print(f"  Hold-out MAPE:          {mape:.2f}% (threshold: <30%)")
print(f"  TTB accuracy:           within ±30% of true value")
print(f"  Inverted metric:        PASS")
print(f"  Flat trend → None:      PASS")
print(f"  Already breached → None: PASS")
print("")
print("INTEL-005 SATISFIED: Capacity exhaustion forecasts predict metric")
print("breaches with ≥70% accuracy (MAPE < 30%).")
sys.exit(0)

PYTHON_SCRIPT

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "=== INTEL-005: PASS ==="
else
    echo "=== INTEL-005: FAIL (exit code: ${EXIT_CODE}) ==="
fi

exit $EXIT_CODE
```

---

## Complete Script

The script is entirely self-contained. The Python code lives inside a heredoc (`<<'PYTHON_SCRIPT'`). No external test framework is required — the script uses only `sys.exit()` for pass/fail signaling.

**Key design decisions:**
- **Heredoc quoting** (`<<'PYTHON_SCRIPT'`): Single-quoted delimiter prevents shell variable expansion inside the Python block. All `$` characters in Python f-strings are safe.
- **`set -euo pipefail`**: Bash strict mode — any unexpected failure exits immediately with a non-zero code.
- **`sys.path.insert(0, os.getcwd())`**: Allows importing `services.api_gateway.forecaster` from the repo root without installing the package. Works in CI and locally when the script is run from repo root.
- **No network, no credentials, no Cosmos**: Pure algorithmic validation. Can run in CI with no Azure access.
- **7 explicit checks**: Each check uses `sys.exit(1)` on failure so the failure point is always identified in the output.

---

## Making the Script Executable

After creating the file:

```bash
chmod +x scripts/ops/26-4-forecast-accuracy-test.sh
```

---

## Expected Output (PASS)

```
=== INTEL-005: Capacity Forecast Accuracy Test ===
Repo root: /path/to/azure-agentic-platform

1. Importing forecaster module...
   OK: forecaster imported successfully

2. Generating synthetic 24-point linear trend series...
   Series: start=40.0, step=2.0/interval, n=24
   First 4: [40.0, 42.0, 44.0, 46.0]
   Last  4: [80.0, 82.0, 84.0, 86.0]
   Threshold: 90.0
   True time-to-breach: 10.0 minutes

3. Computing hold-out MAPE (fit on 18 points, predict 6)...
   Fitted level=74.xxxx, trend=1.xxxx
   Holdout actual:    ['76.0', '78.0', '80.0', '82.0', '84.0', '86.0']
   Holdout predicted: ['75.xx', '77.xx', '79.xx', '81.xx', '83.xx', '85.xx']
   MAPE: x.xx%
   [PASS] MAPE x.xx% < 30.0% threshold (≥70% accuracy)

4. Computing time-to-breach estimate on full 24-point series...
   Full fit: level=xx.xxxx, trend=x.xxxx
   Estimated TTB: xx.x minutes
   True TTB:      10.0 minutes
   Acceptable range: [7.0, 13.0] minutes (±30%)
   [PASS] TTB estimate xx.xm within ±30% of truth (error=x.x%)

5. Edge case: inverted metric (declining toward threshold)...
   [PASS] Inverted metric TTB computed correctly

6. Edge case: flat trend should return None...
   [PASS] Flat trend correctly returns None

7. Edge case: already breached threshold should return None...
   [PASS] Already-breached metric correctly returns None

============================================================
INTEL-005 ACCURACY TEST: ALL CHECKS PASSED
============================================================
  Hold-out MAPE:          x.xx% (threshold: <30%)
  TTB accuracy:           within ±30% of true value
  Inverted metric:        PASS
  Flat trend → None:      PASS
  Already breached → None: PASS

INTEL-005 SATISFIED: Capacity exhaustion forecasts predict metric
breaches with ≥70% accuracy (MAPE < 30%).

=== INTEL-005: PASS ===
```

---

## Verification Steps

```bash
# 1. Make executable
chmod +x scripts/ops/26-4-forecast-accuracy-test.sh

# 2. Run from repo root (must have forecaster.py created by Plan 26-2)
cd /path/to/azure-agentic-platform
bash scripts/ops/26-4-forecast-accuracy-test.sh

# 3. Verify exit code
echo "Exit code: $?"   # should be 0

# 4. Verify FAIL path works (manual test — temporarily break something)
# The script should exit 1 when MAPE >= 30% or TTB outside bounds

# 5. Run in CI context (no Azure credentials needed)
AZURE_CLIENT_ID="" COSMOS_ENDPOINT="" bash scripts/ops/26-4-forecast-accuracy-test.sh
```

---

## Acceptance Criteria

- [ ] `scripts/ops/26-4-forecast-accuracy-test.sh` created and executable (`chmod +x`)
- [ ] Script imports `_holt_smooth`, `_compute_mape`, `_compute_time_to_breach` from `services.api_gateway.forecaster`
- [ ] Generates 24-point synthetic linear trend series inline (no file I/O)
- [ ] Asserts hold-out MAPE < 30% → exits 1 on failure
- [ ] Asserts estimated TTB within ±30% of true value → exits 1 on failure
- [ ] Tests inverted metric (declining series + `invert=True`) → positive TTB
- [ ] Tests flat trend → `None` TTB
- [ ] Tests already-breached metric → `None` TTB
- [ ] Reports INTEL-005 PASS/FAIL clearly in stdout
- [ ] Exits 0 on all checks passing, 1 on any check failing
- [ ] Runs with no Azure credentials, no Cosmos, no network access

---

## Notes

- **Why not pytest?** This script is an operational validation artifact (like `22-4-topology-load-test.sh`), not a unit test. It runs from CI as a `bash` script, not via `pytest`. The existing ops scripts in `scripts/ops/` all follow the shell + inline Python pattern.
- **`sys.path.insert(0, os.getcwd())`**: Works when the script is run from the repo root (`cd /repo && bash scripts/ops/26-4-forecast-accuracy-test.sh`). If run from a different directory, the import will fail with a clear error message.
- **True TTB = 10 minutes** for the test series: This is intentionally short and well within the "30 minutes" requirement of INTEL-005 — the test validates algorithm accuracy, not that the system always forecasts >30 minutes ahead. The 30-minute requirement means the system can provide ≥30 minutes of warning; the accuracy test validates that the estimate is within 30% of truth.
- **`set -euo pipefail`**: The Python heredoc runs as a subprocess. If Python exits with non-zero, `bash` will catch it and `exit $EXIT_CODE` will propagate the failure. The script correctly captures the Python exit code via `EXIT_CODE=$?` (the assignment after `<<'PYTHON_SCRIPT'`).
