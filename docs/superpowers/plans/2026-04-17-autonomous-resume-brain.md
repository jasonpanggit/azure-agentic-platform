# Autonomous Resume Brain Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude automatically writes a RESUME.md checkpoint during sessions and reads it on every session start — so `/clear` feels like context never cleared.

**Architecture:** basic-memory MCP server provides read/write access to a `~/brain/` Markdown vault. CLAUDE.md rules instruct Claude to write RESUME.md proactively during sessions. The SessionStart hook (`gsd-session-start.js`) is updated to detect the current project, read RESUME.md, and inject it as context before the first user message. claude-mem continues operating alongside as the semantic recall layer.

**Tech Stack:** basic-memory (Python, `uvx basic-memory mcp`), Node.js (SessionStart hook), Markdown vault at `~/brain/`, Claude Code MCP config in `~/.claude/settings.json`

**Spec:** `docs/superpowers/specs/2026-04-17-autonomous-resume-brain-design.md`

---

## Chunk 1: Vault + basic-memory MCP setup

### Task 1: Create the brain vault structure

**Files:**
- Create: `~/brain/global/lessons.md`
- Create: `~/brain/global/tech-patterns.md`
- Create: `~/brain/global/tooling.md`
- Create: `~/brain/projects/azure-agentic-platform/RESUME.md`
- Create: `~/brain/projects/azure-agentic-platform/decisions/.gitkeep`

- [ ] **Step 1: Create vault directories**

```bash
mkdir -p ~/brain/global
mkdir -p ~/brain/projects/azure-agentic-platform/decisions
```

- [ ] **Step 2: Create global/lessons.md**

```bash
cat > ~/brain/global/lessons.md << 'EOF'
# Lessons — Cross-Project Rules

> Rules learned from corrections and dead ends. Never-do-again patterns.
> Format: `- YYYY-MM-DD [project]: <rule>`

EOF
```

- [ ] **Step 3: Create global/tech-patterns.md**

```bash
cat > ~/brain/global/tech-patterns.md << 'EOF'
# Tech Patterns — Cross-Project

> Reusable patterns Claude has learned across projects.
> Format: `## Pattern Name` with context, usage, and caveats.

EOF
```

- [ ] **Step 4: Create global/tooling.md**

```bash
cat > ~/brain/global/tooling.md << 'EOF'
# Tooling Facts

> Claude Code setup facts, hook behaviour, MCP quirks.

## basic-memory MCP
- Vault: ~/brain/
- Config: ~/.claude/settings.json mcpServers.basic-memory
- BASIC_MEMORY_HOME must be absolute path — tilde not expanded in JSON

## claude-mem
- Version: 12.x
- Runs on port 37777
- SQLite + ChromaDB hybrid search
- Auto-captures via lifecycle hooks — never needs manual invocation

EOF
```

- [ ] **Step 5: Create seed RESUME.md**

```bash
cat > ~/brain/projects/azure-agentic-platform/RESUME.md << 'EOF'
# Resume Checkpoint
**Last updated:** 2026-04-17
**Branch:** main
**Session summary:** Set up autonomous resume brain system. basic-memory MCP installed, vault created, SessionStart hook updated, CLAUDE.md rules added.

## In Progress
- Task: Autonomous resume brain implementation
- File: N/A
- Step: Phase 1 MVP complete — ready to test
- Status: Test by doing real work then /clear

## Next Actions (ordered)
1. Do real work on the project
2. Run /clear
3. Verify Claude announces resume state and executes next action without prompting

## Decisions Made This Session
- basic-memory chosen over raw obsidian-mcp: hybrid semantic+keyword search, better recall quality
- claude-mem kept alongside: only tool with native auto-capture hooks
- No Stop hook: Stop fires after Claude is done — cannot prompt writes; CLAUDE.md rules replace it

## Dead Ends (do not retry)
- Stop hook for checkpoint writes: shell script cannot prompt Claude after session ends

## Env/Infra Facts Discovered
- None yet
EOF
```

- [ ] **Step 6: Verify structure**

```bash
find ~/brain -type f | sort
```

Expected output:
```
/Users/jasonmba/brain/global/lessons.md
/Users/jasonmba/brain/global/tech-patterns.md
/Users/jasonmba/brain/global/tooling.md
/Users/jasonmba/brain/projects/azure-agentic-platform/RESUME.md
/Users/jasonmba/brain/projects/azure-agentic-platform/decisions/.gitkeep
```

---

### Task 2: Install basic-memory and register MCP

**Files:**
- Modify: `~/.claude/settings.json`

- [ ] **Step 1: Install uv if not present**

```bash
which uv || brew install uv
```

Expected: path to uv binary, or brew installs it.

- [ ] **Step 2: Verify basic-memory works**

```bash
uvx basic-memory --version
```

Expected: version string (e.g. `basic-memory 0.20.3`). If uvx fails, run `pip install basic-memory` instead and use `basic-memory mcp` as the command.

- [ ] **Step 3: Read current settings.json**

```bash
cat ~/.claude/settings.json
```

Note the current structure — specifically whether `mcpServers` key already exists.

- [ ] **Step 4: Add basic-memory to mcpServers in settings.json**

Open `~/.claude/settings.json` and add `basic-memory` inside the `mcpServers` object.

**If `mcpServers` does not exist**, add this inside the root object:
```json
"mcpServers": {
  "basic-memory": {
    "command": "uvx",
    "args": ["basic-memory", "mcp"],
    "env": {
      "BASIC_MEMORY_HOME": "/Users/jasonmba/brain"
    }
  }
}
```

**If `mcpServers` already exists** (e.g. it has an `obsidian` or other server), add `basic-memory` alongside — do not replace existing entries:
```json
"mcpServers": {
  "existing-server": { "...": "..." },
  "basic-memory": {
    "command": "uvx",
    "args": ["basic-memory", "mcp"],
    "env": {
      "BASIC_MEMORY_HOME": "/Users/jasonmba/brain"
    }
  }
}
```

- [ ] **Step 5: Verify MCP config is valid JSON**

```bash
python3 -c "import json, os; json.load(open(os.path.expanduser('~/.claude/settings.json'))); print('JSON valid')" 2>&1 || echo "INVALID JSON — fix before continuing"
```

Expected: `JSON valid`. Fix any syntax errors before continuing.

- [ ] **Step 6: Commit vault creation**

```bash
cd ~/brain && git init && git add -A && git commit -m "chore: initialise brain vault"
```

Note: vault is its own git repo for version history. Not inside the project repo.

---

## Chunk 2: SessionStart hook update

### Task 3: Update gsd-session-start.js to inject RESUME.md

**Files:**
- Modify: `~/.claude/hooks/gsd-session-start.js` (or wherever it lives — check settings.json for exact path)

- [ ] **Step 1: Find the current hook file path**

```bash
HOOK_PATH=$(cat ~/.claude/settings.json | python3 -c "import json,sys; h=json.load(sys.stdin); hooks=h.get('hooks',{}).get('SessionStart',[]); [print(x.get('command','')) for entry in hooks for x in entry.get('hooks',[])]" | head -1)
echo "Hook path: ${HOOK_PATH:-NOT FOUND — check settings.json manually}"
```

Expected: absolute path to `gsd-session-start.js`. If `NOT FOUND`, open `~/.claude/settings.json` and locate the `SessionStart` hook command path manually.

- [ ] **Step 2: Read the current hook file**

```bash
cat "$HOOK_PATH"
```

Read carefully — note the exact env var used for session ID and the exact cache file path. These must be preserved verbatim in Step 3. Do not proceed until you understand what the existing hook does.

- [ ] **Step 3: Write the updated hook**

Replace the hook file content, preserving existing timestamp logic and appending the RESUME.md injection. The new hook must:

1. Keep existing timestamp write (`~/.claude/cache/claude-session-start-<id>.json`)
2. Detect project from `git remote get-url origin` in cwd
3. Map remote URL to project folder name (e.g. `azure-agentic-platform`)
4. Read `~/brain/projects/<project>/RESUME.md` (max 200 lines)
5. Print the content to stdout — Claude Code SessionStart hooks inject stdout as context
6. Gracefully skip if: not in git repo, project not recognised, RESUME.md missing

```javascript
#!/usr/bin/env node
// gsd-session-start.js
// Preserves: session timestamp tracking
// Adds: RESUME.md injection from ~/brain vault

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

// --- Existing: timestamp tracking ---
const sessionId = process.env.CLAUDE_SESSION_ID || 'unknown';
const cacheDir = path.join(os.homedir(), '.claude', 'cache');
if (!fs.existsSync(cacheDir)) fs.mkdirSync(cacheDir, { recursive: true });
fs.writeFileSync(
  path.join(cacheDir, `claude-session-start-${sessionId}.json`),
  JSON.stringify({ start: Date.now() })
);

// --- New: RESUME.md injection ---
const BRAIN_DIR = path.join(os.homedir(), 'brain');
const MAX_LINES = 200;

function getProjectName() {
  try {
    const remote = execSync('git remote get-url origin 2>/dev/null', {
      cwd: process.cwd(),
      encoding: 'utf8',
      timeout: 3000,
    }).trim();
    // Extract repo name from URL: handles https and ssh formats
    const match = remote.match(/[/:]([^/:]+?)(?:\.git)?$/);
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

function injectResume(projectName) {
  const resumePath = path.join(BRAIN_DIR, 'projects', projectName, 'RESUME.md');
  if (!fs.existsSync(resumePath)) return;

  const lines = fs.readFileSync(resumePath, 'utf8').split('\n');
  const capped = lines.slice(0, MAX_LINES).join('\n');
  const truncated = lines.length > MAX_LINES ? '\n\n[...RESUME.md truncated at 200 lines]' : '';

  console.log(`\n---RESUME---\n${capped}${truncated}\n---END RESUME---\n`);
}

const project = getProjectName();
if (project) {
  injectResume(project);
}
```

- [ ] **Step 4: Make the hook executable**

```bash
chmod +x <path-to-hook>
```

- [ ] **Step 5: Test the hook manually**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
node <path-to-hook>
```

Expected: prints the RESUME.md content wrapped in `---RESUME---` markers.

- [ ] **Step 6: Test graceful fallback (non-git dir)**

```bash
cd /tmp
node <path-to-hook>
```

Expected: no output, no error, exits cleanly.

- [ ] **Step 7: Verify hook was saved**

```bash
ls -la "$HOOK_PATH" && echo "Hook saved successfully"
```

Expected: file listing with updated timestamp. Note: `~/.claude` is not a git repo — the file is saved to disk only. If you want version history, back it up manually:
```bash
cp "$HOOK_PATH" "$HOOK_PATH.bak.$(date +%Y%m%d)"
```

---

## Chunk 3: CLAUDE.md rules

### Task 4: Add Autonomous Resume Protocol to ~/.claude/CLAUDE.md

**Files:**
- Modify: `~/.claude/CLAUDE.md`

- [ ] **Step 1: Read current CLAUDE.md**

```bash
cat ~/.claude/CLAUDE.md
```

Find a good insertion point — after existing workflow rules, before project-specific sections.

- [ ] **Step 2: Add the Autonomous Resume Protocol section**

Insert the following section into `~/.claude/CLAUDE.md`:

```markdown
## Autonomous Resume Protocol

### On every session start
1. The SessionStart hook injects RESUME.md automatically — read it silently
2. Announce: "Resuming [project] — was doing [task], next step is [X]. Continuing."
3. Execute the next action immediately — do not wait for user confirmation
   UNLESS the action is destructive (see list below)

### Before any /clear or when wrapping up work
1. Write RESUME.md to the brain vault via basic-memory MCP:
   - Current task: exact name, file, step, status
   - Next actions: 3 ordered, specific enough to execute
   - Decisions made this session: decision + one-line rationale
   - Dead ends: what failed and why — never retry these
   - Env/infra facts discovered at runtime
2. Append new lessons to ~/brain/global/lessons.md
3. Update ~/brain/projects/<project>/project-status.md if phase/PR state changed

### Destructive actions — always confirm before executing on resume
git push, git reset --hard, terraform apply, terraform destroy, az delete, rm -rf

## Proactive Vault Writes

Write to basic-memory MCP immediately (do not wait for /clear) when ANY of these occur:

| Trigger | Target file |
|---|---|
| User corrects Claude | ~/brain/global/lessons.md |
| Dead end or failed approach hit | RESUME.md dead ends + lessons.md |
| Architectural decision finalised | ~/brain/projects/<project>/decisions/YYYY-MM-DD-<topic>.md |
| Env/infra fact discovered at runtime | ~/brain/projects/<project>/prod-ops.md |
| Unexpected API/SDK behaviour learned | relevant topic file |
| Bug root cause identified | ~/brain/global/lessons.md |
| Phase/PR state changes | ~/brain/projects/<project>/project-status.md |

### Write discipline
- Append to existing files — never duplicate entries
- 1 sentence minimum, 3 maximum per entry
- Include date and project context
- If unsure whether to write — write it
```

- [ ] **Step 3: Verify CLAUDE.md is valid (no broken markdown)**

```bash
cat ~/.claude/CLAUDE.md | grep -c "##"
```

Expected: count increases by 2 (new `## Autonomous Resume Protocol` and `## Proactive Vault Writes` headings).

- [ ] **Step 4: Commit**

```bash
# CLAUDE.md is a user-global file — no git commit needed
# Confirm it was saved correctly
head -5 ~/.claude/CLAUDE.md && echo "..." && grep -n "Autonomous Resume" ~/.claude/CLAUDE.md
```

Expected: line number of new section printed.

---

## Chunk 4: End-to-end test

### Task 5: Verify the full resume loop

This task proves the system works. Do it with real project work — not a synthetic test.

- [ ] **Step 1: Start a real work session**

Open Claude Code in `/Users/jasonmba/workspace/azure-agentic-platform`. Do something meaningful — edit a file, fix a bug, make a decision. Anything that produces real state worth resuming.

- [ ] **Step 2: Ask Claude to write RESUME.md before clearing**

Prompt: `"Before I clear context, write the current RESUME.md checkpoint to the brain vault."`

Expected: Claude uses basic-memory MCP `create-note` or `edit-note` tool to write/update `~/brain/projects/azure-agentic-platform/RESUME.md`.

- [ ] **Step 3: Verify RESUME.md was written**

```bash
cat ~/brain/projects/azure-agentic-platform/RESUME.md
```

Expected: updated content reflecting what was just done — current task, next actions, any decisions.

- [ ] **Step 4: Clear context**

Run `/clear` in Claude Code.

- [ ] **Step 5: Verify auto-resume**

The new session should start with Claude announcing resume state. Expected first response pattern:

```
Resuming azure-agentic-platform — was doing [task], next step is [X]. Continuing.
```

Claude should then proceed to execute the next action without being asked.

- [ ] **Step 6: If resume doesn't fire — debug**

Check hook output:
```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
node <path-to-gsd-session-start.js>
```

If no output: RESUME.md path mismatch — verify `getProjectName()` returns `azure-agentic-platform`.
If hook output looks right but Claude ignores it: check CLAUDE.md rule is present and correctly formatted.

- [ ] **Step 7: Confirm dead ends are preserved**

Ask Claude: "What approaches have been tried and failed for this project?"

Expected: Claude references the Dead Ends section from RESUME.md without re-suggesting them.

---

## Success Criteria

- [ ] `/clear` → new session → Claude announces resume state in first response
- [ ] Claude executes next action without being asked (non-destructive)
- [ ] RESUME.md updated before every `/clear` via basic-memory MCP
- [ ] Dead ends not retried across sessions
- [ ] Hook runs without error in both git and non-git directories
- [ ] basic-memory MCP tools appear in Claude's available tools list

---

## Phase 2 (deferred — after MVP confirmed)

1. Install Obsidian, open `~/brain/` as vault
2. Enable graph view — see connections between decisions and lessons
3. Migrate `~/.claude/projects/.../memory/*.md` into `~/brain/projects/azure-agentic-platform/`
4. Migrate `tasks/lessons.md` content to `~/brain/global/lessons.md`
5. Verify claude-mem + basic-memory coexist (both active simultaneously)
