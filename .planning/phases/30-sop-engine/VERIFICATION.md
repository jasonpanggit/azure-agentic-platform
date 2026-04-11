---
phase: 30-sop-engine
verified: 2026-04-11
status: passed
verifier: claude
---

# Phase 30 Verification — SOP Engine

**Overall Status: ✅ PASSED**

All 8 must-have success criteria are met. Two minor naming deviations from the verification checklist are noted below — both are intentional adaptations that follow existing project conventions and do not represent gaps.

---

## Must-Have Checklist

### 1. PostgreSQL Migration — `sops` table ✅

**File:** `services/api-gateway/migrations/003_create_sops_table.py`

Present and correct. Schema includes all required columns:

| Column (verification spec) | Column (implementation) | Status |
|---|---|---|
| `id` | `id UUID PRIMARY KEY DEFAULT gen_random_uuid()` | ✅ |
| `filename` | `foundry_filename TEXT NOT NULL UNIQUE` | ✅ (renamed — see note) |
| `title` | `title TEXT NOT NULL` | ✅ |
| `domain` | `domain TEXT NOT NULL` | ✅ |
| `resource_type` | `resource_types TEXT[]` | ✅ (plural array — richer design) |
| `scenario_tags[]` | `scenario_tags TEXT[]` | ✅ |
| `content_hash` | `content_hash TEXT` | ✅ |
| `vector_store_file_id` | `foundry_file_id TEXT` | ✅ (renamed — see note) |

**Additional columns beyond spec:** `version`, `description`, `severity_threshold`, `is_generic`, `created_at`, `updated_at` — all additive, no gaps.

Indexes: `idx_sops_domain_generic (domain, is_generic)` and `idx_sops_foundry_filename` — both present.

**Note on naming:** The verification checklist used `filename` and `vector_store_file_id`. The implementation uses `foundry_filename` and `foundry_file_id` — more descriptive names that make the Foundry-specific context clear. The SUMMARY.md documents this as an intentional adaptation. Not a gap.

---

### 2. `agents/shared/sop_store.py` — `provision_sop_vector_store()` ✅

**File:** `agents/shared/sop_store.py`

- `provision_sop_vector_store(project, sop_files)` function present
- Uses `project.get_openai_client()` → `openai.vector_stores.create(name="aap-sops-v1")` ✅
- Uploads each SOP file via `vector_stores.files.upload_and_poll()` ✅
- Returns vector store ID string ✅
- Docstring correctly marks it as exclusive to `scripts/upload_sops.py` ✅

---

### 3. `agents/shared/sop_loader.py` — `select_sop_for_incident()` ✅

**File:** `agents/shared/sop_loader.py`

- `select_sop_for_incident(incident, domain, pg_conn)` async function present ✅
- Tag overlap SQL using `ARRAY(SELECT unnest(scenario_tags) INTERSECT SELECT unnest($3::text[]))` ✅
- Two-layer lookup: scenario-specific first, generic domain fallback second ✅
- Returns `SopLoadResult` dataclass with `grounding_instruction` ✅
- Grounding instruction includes `file_search` reference, `REMEDIATION` rules, `ApprovalRecord` requirement, and `sop_notify` rule ✅
- `ValueError` raised if no SOP found (not silently swallowed) ✅

---

### 4. `agents/shared/sop_notify.py` — `sop_notify` @ai_function ✅

**File:** `agents/shared/sop_notify.py`

- `@ai_function` decorator applied ✅
- `channels: list[Literal["teams", "email"]]` — no "both" shorthand ✅
- Teams and email channels handled independently ✅
- Failures logged but never raised (never interrupts agent workflow) ✅
- Structured error dict returned on failure ✅
- `azure.communication.email.EmailClient` used for ACS email ✅

---

### 5. Teams bot — 3 new card types ✅

**File:** `services/teams-bot/src/types.ts`

`CardType` union extended to:
```typescript
| "sop_notification" | "sop_escalation" | "sop_summary"
```
All three present ✅

**Payload interfaces present:**
- `SopNotificationPayload` (incident_id, resource_name, message, severity, sop_step) ✅
- `SopEscalationPayload` (incident_id, resource_name, message, sop_step, context) ✅
- `SopSummaryPayload` (incident_id, resource_name, sop_title, steps_run, steps_skipped, outcome) ✅

**Card builder files:**
- `services/teams-bot/src/cards/sop-notification-card.ts` ✅
- `services/teams-bot/src/cards/sop-escalation-card.ts` ✅
- `services/teams-bot/src/cards/sop-summary-card.ts` ✅

**Note on location:** The verification checklist referenced `card-builder.ts`. The existing codebase uses individual files per card in `src/cards/` — the implementation followed that convention. Not a gap.

---

### 6. `scripts/upload_sops.py` — SHA-256 content hash idempotency ✅

**File:** `scripts/upload_sops.py`

- `compute_sop_hash(sop_path)` uses `hashlib.sha256(content).hexdigest()` ✅
- Idempotency check: fetches existing row by `foundry_filename`, compares `content_hash`, skips if match ✅
- On update: deletes old Foundry file, re-uploads, upserts PostgreSQL row ✅
- YAML front matter parsed via `parse_sop_front_matter()` ✅
- `SOP_VECTOR_STORE_ID` written to `.env.sops` after run ✅
- Template files (`_` prefix) skipped ✅

---

### 7. Terraform — ACS Email resource ✅

**File:** `terraform/modules/notifications/main.tf`

- `azurerm_email_communication_service.acs_email` resource present ✅
- `azurerm_communication_service.acs` resource present ✅
- Separate `terraform/modules/notifications/` module (clean separation) ✅
- `SOP_VECTOR_STORE_ID` env var via `sop_vector_store_id` variable in `terraform/modules/agent-apps/variables.tf` ✅
- `notification_email_from` and `notification_email_to` variables also present ✅

**Note:** The verification checklist referenced `infra/terraform/acs.tf`. The implementation created `terraform/modules/notifications/main.tf` — a module-based approach consistent with the existing Terraform structure (`terraform/modules/`). Not a gap; better separation.

---

### 8. Integration smoke test ✅

**File:** `agents/tests/integration/test_phase30_smoke.py`

11 smoke tests present and covering:

| Test | Covers |
|---|---|
| `test_sop_store_importable` | `provision_sop_vector_store` importable |
| `test_sop_loader_importable` | `select_sop_for_incident` + `SopLoadResult` importable |
| `test_sop_notify_importable` | `sop_notify` importable |
| `test_migration_file_exists` | Migration file at correct path |
| `test_upload_sops_script_importable` | All upload_sops functions importable |
| `test_sop_store_vector_store_name` | Store name = "aap-sops-v1" |
| `test_sop_loader_returns_grounding_for_mock_incident` | grounding contains `file_search` |
| `test_sop_loader_grounding_contains_remediation_rule` | grounding contains `REMEDIATION` + `ApprovalRecord` |
| `test_terraform_notifications_module_exists` | All 3 Terraform notification files present |
| `test_terraform_agent_apps_has_sop_vector_store_var` | `sop_vector_store_id` in agent-apps variables |
| `test_terraform_agent_apps_has_notification_email_vars` | Both email vars in agent-apps variables |

---

## Additional Verification Items

### Test coverage

52 new tests added across 6 test files. Summary reports 112 Teams bot tests passing, 0 failures. Pre-existing failures (8) are unrelated to Phase 30 (eol_agent, patch_agent, approval_lifecycle).

### Naming deviations (intentional, not gaps)

| Checklist reference | Actual implementation | Reason |
|---|---|---|
| `007_sops.sql` | `003_create_sops_table.py` | Followed existing Python async migration pattern; numbered to fit existing sequence |
| `card-builder.ts` | `src/cards/sop-{type}-card.ts` | Followed existing per-card file structure |
| `infra/terraform/acs.tf` | `terraform/modules/notifications/main.tf` | Followed existing Terraform module structure |
| `vector_store_file_id` column | `foundry_file_id` column | More descriptive naming; functionally identical |
| `filename` column | `foundry_filename` column | More descriptive naming; functionally identical |

All deviations are documented in the SUMMARY.md `Deviations from Plan` section.

---

## Summary

| # | Criterion | Status |
|---|---|---|
| 1 | `sops` migration with correct columns | ✅ passed |
| 2 | `sop_store.py` with `provision_sop_vector_store()` | ✅ passed |
| 3 | `sop_loader.py` with `select_sop_for_incident()` + tag overlap SQL | ✅ passed |
| 4 | `sop_notify.py` with `@ai_function` + `channels: list[Literal[...]]` | ✅ passed |
| 5 | Teams bot — 3 new card types + payload interfaces + card builders | ✅ passed |
| 6 | `upload_sops.py` with SHA-256 idempotency | ✅ passed |
| 7 | Terraform ACS Email resource | ✅ passed |
| 8 | Integration smoke test (11 tests) | ✅ passed |

**Phase 30 goal: ACHIEVED ✅**
