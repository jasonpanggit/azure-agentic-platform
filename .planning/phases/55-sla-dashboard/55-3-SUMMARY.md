---
wave: 3
status: complete
---

## Summary

Created `services/api-gateway/sla_report.py` and `tests/test_sla_report.py`. Extended `sla_endpoints.py`.

### sla_report.py
**ReportResult** Pydantic model with all fields.

**_build_narrative(compliance_result, sla_def):**
- Calls GPT-4o via `AIProjectClient` if available + `AZURE_AI_PROJECT_ENDPOINT` set
- Falls back to `_fallback_narrative()` on any exception, missing SDK, or missing env var

**_build_pdf(sla_def, compliance_result, narrative, incidents) → bytes:**
- 4-section ReportLab PDF: cover page, attainment summary table, resource breakdown, incidents log, executive summary
- Header rows: `HexColor("#0078D4")` with white text; compliant rows: `#d4edda`; breach: `#f8d7da`
- Falls back to `b"PDF generation unavailable: reportlab not installed."` if reportlab absent

**_send_email(pdf_bytes, sla_name, period, recipients) → list[str]:**
- SMTP with STARTTLS (port 587); returns `[]` when `SMTP_HOST` unset or send fails
- 5 env vars: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`

**generate_and_send_sla_report(sla_id) → ReportResult (async):**
- Loads SLA from Postgres; returns `ReportResult(error="SLA not found")` if absent
- Cosmos incident fetch guarded in try/except; falls back to `[]`
- `duration_ms` recorded end-to-end

### sla_endpoints.py additions
- `POST /api/v1/sla/report/{sla_id}` — trigger report; 404 if SLA not found
- `POST /api/v1/admin/sla-report-job` — describe cron schedule (no in-process scheduler); auth-gated

### Tests
16 tests: 13 passed, 3 skipped (PDF tests skip without reportlab locally; pass in Docker).
Combined with Wave 2: 40 passed, 3 skipped total.
