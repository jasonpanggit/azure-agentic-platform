# Status Line Revamp — Design Spec

**Date:** 2026-03-31
**Status:** Approved
**Scope:** `~/.claude/hooks/gsd-statusline.js` + `SessionStart` hook addition

---

## Overview

Revamp the Claude Code status line from a single dense line to a two-line tiered layout. Line 1 is always visible and shows urgent/persistent signals. Line 2 is contextual — only rendered when there is active work (in-progress todo, GSD project, or recent test result).

---

## Line 1 — Always Visible

### Layout

```
⚠ blockers │ ⬆ /gsd:update │ sonnet-4.6 │ 14:32 +47m │  main* ↑2↓1 ≡1 ±3 │ ████░░░░░░ 40%
```

### Segments

| Segment | Example | Condition | Colour |
|---|---|---|---|
| Blocker alert | `⚠ blockers` | `## Blockers` section in `STATE.md` contains `OPEN` or `BLOCKING` | Red |
| GSD update | `⬆ /gsd:update` | `gsd-update-check.json` has `update_available: true` | Yellow |
| Stale hooks | `⚠ stale hooks` | `gsd-update-check.json` has `stale_hooks` entries | Red |
| Model | `sonnet-4.6` | Always | Dim white |
| Clock + elapsed | `14:32 +47m` | Always; elapsed hidden if no session start timestamp | Dim |
| Repo name | `azure-agentic-platform` | Always | White |
| Branch | `main` | In a git repo | Green (clean) / Yellow (dirty) |
| Dirty marker | `*` | Uncommitted changes exist | Yellow |
| Ahead/behind | `↑2↓1` | Non-zero; each shown independently | Green `↑` / Red `↓` |
| Stash count | `≡1` | Stashes exist | Dim |
| Dirty file count | `±3` | Uncommitted files exist | Yellow |
| Context bar | `████░░░░░░ 40%` | Always | Green <50% / Yellow <65% / Orange <80% / Red+blink 💀 ≥80% |

### Elapsed Time

- At `SessionStart`, write `{ "start": <unix_ms> }` to `~/.claude/cache/claude-session-start-<session_id>.json`
- Status line reads this file and computes `now - start`
- Display: `+Xm` for < 60 min, `+Xhm` for ≥ 60 min (e.g. `+2h3m`)
- If file missing or session ID unavailable: elapsed segment omitted silently

---

## Line 2 — Contextual (Active Work Only)

### Layout

```
Fixing auth bug… │ ▰▰▰▰▱▱▱▱ 5/12ph 20/41p │ ✗ 3 tests │ ✓ build
```

### Segments

| Segment | Example | Condition | Colour |
|---|---|---|---|
| Active task | `Fixing auth bug…` | Todo with `status: in_progress` exists | Bold white |
| GSD progress bar | `▰▰▰▰▱▱▱▱ 5/12ph 20/41p` | `.planning/STATE.md` present and parseable | Cyan (in progress) / Green (all done) |
| Test status | `✗ 3 tests` / `✓ tests` | Cached result exists and age < 30 min | Red (fail) / Green (pass) |
| Build status | `✗ build` / `✓ build` | Cached result exists and age < 30 min | Red (fail) / Green (pass) |

### Suppression Logic

Line 2 is **not written at all** (no blank line) when all of the following are true:
- No in-progress todo
- No parseable `STATE.md` in the working directory
- No cached test/build result younger than 30 minutes

### Test/Build Cache

A `PostToolUse` hook fires after `Bash` tool calls. It inspects the command string for test/build keywords:

**Test keywords:** `jest`, `vitest`, `pytest`, `npm test`, `yarn test`, `pnpm test`, `npx playwright`, `go test`, `cargo test`, `dotnet test`
**Build keywords:** `npm run build`, `yarn build`, `pnpm build`, `next build`, `tsc`, `cargo build`, `go build`, `dotnet build`

On match, the hook captures:
- `exit_code` from the tool result
- A pass/fail boolean
- Failure count (parsed from output where possible — e.g. `3 failed` in jest output)
- Timestamp

Written to: `~/.claude/cache/last-test-result.json` (test) and `~/.claude/cache/last-build-result.json` (build)

Schema:
```json
{
  "passed": false,
  "failure_count": 3,
  "timestamp_ms": 1743400000000,
  "command": "npm test"
}
```

---

## Full Examples

### Active session, mid-work, problems present
```
⚠ blockers │ sonnet-4.6 │ 14:32 +47m │  main* ↑2↓1 ≡1 ±3 │ ████░░░░░░ 40%
Fixing auth bug… │ ▰▰▰▰▱▱▱▱ 5/12ph 20/41p │ ✗ 3 tests │ ✓ build
```

### Clean idle session
```
sonnet-4.6 │ 14:32 +12m │  main ↑1 │ ██░░░░░░░░ 20%
```

### All green, active work
```
sonnet-4.6 │ 09:15 +3m │  main │ ░░░░░░░░░░ 5%
Refactoring cache layer │ ▰▰▰▰▰▰▱▱▱▱▱▱ 9/12ph │ ✓ tests ✓ build
```

### Context critical
```
⚠ blockers │ sonnet-4.6 │ 16:55 +2h3m │  feat/auth* ↑4↓0 ±7 │ 💀 ████████████ 95%
Writing migration script… │ ✗ 12 tests
```

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| Not in a git repo | All git segments (branch, dirty, ahead/behind, stash, file count) hidden |
| `git` command times out (>500ms) | Git segments skipped silently |
| No session ID | Elapsed time hidden; session start file not written |
| Test result > 30 min old | Test/build badges hidden |
| `STATE.md` missing or malformed | GSD segment silently omitted |
| Session start file missing | Elapsed segment omitted |
| stdin parse error | Hook exits silently (existing behaviour preserved) |
| Line 2 all empty | Line 2 not written — no blank line emitted |

---

## Files Changed

| File | Change |
|---|---|
| `~/.claude/hooks/gsd-statusline.js` | Full rewrite with two-line tiered layout |
| `~/.claude/settings.json` | Add `SessionStart` hook entry for session timestamp writer |
| `~/.claude/hooks/gsd-session-start.js` | New: writes session start timestamp |
| `~/.claude/hooks/gsd-test-build-watcher.js` | New: `PostToolUse` hook that caches test/build results |

---

## Out of Scope

- PR number display (requires `gh` CLI call — latency risk, deferred)
- Token cost estimate (not exposed in status line data payload)
- Active subagent count (not available in hook data)
- Last tool used badge
