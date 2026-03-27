# Quick Task Summary: Move run-mock.sh to scripts/ and update paths

**ID:** 260328-1ca
**Status:** complete
**Branch:** quick/260328-1ca-move-run-mock-sh
**Commit:** 4b26f66

---

## What Changed

1. **Moved `run-mock.sh` to `scripts/run-mock.sh`** via `git mv` — aligns with all other operational scripts already in `scripts/`.

2. **Added `cd "$(dirname "$0")/.."` guard** at the top of the script (after shebang, before logic) — ensures all relative paths (`services/api-gateway/...`, `_aap_bootstrap.py`) resolve correctly regardless of invocation directory. No other path changes needed.

3. **Updated usage comment** from `./run-mock.sh` to `./scripts/run-mock.sh`.

4. **Added `_aap_bootstrap.py` to `.gitignore`** — this is a generated temp file written by the script at runtime; should never be tracked.

## Verification

| Check | Result |
|-------|--------|
| `scripts/run-mock.sh` exists and is executable | PASS |
| `run-mock.sh` no longer exists at repo root | PASS |
| `.gitignore` includes `_aap_bootstrap.py` | PASS |
| `services/api-gateway/requirements.txt` reachable from computed repo root | PASS |
| `cd` guard resolves to correct repo root | PASS |

## Files Changed

- `run-mock.sh` -> `scripts/run-mock.sh` (moved + updated)
- `.gitignore` (added `_aap_bootstrap.py`)
