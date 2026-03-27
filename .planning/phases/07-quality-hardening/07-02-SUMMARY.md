# Plan 07-02 Summary: Remediation Audit Trail + Audit Export

## Goal

Implement the OneLake remediation audit trail (REMEDI-007) so every executed/rejected/expired remediation event is recorded in Fabric OneLake with the required schema, and add a report export endpoint + UI button for SOC 2 audit readiness (AUDIT-006).

## Tasks Completed

### Task 7-02-01: remediation_logger.py — OneLake write module ✅
- Added `azure-storage-file-datalake>=12.0.0` to `services/api-gateway/requirements.txt`
- Created `services/api-gateway/remediation_logger.py` with:
  - `async def log_remediation_event(event)` — fire-and-forget OneLake write (never raises)
  - `def build_remediation_event(approval_record, outcome, ...)` — builds REMEDI-007 schema dict
  - Date-partitioned OneLake path: `year=YYYY/month=MM/day=DD`
  - Conditional on `FABRIC_WORKSPACE_NAME` + `FABRIC_LAKEHOUSE_NAME` env vars

### Task 7-02-02: Hook remediation_logger into approvals.py ✅
- Added import of `build_remediation_event` and `log_remediation_event` to `approvals.py`
- `process_approval_decision()` now calls `log_remediation_event` for:
  - Approve/reject decisions (after Cosmos DB update, before Foundry thread resume)
  - Expired records (after marking expired in Cosmos, before raising ValueError)
- All OneLake log calls wrapped in `try/except` — never break the approval flow

### Task 7-02-03: audit_export.py + AuditExportResponse model + export endpoint ✅
- Created `services/api-gateway/audit_export.py` with:
  - `async def generate_remediation_report(from_time, to_time)` — returns structured report
  - `async def _read_onelake_events(from_time, to_time)` — reads date-partitioned OneLake files
  - `async def _read_approval_records(from_time, to_time)` — reads from Cosmos DB
  - Falls back to Cosmos DB records when OneLake has no data
  - Each event enriched with full `approval_chain` object
- Added `class AuditExportResponse(BaseModel)` to `services/api-gateway/models.py`
- Added `GET /api/v1/audit/export` endpoint to `services/api-gateway/main.py`
  - Requires `from_time` and `to_time` query params
  - Requires `Depends(verify_token)` authentication

### Task 7-02-04: AuditLogViewer "Export Report" button ✅
- Added `Button` to Fluent UI imports in `AuditLogViewer.tsx`
- Added `import { DocumentTextRegular } from '@fluentui/react-icons'`
- Added `exportLoading` state for double-click prevention
- Added `handleExport` callback:
  - Fetches `/api/proxy/audit/export` with 30-day default time range
  - Triggers browser file download with filename `remediation-report-{from}-{to}.json`
- Added Export Report `<Button>` with `appearance="subtle"` and `DocumentTextRegular` icon inside `<Toolbar>`

### Task 7-02-05: Unit tests ✅
- Created `services/api-gateway/tests/test_remediation_logger.py` — 7 test functions:
  - `test_build_remediation_event_approved` — all 10 REMEDI-007 schema fields
  - `test_build_remediation_event_rejected` — outcome + durationMs=0 + toolName fallback
  - `test_build_remediation_event_expired_no_decided_by` — expired with no approvedBy
  - `test_build_remediation_event_all_ten_schema_fields` — exact schema key set assertion
  - `test_log_remediation_event_skips_when_not_configured` — no-op with empty env vars
  - `test_log_remediation_event_writes_to_onelake` — ADLS SDK call verification via sys.modules mock
  - `test_log_remediation_event_does_not_raise_on_error` — fire-and-forget pattern verified
- Created `services/api-gateway/tests/test_audit_export.py` — 5 test functions:
  - `test_generate_report_from_cosmos_fallback` — Cosmos DB as fallback when no OneLake data
  - `test_generate_report_empty` — empty report with correct metadata structure
  - `test_generate_report_enriches_onelake_events_with_approval_chain` — enrichment path
  - `test_generate_report_multiple_events_from_cosmos` — multiple events with mixed outcomes
  - `test_generate_report_metadata_structure` — period + total_events + generated_at fields

## Files Modified

| File | Change |
|---|---|
| `services/api-gateway/requirements.txt` | Added `azure-storage-file-datalake>=12.0.0` |
| `services/api-gateway/approvals.py` | Added REMEDI-007 logging calls for approve/reject/expire |
| `services/api-gateway/models.py` | Added `AuditExportResponse(BaseModel)` |
| `services/api-gateway/main.py` | Added `GET /api/v1/audit/export` endpoint |
| `services/web-ui/components/AuditLogViewer.tsx` | Added Button import, DocumentTextRegular icon, exportLoading state, handleExport, Export Report button |

## Files Created

| File | Purpose |
|---|---|
| `services/api-gateway/remediation_logger.py` | OneLake write module (REMEDI-007) |
| `services/api-gateway/audit_export.py` | Remediation report generation (AUDIT-006) |
| `services/api-gateway/tests/test_remediation_logger.py` | Unit tests for remediation_logger |
| `services/api-gateway/tests/test_audit_export.py` | Unit tests for audit_export |

## Acceptance Criteria Results

### REMEDI-007
- [x] `requirements.txt` contains `azure-storage-file-datalake>=12.0.0`
- [x] `remediation_logger.py` exists with `async def log_remediation_event(event: dict`
- [x] `build_remediation_event` returns dict with all 10 required fields
- [x] Fire-and-forget pattern: catches all exceptions, logs error, never raises
- [x] OneLake path includes date partitioning: `year=YYYY/month=MM/day=DD`
- [x] Conditional on `FABRIC_WORKSPACE_NAME` and `FABRIC_LAKEHOUSE_NAME` env vars
- [x] `approvals.py` calls `log_remediation_event` for approved/rejected and expired records
- [x] All OneLake log calls wrapped in `try/except` — never break the approval flow

### AUDIT-006
- [x] `audit_export.py` contains `async def generate_remediation_report(`
- [x] Returns `report_metadata` with `generated_at`, `period`, `total_events`
- [x] Each `remediation_events` item contains `agentId`, `toolName`, `toolParameters`, `approvedBy`, `outcome`, `approval_chain`
- [x] `models.py` contains `class AuditExportResponse(BaseModel)`
- [x] `main.py` contains `@app.get("/api/v1/audit/export"`
- [x] Endpoint requires `from_time` and `to_time` query parameters
- [x] Endpoint requires authentication via `Depends(verify_token)`
- [x] `AuditLogViewer.tsx` contains `import { DocumentTextRegular } from '@fluentui/react-icons'`
- [x] Export button with `appearance="subtle"` and `DocumentTextRegular` icon
- [x] `handleExport` fetches `/api/proxy/audit/export` with `from_time`/`to_time`
- [x] Download triggers with filename `remediation-report-{from}-{to}.json`
- [x] `exportLoading` state prevents double-click

### Tests
- [x] All 12 unit tests pass (`pytest services/api-gateway/tests/test_remediation_logger.py services/api-gateway/tests/test_audit_export.py`)

## Test Results

```
12 passed, 1 warning in 0.07s
```
