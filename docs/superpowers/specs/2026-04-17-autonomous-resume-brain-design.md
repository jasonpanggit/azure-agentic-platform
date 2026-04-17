# Autonomous Resume Brain — Design Spec
**Date:** 2026-04-17  
**Status:** Approved (rev 2 — Stop hook architecture corrected)  
**Goal:** `/clear` → new session starts → Claude resumes mid-task autonomously. Feels like unlimited context window.

---

## Problem

Current state:
- Nothing is saved automatically on session end (no Stop hook)
- SessionStart hook saves only a timestamp — injects no context
- `/save-session` and `/resume-session` exist but require manual invocation
- claude-mem auto-captures but its DB is opaque — unverifiable, uneditable
- Result: every `/clear` is full amnesia

Desired state:
- Claude writes a structured checkpoint automatically on every session end
- Claude reads that checkpoint automatically on every session start
- Claude announces resume state and executes the next action without being asked
- All checkpoints are human-readable Markdown files visible in Obsidian

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  DURING SESSION (proactive — CLAUDE.md rules)               │
│  Claude writes RESUME.md via basic-memory MCP when:        │
│  → task completes, decision made, dead end hit, /clear      │
└──────────────────────────┬──────────────────────────────────┘
                           │ writes Markdown
                    ┌──────▼──────────┐
                    │  ~/brain/       │  ← basic-memory vault
                    │                 │    (readable in Obsidian)
                    └──────┬──────────┘
                           │ reads via MCP + SessionStart hook
┌──────────────────────────▼──────────────────────────────────┐
│  SESSION START (automatic hook)                             │
│  Hook injects RESUME.md + project context                  │
│  claude-mem surfaces relevant past observations            │
│  Claude reads silently → announces resume → continues      │
└─────────────────────────────────────────────────────────────┘
```

### Three Layers

| Layer | Tool | Job |
|---|---|---|
| Auto-capture | claude-mem | Background semantic recorder — never touched manually |
| Deliberate knowledge | basic-memory + Obsidian | Curated checkpoints, decisions, patterns — human-readable |
| Resume engine | CLAUDE.md rules + SessionStart hook | Claude writes checkpoint proactively; hook injects on entry |

---

## Vault Structure

```
~/brain/
├── global/
│   ├── lessons.md          ← cross-project rules, corrections, never-do-agains
│   ├── tech-patterns.md    ← reusable patterns learned across projects
│   └── tooling.md          ← Claude Code setup facts
│
└── projects/
    └── azure-agentic-platform/
        ├── RESUME.md           ← written proactively, injected every SessionStart
        ├── project-status.md
        ├── agent-architecture.md
        ├── web-ui.md
        ├── infrastructure.md
        ├── prod-ops.md
        ├── roadmap.md
        ├── detection-plane.md
        ├── teams-integration.md
        ├── quality-testing.md
        └── decisions/
            └── YYYY-MM-DD-<topic>.md
```

### RESUME.md Schema

```markdown
# Resume Checkpoint
**Last updated:** YYYY-MM-DD HH:MM
**Branch:** <current git branch>
**Session summary:** <2-3 sentences of what happened>

## In Progress
- Task: <exact task name>
- File: <file being edited>
- Step: <what step within the task>
- Status: <where it was left mid-flight>

## Next Actions (ordered)
1. <immediate next step — specific enough to execute>
2. <after that>
3. <after that>

## Decisions Made This Session
- <decision>: <rationale in one line>

## Dead Ends (do not retry)
- <what was tried>: <why it failed>

## Env/Infra Facts Discovered
- <fact discovered at runtime>
```

---

## Hooks

### Why No Stop Hook

A Stop hook fires a shell script **after** Claude has finished — the script cannot instruct Claude to call MCP tools or write files. Claude is already done. The Stop hook is removed from this design.

Instead, RESUME.md is written **proactively during the session** via CLAUDE.md rules. Claude writes the checkpoint when it has meaningful state to capture — after completing a task, before a `/clear`, or on any proactive write trigger. No shutdown hook required.

### SessionStart Hook

The only hook required. Updates `gsd-session-start.js` to:

1. Detect current project from `git remote get-url origin` (fallback: `global/` context if not in a git repo or project not recognised)
2. Read `~/brain/projects/<project>/RESUME.md` (max 200 lines — cap prevents context bloat)
3. Inject content as system context before first user message
4. Skip gracefully if `RESUME.md` does not yet exist (first session)

**`~/.claude/settings.json` addition:**
```json
{
  "mcpServers": {
    "basic-memory": {
      "command": "uvx",
      "args": ["basic-memory", "mcp"],
      "env": {
        "BASIC_MEMORY_HOME": "~/brain"
      }
    }
  }
}
```

**Prerequisites:** `uv` installed (`brew install uv` or `pip install uv`). Falls back to `pip install basic-memory` if `uvx` unavailable.

---

## CLAUDE.md Rules

Added to `~/.claude/CLAUDE.md`:

```markdown
## Autonomous Resume Protocol

At every session start:
1. Read RESUME.md from basic-memory vault silently
2. Announce: "Resuming [project] — was doing [task], next step is [X]. Continuing."
3. Execute next action immediately — do not wait for user confirmation
   unless the next action is destructive (git push, terraform apply, delete)

Before any /clear or when wrapping up work:
1. Write RESUME.md checkpoint — current task, decisions, dead ends, next actions
2. Append new lessons to global/lessons.md
3. Update project-status.md if state changed

Destructive action definition (always confirm before executing on resume):
git push, git reset --hard, terraform apply, terraform destroy, az delete, rm -rf

## Proactive Vault Writes

Write to basic-memory immediately (do not wait for session end) when:
- You hit a dead end or failed approach
- A user correction reveals a wrong assumption
- An architectural decision is finalised
- You discover an env/infra fact not already in prod-ops.md
- You learn unexpected API/SDK behaviour
- You identify a bug root cause

Write discipline:
- Append to existing files — never duplicate entries
- One sentence minimum, three maximum per entry
- Include date, project context, and why it matters
- If unsure whether to write — write it
```

---

## Proactive Mid-Session Writes

| Trigger | Target file | What's written |
|---|---|---|
| User corrects Claude | `global/lessons.md` | Rule + never-do-again pattern |
| Dead end hit | `RESUME.md` + `global/lessons.md` | What failed, why, don't retry |
| Architectural decision | `decisions/YYYY-MM-DD-<topic>.md` | Decision, alternatives, rationale |
| Env/infra fact discovered | `prod-ops.md` | Fact + how discovered |
| New API/SDK behaviour | relevant topic file | Behaviour + version |
| Bug root cause | `global/lessons.md` | Root cause + fix pattern |
| Phase/PR state changes | `project-status.md` | Updated state |

---

## Implementation Phases

### Phase 1 — MVP (prove the loop)
1. Create `~/brain/` vault with correct folder structure
2. Install basic-memory: `pip install basic-memory` (or `brew install uv && uvx basic-memory mcp`)
3. Register basic-memory MCP in `~/.claude/settings.json`
4. Update `gsd-session-start.js` (SessionStart hook — detect project, inject RESUME.md, 200-line cap, graceful skip if missing)
5. Add Autonomous Resume Protocol + Proactive Vault Writes rules to `~/.claude/CLAUDE.md`
6. Create seed `RESUME.md` manually with current project state
7. **Test:** do real work → `/clear` → verify Claude announces resume and executes next action

### Phase 2 — Full system (after MVP confirmed)
1. Install Obsidian, point at `~/brain/`
2. Enable graph view, set up templates for `decisions/`
3. Migrate existing memory files from `.../memory/` to vault
4. Migrate `tasks/lessons.md` content to `global/lessons.md`
5. Verify claude-mem + basic-memory coexist cleanly

---

## Success Criteria

- [ ] `/clear` → new session → Claude announces resume state within first response
- [ ] Claude executes next action without being asked
- [ ] RESUME.md is updated every session end without manual intervention
- [ ] Dead ends are never retried across sessions
- [ ] All knowledge is visible and editable in Obsidian
- [ ] claude-mem continues operating invisibly alongside

---

## What This Is NOT

- Not a replacement for GSD phase planning — GSD manages work structure, this manages memory
- Not a replacement for claude-mem — they are complementary layers
- Not dependent on Obsidian being installed — vault is plain Markdown; Obsidian is optional visibility
