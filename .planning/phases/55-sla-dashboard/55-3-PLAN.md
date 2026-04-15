---
wave: 3
depends_on: [55-2]
files_modified:
  - services/api-gateway/sla_report.py              # new — PDF + GPT-4o + email
  - services/api-gateway/sla_endpoints.py            # add /report/{sla_id} + /admin/sla-report-job
  - services/api-gateway/requirements.txt            # add reportlab if missing
  - services/api-gateway/tests/test_sla_report.py    # new — 15+ tests
autonomous: true
---

## Goal

Build the monthly SLA report pipeline:
1. Fetch current-period compliance data for one SLA definition.
2. Generate a GPT-4o narrative paragraph via `azure-ai-projects` `AIProjectClient`.
3. Render a PDF (cover page + attainment table + incident log + narrative) using
   `reportlab`.
4. Email the PDF to `report_recipients` via Python stdlib `smtplib` + `email.mime`.
5. Expose a `POST /api/v1/sla/report/{sla_id}` endpoint (manual trigger) and a
   `POST /api/v1/admin/sla-report-job` endpoint (register/describe the monthly
   cron schedule).

---

## Tasks

<task id="55-3-1">
### Confirm `reportlab` in `requirements.txt`

<read_first>
- `services/api-gateway/requirements.txt` — scan for `reportlab`.
</read_first>

<action>
If `reportlab` is NOT already present in `requirements.txt`, append the line:
```
reportlab>=4.0.0
```
If it IS already present, make no change.

Do not add `APScheduler` — the `sla-report-job` endpoint is a documentation-only
endpoint that describes the schedule; actual cron triggering is handled externally
(Azure Container Apps job or Azure Logic App).
</action>

<acceptance_criteria>
`grep "reportlab" services/api-gateway/requirements.txt` outputs at least one line.
</acceptance_criteria>
</task>

<task id="55-3-2">
### Write `services/api-gateway/sla_report.py`

<read_first>
- `services/api-gateway/sla_endpoints.py` — `_calculate_compliance()`, Pydantic
  models `SLADefinitionResponse`, `SLAComplianceResult`.
- `services/api-gateway/runbook_rag.py` — `resolve_postgres_dsn()`.
- `services/api-gateway/main.py` lines 1–50 — `AIProjectClient` / Foundry pattern
  (note: `azure-ai-projects` used; grep for `AIProjectClient` or `ChatCompletionsClient`).
- `services/api-gateway/requirements.txt` — confirm `azure-ai-projects` version.
</read_first>

<action>
Create `services/api-gateway/sla_report.py` with the following sections:

#### Imports & SDK guards

```python
"""SLA monthly report generation — PDF + GPT-4o narrative + SMTP email (Phase 55).

Entry point: generate_and_send_sla_report(sla_id) -> ReportResult
"""
from __future__ import annotations

import io
import logging
import os
import smtplib
import time
import uuid
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError:
    SimpleDocTemplate = None  # type: ignore[assignment,misc]
    logger.warning("reportlab not installed — PDF generation disabled")

try:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential as _DefaultCred
except ImportError:
    AIProjectClient = None        # type: ignore[assignment,misc]
    _DefaultCred = None           # type: ignore[assignment,misc]
    logger.warning("azure-ai-projects not installed — narrative generation disabled")
```

#### Pydantic models

```python
from pydantic import BaseModel

class ReportResult(BaseModel):
    sla_id: str
    sla_name: str
    report_period: str          # e.g. "2026-04"
    attained_availability_pct: Optional[float]
    is_compliant: Optional[bool]
    pdf_bytes_size: int         # byte length of generated PDF
    emailed_to: list[str]       # recipients actually emailed
    narrative_generated: bool
    duration_ms: float
    error: Optional[str] = None
```

#### `_build_narrative(compliance_result, sla_def) -> str`

Call GPT-4o via `AIProjectClient`:
```python
def _build_narrative(compliance_result, sla_def: dict) -> str:
    """Generate a 2–3 sentence plain-English SLA attainment summary."""
    if AIProjectClient is None or _DefaultCred is None:
        return _fallback_narrative(compliance_result, sla_def)

    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
    if not endpoint:
        return _fallback_narrative(compliance_result, sla_def)

    try:
        client = AIProjectClient(endpoint=endpoint, credential=_DefaultCred())
        attained = compliance_result.get("attained_availability_pct")
        target   = sla_def.get("target_availability_pct")
        period   = compliance_result.get("period_start", "")[:7]
        status   = "met" if compliance_result.get("is_compliant") else "NOT met"
        prompt = (
            f"Write a 2-3 sentence professional SLA compliance summary for a customer report. "
            f"SLA name: '{sla_def['name']}'. Target: {target}% availability. "
            f"Attained: {attained:.3f}% in period {period}. "
            f"SLA was {status}. "
            f"Mention any significant downtime events if attainment is below target."
        )
        response = client.inference.get_chat_completions(
            model_name=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("GPT-4o narrative generation failed: %s", exc)
        return _fallback_narrative(compliance_result, sla_def)

def _fallback_narrative(compliance_result, sla_def: dict) -> str:
    attained = compliance_result.get("attained_availability_pct")
    target   = sla_def.get("target_availability_pct")
    period   = compliance_result.get("period_start", "")[:7]
    if attained is None:
        return f"Availability data was unavailable for period {period}. Manual review required."
    status = "met" if compliance_result.get("is_compliant") else "not met"
    return (
        f"For period {period}, the '{sla_def['name']}' SLA attained "
        f"{attained:.3f}% availability against a target of {target}%. "
        f"The SLA was {status}."
    )
```

#### `_build_pdf(sla_def, compliance_result, narrative, incidents) -> bytes`

Build a PDF in memory using `reportlab`:
```
Structure:
  Cover page:
    - Title: "SLA Compliance Report — {sla_name}"
    - Customer: {customer_name}
    - Period: {period_start} – {period_end}
    - Generated: {now UTC ISO}

  Section 1 — Attainment Summary (2-column table):
    | Metric              | Value          |
    | Target Availability | 99.900%        |
    | Attained            | 99.987%        |
    | Status              | COMPLIANT ✓    |
    | Period              | 2026-04        |

  Section 2 — Resource Breakdown (table):
    | Resource ID | Availability % | Downtime (min) | Data Source |

  Section 3 — Contributing Incidents (table):
    | Incident ID | Title | Severity | Start | Duration |
    (populated from `incidents` arg; empty table if none)

  Section 4 — Narrative
    Plain paragraph with the GPT-4o (or fallback) text.
```

Color rules (use reportlab Color directly; no CSS tokens in Python):
- COMPLIANT rows: `colors.HexColor("#d4edda")` (light green)
- NON-COMPLIANT rows: `colors.HexColor("#f8d7da")` (light red)
- Header rows: `colors.HexColor("#0078D4")` with white text

Return `bytes` (the PDF buffer).

If `SimpleDocTemplate is None` (reportlab not installed):
- Return a UTF-8 encoded plain-text fallback: `b"PDF generation unavailable: reportlab not installed."`

#### `_send_email(pdf_bytes, sla_name, period, recipients) -> list[str]`

```python
def _send_email(pdf_bytes: bytes, sla_name: str, period: str, recipients: list[str]) -> list[str]:
    """Send PDF report via SMTP. Returns list of recipients actually emailed."""
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)

    if not smtp_host or not recipients:
        logger.info("SMTP not configured or no recipients — skipping email delivery")
        return []

    msg = MIMEMultipart()
    msg["From"] = smtp_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"SLA Compliance Report — {sla_name} — {period}"

    body = MIMEText(
        f"Please find attached the SLA compliance report for '{sla_name}' "
        f"covering period {period}.\n\nThis report was generated automatically "
        f"by the Azure Agentic Platform.",
        "plain",
    )
    msg.attach(body)

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=f"sla-report-{sla_name.lower().replace(' ', '-')}-{period}.pdf",
    )
    msg.attach(attachment)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            if smtp_port != 465:
                server.starttls()
                server.ehlo()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, recipients, msg.as_string())
        logger.info("SLA report emailed to %s recipients", len(recipients))
        return recipients
    except Exception as exc:
        logger.error("SMTP delivery failed: %s", exc)
        return []
```

#### `generate_and_send_sla_report(sla_id: str) -> ReportResult` (public API)

```
1. start_time = time.monotonic()
2. Load sla_def from Postgres (resolve_postgres_dsn + asyncpg.connect).
   If not found: return ReportResult with error="SLA not found".
3. Call _calculate_compliance(sla_row) [imported from sla_endpoints].
4. Fetch contributing incidents from Cosmos DB if COSMOS_URL configured:
   SELECT incidents WHERE any(resource_id in sla_def.covered_resource_ids)
   AND occurred_at in period. Graceful fallback to [] if unavailable.
5. narrative = _build_narrative(compliance_result, sla_def)
6. pdf_bytes = _build_pdf(sla_def, compliance_result, narrative, incidents)
7. emailed_to = _send_email(pdf_bytes, sla_def["name"], period, sla_def["report_recipients"])
8. duration_ms = (time.monotonic() - start_time) * 1000
9. Return ReportResult(...).
```

This is an **async** function so it can call the asyncpg coroutines:
`async def generate_and_send_sla_report(sla_id: str) -> ReportResult:`
</action>

<acceptance_criteria>
1. `grep -n "def generate_and_send_sla_report" services/api-gateway/sla_report.py` shows the function.
2. `grep -n "_build_pdf\|_build_narrative\|_send_email" services/api-gateway/sla_report.py | wc -l` ≥ 6 (defined + called).
3. `grep -n "SimpleDocTemplate = None" services/api-gateway/sla_report.py` shows reportlab guard.
4. `grep -n "AIProjectClient = None" services/api-gateway/sla_report.py` shows SDK guard.
5. `grep -n "smtplib.SMTP" services/api-gateway/sla_report.py` shows SMTP send.
6. `grep -n "SMTP_HOST\|SMTP_PORT\|SMTP_USER\|SMTP_PASSWORD\|SMTP_FROM" services/api-gateway/sla_report.py | wc -l` = 5 (all 5 env vars read).
7. `python -m py_compile services/api-gateway/sla_report.py && echo PASS`
</acceptance_criteria>
</task>

<task id="55-3-3">
### Add report endpoints to `sla_endpoints.py`

<read_first>
- `services/api-gateway/sla_endpoints.py` — existing `sla_router` and
  `admin_sla_router` to extend.
</read_first>

<action>
Add the following two new endpoints to `sla_endpoints.py`.  Do NOT duplicate the
file — only append/edit.

**1. `POST /api/v1/sla/report/{sla_id}`** on `sla_router`

```python
from services.api_gateway.sla_report import generate_and_send_sla_report

@sla_router.post("/report/{sla_id}", tags=["sla"])
async def trigger_sla_report(sla_id: str):
    """Manually trigger SLA report generation and email delivery."""
    result = await generate_and_send_sla_report(sla_id)
    if result.error:
        raise HTTPException(status_code=404, detail=result.error)
    return result
```

**2. `POST /api/v1/admin/sla-report-job`** on `admin_sla_router`

```python
class SLAReportJobConfig(BaseModel):
    schedule: str = "0 6 1 * *"   # cron: 06:00 UTC on 1st of every month
    enabled: bool = True
    description: str = (
        "Monthly SLA report generation job. "
        "Trigger via POST /api/v1/sla/report/{sla_id} or schedule externally."
    )

@admin_sla_router.post("/sla-report-job", tags=["admin-sla"])
async def register_sla_report_job(config: SLAReportJobConfig, _=Depends(verify_token)):
    """Register/describe the monthly SLA report schedule.

    Does not start an in-process scheduler.  Returns the schedule config for
    use by an external trigger (Azure Container Apps Job, Logic App, etc.).
    """
    return {
        "schedule": config.schedule,
        "enabled": config.enabled,
        "description": config.description,
        "note": (
            "External trigger required. POST /api/v1/sla/report/{sla_id} "
            "on the 1st of each month to generate and email reports."
        ),
    }
```
</action>

<acceptance_criteria>
1. `grep -n "trigger_sla_report\|register_sla_report_job" services/api-gateway/sla_endpoints.py`
   shows both functions.
2. `grep -n "generate_and_send_sla_report" services/api-gateway/sla_endpoints.py`
   shows the import and call.
3. `python -m py_compile services/api-gateway/sla_endpoints.py && echo PASS`
</acceptance_criteria>
</task>

<task id="55-3-4">
### Write `tests/test_sla_report.py` (15+ tests)

<read_first>
- `services/api-gateway/tests/test_admin_endpoints.py` — mock pattern for asyncpg.
- `services/api-gateway/sla_report.py` — functions under test.
</read_first>

<action>
Create `services/api-gateway/tests/test_sla_report.py` with these test groups:

**Group A — `_build_narrative` (4 tests)**
| # | Name | Asserts |
|---|------|---------|
| 1 | `test_narrative_fallback_compliant` | Returns string containing "met" when `is_compliant=True` |
| 2 | `test_narrative_fallback_non_compliant` | Returns string containing "not met" |
| 3 | `test_narrative_fallback_no_data` | Returns string mentioning "unavailable" when `attained=None` |
| 4 | `test_narrative_gpt4o_failure_falls_back` | Patches `AIProjectClient` to raise; fallback string returned |

**Group B — `_build_pdf` (4 tests)**
| # | Name | Asserts |
|---|------|---------|
| 5 | `test_build_pdf_returns_bytes` | Returns `bytes`, len > 1000 |
| 6 | `test_build_pdf_contains_sla_name` | PDF bytes contain sla_name encoded |
| 7 | `test_build_pdf_no_reportlab` | Patches `SimpleDocTemplate=None`; returns fallback bytes |
| 8 | `test_build_pdf_empty_incidents` | No crash with `incidents=[]` |

**Group C — `_send_email` (4 tests)**
| # | Name | Asserts |
|---|------|---------|
| 9 | `test_send_email_no_smtp_host` | Returns `[]` (no SMTP_HOST) |
| 10 | `test_send_email_no_recipients` | Returns `[]` |
| 11 | `test_send_email_smtp_success` | Patches `smtplib.SMTP`; returns recipients list |
| 12 | `test_send_email_smtp_failure` | `smtplib.SMTP` raises; returns `[]`, no exception propagated |

**Group D — `generate_and_send_sla_report` (4 tests)**
| # | Name | Asserts |
|---|------|---------|
| 13 | `test_generate_report_sla_not_found` | Returns `ReportResult` with `error="SLA not found"` |
| 14 | `test_generate_report_full_pipeline` | Mocks DB + compliance + email; `ReportResult.pdf_bytes_size > 0` |
| 15 | `test_generate_report_email_disabled` | `emailed_to=[]` when SMTP_HOST unset |
| 16 | `test_generate_report_duration_ms_positive` | `duration_ms > 0` |

Minimum: **15 tests** passing.
</action>

<acceptance_criteria>
1. `grep -c "^def test_\|^async def test_" services/api-gateway/tests/test_sla_report.py` ≥ 15.
2. `python -m pytest services/api-gateway/tests/test_sla_report.py -v --tb=short 2>&1 | tail -5`
   shows 0 failures, 0 errors.
</acceptance_criteria>
</task>

---

## Verification

```bash
# 1. reportlab in requirements
grep "reportlab" services/api-gateway/requirements.txt

# 2. All public functions present
grep -n "def generate_and_send_sla_report\|def _build_pdf\|def _build_narrative\|def _send_email" \
  services/api-gateway/sla_report.py

# 3. Both new endpoints in sla_endpoints.py
grep -n "trigger_sla_report\|register_sla_report_job" services/api-gateway/sla_endpoints.py

# 4. All SMTP env vars read
grep -n "SMTP_HOST\|SMTP_PORT\|SMTP_USER\|SMTP_PASSWORD\|SMTP_FROM" services/api-gateway/sla_report.py

# 5. Syntax
python -m py_compile services/api-gateway/sla_report.py && echo "sla_report OK"
python -m py_compile services/api-gateway/sla_endpoints.py && echo "sla_endpoints OK"

# 6. Test count + run
grep -c "^def test_\|^async def test_" services/api-gateway/tests/test_sla_report.py
python -m pytest services/api-gateway/tests/test_sla_report.py -v --tb=short

# 7. No regression
python -m pytest services/api-gateway/tests/test_sla_endpoints.py -v --tb=short
```

---

## must_haves

- [ ] `reportlab` guard present — module loads cleanly even without the package
- [ ] `AIProjectClient` guard present — narrative falls back to template string if SDK missing or Foundry unreachable
- [ ] SMTP only sends when `SMTP_HOST` env var is set — never errors when unconfigured
- [ ] `generate_and_send_sla_report` is `async` (uses asyncpg coroutines)
- [ ] `_send_email` returns `[]` (not raises) on any SMTP failure
- [ ] `_build_pdf` returns `bytes` — not a file path, not a file object
- [ ] Cosmos incident fetch wrapped in try/except; falls back to `[]`
- [ ] `duration_ms` recorded end-to-end including PDF generation and email
- [ ] 15+ tests, all passing
