# Autonomous Resume Brain — Design Spec
**Date:** 2026-04-17  
**Status:** Approved  
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
│  STOP (automatic)                                           │
│  Claude writes checkpoint to basic-memory vault            │
│  → current task, decisions, failures, next queue           │
└──────────────────────────┬──────────────────────────────────┘
                           │ writes Markdown
                    ┌──────▼──────────┐
                    │  ~/brain/       │  ← basic-memory vault
                    │                 │    (readable in Obsidian)
                    └──────┬──────────┘
                           │ reads via MCP
┌──────────────────────────▼──────────────────────────────────┐
│  SESSION START (automatic)                                  │
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
| Resume engine | Stop hook + SessionStart hook | Writes checkpoint on exit, injects on entry |

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
        ├── RESUME.md           ← written every Stop, read every Start
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

### Stop Hook

Fires on every session end and `/clear`. Prompts Claude to write RESUME.md via basic-memory MCP before closing.

**`~/.claude/settings.json` addition:**
```json
{
  "hooks": {
    "Stop": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "node ~/.claude/hooks/auto-checkpoint.js"
      }]
    }]
  }
}
```

**`~/.claude/hooks/auto-checkpoint.js`** — injects a system prompt instructing Claude to:
1. Write RESUME.md with current task, decisions, dead ends, next actions
2. Append new lessons to `global/lessons.md`
3. Update `project-status.md` if phase/PR state changed

### SessionStart Hook

Updates `gsd-session-start.js` to additionally:
1. Detect current project from `git remote get-url origin`
2. Read `~/brain/projects/<project>/RESUME.md`
3. Inject content as system context before first user message
4. Fall back to `global/` context if project not recognised

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

At every session end (/clear or Stop):
1. Write RESUME.md checkpoint — current task, decisions, dead ends, next actions
2. Append new lessons to global/lessons.md
3. Update project-status.md if state changed

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
2. Install basic-memory MCP server (`uvx basic-memory mcp`)
3. Register MCP in `~/.claude/settings.json`
4. Write `~/.claude/hooks/auto-checkpoint.js` (Stop hook)
5. Update `gsd-session-start.js` (SessionStart hook — inject RESUME.md)
6. Add Autonomous Resume Protocol to `~/.claude/CLAUDE.md`
7. Migrate existing memory files from `.../memory/` to vault
8. **Test:** do real work → `/clear` → verify Claude resumes correctly

### Phase 2 — Full system (after MVP confirmed)
1. Add proactive mid-session write rules to CLAUDE.md
2. Install Obsidian, point at `~/brain/`
3. Enable graph view, set up templates for decisions/
4. Verify claude-mem + basic-memory coexist cleanly
5. Migrate `tasks/lessons.md` content to `global/lessons.md`

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
