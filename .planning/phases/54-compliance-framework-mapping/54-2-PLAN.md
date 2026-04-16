# Plan 54-2: Compliance Posture + Export API Endpoints

---
wave: 2
depends_on: ["54-1"]
files_modified:
  - services/api-gateway/compliance_posture.py
  - services/api-gateway/compliance_endpoints.py
  - services/api-gateway/main.py
  - services/api-gateway/requirements.txt
  - services/api-gateway/tests/test_compliance_endpoints.py
autonomous: true
---

## Goal

Implement `GET /api/v1/compliance/posture` (compliance scores per framework per subscription with 30-day trend) and `GET /api/v1/compliance/export` (PDF/CSV audit report). Register the router in `main.py`. Add `reportlab` to requirements.

## Tasks

<task id="54-2-1" title="Create compliance_posture.py — posture computation logic">
<read_first>
- services/api-gateway/finops_endpoints.py (SDK lazy import pattern, credential dependency)
- .planning/phases/54-compliance-framework-mapping/54-RESEARCH.md (Section 5.1 algorithm, Section 3 data sources)
- services/api-gateway/migrations/004_create_compliance_mappings.py
</read_first>
<action>
Create `services/api-gateway/compliance_posture.py` with the posture computation logic separated from routing (follows the project pattern of separating business logic from endpoints).

**Lazy SDK imports** (follow `finops_endpoints.py` exactly):
```python
try:
    from azure.mgmt.security import SecurityCenter
    _SECURITY_IMPORT_ERROR: str = ""
except Exception as _e:
    SecurityCenter = None
    _SECURITY_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.policyinsights import PolicyInsightsClient
    from azure.mgmt.policyinsights.models import QueryOptions
    _POLICY_IMPORT_ERROR: str = ""
except Exception as _e:
    PolicyInsightsClient = None
    QueryOptions = None
    _POLICY_IMPORT_ERROR = str(_e)
```

**Key functions:**

1. `async def fetch_defender_assessments(credential, subscription_id: str) -> list[dict]`
   - Calls `SecurityCenter(credential, subscription_id).assessments.list()`
   - Returns list of `{"name": guid, "display_name": str, "status": "Healthy"|"Unhealthy"|"NotApplicable", "severity": str}`
   - Wraps SDK exceptions, returns empty list on failure with logger.warning

2. `async def fetch_policy_compliance(credential, subscription_id: str) -> list[dict]`
   - Calls `PolicyInsightsClient(credential).policy_states.list_query_results_for_subscription("latest", subscription_id, query_options=QueryOptions(top=1000, filter="complianceState eq 'NonCompliant'"))`
   - Returns list of `{"policy_definition_name": str, "compliance_state": str, "resource_id": str}`
   - Wraps SDK exceptions gracefully

3. `def compute_posture(mappings: list[dict], assessments: list[dict], policy_states: list[dict]) -> dict`
   - Pure function (no SDK calls). Takes mapping rows + live assessment/policy data.
   - Builds a dict keyed by `(framework, control_id)` with status: `passing` (all mapped findings healthy) / `failing` (any unhealthy) / `not_assessed` (no live data matched)
   - Computes per-framework scores: `score = passing / (passing + failing) * 100` (exclude not_assessed from denominator)
   - Returns the response shape:
     ```python
     {
       "subscription_id": str,
       "generated_at": iso_timestamp,
       "frameworks": {
         "asb": {"score": float, "total_controls": int, "passing": int, "failing": int, "not_assessed": int},
         "cis": {...},
         "nist": {...},
       },
       "controls": [
         {"framework": str, "control_id": str, "control_title": str, "status": str,
          "findings": [{"finding_type": str, "defender_rule_id": str, "display_name": str, "severity": str}]}
       ]
     }
     ```

4. `_posture_cache: dict[str, tuple[float, dict]] = {}` — in-memory cache keyed by subscription_id, TTL 3600s (1 hour). `get_cached_posture(sub_id)` returns cached result or None. `set_cached_posture(sub_id, result)` stores with timestamp.

5. `async def get_compliance_mappings(dsn: str) -> list[dict]` — queries PostgreSQL `compliance_mappings` table, returns all rows as list of dicts. Uses `asyncpg.connect(dsn)`. Caches result for 24h (mappings change rarely).

**Constants:**
```python
FRAMEWORK_COLUMNS = {
    "asb": ("asb_control_id", "asb_title"),
    "cis": ("cis_control_id", "cis_title"),
    "nist": ("nist_control_id", "nist_title"),
}
POSTURE_CACHE_TTL_SECONDS = 3600
MAPPINGS_CACHE_TTL_SECONDS = 86400
```
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/compliance_posture.py`
- `grep "def compute_posture" services/api-gateway/compliance_posture.py` succeeds
- `grep "def fetch_defender_assessments" services/api-gateway/compliance_posture.py` succeeds
- `grep "def fetch_policy_compliance" services/api-gateway/compliance_posture.py` succeeds
- `grep "def get_compliance_mappings" services/api-gateway/compliance_posture.py` succeeds
- `grep "_posture_cache" services/api-gateway/compliance_posture.py` succeeds
- `grep "SecurityCenter" services/api-gateway/compliance_posture.py` succeeds
- `grep "PolicyInsightsClient" services/api-gateway/compliance_posture.py` succeeds
- `grep "FRAMEWORK_COLUMNS" services/api-gateway/compliance_posture.py` succeeds
</acceptance_criteria>
</task>

<task id="54-2-2" title="Create compliance_endpoints.py — FastAPI router">
<read_first>
- services/api-gateway/finops_endpoints.py (router pattern, Query params, credential Depends)
- services/api-gateway/compliance_posture.py (created in 54-2-1)
- services/api-gateway/audit_export.py (StreamingResponse pattern for file downloads)
</read_first>
<action>
Create `services/api-gateway/compliance_endpoints.py` with an `APIRouter(prefix="/api/v1/compliance", tags=["compliance"])`.

**Endpoint 1: `GET /posture`**

Parameters:
- `subscription_id: str = Query(...)`
- `framework: Optional[str] = Query(None)` — filter: `"cis"` | `"nist"` | `"asb"` | None (all)

Logic:
1. Check posture cache for subscription_id, return if fresh (set `cache_hit: True` on response)
2. Resolve PostgreSQL DSN from `PGVECTOR_CONNECTION_STRING` or `POSTGRES_DSN` env vars (same pattern as `runbook_rag.py`)
3. Call `get_compliance_mappings(dsn)` to get mapping rows
4. If no mappings found, return 404 with `{"error": "No compliance mappings configured"}`
5. Call `fetch_defender_assessments(credential, subscription_id)` and `fetch_policy_compliance(credential, subscription_id)` in parallel via `asyncio.gather`
6. Call `compute_posture(mappings, assessments, policy_states)` — pure function
7. If `framework` param is set, filter controls list to that framework only
8. Cache result, return 200

Return type: `Dict[str, Any]` (matches the response shape from `compute_posture`)

**Endpoint 2: `GET /export`**

Parameters:
- `subscription_id: str = Query(...)`
- `format: str = Query(..., description="csv or pdf")`
- `framework: Optional[str] = Query(None)` — filter to one framework

Logic:
1. Get posture data (call posture endpoint logic or cache)
2. If `format == "csv"`: use `csv.writer` + `io.StringIO`, write header row `framework,control_id,control_title,status,finding_display_name,severity`, write one row per control×finding. Return `StreamingResponse` with `media_type="text/csv"` and `Content-Disposition: attachment; filename=compliance-report-{date}.csv`
3. If `format == "pdf"`: use `reportlab.platypus.SimpleDocTemplate` + `io.BytesIO`. Title page with subscription, date, scores. One section per framework with a `Table` of controls. Return `StreamingResponse` with `media_type="application/pdf"` and `Content-Disposition: attachment; filename=compliance-report-{date}.pdf`
4. If format is not `csv` or `pdf`: return 422 `{"error": "format must be 'csv' or 'pdf'"}`

**Imports:**
```python
import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from services.api_gateway.dependencies import get_credential
from services.api_gateway.compliance_posture import (
    compute_posture, fetch_defender_assessments, fetch_policy_compliance,
    get_compliance_mappings, get_cached_posture, set_cached_posture,
)
```

For PDF generation:
```python
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False
```
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/compliance_endpoints.py`
- `grep 'APIRouter(prefix="/api/v1/compliance"' services/api-gateway/compliance_endpoints.py` succeeds
- `grep "def get_compliance_posture" services/api-gateway/compliance_endpoints.py` OR `grep 'async def.*posture' services/api-gateway/compliance_endpoints.py` succeeds
- `grep "def export_compliance" services/api-gateway/compliance_endpoints.py` OR `grep 'async def.*export' services/api-gateway/compliance_endpoints.py` succeeds
- `grep "StreamingResponse" services/api-gateway/compliance_endpoints.py` succeeds
- `grep "text/csv" services/api-gateway/compliance_endpoints.py` succeeds
- `grep "application/pdf" services/api-gateway/compliance_endpoints.py` succeeds
- `grep "reportlab" services/api-gateway/compliance_endpoints.py` succeeds
- `grep 'router = APIRouter' services/api-gateway/compliance_endpoints.py` succeeds
</acceptance_criteria>
</task>

<task id="54-2-3" title="Add reportlab to requirements.txt">
<read_first>
- services/api-gateway/requirements.txt
</read_first>
<action>
Add the following line to `services/api-gateway/requirements.txt` after the existing dependencies:

```
# PDF report generation — compliance audit export (Phase 54)
reportlab>=4.0.0
```

Add between the `azure-mgmt-appcontainers` line and the `# Test dependencies` section.
</action>
<acceptance_criteria>
- `grep "reportlab" services/api-gateway/requirements.txt` succeeds
- `grep "reportlab>=4.0.0" services/api-gateway/requirements.txt` succeeds
</acceptance_criteria>
</task>

<task id="54-2-4" title="Register compliance router in main.py">
<read_first>
- services/api-gateway/main.py (import section lines 103-136, include_router section lines 569-586)
</read_first>
<action>
Add the compliance router import and registration to `services/api-gateway/main.py`.

**Import** (add after the `from services.api_gateway.war_room import` block):
```python
from services.api_gateway.compliance_endpoints import router as compliance_router
```

**Registration** (add after `app.include_router(admin_router)` on line 586):
```python
app.include_router(compliance_router)
```
</action>
<acceptance_criteria>
- `grep "compliance_router" services/api-gateway/main.py` succeeds
- `grep "compliance_endpoints" services/api-gateway/main.py` succeeds
- `grep "include_router(compliance_router)" services/api-gateway/main.py` succeeds
</acceptance_criteria>
</task>

<task id="54-2-5" title="Create comprehensive endpoint tests">
<read_first>
- services/api-gateway/tests/test_finops_endpoints.py (test pattern: standalone FastAPI + TestClient + mock SDK)
- services/api-gateway/compliance_endpoints.py
- services/api-gateway/compliance_posture.py
</read_first>
<action>
Create `services/api-gateway/tests/test_compliance_endpoints.py` with 25+ tests.

Test setup (follow `test_finops_endpoints.py` exactly):
```python
import os
os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.compliance_endpoints import router
_test_app = FastAPI()
_test_app.include_router(router)
_test_app.state.credential = MagicMock()
client = TestClient(_test_app, raise_server_exceptions=False)
```

**Test classes and methods:**

class TestCompliancePosture:
1. `test_posture_returns_200_with_valid_params` — mock assessments + policy states + mappings, assert 200 with `frameworks` key
2. `test_posture_returns_frameworks_asb_cis_nist` — assert all three framework keys present in response
3. `test_posture_score_computation_all_passing` — all assessments healthy → score = 100.0
4. `test_posture_score_computation_mixed` — 5 passing + 5 failing → score = 50.0
5. `test_posture_score_computation_all_failing` — all unhealthy → score = 0.0
6. `test_posture_returns_controls_list` — response contains `controls` array with `control_id`, `status`, `findings`
7. `test_posture_framework_filter_returns_only_asb` — pass `framework=asb`, verify only ASB controls in response
8. `test_posture_framework_filter_returns_only_cis` — same for CIS
9. `test_posture_framework_filter_returns_only_nist` — same for NIST
10. `test_posture_returns_404_when_no_mappings` — mock empty mappings, assert 404
11. `test_posture_cache_returns_hit_on_second_call` — call twice, second should have `cache_hit: true`
12. `test_posture_handles_security_sdk_missing` — mock SecurityCenter = None, still returns partial result
13. `test_posture_handles_policy_sdk_missing` — mock PolicyInsightsClient = None, partial result
14. `test_posture_handles_sdk_exception` — SDK raises exception, returns graceful error
15. `test_posture_missing_subscription_id_returns_422` — no subscription_id param

class TestComplianceExport:
16. `test_export_csv_returns_200_with_csv_content_type` — assert content-type contains text/csv
17. `test_export_csv_contains_correct_columns` — CSV header has: framework,control_id,control_title,status,finding_display_name,severity
18. `test_export_csv_has_data_rows` — at least 1 data row beyond header
19. `test_export_pdf_returns_200_with_pdf_content_type` — assert content-type application/pdf
20. `test_export_pdf_returns_valid_pdf_bytes` — response body starts with `%PDF`
21. `test_export_unknown_format_returns_422` — format=xml returns 422
22. `test_export_missing_subscription_id_returns_422` — no subscription_id
23. `test_export_missing_format_returns_422` — no format param
24. `test_export_framework_filter_csv` — filter=asb, CSV only contains ASB rows

class TestComputePosture:
25. `test_compute_posture_pure_function` — call compute_posture with mock data, verify output shape
26. `test_compute_posture_empty_assessments` — empty assessments → all controls not_assessed
27. `test_compute_posture_no_mappings` — empty mappings → empty frameworks
28. `test_compute_posture_partial_framework_coverage` — some rows have only ASB, verify CIS/NIST show not_assessed for those

All tests mock the PostgreSQL connection (patch `get_compliance_mappings`) and SDK clients (patch `fetch_defender_assessments`, `fetch_policy_compliance`).
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/tests/test_compliance_endpoints.py`
- `grep -c "def test_" services/api-gateway/tests/test_compliance_endpoints.py` returns >= 25
- `grep "TestCompliancePosture" services/api-gateway/tests/test_compliance_endpoints.py` succeeds
- `grep "TestComplianceExport" services/api-gateway/tests/test_compliance_endpoints.py` succeeds
- `grep "TestComputePosture" services/api-gateway/tests/test_compliance_endpoints.py` succeeds
- `grep "test_posture_returns_200" services/api-gateway/tests/test_compliance_endpoints.py` succeeds
- `grep "test_export_csv_returns_200" services/api-gateway/tests/test_compliance_endpoints.py` succeeds
- `grep "test_export_pdf_returns_200" services/api-gateway/tests/test_compliance_endpoints.py` succeeds
- `cd services/api-gateway && python -m pytest tests/test_compliance_endpoints.py -v` passes all tests
</acceptance_criteria>
</task>

## Verification

```bash
# 1. Router registered
grep "compliance_router" services/api-gateway/main.py

# 2. reportlab in requirements
grep "reportlab" services/api-gateway/requirements.txt

# 3. All endpoint tests pass
cd services/api-gateway && python -m pytest tests/test_compliance_endpoints.py -v

# 4. No regressions
cd services/api-gateway && python -m pytest tests/ -v --timeout=60
```

## must_haves

- [ ] `GET /api/v1/compliance/posture` returns scores for ASB, CIS, NIST frameworks
- [ ] `GET /api/v1/compliance/export?format=csv` returns valid CSV with control columns
- [ ] `GET /api/v1/compliance/export?format=pdf` returns valid PDF (starts with %PDF)
- [ ] Posture computation is a pure function (no SDK calls in `compute_posture`)
- [ ] In-memory cache with 1h TTL for posture results
- [ ] `reportlab` added to requirements.txt
- [ ] compliance_router registered in main.py
- [ ] 25+ tests passing with no regressions
