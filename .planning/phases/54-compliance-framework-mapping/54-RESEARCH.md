# Phase 54: Compliance Framework Mapping — Research

> Research date: 2026-04-15
> Depends on: Phase 52 (FinOps Intelligence Agent — `ca-finops-prod` Container App, Cost Management endpoints)

---

## 1. What This Phase Must Build

Four deliverables, each with a clear acceptance test:

| Deliverable | Acceptance Test |
|---|---|
| PostgreSQL `compliance_mappings` table seeded with 150+ rows | `SELECT COUNT(*) FROM compliance_mappings` ≥ 150 covering CIS v8, NIST 800-53 Rev 5, ASB v3 |
| `GET /api/v1/compliance/posture` | Returns scores for ≥50 controls per framework per subscription |
| `GET /api/v1/compliance/export?format=csv` and `?format=pdf` | Valid CSV + PDF with every finding attributed to ≥1 control ID |
| Compliance tab in UI | Heat-map of controls (passing/failing/not-assessed); click-through to findings |

**Dependency note:** Phase 52 is listed as the dependency but the actual data sources for this phase are the **Security agent's existing tools** (Defender alerts, Policy compliance, secure score, RBAC, Key Vault audit) plus the Azure Policy `PolicyInsightsClient` SDK that already lives in `agents/security/tools.py`. Phase 52 simply ensures the FinOps agent is deployed so this phase doesn't need to spin up a new Container App — compliance runs on the existing API gateway.

---

## 2. Framework Structures (What to Map)

### 2.1 CIS Controls v8

- **18 top-level controls**, **153 safeguards**, 3 Implementation Groups (IG1/2/3)
- Identifiers: `1.1`, `1.2`, ... `18.5`
- Security-relevant controls for Azure cloud (IG1 + IG2 subset, ~80 controls):
  - CIS 1: Asset Inventory → maps to ARG resource inventory
  - CIS 2: Software Inventory → maps to VM extension health
  - CIS 3: Data Protection → maps to encryption/Key Vault findings
  - CIS 4: Secure Configuration → maps to Defender misconfig recommendations
  - CIS 5/6: Access Control → maps to RBAC + MFA Defender alerts
  - CIS 7: Vulnerability Management → maps to Defender TVM / patch data
  - CIS 8: Audit Log Management → maps to diagnostic settings findings
  - CIS 10: Malware Defenses → maps to Defender antimalware recommendations
  - CIS 12/13: Network Monitoring → maps to NSG/flow log findings
- **Seed strategy:** Focus on IG1+IG2 controls that have a direct Azure Defender/Policy analog (~60 CIS mappings)

### 2.2 NIST SP 800-53 Rev 5

- **20 control families**, ~1,000+ controls + enhancements
- Key families for Azure cloud:
  - `AC` (Access Control): RBAC, PIM, JIT — maps to Defender RBAC alerts
  - `AU` (Audit and Accountability): diagnostic settings, LAW — maps to logging findings
  - `CM` (Configuration Management): secure baseline — maps to Defender recommendations
  - `IA` (Identification and Authentication): MFA, managed identity — maps to Defender identity alerts
  - `SC` (System & Comms Protection): encryption in transit, NSG — maps to network findings
  - `SI` (System & Information Integrity): antimalware, patch — maps to TVM/patch agent data
  - `RA` (Risk Assessment): vulnerability assessment — maps to Defender findings
- **Seed strategy:** Use moderate-baseline controls (400+ controls) but seed the ~60 most commonly assessed ones for Azure workloads

### 2.3 Azure Security Benchmark (ASB) v3 / MCSB v1

- **12 domains**, ~84 controls total — the most direct Azure mapping
- Control IDs: `NS-1` through `NS-10`, `AM-1` through `AM-5`, `IM-1`…`IM-9`, `PA-1`…`PA-8`, `DP-1`…`DP-8`, `LT-1`…`LT-7`, `IR-1`…`IR-7`, `VA-1`…`VA-6`, `ES-1`…`ES-3`, `BR-1`…`BR-4`, `DS-1`…`DS-6`, `GS-1`…`GS-11`
- Microsoft publishes the mapping from each ASB control to Defender for Cloud recommendations — this is the primary anchor for seeding mappings
- **Seed strategy:** All 84 ASB controls with Defender recommendation IDs (official MS mapping available at `https://aka.ms/benchmarkv3`)

---

## 3. Data Sources Available in the Platform

### 3.1 Microsoft Defender for Cloud — Assessments API

The Security agent already calls `SecurityCenter` from `azure-mgmt-security`. The assessments endpoint is:

```
GET /subscriptions/{subId}/providers/Microsoft.Security/assessments?api-version=2021-06-01
```

Each assessment has:
- `name` = recommendation GUID (e.g., `550e8400-e29b-41d4-a716-446655440000`)
- `properties.displayName` = human-readable name
- `properties.status.code` = `Healthy | Unhealthy | NotApplicable`
- `properties.metadata.severity` = `High | Medium | Low`

**What this means for mapping:** The `compliance_mappings.defender_rule_id` column stores the assessment GUID. The posture query joins live assessment results against the mapping table.

**Practical guidance:** Defender assessment GUIDs are stable — they don't change between subscriptions. We can hard-code the well-known ones in the seed data. Microsoft's GitHub has the complete list: `https://github.com/MicrosoftDocs/SecurityBenchmarks`.

### 3.2 Azure Policy Compliance — PolicyInsightsClient

`agents/security/tools.py` already imports `PolicyInsightsClient`. The API surface:

```python
client.policy_states.list_query_results_for_subscription(
    policy_states_resource="latest",
    subscription_id=sub_id,
    query_options=QueryOptions(top=1000, filter="complianceState eq 'NonCompliant'")
)
```

Returns `policy_definition_name` (the built-in policy GUID). Built-in policy definitions map directly to ASB controls — Microsoft publishes this mapping.

**What this means for mapping:** `compliance_mappings.finding_type = 'policy'` rows use `defender_rule_id = NULL` and instead use the policy definition name as the key. The posture endpoint queries policy states by `policy_definition_name` to get pass/fail status.

### 3.3 Secure Score — Already Implemented

`agents/security/tools.py` calls `SecurityCenter.secure_score.get("ascScore")`. The existing `get_secure_score` tool returns `current_score`, `max_score`, `percentage`. This feeds into the overall compliance posture score.

### 3.4 Defender Recommendations via Security Agent

The Security agent tools already in production:
- `query_defender_alerts` — active alerts
- `get_secure_score` — overall score
- `query_policy_compliance` — policy states
- `query_rbac_assignments` — RBAC findings
- `query_keyvault_diagnostics` — Key Vault audit events
- `scan_public_endpoints` — public exposure

These are the **finding sources**. The compliance mapping table tells us: "when this finding is present, which control IDs does it impact?"

---

## 4. PostgreSQL Schema Design

### 4.1 Migration: `004_create_compliance_mappings.py`

```sql
CREATE TABLE IF NOT EXISTS compliance_mappings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_type        TEXT NOT NULL,          -- 'defender_assessment' | 'policy' | 'advisor'
    defender_rule_id    TEXT,                   -- Defender assessment GUID OR policy def name
    display_name        TEXT NOT NULL,
    description         TEXT,
    cis_control_id      TEXT,                   -- e.g. '4.1', '7.3'
    cis_title           TEXT,
    nist_control_id     TEXT,                   -- e.g. 'CM-6', 'SI-2'
    nist_title          TEXT,
    asb_control_id      TEXT,                   -- e.g. 'VA-3', 'ES-1'
    asb_title           TEXT,
    severity            TEXT NOT NULL DEFAULT 'Medium',  -- 'High' | 'Medium' | 'Low'
    remediation_sop_id  UUID REFERENCES sops(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_mappings_defender_rule_id ON compliance_mappings (defender_rule_id);
CREATE INDEX IF NOT EXISTS idx_compliance_mappings_asb ON compliance_mappings (asb_control_id);
CREATE INDEX IF NOT EXISTS idx_compliance_mappings_nist ON compliance_mappings (nist_control_id);
CREATE INDEX IF NOT EXISTS idx_compliance_mappings_cis ON compliance_mappings (cis_control_id);
```

**Key design decisions:**
- `finding_type` distinguishes source (Defender assessment vs. Policy vs. Advisor recommendation)
- `defender_rule_id` is the pivot — either a Defender assessment GUID or a Policy definition name
- All three framework columns are nullable — not every finding maps to all three frameworks
- `remediation_sop_id` links to the existing `sops` table from Phase 30/31 (nullable FK)
- One row per unique finding × framework mapping (a single finding may appear in multiple rows if it maps to multiple controls in different frameworks — OR use a single row with all three columns populated where cross-framework alignment exists)

**Alternative schema (single row per finding):** Since most Defender recommendations map to one ASB control, one CIS safeguard, and one NIST control, a single row per `defender_rule_id` with all three columns is cleaner than a junction table. Use this approach. 150 mappings = ~150 distinct Defender findings.

### 4.2 Seed Data Structure (150+ rows)

Split across three finding categories:
- **~90 Defender assessment mappings** — well-known Defender for Cloud recommendations with known GUIDs, each mapped to ASB + NIST + CIS
- **~40 Azure Policy built-in compliance mappings** — built-in policies for regulatory compliance initiatives
- **~20 Advisor security recommendations** — Advisor high/medium security recommendations

**CIS-heavy subset (security-relevant Azure controls):**
- CIS 1.x (5 safeguards) → Asset management findings
- CIS 3.x (6 safeguards) → Encryption findings
- CIS 4.x (3 safeguards) → Secure config findings
- CIS 5.x/6.x (4 safeguards) → Access control/MFA findings
- CIS 7.x (4 safeguards) → Vulnerability/patch findings
- CIS 8.x (3 safeguards) → Audit logging findings
- CIS 12.x/13.x (4 safeguards) → Network findings

---

## 5. API Endpoint Design

### 5.1 `GET /api/v1/compliance/posture`

**Query params:**
- `subscription_id` (required)
- `framework` (optional): `cis` | `nist` | `asb` | all (default: all)
- `days` (optional): trend window, default 30

**Algorithm:**
1. Query Defender assessments for the subscription (live SDK call, cached 1h in PostgreSQL `compliance_posture_cache` or just in-memory)
2. Query Policy compliance states (live SDK call)
3. JOIN results against `compliance_mappings` table
4. Compute per-control status: `passing` (all findings healthy) / `failing` (any finding unhealthy) / `not_assessed` (no data)
5. Aggregate to framework-level score: `score = passing_controls / (passing + failing) * 100`
6. Return structured response per framework

**Response shape:**
```json
{
  "subscription_id": "...",
  "generated_at": "2026-04-15T...",
  "frameworks": {
    "asb": {
      "score": 73.2,
      "total_controls": 84,
      "passing": 61,
      "failing": 14,
      "not_assessed": 9,
      "trend_30d": [{ "date": "2026-03-16", "score": 70.1 }, ...]
    },
    "cis": { ... },
    "nist": { ... }
  },
  "controls": [
    {
      "framework": "asb",
      "control_id": "VA-3",
      "control_title": "Remediate software vulnerabilities rapidly",
      "status": "failing",
      "findings": [
        {
          "finding_type": "defender_assessment",
          "defender_rule_id": "550e...",
          "display_name": "System updates should be applied",
          "severity": "High",
          "resource_count": 3
        }
      ]
    }
  ]
}
```

**Performance considerations:**
- Defender assessments API can return 100+ items — paginate and batch
- Policy states can return 1000+ items — filter to `NonCompliant` only for the posture view
- Cache result for 1 hour in a simple in-memory dict keyed by `subscription_id` (same pattern as topology sync loop)
- Add `cache_hit: bool` field to response for transparency

### 5.2 `GET /api/v1/compliance/export`

**Query params:**
- `subscription_id` (required)
- `format` (required): `csv` | `pdf`
- `framework` (optional): filter to one framework

**CSV response:**
```
framework,control_id,control_title,status,finding_display_name,severity,resource_count,remediation_sop
ASB,VA-3,Remediate software vulnerabilities rapidly,failing,System updates should be applied,High,3,patch-vm-update.md
```

Use Python's built-in `csv` module + `io.StringIO` + `StreamingResponse`. No extra dependencies.

**PDF response:**
Use `reportlab` (already a common Python dependency, available on PyPI). Pattern:
```python
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, Paragraph
```

Or use `weasyprint` (HTML → PDF, better for styled reports). **Decision: use `reportlab`** — lighter weight, no system libpango dependency, already in the Python ecosystem for similar reporting tools. `weasyprint` requires OS-level libraries that complicate Docker builds.

**ReportLab approach:**
- Title page: subscription, date, overall scores
- One section per framework: score gauge bar, controls table
- Controls table columns: Control ID | Title | Status | Failing Findings | Severity

**FastAPI streaming pattern:**
```python
from fastapi.responses import StreamingResponse
import io

buffer = io.BytesIO()
# ... generate PDF into buffer ...
buffer.seek(0)
return StreamingResponse(
    buffer,
    media_type="application/pdf",
    headers={"Content-Disposition": f"attachment; filename=compliance-report-{date}.pdf"}
)
```

---

## 6. Existing Patterns to Follow

### 6.1 Router Pattern — `finops_endpoints.py`

Phase 54 creates `compliance_endpoints.py` as a new `APIRouter`:
```python
router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])
```

Registered in `main.py`:
```python
from services.api_gateway.compliance_endpoints import router as compliance_router
app.include_router(compliance_router)
```

### 6.2 SDK Import Pattern (lazy imports)

Follow `finops_endpoints.py` / `agents/security/tools.py` exactly:
```python
try:
    from azure.mgmt.security import SecurityCenter
    _SECURITY_IMPORT_ERROR: str = ""
except Exception as _e:
    SecurityCenter = None
    _SECURITY_IMPORT_ERROR = str(_e)
```

### 6.3 Migration Pattern — `003_create_sops_table.py`

```python
UP_SQL = """CREATE TABLE IF NOT EXISTS compliance_mappings (...);"""
DOWN_SQL = """DROP TABLE IF EXISTS compliance_mappings;"""

async def up(conn) -> None:
    await conn.execute(UP_SQL)
```

File: `services/api-gateway/migrations/004_create_compliance_mappings.py`

### 6.4 Seed Script Pattern — `002_seed_runbooks.py`

The seed script for compliance mappings is simpler (no embeddings needed) — just `INSERT ... ON CONFLICT DO NOTHING` rows into the table. Follow the same standalone script pattern.

File: `scripts/seed-compliance-mappings.py`

### 6.5 Proxy Route Pattern — `finops/cost-breakdown/route.ts`

Each compliance endpoint needs a proxy route:
```
app/api/proxy/compliance/posture/route.ts
app/api/proxy/compliance/export/route.ts
```

Follow the exact `buildUpstreamHeaders`, `AbortSignal.timeout(15000)`, graceful-error-fallback pattern.

### 6.6 Dashboard Tab Registration — `DashboardPanel.tsx`

Add `compliance` tab to the `TABS` array and `TabId` union type. New tab comes after `patch` (position 12 of 14). Use `ShieldCheck` or `CheckCircle` lucide icon (note: `ShieldCheck` is already used by Patch tab — use `CheckSquare` or `FileCheck` instead).

---

## 7. UI Component Design

### 7.1 `ComplianceTab.tsx`

**Layout:**
1. **Header row:** Framework selector (ASB / CIS / NIST / All), Subscription selector, Refresh button, Last updated
2. **Score cards (3 cards):** ASB score, CIS score, NIST score — each with circular/gauge metric, passing/failing/not-assessed counts
3. **Heat-map grid:** Controls grid where each cell = one control, colored by status
4. **Findings drawer:** Click a control cell → slide-out panel with findings list for that control

**Heat-map implementation:**
The heat-map is the centerpiece UI. There is no shadcn heat-map component, so build it with CSS Grid:

```tsx
<div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
  {controls.map(ctrl => (
    <div
      key={ctrl.control_id}
      onClick={() => setSelectedControl(ctrl)}
      title={ctrl.control_title}
      style={{
        background: ctrl.status === 'passing'
          ? 'color-mix(in srgb, var(--accent-green) 60%, transparent)'
          : ctrl.status === 'failing'
          ? 'color-mix(in srgb, var(--accent-red) 60%, transparent)'
          : 'color-mix(in srgb, var(--border) 60%, transparent)',
        cursor: 'pointer',
      }}
      className="h-8 rounded text-[9px] flex items-center justify-center font-mono"
    >
      {ctrl.control_id}
    </div>
  ))}
</div>
```

**Color scheme (consistent with project patterns):**
- `passing` → `var(--accent-green)` at 60% opacity
- `failing` → `var(--accent-red)` at 60% opacity
- `not_assessed` → `var(--border)` at 60% opacity (greyed out)
- Hover → full opacity + border highlight

**Findings click-through:** Use a `Sheet` (shadcn slide-over) or an inline expanded section below the heat-map to show findings for a selected control. Sheet is cleaner — follows VMDetailPanel pattern.

**Export button:**
```tsx
<Button onClick={() => downloadExport('pdf')} variant="outline" size="sm">
  <Download className="h-3.5 w-3.5 mr-1" />
  Export PDF
</Button>
<Button onClick={() => downloadExport('csv')} variant="ghost" size="sm">
  Export CSV
</Button>
```

Client-side: `window.open('/api/proxy/compliance/export?subscription_id=...&format=pdf', '_blank')` — browser handles the file download.

---

## 8. Test Strategy

### 8.1 Backend Tests

Follow `test_finops_endpoints.py` pattern — standalone `FastAPI` + `TestClient` + mock SDK clients.

**Test file:** `services/api-gateway/tests/test_compliance_endpoints.py`

Required tests (minimum 25):
1. `test_posture_returns_200_with_valid_params`
2. `test_posture_returns_404_when_no_mappings`
3. `test_posture_security_center_sdk_missing_returns_error`
4. `test_posture_policy_client_sdk_missing_returns_graceful_fallback`
5. `test_posture_asb_score_computation_correct`
6. `test_posture_cis_score_computation_correct`
7. `test_posture_nist_score_computation_correct`
8. `test_posture_framework_filter_returns_only_asb`
9. `test_posture_cache_returns_hit_on_second_call` (test `cache_hit` flag)
10. `test_export_csv_returns_200_with_csv_content_type`
11. `test_export_csv_contains_correct_columns`
12. `test_export_pdf_returns_200_with_pdf_content_type`
13. `test_export_pdf_returns_valid_pdf_bytes`
14. `test_export_unknown_format_returns_422`
15. `test_export_missing_subscription_id_returns_422`
16-25: Edge cases — empty assessments, all passing, all failing, subscription not found, SDK exception wrapping

**Migration test:** `services/api-gateway/tests/test_sops_migration.py` pattern → `test_compliance_migration.py` verifying UP_SQL DDL is valid.

**Seed script test:** Verify at least 150 rows exist after seeding, and that each row has at least one non-null framework control ID.

---

## 9. Dependencies & Package Requirements

### Python (api-gateway)

No new packages needed for the endpoints themselves — all SDK imports are already in requirements:
- `azure-mgmt-security` — already in security agent requirements
- `azure-mgmt-policyinsights` — already in security agent requirements
- `asyncpg` — already in api-gateway requirements

**New package for PDF export:**
- `reportlab` — not currently in requirements. Lightweight (pure Python), no OS dependencies, ~3MB. Add to `services/api-gateway/requirements.txt`.
- Alternative: skip PDF for the first plan and return only JSON/CSV (PDF as Plan 2). **Decision: build PDF from the start with reportlab** — it's the compliance audit requirement.

### TypeScript (web-ui)

No new packages needed:
- `recharts` — already installed (used in ObservabilityTab)
- `lucide-react` — already installed
- shadcn `Sheet` component — check if already in `components/ui/`

Check existing shadcn components:
```bash
ls services/web-ui/components/ui/
```

If `Sheet` not installed: `npx shadcn add sheet` (it likely is — used in detail panels).

---

## 10. Plan Decomposition (Recommended)

### Plan 54-1: Database + Seed Data (2-3 hours)

**What:**
- `services/api-gateway/migrations/004_create_compliance_mappings.py` — DDL + UP/DOWN
- `scripts/seed-compliance-mappings.py` — 150+ rows covering all three frameworks
- `services/api-gateway/tests/test_compliance_migration.py` — migration DDL test

**Seed data breakdown:**
- 84 ASB v3 controls (all of them, each mapped to a Defender finding or Policy definition)
- 60 CIS v8 safeguards (IG1+IG2, security-focused subset)
- 40 NIST 800-53 Rev 5 controls (moderate baseline, most commonly audited)
- Total rows: ~160 (some overlap in rows mapping the same finding to multiple frameworks)

**Key seed rows to include (representative sample):**
```python
COMPLIANCE_MAPPINGS = [
  # ASB + CIS + NIST triple-mapping for top Defender findings
  {
    "finding_type": "defender_assessment",
    "defender_rule_id": "550e8400-e29b-41d4-a716-446655440001",  # MFA for privileged accounts
    "display_name": "MFA should be enabled on accounts with owner permissions on your subscription",
    "cis_control_id": "6.3", "cis_title": "Require MFA for Admin Access",
    "nist_control_id": "IA-5", "nist_title": "Authenticator Management",
    "asb_control_id": "PA-1", "asb_title": "Separate and limit highly privileged/administrative users",
    "severity": "High",
  },
  {
    "finding_type": "defender_assessment",
    "defender_rule_id": "550e8400-e29b-41d4-a716-446655440002",  # System updates
    "display_name": "System updates should be applied on your machines",
    "cis_control_id": "7.3", "cis_title": "Perform Automated OS Patch Management",
    "nist_control_id": "SI-2", "nist_title": "Flaw Remediation",
    "asb_control_id": "VA-3", "asb_title": "Remediate software vulnerabilities rapidly",
    "severity": "High",
  },
  # ... 148+ more rows
]
```

> **Important planning note:** The actual Defender assessment GUIDs are well-known and documented at `https://github.com/MicrosoftDocs/SecurityBenchmarks/blob/master/Azure%20Security%20Benchmark/3.0/asb-v3-recommendations.json`. During implementation, pull the real GUIDs from this file rather than using placeholders. The implementation phase should fetch this JSON as part of seed script creation.

### Plan 54-2: Backend Endpoints (3-4 hours)

**What:**
- `services/api-gateway/compliance_endpoints.py` — `posture` + `export` endpoints
- `services/api-gateway/compliance_posture.py` — posture computation logic (separate from routing per project pattern)
- `reportlab` added to `services/api-gateway/requirements.txt`
- Main.py router registration
- `services/api-gateway/tests/test_compliance_endpoints.py` — 25+ tests

### Plan 54-3: Frontend + Proxy Routes (3-4 hours)

**What:**
- `services/web-ui/app/api/proxy/compliance/posture/route.ts`
- `services/web-ui/app/api/proxy/compliance/export/route.ts`
- `services/web-ui/components/ComplianceTab.tsx` — heat-map + score cards + findings sheet + export buttons
- `services/web-ui/components/DashboardPanel.tsx` — add `compliance` tab entry
- TypeScript types for compliance response models

---

## 11. Key Architectural Decisions

| Decision | Recommendation | Rationale |
|---|---|---|
| Single row per finding vs. junction table | Single row per finding with all three framework columns nullable | 150 mappings fit easily in one table; simpler JOIN; most findings map to one control per framework |
| Caching posture results | In-memory dict + TTL (1h), key=subscription_id | Same pattern as topology sync loop; avoids hitting Defender API on every UI refresh |
| PDF library | `reportlab` | Pure Python, no OS deps, lightweight; avoids WeasyPrint's libpango requirement in Docker |
| CSV vs. PDF split | Both in same endpoint with `?format=` query param | Follows existing audit export pattern in `audit_export.py` |
| Trend data storage | Do NOT add a separate trend table in Phase 54 | Compliance posture score snapshots can be derived from existing data; add trend table in Phase 59 (Security Posture Scoring) when it becomes the main dashboard |
| Heat-map library | CSS Grid (no library) | No new npm dependency; full control over styling; consistent with project's CSS token system |
| Defender finding key | Assessment GUID in `defender_rule_id` | GUIDs are stable across subscriptions; display name can change; GUID is the canonical identifier |

---

## 12. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Defender assessment GUIDs differ from what we seed | Medium | High | Query live assessments first; use `display_name` as fallback match key |
| PolicyInsightsClient returns 0 results for compliant-only subscription | Low | Medium | Handle empty policy results gracefully; don't fail posture if no NonCompliant findings |
| `reportlab` adds to Docker image size | Low | Low | reportlab is ~3MB; acceptable. Add to requirements.txt pinned version |
| ASB v3 control count differs from the 84 we documented | Low | Low | Use the MCSB v1 GitHub as authoritative source during implementation |
| 150-row seed takes too long to run manually | Low | Low | Pure SQL INSERT — should complete in <5 seconds; no embeddings needed |
| Heat-map 84 cells is too dense for smaller screens | Medium | Low | Show abbreviated IDs (e.g., "NS-1") + tooltip; responsive grid with `min(10, gridCols)` |

---

## 13. Files to Create / Modify

### New Files

```
services/api-gateway/migrations/004_create_compliance_mappings.py
services/api-gateway/compliance_posture.py       # posture computation logic
services/api-gateway/compliance_endpoints.py     # FastAPI router
services/api-gateway/tests/test_compliance_endpoints.py
services/api-gateway/tests/test_compliance_migration.py
scripts/seed-compliance-mappings.py
services/web-ui/components/ComplianceTab.tsx
services/web-ui/app/api/proxy/compliance/posture/route.ts
services/web-ui/app/api/proxy/compliance/export/route.ts
```

### Modified Files

```
services/api-gateway/main.py               # include compliance_router
services/api-gateway/requirements.txt      # add reportlab
services/web-ui/components/DashboardPanel.tsx   # add compliance tab
```

---

## 14. What Phase 59 Builds on Top of This

Phase 59 (Security Posture Scoring Dashboard) will:
- Add a `security_posture` Cosmos container for caching scores with 1h TTL (instead of in-memory)
- Add `GET /api/v1/security/posture` (different from compliance posture — this is a composite Secure Score)
- Add a 30-day trend via Cosmos stored snapshots
- Add "Remediate via agent" action buttons

Phase 54 deliberately avoids the Cosmos caching to keep scope tight. The in-memory cache is sufficient for Phase 54 compliance posture.

---

## 15. Summary: What the Planner Needs to Know

1. **No new Container App needed** — compliance endpoints live on the existing `ca-api-gateway-prod`. No Terraform changes required.

2. **Seed data is the hardest part** — 150+ rows requires research into exact Defender assessment GUIDs. During Plan 54-1 implementation, fetch the canonical list from `https://github.com/MicrosoftDocs/SecurityBenchmarks` before writing the seed script.

3. **PDF export uses `reportlab`** — one new Python package. Pin to `reportlab==4.2.2` (latest stable as of 2026).

4. **Heat-map is CSS Grid, not a library** — no new npm dependencies for the UI.

5. **Existing security agent data is the foundation** — `query_defender_alerts`, `query_policy_compliance`, and `get_secure_score` already implement the data access layer. The compliance endpoints are essentially a reporting layer on top.

6. **The posture computation is a JOIN** — live Defender assessment results JOIN against the `compliance_mappings` table. Control status = `passing` if all mapped findings are `Healthy`, `failing` if any are `Unhealthy`.

7. **Success metric is testable** — posture endpoint returns scores for CIS v8, NIST 800-53, ASB for at least 50 controls; export generates valid audit report with every finding attributed to ≥1 control ID.

Sources:
- [CIS Controls v8 - cisecurity.org](https://www.cisecurity.org/controls/v8)
- [NIST SP 800-53 Rev 5 - csrc.nist.gov](https://csrc.nist.gov/publications/detail/sp/800-53/rev-5/final)
- [Azure Security Benchmark v3 - aka.ms/benchmarkv3](https://aka.ms/benchmarkv3)
- [Microsoft Security Benchmarks GitHub](https://github.com/MicrosoftDocs/SecurityBenchmarks)
- [azure-mgmt-policyinsights - PyPI](https://pypi.org/project/azure-mgmt-policyinsights/)
- [NIST OSCAL Content - GitHub](https://github.com/usnistgov/oscal-content)
