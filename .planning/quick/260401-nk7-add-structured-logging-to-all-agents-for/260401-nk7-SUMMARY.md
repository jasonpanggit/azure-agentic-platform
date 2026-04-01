# Summary: Add Structured Logging to All Agents

**ID:** 260401-nk7
**Type:** quick
**Status:** COMPLETE
**Date:** 2026-04-01

---

## What Changed

### Task 1: Created `agents/shared/logging_config.py`

New shared utility providing `setup_logging(agent_name: str) -> logging.Logger`:
- Reads `LOG_LEVEL` env var (default: `INFO`)
- Calls `logging.basicConfig` with format: `%(asctime)s %(levelname)s %(name)s %(message)s`
- Returns `logging.getLogger(f"aiops.{agent_name}")` for consistent log name filtering
- No new dependencies (stdlib `logging` only)

### Task 2: Wired logging into all 9 agent containers

**8 domain agents** (compute, network, storage, security, arc, patch, eol, sre):
- Added `import logging` + `logger = logging.getLogger(__name__)` at module level
- Added `logger.info()` calls in each factory function (init + created)
- Updated `__main__` to call `setup_logging()` and log startup/exit

**Orchestrator** refactored:
- Replaced inline `logging.basicConfig(...)` with `setup_logging("orchestrator")` call (DRY)

**Agent-specific logging additions:**
- `arc/agent.py`: Logs whether `ARC_MCP_SERVER_URL` is set; warns if absent (degraded mode)
- `patch/agent.py`: Logs whether `AZURE_MCP_SERVER_URL` is set; warns if absent
- `eol/agent.py`: Logs whether `AZURE_MCP_SERVER_URL` is set; warns if absent; notes MCPStreamableHTTPTool usage

### Task 3: Verification

- `setup_logging('test')` imports and runs cleanly
- `LOG_LEVEL=DEBUG` correctly sets root logger to level 10
- All 276 existing tests pass (0 failures, 7 warnings)
- Every agent's `__main__` block calls `setup_logging()` before other work
- Every factory function has at least 2 `logger.info()` calls (init + created)

---

## Files Changed

| File | Action |
|------|--------|
| `agents/shared/logging_config.py` | CREATE |
| `agents/compute/agent.py` | EDIT |
| `agents/network/agent.py` | EDIT |
| `agents/storage/agent.py` | EDIT |
| `agents/security/agent.py` | EDIT |
| `agents/arc/agent.py` | EDIT |
| `agents/patch/agent.py` | EDIT |
| `agents/eol/agent.py` | EDIT |
| `agents/sre/agent.py` | EDIT |
| `agents/orchestrator/agent.py` | EDIT |

**Total:** 1 new file + 9 edits. No new dependencies. 2 atomic commits.

## Commits

1. `1ed57d8` — `feat: add shared setup_logging() helper for agent containers`
2. `cc63484` — `feat: wire structured logging into all 9 agent containers`
