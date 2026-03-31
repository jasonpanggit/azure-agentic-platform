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
| Blocker alert | `⚠ blockers` | `## Blockers` section in `STATE.md` (see GSD Project State below) contains `OPEN` or `BLOCKING` | Red |
| GSD update | `⬆ /gsd:update` | `~/.claude/cache/gsd-update-check.json` has `"update_available": true` | Yellow |
| Stale hooks | `⚠ stale hooks — run /gsd:update` | `~/.claude/cache/gsd-update-check.json` has `"stale_hooks"` array with ≥1 entry | Red |
| Model | `sonnet-4.6` | Always; sourced from `data.model.display_name` or `data.model.id` in stdin JSON | Dim white |
| Clock + elapsed | `14:32 +47m` | Always; elapsed segment omitted if session ID unavailable or start file missing | Dim |
| Repo name | `azure-agentic-platform` | Always; `path.basename(data.workspace.current_dir)` | White |
| Branch | `main` | In a git repo (`git branch --show-current`); omit entire git block if not a repo | Green (clean) / Yellow (dirty) |
| Dirty marker | `*` | `git status --porcelain` output is non-empty | Yellow |
| Ahead/behind | `↑2↓1` | `git rev-list --count HEAD..@{u}` and `@{u}..HEAD`; each shown independently only if non-zero; omit if no upstream | Green `↑` / Red `↓` |
| Stash count | `≡1` | `git stash list` line count ≥ 1; omit if zero or git unavailable | Dim |
| Dirty file count | `±3` | Count of lines from `git status --porcelain`; omit if zero | Yellow |
| Context bar | `████░░░░░░ 40%` | Sourced from `data.context_window.remaining_percentage` / `used_percentage` in stdin JSON; always shown when present | Green <50% / Yellow <65% / Orange <80% / Red+blink 💀 ≥80% |

### Elapsed Time

- **Session ID source:** `data.session_id` from the stdin JSON payload passed to the status line hook. The same field is available in the `SessionStart` hook input.
- At `SessionStart`, write `{ "start": <unix_ms> }` to `~/.claude/cache/claude-session-start-<session_id>.json`. Create the `~/.claude/cache/` directory if absent (`fs.mkdirSync(..., { recursive: true })`).
- Status line reads this file, parses `start`, computes elapsed as `Date.now() - start`.
- Display: `+Xm` for elapsed < 3600s, `+XhYm` for ≥ 3600s (e.g. `+2h3m`).
- If file is missing, unreadable, or malformed (JSON parse error): elapsed segment omitted silently.
- If `data.session_id` is absent: session start file is not written; elapsed segment omitted.

### Git Timeout

All `git` calls use `execSync` with a `timeout: 500` option (milliseconds). On timeout or any error, the entire git block (branch, dirty, ahead/behind, stash, file count) is silently omitted.

---

## Line 2 — Contextual (Active Work Only)

### Layout

```
Fixing auth bug… │ ▰▰▰▰▱▱▱▱ 5/12ph 20/41p │ ✗ 3 tests │ ✓ build
```

### Segments

| Segment | Example | Condition | Colour |
|---|---|---|---|
| Active task | `Fixing auth bug…` | Todo with `status: in_progress` exists in the session todos file | Bold white |
| GSD progress bar | `▰▰▰▰▱▱▱▱ 5/12ph 20/41p` | `<cwd>/.planning/STATE.md` present and frontmatter parseable (see GSD Project State) | Cyan (in progress) / Green (all done) |
| Test status | `✗ 3 tests` / `✓ tests` | `~/.claude/cache/last-test-result.json` exists and `Date.now() - timestamp_ms < 1_800_000` (30 min wall clock) | Red (fail) / Green (pass) |
| Build status | `✗ build` / `✓ build` | `~/.claude/cache/last-build-result.json` exists and `Date.now() - timestamp_ms < 1_800_000` (30 min wall clock) | Red (fail) / Green (pass) |

### Suppression Logic

Line 2 is **not written at all** (no trailing newline, no blank line) when ALL of the following are true:
- No in-progress todo (`activeTodo === null`)
- `STATE.md` does not exist at `<cwd>/.planning/STATE.md` OR its frontmatter is unparseable
- Neither `last-test-result.json` nor `last-build-result.json` passes the 30-min freshness check

**Partial Line 2:** When Line 2 IS rendered but only some segments have data, only segments with data are shown. Segments with no data are omitted (no empty placeholder). A Line 2 with only a task and no GSD/test data is valid — it renders just the task.

### GSD Project State

`STATE.md` location: `<cwd>/.planning/STATE.md` where `<cwd>` is `data.workspace.current_dir` from the stdin JSON.

"Parseable" means: the file exists, is readable, contains a YAML frontmatter block delimited by `---`, and that block includes at least `total_phases` and `completed_phases` as integers.

Frontmatter fields read:
- `total_phases` (integer, required)
- `completed_phases` (integer, required)
- `total_plans` (integer, optional)
- `completed_plans` (integer, optional)

Blocker detection: split on `## Blockers` heading (case-insensitive), take the text up to the next `##` heading, test for `/\bOPEN\b|\bBLOCKING\b/i`.

On any read/parse error: GSD segment silently omitted.

### Test/Build Cache

A `PostToolUse` hook (`gsd-test-build-watcher.js`) fires after `Bash` tool calls. It inspects `tool_input.command` (the bash command string) for keyword matches:

**Test command keywords (substring match, case-insensitive):**
`jest`, `vitest`, `pytest`, `npm test`, `yarn test`, `pnpm test`, `npx playwright`, `go test`, `cargo test`, `dotnet test`, `make test`

**Build command keywords (substring match, case-insensitive):**
`npm run build`, `yarn build`, `pnpm build`, `next build`, `tsc --`, `cargo build`, `go build`, `dotnet build`, `make build`

On keyword match, the hook reads `tool_result.content` (stdout/stderr) and `tool_result.exit_code`:
- `passed`: `exit_code === 0`
- `failure_count`: parse from output using patterns like `(\d+) (failed|failures|errors)` (best-effort; `null` if unparseable)
- `timestamp_ms`: `Date.now()`
- `command`: the matched command string (truncated to 120 chars)

Written to: `~/.claude/cache/last-test-result.json` (test match) and/or `~/.claude/cache/last-build-result.json` (build match). Create `~/.claude/cache/` directory if absent.

Schema:
```json
{
  "passed": false,
  "failure_count": 3,
  "timestamp_ms": 1743400000000,
  "command": "npm test"
}
```

**Read failure behavior:** If either cache file exists but is malformed (JSON parse error, missing `passed` or `timestamp_ms` fields): treat as absent — silently omit the segment. Do not error.

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
| `git` command times out (>500ms) or errors | Entire git block silently omitted |
| No upstream branch configured | Ahead/behind segment omitted (no error) |
| No session ID in stdin | Elapsed time hidden; session start file not written |
| Session start file missing or malformed | Elapsed segment omitted silently |
| `~/.claude/cache/` directory absent | Created with `fs.mkdirSync(..., { recursive: true })` before any write |
| Test/build result > 30 min old | Badge hidden (staleness: `Date.now() - timestamp_ms >= 1_800_000`) |
| Test/build cache file malformed | Segment omitted silently |
| `STATE.md` missing | GSD segment omitted silently |
| `STATE.md` malformed (bad frontmatter) | GSD segment omitted silently |
| Line 2 all segments empty | Line 2 not written — no newline, no blank line |
| Partial Line 2 (some segments have data) | Only populated segments rendered; no placeholders |
| stdin JSON parse error | Hook exits with code 0, writes nothing (status line shows blank) |

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
