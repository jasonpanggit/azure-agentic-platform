---
status: complete
phase: 27-closed-loop-remediation
source: [27-VERIFICATION.md, 27-3-execute-endpoint-PLAN.md, 27-2-remediation-executor-PLAN.md]
started: 2026-04-04T00:00:00Z
updated: 2026-04-04T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Execute endpoint exists and rejects missing approvals
expected: POST /api/v1/approvals/nonexistent-id/execute returns HTTP 404.
result: pass
notes: test_execute_returns_404_for_missing_approval ✅ confirmed via unit test

### 2. Execute endpoint rejects expired approvals with 410
expected: A previously-created approval past its expiry returns HTTP 410 Gone.
result: pass
notes: test_execute_returns_410_for_expired_approval ✅ confirmed via unit test

### 3. Verification endpoint returns 202 + Retry-After while pending
expected: GET /api/v1/approvals/{id}/verification for pending execution returns HTTP 202 with Retry-After: 60 header.
result: pass
notes: test_verification_returns_202_while_pending ✅ — JSONResponse(status_code=202) + Retry-After header confirmed

### 4. Verification endpoint returns full audit record when complete
expected: GET /api/v1/approvals/{id}/verification returns HTTP 200 with verification_result, executed_at, status, preflight_blast_radius_size.
result: pass
notes: test_verification_returns_audit_record_when_complete ✅ — full RemediationAuditRecord returned

### 5. Remediation audit export endpoint is accessible
expected: GET /api/v1/audit/remediation-export returns HTTP 200 with sources list including "cosmos_remediation_audit".
result: pass
notes: test_remediation_export_includes_cosmos_audit_records ✅ + test_export_endpoint_handler ✅

### 6. Unit test suite passes (31 Phase 27 tests)
expected: python3 -m pytest test_remediation_executor.py test_execute_endpoint.py exits 0. All 31 tests pass.
result: pass
notes: 31/31 passed — 19 executor tests + 12 endpoint tests. 2 RuntimeWarning about unawaited coroutines are expected fire-and-forget artefacts (documented in VERIFICATION.md).

### 7. WAL stale monitor starts in lifespan logs
expected: Startup log contains "startup: WAL stale monitor started".
result: pass
notes: Confirmed in main.py line 356: `logger.info("startup: WAL stale monitor started | interval=300s")`

### 8. remediation_audit Cosmos container provisioned in Terraform
expected: cosmos.tf contains azurerm_cosmosdb_sql_container.remediation_audit with partition_key_paths = ["/incident_id"] and no TTL.
result: pass
notes: Confirmed — partition_key_version=2, partition="/incident_id", no default_ttl field

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none]
