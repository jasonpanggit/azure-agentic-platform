# Quick Task Summary: 260328-va0

**Task:** Validate MANUAL-SETUP.md Provisioning State
**Date:** 2026-03-28
**Type:** Read-only validation
**Branch:** `quick/260328-va0-validate-manual-setup`

---

## Objective

Determine which of the 10 MANUAL-SETUP.md steps are already provisioned vs. still pending by running read-only Azure CLI queries against `rg-aap-prod`.

---

## Results

| Step | Description | Status |
|------|-------------|--------|
| 1 | API Gateway env vars | **PARTIAL** — Terraform-injected vars differ from guide names; `ORCHESTRATOR_AGENT_ID` missing; `CORS_ALLOWED_ORIGINS=*` |
| 2 | Foundry RBAC | **PENDING** — `Azure AI Developer` role not assigned to gateway MI; has `Cognitive Services User` |
| 3 | Log Analytics on Web UI | **DONE** |
| 4 | Cosmos DB incidents + RBAC | **DONE** — container exists, 10 SQL role assignments including gateway + orchestrator |
| 5 | Teams Bot Registration | **PARTIAL** — Container App exists; Azure Bot resource not created |
| 6 | GitHub Secrets/Variables | **PARTIAL** — 6/9 secrets, 4/4 variables; missing `POSTGRES_ADMIN_PASSWORD`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` |
| 7 | Runbook Seeding | **CANNOT_VERIFY** — seed script exists; PG server exists; VNet blocks remote verification |
| 8 | Multi-Sub Reader | **SKIPPED** — optional; single-subscription deployment |
| 9 | Entra Redirect URIs | **DONE** |
| 10 | Secret Rotation | **PARTIAL** — `.gitignore` has `credentials.tfvars`; rotation status unverifiable |

---

## Blocking Issues (Platform Will Not Work)

1. **Step 1 — `ORCHESTRATOR_AGENT_ID` not set** — Foundry agent dispatch will fail. Need to create the orchestrator agent in AI Foundry and inject its ID.
2. **Step 2 — `Azure AI Developer` role missing** — Gateway MI cannot manage Foundry agents. Currently has `Cognitive Services User` which may allow inference but not full agent access.
3. **Step 1 — `CORS_ALLOWED_ORIGINS=*`** — Security risk in production; should be locked to `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io`.

## Documentation Discrepancies

- Guide says `AZURE_PROJECT_ENDPOINT` but Terraform injects `FOUNDRY_ACCOUNT_ENDPOINT` — verify api-gateway code for actual var name
- Guide says partition key `/incident_id` but actual container uses `/resource_id`

---

## Artifacts

- **Detailed report:** [260328-va0-REPORT.md](./260328-va0-REPORT.md)
- **Plan:** [260328-va0-PLAN.md](./260328-va0-PLAN.md)
