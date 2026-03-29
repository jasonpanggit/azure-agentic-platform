---
quick_id: 260329-qro
task: validate 08-01 provisioning gaps are done
date: 2026-03-29
status: complete
---

# Plan: Validate 08-01 Provisioning Gaps

## Objective

Read-only validation of the 5 operator tasks listed in
`.planning/phases/08-azure-validation-incident-simulation/08-01-USER-SETUP.md`.
No changes to any resource.

## Checks

| # | Task | CLI Command |
|---|------|-------------|
| 1 | 08-01-02: Foundry Orchestrator Agent created | `az containerapp show ... --query env[ORCHESTRATOR_AGENT_ID]` |
| 2 | 08-01-03: ORCHESTRATOR_AGENT_ID + CORS set on gateway | `az containerapp show ... --query env[ORCHESTRATOR_AGENT_ID\|CORS_ALLOWED_ORIGINS]` |
| 3 | 08-01-04: Azure AI Developer role on gateway MI | `az role assignment list --assignee 69e05934-...` |
| 4 | 08-01-05: Azure Bot Service + Teams channel | `az bot show --name aap-teams-bot-prod ...` |
| 5 | 08-01-06: 3 GitHub secrets present | `gh secret list \| grep POSTGRES_ADMIN_PASSWORD\|AZURE_OPENAI_*` |

## Constraints

- Read-only: no `az ... create/update/set`, no `gh secret set`
- No commits
- Report ✅ Done / ❌ Not done / ⚠️ Partial per task
