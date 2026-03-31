# Status Line Revamp Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-line Claude Code status bar with a two-line tiered layout — Line 1 always visible (alerts, model, clock, git, context), Line 2 contextual (active task, GSD progress, test/build results).

**Architecture:** Four files are touched: the existing `gsd-statusline.js` is fully rewritten; a new `gsd-session-start.js` hook writes a session timestamp at startup; a new `gsd-test-build-watcher.js` PostToolUse hook caches test/build results; `settings.json` gets two new hook registrations. All hooks communicate via JSON files in `~/.claude/cache/`.

**Tech Stack:** Node.js (no external dependencies), `execSync` for git commands, stdin/stdout JSON for Claude Code hook protocol.

**Spec:** `docs/superpowers/specs/2026-03-31-statusline-revamp-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `~/.claude/hooks/gsd-statusline.js` | Rewrite | Two-line status renderer — reads stdin JSON, git, cache files, emits ANSI output |
| `~/.claude/hooks/gsd-session-start.js` | Create | Writes `~/.claude/cache/claude-session-start-<session_id>.json` at session start |
| `~/.claude/hooks/gsd-test-build-watcher.js` | Create | PostToolUse hook — detects test/build Bash commands, caches pass/fail result |
| `~/.claude/settings.json` | Modify | Register `gsd-session-start.js` in `SessionStart` and `gsd-test-build-watcher.js` in `PostToolUse` |

---

## Chunk 1: Session Start Timestamp Hook

### Task 1: Create `gsd-session-start.js`

**Files:**
- Create: `~/.claude/hooks/gsd-session-start.js`

- [ ] **Step 1: Create the file**

```js
#!/usr/bin/env node
// gsd-hook-version: 1.30.0
// SessionStart hook — writes session start timestamp for elapsed-time display
// Output: ~/.claude/cache/claude-session-start-<session_id>.json

const fs = require('fs');
const path = require('path');
const os = require('os');

const homeDir = os.homedir();

function getConfigDir() {
  const envDir = process.env.CLAUDE_CONFIG_DIR;
  if (envDir) return envDir;
  return path.join(homeDir, '.claude');
}

let input = '';
const stdinTimeout = setTimeout(() => process.exit(0), 3000);
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);
    const sessionId = data.session_id;
    if (!sessionId) process.exit(0);

    const cacheDir = path.join(getConfigDir(), 'cache');
    fs.mkdirSync(cacheDir, { recursive: true });

    const outPath = path.join(cacheDir, `claude-session-start-${sessionId}.json`);
    // Only write if not already written (session may fire multiple SessionStart events)
    if (!fs.existsSync(outPath)) {
      fs.writeFileSync(outPath, JSON.stringify({ start: Date.now() }));
    }
  } catch (e) { /* silent */ }
  process.exit(0);
});
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x /Users/jasonmba/.claude/hooks/gsd-session-start.js
```

- [ ] **Step 3: Smoke test — run it manually with mock input**

```bash
echo '{"session_id":"test-smoke-123"}' | node /Users/jasonmba/.claude/hooks/gsd-session-start.js
cat /Users/jasonmba/.claude/cache/claude-session-start-test-smoke-123.json
```

Expected output: `{"start":<unix_ms>}` — a number around 1743000000000.

- [ ] **Step 4: Verify idempotency — running it twice does not overwrite the start time**

```bash
echo '{"session_id":"test-smoke-123"}' | node /Users/jasonmba/.claude/hooks/gsd-session-start.js
cat /Users/jasonmba/.claude/cache/claude-session-start-test-smoke-123.json
```

Expected: same timestamp as before (file not overwritten).

- [ ] **Step 5: Clean up smoke test file**

```bash
rm /Users/jasonmba/.claude/cache/claude-session-start-test-smoke-123.json
```

- [ ] **Step 6: Commit**

```bash
git -C /Users/jasonmba/.claude add hooks/gsd-session-start.js
git -C /Users/jasonmba/.claude commit -m "feat: add session-start timestamp hook for elapsed time display"
```

---

## Chunk 2: Test/Build Watcher Hook

### Task 2: Create `gsd-test-build-watcher.js`

**Files:**
- Create: `~/.claude/hooks/gsd-test-build-watcher.js`

**Claude Code PostToolUse stdin payload shape:**
```json
{
  "session_id": "abc123",
  "tool_name": "Bash",
  "tool_input": { "command": "npm test" },
  "tool_result": {
    "exit_code": 1,
    "content": "3 failed, 10 passed"
  }
}
```

Key paths:
- `data.tool_name` — string, e.g. `"Bash"`
- `data.tool_input.command` — the bash command string
- `data.tool_result.exit_code` — number or string; `0` = pass, non-zero = fail; may be absent (treat as 0)
- `data.tool_result.content` — stdout/stderr as string or array of `{ text: string }` objects

**Failure count regex patterns (try in order, return first match, else `null`):**
1. `/(\d+)\s+(?:failed|failures)/i` — matches pytest: `3 failed`, jest: `3 failures`
2. `/(\d+)\s+tests?\s+failed/i` — matches: `3 tests failed`
3. `/FAILED\s+\[(\d+)/i` — matches pytest verbose: `FAILED [3`
4. `/(\d+)\s+errors?/i` — matches tsc/dotnet: `2 errors`

**Dual-match behavior:** If a command matches both TEST_KEYWORDS and BUILD_KEYWORDS (rare edge case like `npm test && npm run build`), write **both** `last-test-result.json` and `last-build-result.json` with the same record. Each file tracks its own type independently.

- [ ] **Step 1: Create the file**

```js
#!/usr/bin/env node
// gsd-hook-version: 1.30.0
// PostToolUse hook — detects test/build Bash commands, caches pass/fail result
// Output: ~/.claude/cache/last-test-result.json
//         ~/.claude/cache/last-build-result.json
//
// Stdin payload: { session_id, tool_name, tool_input: { command }, tool_result: { exit_code, content } }

const fs = require('fs');
const path = require('path');
const os = require('os');

const homeDir = os.homedir();

function getConfigDir() {
  const envDir = process.env.CLAUDE_CONFIG_DIR;
  if (envDir) return envDir;
  return path.join(homeDir, '.claude');
}

// Keyword lists — substring match, case-insensitive
const TEST_KEYWORDS = [
  'jest', 'vitest', 'pytest', 'npm test', 'yarn test', 'pnpm test',
  'npx playwright', 'go test', 'cargo test', 'dotnet test', 'make test'
];
const BUILD_KEYWORDS = [
  'npm run build', 'yarn build', 'pnpm build', 'next build', 'tsc --',
  'cargo build', 'go build', 'dotnet build', 'make build'
];

function matchesAny(cmd, keywords) {
  const lower = cmd.toLowerCase();
  return keywords.some(kw => lower.includes(kw.toLowerCase()));
}

/**
 * Best-effort failure count extraction from stdout/stderr.
 * Returns a number if parseable, null otherwise.
 */
function parseFailureCount(output) {
  if (!output) return null;
  const patterns = [
    /(\d+)\s+(?:failed|failures)/i,      // pytest: "3 failed", jest: "3 failures"
    /(\d+)\s+tests?\s+failed/i,           // "3 tests failed"
    /FAILED\s+\[(\d+)/i,                  // pytest verbose: "FAILED [3"
    /(\d+)\s+errors?/i,                   // tsc/dotnet: "2 errors"
  ];
  for (const re of patterns) {
    const m = output.match(re);
    if (m) return parseInt(m[1], 10);
  }
  return null;
}

/** Extract combined stdout/stderr string from tool_result.content (string or array) */
function extractOutput(toolResult) {
  if (!toolResult) return '';
  const c = toolResult.content;
  if (typeof c === 'string') return c;
  if (Array.isArray(c)) {
    return c.map(item => (typeof item === 'string' ? item : (item && item.text) || '')).join('\n');
  }
  return '';
}

let input = '';
const stdinTimeout = setTimeout(() => process.exit(0), 10000);
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);

    // Only fire on Bash tool (data.tool_name is the tool name string)
    if (data.tool_name !== 'Bash') process.exit(0);

    // Command is at data.tool_input.command
    const cmd = (data.tool_input && data.tool_input.command) || '';
    if (!cmd) process.exit(0);

    const isTest  = matchesAny(cmd, TEST_KEYWORDS);
    const isBuild = matchesAny(cmd, BUILD_KEYWORDS);
    if (!isTest && !isBuild) process.exit(0);

    // Pass/fail from data.tool_result.exit_code (number or string; absent = treat as 0)
    const exitCode = (data.tool_result && data.tool_result.exit_code != null)
      ? parseInt(String(data.tool_result.exit_code), 10)
      : 0;
    const passed = exitCode === 0;

    const output = extractOutput(data.tool_result);

    const record = {
      passed,
      failure_count: passed ? null : parseFailureCount(output),
      timestamp_ms: Date.now(),
      command: cmd.slice(0, 120),
    };

    const cacheDir = path.join(getConfigDir(), 'cache');
    fs.mkdirSync(cacheDir, { recursive: true });

    // Write both files if command matches both (e.g. chained commands)
    if (isTest)  fs.writeFileSync(path.join(cacheDir, 'last-test-result.json'),  JSON.stringify(record));
    if (isBuild) fs.writeFileSync(path.join(cacheDir, 'last-build-result.json'), JSON.stringify(record));
  } catch (e) { /* silent */ }
  process.exit(0);
});
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x /Users/jasonmba/.claude/hooks/gsd-test-build-watcher.js
```

- [ ] **Step 3: Test — passing jest command**

```bash
echo '{
  "tool_name": "Bash",
  "tool_input": {"command": "npm test"},
  "tool_result": {"exit_code": 0, "content": "3 tests passed"}
}' | node /Users/jasonmba/.claude/hooks/gsd-test-build-watcher.js
cat /Users/jasonmba/.claude/cache/last-test-result.json
```

Expected: `{"passed":true,"failure_count":null,"timestamp_ms":...,"command":"npm test"}`

- [ ] **Step 4: Test — failing pytest command**

```bash
echo '{
  "tool_name": "Bash",
  "tool_input": {"command": "pytest tests/"},
  "tool_result": {"exit_code": 1, "content": "5 failed, 10 passed"}
}' | node /Users/jasonmba/.claude/hooks/gsd-test-build-watcher.js
cat /Users/jasonmba/.claude/cache/last-test-result.json
```

Expected: `{"passed":false,"failure_count":5,...}`

- [ ] **Step 5: Test — failing build command**

```bash
echo '{
  "tool_name": "Bash",
  "tool_input": {"command": "npm run build"},
  "tool_result": {"exit_code": 1, "content": "Build failed with 2 errors"}
}' | node /Users/jasonmba/.claude/hooks/gsd-test-build-watcher.js
cat /Users/jasonmba/.claude/cache/last-build-result.json
```

Expected: `{"passed":false,"failure_count":2,...}` (`errors` pattern matches `"2 errors"`)

- [ ] **Step 6: Test — non-matching Bash command is ignored**

```bash
echo '{
  "tool_name": "Bash",
  "tool_input": {"command": "ls -la"},
  "tool_result": {"exit_code": 0, "content": ""}
}' | node /Users/jasonmba/.claude/hooks/gsd-test-build-watcher.js
# Should not update the cache file — check timestamp hasn't changed
```

- [ ] **Step 7: Test — non-Bash tool is ignored**

```bash
echo '{
  "tool_name": "Edit",
  "tool_input": {"file_path": "foo.py"},
  "tool_result": {"exit_code": 0}
}' | node /Users/jasonmba/.claude/hooks/gsd-test-build-watcher.js
echo "Exit code: $?"
```

Expected: exit 0, no file changes.

- [ ] **Step 8: Commit**

```bash
git -C /Users/jasonmba/.claude add hooks/gsd-test-build-watcher.js
git -C /Users/jasonmba/.claude commit -m "feat: add test/build result watcher hook"
```

---

## Chunk 3: Register New Hooks in settings.json

### Task 3: Wire up `settings.json`

**Files:**
- Modify: `~/.claude/settings.json`

**Current state of hooks in settings.json:**
- `SessionStart`: 1 entry (`gsd-check-update.js`)
- `PostToolUse`: 1 entry with matcher `Bash|Edit|Write|MultiEdit|Agent|Task` containing 1 hook (`gsd-context-monitor.js`)

After this task:
- `SessionStart`: 2 entries (append `gsd-session-start.js` as a second object in the array)
- `PostToolUse`: 1 entry (same matcher), 2 hooks (`gsd-context-monitor.js` + `gsd-test-build-watcher.js`)

The watcher's `tool_name` filtering is done inside the script, so no additional `matcher` field is needed on the hook entry — it can share the existing broad matcher.

- [ ] **Step 1: Read current settings.json to confirm current structure**

```bash
node -e "
const s = JSON.parse(require('fs').readFileSync('/Users/jasonmba/.claude/settings.json','utf8'));
console.log('SessionStart entries:', s.hooks.SessionStart.length);
console.log('PostToolUse entries:', s.hooks.PostToolUse.length);
console.log('PostToolUse[0] hooks count:', s.hooks.PostToolUse[0].hooks.length);
"
```

Expected:
```
SessionStart entries: 1
PostToolUse entries: 1
PostToolUse[0] hooks count: 1
```

- [ ] **Step 2: Add `gsd-session-start.js` to the `SessionStart` array**

Append to `SessionStart` array in `~/.claude/settings.json`:

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "node \"/Users/jasonmba/.claude/hooks/gsd-session-start.js\""
    }
  ]
}
```

The full `SessionStart` block should now be:

```json
"SessionStart": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "node \"/Users/jasonmba/.claude/hooks/gsd-check-update.js\""
      }
    ]
  },
  {
    "hooks": [
      {
        "type": "command",
        "command": "node \"/Users/jasonmba/.claude/hooks/gsd-session-start.js\""
      }
    ]
  }
]
```

- [ ] **Step 3: Add `gsd-test-build-watcher.js` to `PostToolUse[0].hooks` array**

Append to the `hooks` array inside `PostToolUse[0]`:

```json
{
  "type": "command",
  "command": "node \"/Users/jasonmba/.claude/hooks/gsd-test-build-watcher.js\"",
  "timeout": 10
}
```

- [ ] **Step 4: Validate JSON is well-formed AND structure is correct**

```bash
node -e "
const s = JSON.parse(require('fs').readFileSync('/Users/jasonmba/.claude/settings.json','utf8'));

// Structure assertions
console.assert(s.hooks.SessionStart.length === 2, 'SessionStart should have 2 entries');
console.assert(s.hooks.PostToolUse[0].hooks.length === 2, 'PostToolUse[0] should have 2 hooks');

// Confirm the right scripts are registered
const ssCommands = s.hooks.SessionStart.flatMap(e => e.hooks).map(h => h.command);
console.assert(ssCommands.some(c => c.includes('gsd-check-update')), 'gsd-check-update missing from SessionStart');
console.assert(ssCommands.some(c => c.includes('gsd-session-start')), 'gsd-session-start missing from SessionStart');

const ptCommands = s.hooks.PostToolUse[0].hooks.map(h => h.command);
console.assert(ptCommands.some(c => c.includes('gsd-context-monitor')), 'gsd-context-monitor missing from PostToolUse');
console.assert(ptCommands.some(c => c.includes('gsd-test-build-watcher')), 'gsd-test-build-watcher missing from PostToolUse');

// All hook entries have required fields
s.hooks.SessionStart.flatMap(e => e.hooks).forEach((h, i) => {
  console.assert(h.type === 'command', 'SessionStart hook ' + i + ' missing type');
  console.assert(typeof h.command === 'string', 'SessionStart hook ' + i + ' missing command');
});

console.log('All assertions passed ✓');
"
```

Expected: `All assertions passed ✓`

- [ ] **Step 5: Commit**

```bash
git -C /Users/jasonmba/.claude add settings.json
git -C /Users/jasonmba/.claude commit -m "feat: register session-start and test-build-watcher hooks"
```

---

## Chunk 4: Rewrite `gsd-statusline.js`

### Task 4: Rewrite the status line renderer

This is the main event. The existing file is fully replaced.

**Files:**
- Rewrite: `~/.claude/hooks/gsd-statusline.js`

- [ ] **Step 1: Write the new `gsd-statusline.js`**

```js
#!/usr/bin/env node
// gsd-hook-version: 1.30.0
// Claude Code Statusline - GSD Edition (two-line tiered)
//
// Line 1 (always): alerts | model | clock+elapsed | dir  branch [dirty] [↑↓] [≡] [±] | ctx bar
// Line 2 (active): task | gsd progress | test result | build result

const fs   = require('fs');
const path = require('path');
const os   = require('os');
const { execSync } = require('child_process');

// ─── helpers ────────────────────────────────────────────────────────────────

function getConfigDir() {
  const envDir = process.env.CLAUDE_CONFIG_DIR;
  if (envDir) return envDir;
  return path.join(os.homedir(), '.claude');
}

/** Strip proxy prefix and "claude-" prefix from model name */
function shortModel(raw) {
  if (!raw) return 'Claude';
  const name = raw.includes('/') ? raw.slice(raw.lastIndexOf('/') + 1) : raw;
  return name.replace(/^claude-/, '').replace(/-latest$/, '') || name;
}

/** Truncate string to maxLen, appending "…" if trimmed */
function truncate(str, maxLen) {
  if (!str || str.length <= maxLen) return str;
  return str.slice(0, maxLen - 1) + '…';
}

/** Run a git command with 500ms timeout; return stdout or null on any error */
function git(args, cwd) {
  try {
    return execSync(`git ${args} 2>/dev/null`, {
      cwd, stdio: ['ignore', 'pipe', 'ignore'], timeout: 500
    }).toString().trim();
  } catch (e) { return null; }
}

/** Read and parse a JSON cache file; return null on any error */
function readCache(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    const obj = JSON.parse(raw);
    return obj;
  } catch (e) { return null; }
}

// ─── Read JSON from stdin ────────────────────────────────────────────────────
let input = '';
const stdinTimeout = setTimeout(() => process.exit(0), 3000);
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data       = JSON.parse(input);
    const configDir  = getConfigDir();
    const cacheDir   = path.join(configDir, 'cache');
    const dir        = data.workspace?.current_dir || process.cwd();
    const session    = data.session_id || '';

    // ── Model ───────────────────────────────────────────────────────────────
    const rawModel = data.model?.display_name || data.model?.id || 'Claude';
    const model    = shortModel(rawModel);

    // ── Context window ──────────────────────────────────────────────────────
    const remaining  = data.context_window?.remaining_percentage;
    const usedDirect = data.context_window?.used_percentage;
    const AUTO_COMPACT_BUFFER_PCT = 16.5;
    let ctx = '';
    let usedPct = 0;

    if (remaining != null) {
      if (usedDirect != null) {
        usedPct = Math.max(0, Math.min(100, Math.round(usedDirect)));
      } else {
        const usableRemaining = Math.max(0, ((remaining - AUTO_COMPACT_BUFFER_PCT) / (100 - AUTO_COMPACT_BUFFER_PCT)) * 100);
        usedPct = Math.max(0, Math.min(100, Math.round(100 - usableRemaining)));
      }

      // Write bridge file for context-monitor hook
      if (session) {
        try {
          fs.mkdirSync(cacheDir, { recursive: true });
          fs.writeFileSync(
            path.join(os.tmpdir(), `claude-ctx-${session}.json`),
            JSON.stringify({ session_id: session, remaining_percentage: remaining, used_pct: usedPct, timestamp: Math.floor(Date.now() / 1000) })
          );
        } catch (e) { /* best-effort */ }
      }

      const filled = Math.floor(usedPct / 10);
      const bar    = '█'.repeat(filled) + '░'.repeat(10 - filled);
      const pctStr = `${usedPct}%`;

      if      (usedPct < 50) ctx = ` \x1b[32m${bar} ${pctStr}\x1b[0m`;
      else if (usedPct < 65) ctx = ` \x1b[33m${bar} ${pctStr}\x1b[0m`;
      else if (usedPct < 80) ctx = ` \x1b[38;5;208m${bar} ${pctStr}\x1b[0m`;
      else                   ctx = ` \x1b[5;31m💀 ${bar} ${pctStr}\x1b[0m`;
    }

    // ── Clock + elapsed time ─────────────────────────────────────────────────
    const now    = new Date();
    const hh     = String(now.getHours()).padStart(2, '0');
    const mm     = String(now.getMinutes()).padStart(2, '0');
    let elapsed  = '';
    if (session) {
      const startFile = path.join(cacheDir, `claude-session-start-${session}.json`);
      const startData = readCache(startFile);
      if (startData && typeof startData.start === 'number') {
        const elapsedMs  = Date.now() - startData.start;
        const elapsedSec = Math.floor(elapsedMs / 1000);
        if (elapsedSec < 3600) {
          elapsed = ` +${Math.floor(elapsedSec / 60)}m`;
        } else {
          const h = Math.floor(elapsedSec / 3600);
          const m = Math.floor((elapsedSec % 3600) / 60);
          elapsed = ` +${h}h${m}m`;
        }
      }
    }
    const clockSeg = `\x1b[2m${hh}:${mm}${elapsed}\x1b[0m`;

    // ── GSD alerts ───────────────────────────────────────────────────────────
    let gsdUpdate  = '';
    const cacheFile = path.join(cacheDir, 'gsd-update-check.json');
    const updateData = readCache(cacheFile);
    if (updateData) {
      if (updateData.update_available) gsdUpdate += '\x1b[33m⬆ /gsd:update\x1b[0m │ ';
      if (Array.isArray(updateData.stale_hooks) && updateData.stale_hooks.length > 0)
        gsdUpdate += '\x1b[31m⚠ stale hooks — run /gsd:update\x1b[0m │ ';
    }

    // ── Git ──────────────────────────────────────────────────────────────────
    let gitBlock = '';
    const branch = git('branch --show-current', dir);
    if (branch) {
      const porcelain  = git('status --porcelain', dir) ?? '';
      const isDirty    = porcelain.length > 0;
      const dirtyCount = isDirty ? porcelain.trim().split('\n').filter(Boolean).length : 0;
      const dirtyMark  = isDirty ? '\x1b[33m*\x1b[0m' : '';
      const branchCol  = isDirty ? '\x1b[33m' : '\x1b[32m';

      // Ahead / behind
      let aheadBehind = '';
      const ahead  = git('rev-list --count @{u}..HEAD', dir);
      const behind = git('rev-list --count HEAD..@{u}', dir);
      if (ahead  && parseInt(ahead, 10)  > 0) aheadBehind += ` \x1b[32m↑${ahead}\x1b[0m`;
      if (behind && parseInt(behind, 10) > 0) aheadBehind += ` \x1b[31m↓${behind}\x1b[0m`;

      // Stash count
      let stashSeg = '';
      const stashList = git('stash list', dir);
      if (stashList) {
        const stashCount = stashList.split('\n').filter(Boolean).length;
        if (stashCount > 0) stashSeg = ` \x1b[2m≡${stashCount}\x1b[0m`;
      }

      // Dirty file count
      const dirtySeg = dirtyCount > 0 ? ` \x1b[33m±${dirtyCount}\x1b[0m` : '';

      gitBlock = `  ${branchCol}\x1b[1m${branch}\x1b[0m${dirtyMark}${aheadBehind}${stashSeg}${dirtySeg}`;
    }

    // ── GSD project progress + blockers ──────────────────────────────────────
    let gsdProgress = '';
    let hasBlockers = false;
    const statePath = path.join(dir, '.planning', 'STATE.md');
    if (fs.existsSync(statePath)) {
      try {
        const stateContent = fs.readFileSync(statePath, 'utf8');
        const fmMatch = stateContent.match(/^---\n([\s\S]*?)\n---/);
        if (fmMatch) {
          const fm             = fmMatch[1];
          const totalPhases    = parseInt((fm.match(/total_phases:\s*(\d+)/)    || [])[1], 10);
          const completedPhases= parseInt((fm.match(/completed_phases:\s*(\d+)/)|| [])[1], 10);
          const totalPlans     = parseInt((fm.match(/total_plans:\s*(\d+)/)     || [])[1], 10);
          const completedPlans = parseInt((fm.match(/completed_plans:\s*(\d+)/) || [])[1], 10);

          if (!isNaN(totalPhases) && !isNaN(completedPhases)) {
            const displayMax  = Math.min(totalPhases, 12);
            const scaledDone  = Math.round((completedPhases / totalPhases) * displayMax);
            const phaseBar    = '▰'.repeat(scaledDone) + '▱'.repeat(displayMax - scaledDone);
            const planInfo    = (!isNaN(totalPlans) && !isNaN(completedPlans))
              ? ` ${completedPlans}/${totalPlans}p` : '';
            const phaseColor  = completedPhases >= totalPhases ? '\x1b[32m' : '\x1b[36m';
            gsdProgress = `${phaseColor}${phaseBar} ${completedPhases}/${totalPhases}ph${planInfo}\x1b[0m`;
          }
        }

        // Blocker detection
        if (/##\s*Blockers/i.test(stateContent)) {
          const blockersSection = stateContent.split(/##\s*Blockers/i)[1]?.split(/^##/m)[0] || '';
          hasBlockers = /\bOPEN\b|\bBLOCKING\b/i.test(blockersSection);
        }
      } catch (e) { /* silent */ }
    }

    // ── Active task from todos ───────────────────────────────────────────────
    let activeTask = '';
    const todosDir = path.join(configDir, 'todos');
    if (session && fs.existsSync(todosDir)) {
      try {
        const files = fs.readdirSync(todosDir)
          .filter(f => f.startsWith(session) && f.includes('-agent-') && f.endsWith('.json'))
          .map(f => ({ name: f, mtime: fs.statSync(path.join(todosDir, f)).mtime }))
          .sort((a, b) => b.mtime - a.mtime);
        if (files.length > 0) {
          const todos      = JSON.parse(fs.readFileSync(path.join(todosDir, files[0].name), 'utf8'));
          const inProgress = todos.find(t => t.status === 'in_progress');
          if (inProgress) activeTask = inProgress.activeForm || inProgress.subject || '';
        }
      } catch (e) { /* silent */ }
    }

    // ── Test / build badges ──────────────────────────────────────────────────
    const STALE_MS = 30 * 60 * 1000; // 30 minutes

    function buildBadge(cacheFileName, label) {
      const rec = readCache(path.join(cacheDir, cacheFileName));
      if (!rec || typeof rec.passed !== 'boolean' || typeof rec.timestamp_ms !== 'number') return '';
      if (Date.now() - rec.timestamp_ms >= STALE_MS) return '';
      if (rec.passed) return `\x1b[32m✓ ${label}\x1b[0m`;
      const countStr = rec.failure_count != null ? ` ${rec.failure_count}` : '';
      return `\x1b[31m✗${countStr} ${label}\x1b[0m`;
    }

    const testBadge  = buildBadge('last-test-result.json',  'tests');
    const buildBadge_ = buildBadge('last-build-result.json', 'build');

    // ── Assemble Line 1 ──────────────────────────────────────────────────────
    const blockerAlert = hasBlockers ? ' \x1b[31m⚠ blockers\x1b[0m │' : '';
    const dirname      = path.basename(dir);
    const modelSeg     = `\x1b[2;97m${model}\x1b[0m`;
    const dirSeg       = `\x1b[97m${dirname}\x1b[0m`;

    const line1Parts = [
      blockerAlert ? blockerAlert + ' ' : '',  // ⚠ blockers first (highest urgency)
      gsdUpdate,                                // ⬆ /gsd:update second
      modelSeg,
      ' │ ',
      clockSeg,
      ' │ ',
      dirSeg,
      gitBlock,
      gitBlock || ctx ? ' │' : '',             // separator before ctx bar
      ctx,
    ];
    const line1 = line1Parts.join('');

    // ── Assemble Line 2 ──────────────────────────────────────────────────────
    const line2Segments = [];
    if (activeTask)  line2Segments.push(`\x1b[1;97m${truncate(activeTask, 48)}\x1b[0m`);
    if (gsdProgress) line2Segments.push(gsdProgress);
    if (testBadge)   line2Segments.push(testBadge);
    if (buildBadge_) line2Segments.push(buildBadge_);

    const line2 = line2Segments.length > 0
      ? '\n' + line2Segments.join(' │ ')
      : '';

    process.stdout.write(line1 + line2);

  } catch (e) {
    // Silent fail — don't break the status line on any error
  }
});
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x /Users/jasonmba/.claude/hooks/gsd-statusline.js
```

- [ ] **Step 3: Smoke test — idle session (no todos, no STATE.md)**

Use `/tmp` as workspace so there is no `.planning/STATE.md` and no git repo — confirms Line 2 is suppressed.

```bash
echo '{
  "model": {"display_name": "claude-sonnet-4.6"},
  "session_id": "abc123",
  "workspace": {"current_dir": "/tmp"},
  "context_window": {"remaining_percentage": 80, "used_percentage": 20}
}' | node /Users/jasonmba/.claude/hooks/gsd-statusline.js
```

Expected: single line with `sonnet-4.6`, current time, `tmp`, no branch (not a git repo), green context bar. No newline / no Line 2.

- [ ] **Step 4: Smoke test — elapsed time appears (+Xm format)**

```bash
# Write a fake session start 45 minutes ago
echo '{"start":'$(( $(date +%s) * 1000 - 2700000 ))'}' > /Users/jasonmba/.claude/cache/claude-session-start-abc123.json

echo '{
  "model": {"display_name": "claude-sonnet-4.6"},
  "session_id": "abc123",
  "workspace": {"current_dir": "/tmp"},
  "context_window": {"remaining_percentage": 80, "used_percentage": 20}
}' | node /Users/jasonmba/.claude/hooks/gsd-statusline.js
```

Expected: `+45m` appears after the clock time on Line 1.

- [ ] **Step 4b: Smoke test — elapsed time appears (+XhYm format)**

```bash
# Write a fake session start 125 minutes ago (2h5m)
echo '{"start":'$(( $(date +%s) * 1000 - 7500000 ))'}' > /Users/jasonmba/.claude/cache/claude-session-start-abc123.json

echo '{
  "model": {"display_name": "claude-sonnet-4.6"},
  "session_id": "abc123",
  "workspace": {"current_dir": "/tmp"},
  "context_window": {"remaining_percentage": 80, "used_percentage": 20}
}' | node /Users/jasonmba/.claude/hooks/gsd-statusline.js
```

Expected: `+2h5m` appears after the clock time on Line 1.

- [ ] **Step 5: Smoke test — test badge appears on Line 2**

```bash
# Write a fresh failing test result
echo '{"passed":false,"failure_count":3,"timestamp_ms":'$(date +%s000)',"command":"npm test"}' \
  > /Users/jasonmba/.claude/cache/last-test-result.json

echo '{
  "model": {"display_name": "claude-sonnet-4.6"},
  "session_id": "abc123",
  "workspace": {"current_dir": "/tmp"},
  "context_window": {"remaining_percentage": 80, "used_percentage": 20}
}' | node /Users/jasonmba/.claude/hooks/gsd-statusline.js
```

Expected: Line 2 appears containing `✗ 3 tests` in red. (No GSD progress since `/tmp` has no STATE.md.)

- [ ] **Step 6: Smoke test — stale test badge is hidden, Line 2 suppressed**

```bash
# Write a test result that is 35 minutes old (past the 30-min threshold)
echo '{"passed":false,"failure_count":3,"timestamp_ms":'$(( $(date +%s) * 1000 - 2100000 ))',"command":"npm test"}' \
  > /Users/jasonmba/.claude/cache/last-test-result.json

echo '{
  "model": {"display_name": "claude-sonnet-4.6"},
  "session_id": "abc123",
  "workspace": {"current_dir": "/tmp"},
  "context_window": {"remaining_percentage": 80, "used_percentage": 20}
}' | node /Users/jasonmba/.claude/hooks/gsd-statusline.js
```

Expected: no Line 2 at all — stale result is suppressed and `/tmp` has no STATE.md or active task.

- [ ] **Step 7: Smoke test — context critical (≥80%)**

```bash
echo '{
  "model": {"display_name": "claude-sonnet-4.6"},
  "session_id": "abc123",
  "workspace": {"current_dir": "/tmp"},
  "context_window": {"remaining_percentage": 10, "used_percentage": 90}
}' | node /Users/jasonmba/.claude/hooks/gsd-statusline.js
```

Expected: `💀` and blinking red context bar on Line 1. No Line 2.

- [ ] **Step 8: Clean up smoke test files**

```bash
rm -f /Users/jasonmba/.claude/cache/claude-session-start-abc123.json
rm -f /Users/jasonmba/.claude/cache/last-test-result.json
rm -f /Users/jasonmba/.claude/cache/last-build-result.json
```

- [ ] **Step 9: Commit**

```bash
git -C /Users/jasonmba/.claude add hooks/gsd-statusline.js
git -C /Users/jasonmba/.claude commit -m "feat: rewrite statusline with two-line tiered layout"
```

---

## Chunk 5: End-to-End Verification

### Task 5: Full system verification

- [ ] **Step 1: Verify all four files are in place**

```bash
ls -la /Users/jasonmba/.claude/hooks/gsd-statusline.js \
        /Users/jasonmba/.claude/hooks/gsd-session-start.js \
        /Users/jasonmba/.claude/hooks/gsd-test-build-watcher.js \
        /Users/jasonmba/.claude/settings.json
```

Expected: all four files present, hooks are executable (`-rwxr-xr-x`).

- [ ] **Step 2: Validate settings.json structure (with assertions)**

```bash
node -e "
const s = JSON.parse(require('fs').readFileSync('/Users/jasonmba/.claude/settings.json','utf8'));

console.assert(s.hooks.SessionStart.length === 2, 'FAIL: SessionStart should have 2 entries, got ' + s.hooks.SessionStart.length);
console.assert(s.hooks.PostToolUse[0].hooks.length === 2, 'FAIL: PostToolUse[0] should have 2 hooks');

const ssCommands = s.hooks.SessionStart.flatMap(e => e.hooks).map(h => h.command);
const ptCommands = s.hooks.PostToolUse[0].hooks.map(h => h.command);
console.assert(ssCommands.some(c => c.includes('gsd-session-start')), 'FAIL: gsd-session-start missing from SessionStart');
console.assert(ptCommands.some(c => c.includes('gsd-test-build-watcher')), 'FAIL: gsd-test-build-watcher missing from PostToolUse');

console.log('SessionStart:', ssCommands.map(c => c.match(/hooks\/(.+?)\"/)?.[1]).filter(Boolean).join(', '));
console.log('PostToolUse:', ptCommands.map(c => c.match(/hooks\/(.+?)\"/)?.[1]).filter(Boolean).join(', '));
console.log('settings.json structure ✓');
"
```

Expected:
```
SessionStart: gsd-check-update.js, gsd-session-start.js
PostToolUse: gsd-context-monitor.js, gsd-test-build-watcher.js
settings.json structure ✓
```

- [ ] **Step 3: Test the full two-hook pipeline (session-start → statusline)**

This step exercises the actual data handoff between `gsd-session-start.js` and `gsd-statusline.js`.

```bash
SESSION="e2e-$(date +%s)"

# Step A: pipe mock SessionStart payload through gsd-session-start.js
echo "{\"session_id\":\"${SESSION}\"}" | node /Users/jasonmba/.claude/hooks/gsd-session-start.js

# Verify it wrote the file
cat /Users/jasonmba/.claude/cache/claude-session-start-${SESSION}.json

# Step B: write a passing test result via mock PostToolUse
echo "{
  \"tool_name\": \"Bash\",
  \"tool_input\": {\"command\": \"npm test\"},
  \"tool_result\": {\"exit_code\": 0, \"content\": \"5 passed\"}
}" | node /Users/jasonmba/.claude/hooks/gsd-test-build-watcher.js

# Step C: run statusline — should show elapsed time AND test badge
echo "{
  \"model\": {\"display_name\": \"claude-sonnet-4.6\"},
  \"session_id\": \"${SESSION}\",
  \"workspace\": {\"current_dir\": \"/Users/jasonmba/workspace/azure-agentic-platform\"},
  \"context_window\": {\"remaining_percentage\": 60, \"used_percentage\": 40}
}" | node /Users/jasonmba/.claude/hooks/gsd-statusline.js
```

Expected: Line 1 shows model, `+0m` (just started), repo name + branch, context bar. Line 2 shows GSD progress + `✓ tests`.

- [ ] **Step 4: Clean up E2E test files**

```bash
rm -f /Users/jasonmba/.claude/cache/claude-session-start-e2e-*.json
rm -f /Users/jasonmba/.claude/cache/last-test-result.json
rm -f /Users/jasonmba/.claude/cache/last-build-result.json
```

- [ ] **Step 5: Reload Claude Code to activate new hooks**

Close and reopen the Claude Code session (or run `/reload` if available). The `SessionStart` hook will fire and write the session timestamp automatically.

- [ ] **Step 6: Final visual check in live session**

Confirm in the live status line:
- Clock and elapsed time appear on Line 1
- Git branch shows with dirty/clean colour
- Ahead/behind arrows appear if commits are unpushed
- After running `npm test` in a Bash tool, the test badge appears on Line 2 within one tool call

---

## Summary of Changes

| File | What changed |
|---|---|
| `~/.claude/hooks/gsd-statusline.js` | Full rewrite — two-line tiered layout |
| `~/.claude/hooks/gsd-session-start.js` | New file — writes session start timestamp |
| `~/.claude/hooks/gsd-test-build-watcher.js` | New file — caches test/build pass/fail |
| `~/.claude/settings.json` | Added `gsd-session-start.js` to SessionStart; added `gsd-test-build-watcher.js` to PostToolUse |
