---
phase: 19-production-stabilisation
plan: 5
subsystem: teams-bot
tags: [teams, proactive-alerting, terraform, manifest, bot-framework, PROD-005]

# Dependency graph
requires:
  - phase: 19-production-stabilisation plan 2
    provides: Auth enablement (Bearer token for E2E test)
provides:
  - scripts/ops/19-5-package-manifest.sh (Teams app manifest packaging)
  - scripts/ops/19-5-test-teams-alerting.sh (proactive alerting E2E test)
  - terraform.tfvars teams_channel_id placeholder with operator instructions
affects:
  - ca-teams-bot-prod (TEAMS_CHANNEL_ID env var)
  - teams proactive alert delivery (PROD-005)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "teams_channel_id placeholder in terraform.tfvars with operator instructions"
    - "manifest placeholder substitution script (BOT_ID, CONTAINER_APP_FQDN)"
    - "pre-flight 503 check for ConversationReference readiness"

key-files:
  created:
    - scripts/ops/19-5-package-manifest.sh
    - scripts/ops/19-5-test-teams-alerting.sh
  modified:
    - terraform/envs/prod/terraform.tfvars

key-decisions:
  - "TEAMS_CHANNEL_ID variable + wiring already existed end-to-end (prod/variables.tf, prod/main.tf, agent-apps/variables.tf, agent-apps/main.tf) — Task 9 only needed the tfvars placeholder"
  - "teams_channel_id in teams-bot module variables.tf is NOT needed — the variable belongs in agent-apps which owns the Container App env var"
  - "Import blocks for bot resources already present (commented) in imports.tf — no new blocks required"
  - "Tasks 2, 3, 4, 6, 8 are operator-only steps encapsulated in the two new scripts"
  - "19-5-test-teams-alerting.sh exits gracefully without E2E credentials (prints operator checklist)"

requirements-completed:
  - PROD-005 (code complete; operator must install bot and set TEAMS_CHANNEL_ID to activate)

# Metrics
duration: 22min
completed: 2026-04-02
---

# Phase 19 Plan 5: Teams Proactive Alerting Summary

**Operator runbooks and Terraform scaffolding to enable Teams proactive alert delivery — resolving PROD-005 / F-04 / GAP-004 once the operator installs the bot and captures the channel ID**

## Performance

- **Duration:** 22 min
- **Started:** 2026-04-02T09:00:00Z
- **Completed:** 2026-04-02T09:22:00Z
- **Tasks:** 9 (3 code tasks + 6 operator-only steps)
- **Files modified/created:** 3

## Accomplishments

- Created `scripts/ops/19-5-package-manifest.sh` — packages the Teams app manifest for deployment, auto-substituting `${{BOT_ID}}` and `${{CONTAINER_APP_FQDN}}` placeholders, and prints step-by-step channel ID capture instructions
- Created `scripts/ops/19-5-test-teams-alerting.sh` — full E2E test covering: TEAMS_CHANNEL_ID pre-flight, bot Service messaging endpoint verification, proactive notify readiness probe (503 = ConversationReference not captured), synthetic Sev1 incident injection, and PROD-005 success criteria checklist
- Updated `terraform/envs/prod/terraform.tfvars` — added `teams_channel_id = ""` placeholder with operator instructions for capturing and persisting the channel ID

## Task Commits

All code tasks committed atomically in one commit:

1. **Tasks 1, 5, 7, 9: manifest packaging + E2E test + tfvars placeholder** - `56f1aed` (feat)

Tasks 2 (terraform plan), 3 (verify env vars), 4 (verify bot endpoint), 6 (capture channel ID), and 8 (run E2E test) are operator-only steps documented in the two new scripts.

## Files Created/Modified

- `scripts/ops/19-5-package-manifest.sh` — auto-resolves BOT_ID and CONTAINER_APP_FQDN via az CLI or env vars, substitutes placeholders in `appPackage/manifest.json`, builds `aap-teams-bot.zip`, prints installation and channel ID capture instructions
- `scripts/ops/19-5-test-teams-alerting.sh` — E2E test: pre-flight checks, Container App env var summary, bot endpoint verification, proactive notify readiness probe, synthetic Sev1 incident injection, log check commands, PROD-005 checklist
- `terraform/envs/prod/terraform.tfvars` — added `teams_channel_id` placeholder with operator instructions

## Decisions Made

- **`teams_channel_id` wiring pre-existing:** The variable declaration (`prod/variables.tf`), module pass-through (`prod/main.tf`), module variable (`agent-apps/variables.tf`), and Container App env var (`agent-apps/main.tf` line 394-396) were all already implemented. Task 9 only required adding the `teams_channel_id = ""` entry to `terraform.tfvars` so the value persists across terraform applies.
- **`teams-bot/variables.tf` unchanged:** The plan suggested adding `teams_channel_id` to the teams-bot module — but the env var belongs to the `agent-apps` module (which owns the Container App), not the `teams-bot` module (which owns the Bot Service resource and Entra app). Adding it to the wrong module would have created dead code.
- **Import blocks already present:** The four bot resource import blocks (Bot Service, Entra app, service principal, Teams channel) are already in `imports.tf` with accurate resource IDs and documented pre-requisites. No new blocks required.
- **`19-5-package-manifest.sh` uses `sed` substitution:** The manifest uses `${{BOT_ID}}` placeholder syntax (Teams Toolkit format) — `sed -e "s|\${{BOT_ID}}|${BOT_ID}|g"` handles this without modifying the source file.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Clarification] `teams-bot/variables.tf` change not needed**
- **Found during:** Task 9 review
- **Issue:** Plan suggested adding `teams_channel_id` to `terraform/modules/teams-bot/variables.tf`, but TEAMS_CHANNEL_ID is set on the Container App in `agent-apps/main.tf`, not in the teams-bot module
- **Fix:** Verified end-to-end wiring is already complete; only added the `tfvars` placeholder
- **Impact:** Avoided introducing dead code in the teams-bot module

**2. [Rule 2 - Pre-existing] Task 9 Terraform wiring was already complete**
- **Found during:** Pre-execution code scan
- **Issue:** `teams_channel_id` variable and `TEAMS_CHANNEL_ID` env var injection were already wired end-to-end from Phase 7 (Plan 07-04)
- **Fix:** Task 9 reduced to adding the `terraform.tfvars` placeholder — no module changes needed
- **Impact:** No scope creep; confirms existing architecture is correct

---

**Total deviations:** 2 (both auto-resolved; both clarifications not bugs)

## Issues Encountered

None — the code infrastructure for Teams proactive alerting was already complete. The plan correctly identified that the remaining gap is operational: the bot must be installed in a Teams channel and TEAMS_CHANNEL_ID must be captured and set.

## User Setup Required

**To activate PROD-005 (Teams proactive alerting), the operator must:**

1. **Package the manifest:**
   ```bash
   export BOT_ID="d5b074fc-7ca6-4354-8938-046e034d80da"
   export CONTAINER_APP_FQDN="ca-teams-bot-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
   bash scripts/ops/19-5-package-manifest.sh
   ```

2. **Install the bot in Teams:**
   - Teams → Apps → Manage your apps → Upload a custom app
   - Select `services/teams-bot/appPackage/aap-teams-bot.zip`
   - Add to team/channel (e.g., `#azure-ops-alerts`)
   - Confirm bot posts greeting and `onInstallationUpdate` fires

3. **Capture the channel ID** (from bot logs or Teams admin center):
   ```bash
   az containerapp logs show --name ca-teams-bot-prod --resource-group rg-aap-prod \
     --tail 50 | grep -i 'channelId\|channel'
   ```

4. **Set TEAMS_CHANNEL_ID on the Container App:**
   ```bash
   TEAMS_CHANNEL_ID="<channel-id>"
   az containerapp update --name ca-teams-bot-prod --resource-group rg-aap-prod \
     --set-env-vars "TEAMS_CHANNEL_ID=${TEAMS_CHANNEL_ID}"
   ```

5. **Persist in Terraform** — update `terraform/envs/prod/terraform.tfvars`:
   ```hcl
   teams_channel_id = "<channel-id>"
   ```
   Then run:
   ```bash
   cd terraform/envs/prod
   terraform plan -var-file=credentials.tfvars -target=module.agent_apps
   terraform apply -var-file=credentials.tfvars -target=module.agent_apps
   ```

6. **Run E2E verification:**
   ```bash
   export E2E_CLIENT_ID="<from GitHub secrets>"
   export E2E_CLIENT_SECRET="<from GitHub secrets>"
   bash scripts/ops/19-5-test-teams-alerting.sh
   ```

See `scripts/ops/19-5-test-teams-alerting.sh` for the full PROD-005 success criteria checklist.

## Next Phase Readiness

- Plan 19-5 code complete — operator steps remain
- Phase 19 all 5 plans complete (wave 3 wrap-up)
- PROD-005 will be resolved once operator runs steps 1-6 above
- Bot restart after TEAMS_CHANNEL_ID update triggers re-capture of ConversationReference — send bot a message in Teams to verify

---
*Phase: 19-production-stabilisation*
*Completed: 2026-04-02*
