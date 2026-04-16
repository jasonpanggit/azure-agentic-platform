# Plan 54-1: Compliance Mappings DB Migration + Seed Data

---
wave: 1
depends_on: []
files_modified:
  - services/api-gateway/migrations/004_create_compliance_mappings.py
  - scripts/seed-compliance-mappings.py
  - services/api-gateway/tests/test_compliance_migration.py
autonomous: true
---

## Goal

Create the PostgreSQL `compliance_mappings` table and seed it with 150+ rows mapping Defender assessments, Azure Policy definitions, and Advisor recommendations to CIS v8, NIST 800-53 Rev 5, and ASB v3 controls.

## Tasks

<task id="54-1-1" title="Create compliance_mappings migration">
<read_first>
- services/api-gateway/migrations/003_create_sops_table.py
- services/api-gateway/migrations/005_create_remediation_policies_table.py
</read_first>
<action>
Create `services/api-gateway/migrations/004_create_compliance_mappings.py` following the exact pattern from `003_create_sops_table.py`.

UP_SQL must contain:

```sql
CREATE TABLE IF NOT EXISTS compliance_mappings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_type        TEXT NOT NULL,
    defender_rule_id    TEXT,
    display_name        TEXT NOT NULL,
    description         TEXT,
    cis_control_id      TEXT,
    cis_title           TEXT,
    nist_control_id     TEXT,
    nist_title          TEXT,
    asb_control_id      TEXT,
    asb_title           TEXT,
    severity            TEXT NOT NULL DEFAULT 'Medium',
    remediation_sop_id  UUID,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_mappings_defender_rule_id ON compliance_mappings (defender_rule_id);
CREATE INDEX IF NOT EXISTS idx_compliance_mappings_asb ON compliance_mappings (asb_control_id);
CREATE INDEX IF NOT EXISTS idx_compliance_mappings_nist ON compliance_mappings (nist_control_id);
CREATE INDEX IF NOT EXISTS idx_compliance_mappings_cis ON compliance_mappings (cis_control_id);
CREATE INDEX IF NOT EXISTS idx_compliance_mappings_finding_type ON compliance_mappings (finding_type);
```

DOWN_SQL: `DROP TABLE IF EXISTS compliance_mappings;`

Include `async def up(conn)`, `async def down(conn)`, and `if __name__ == "__main__"` block using `asyncpg.connect(os.environ["DATABASE_URL"])`.

Note: Do NOT add a REFERENCES constraint to `sops(id)` — the sops table may not exist in all environments and the FK is not required for this phase. `remediation_sop_id` is a nullable UUID column only.
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/migrations/004_create_compliance_mappings.py`
- `grep -c "compliance_mappings" services/api-gateway/migrations/004_create_compliance_mappings.py` returns >= 6
- `grep "CREATE TABLE IF NOT EXISTS compliance_mappings" services/api-gateway/migrations/004_create_compliance_mappings.py` succeeds
- `grep "finding_type" services/api-gateway/migrations/004_create_compliance_mappings.py` succeeds
- `grep "defender_rule_id" services/api-gateway/migrations/004_create_compliance_mappings.py` succeeds
- `grep "cis_control_id" services/api-gateway/migrations/004_create_compliance_mappings.py` succeeds
- `grep "nist_control_id" services/api-gateway/migrations/004_create_compliance_mappings.py` succeeds
- `grep "asb_control_id" services/api-gateway/migrations/004_create_compliance_mappings.py` succeeds
- `grep "async def up" services/api-gateway/migrations/004_create_compliance_mappings.py` succeeds
- `grep "async def down" services/api-gateway/migrations/004_create_compliance_mappings.py` succeeds
</acceptance_criteria>
</task>

<task id="54-1-2" title="Create seed script with 150+ compliance mappings">
<read_first>
- services/api-gateway/migrations/004_create_compliance_mappings.py
- .planning/phases/54-compliance-framework-mapping/54-RESEARCH.md (Section 4.2 Seed Data Structure)
</read_first>
<action>
Create `scripts/seed-compliance-mappings.py` — a standalone script that inserts 150+ rows into `compliance_mappings`.

Structure the seed data as a Python list of dicts called `COMPLIANCE_MAPPINGS`. Each dict has keys: `finding_type`, `defender_rule_id`, `display_name`, `description`, `cis_control_id`, `cis_title`, `nist_control_id`, `nist_title`, `asb_control_id`, `asb_title`, `severity`.

The 150+ mappings must cover three finding categories:

**~90 Defender assessment mappings** (finding_type='defender_assessment'):
Use well-known Defender recommendation display names as the anchor. Group by ASB domain:
- Network Security (NS-1 through NS-10): ~10 mappings (NSG rules, DDoS, WAF, TLS, private endpoints, flow logs, etc.)
- Asset Management (AM-1 through AM-5): ~5 mappings
- Identity Management (IM-1 through IM-9): ~9 mappings (MFA, conditional access, managed identity, PIM)
- Privileged Access (PA-1 through PA-8): ~8 mappings (JIT, least privilege, emergency access)
- Data Protection (DP-1 through DP-8): ~8 mappings (encryption at rest/transit, Key Vault, TDE)
- Logging & Threat Detection (LT-1 through LT-7): ~7 mappings (diagnostic settings, Defender plans, SIEM)
- Incident Response (IR-1 through IR-7): ~5 mappings (notification contacts, automation)
- Posture & Vulnerability (PV/VA-1 through VA-6): ~6 mappings (vulnerability assessment, baseline config)
- Endpoint Security (ES-1 through ES-3): ~3 mappings (EDR, antimalware)
- Backup & Recovery (BR-1 through BR-4): ~4 mappings (backup enabled, geo-redundant)
- DevOps Security (DS-1 through DS-6): ~5 mappings
- Governance & Strategy (GS-1 through GS-11): ~8 mappings

For `defender_rule_id`, use descriptive placeholder GUIDs (e.g., `"dabc-mfa-owner-0001"`) since the real Defender assessment GUIDs vary by environment. The posture endpoint will match by `display_name` as fallback.

**~40 Azure Policy mappings** (finding_type='policy'):
Built-in policy definitions for regulatory compliance. Examples:
- "Allowed locations" → CIS 1.x, NIST CM-2
- "Storage accounts should use private link" → ASB NS-2, CIS 12.x
- "Kubernetes clusters should use internal load balancers" → ASB NS-1
- "SQL databases should have vulnerability assessment configured" → ASB VA-2
Use `defender_rule_id` = policy definition display name for matching.

**~20 Advisor security recommendations** (finding_type='advisor'):
- "Enable Azure DDoS Protection Standard" → ASB NS-5
- "Use managed disks for VMs" → ASB AM-2
- etc.

Each row MUST have at least one non-null framework column (cis_control_id OR nist_control_id OR asb_control_id). Most rows should have all three populated.

Severity distribution: ~40 High, ~80 Medium, ~30 Low.

SQL pattern for insert:
```python
INSERT_SQL = """
INSERT INTO compliance_mappings
    (finding_type, defender_rule_id, display_name, description,
     cis_control_id, cis_title, nist_control_id, nist_title,
     asb_control_id, asb_title, severity)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT DO NOTHING
"""
```

Use `ON CONFLICT DO NOTHING` with a unique constraint on `(finding_type, defender_rule_id)` — add this constraint to the migration DDL in task 54-1-1 as well:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_compliance_mappings_unique_finding
    ON compliance_mappings (finding_type, COALESCE(defender_rule_id, display_name));
```

Script entrypoint: `asyncio.run(main())` that connects via `DATABASE_URL` env var, runs the migration UP first (idempotent), then inserts all rows, prints count.
</action>
<acceptance_criteria>
- File exists at `scripts/seed-compliance-mappings.py`
- `grep -c "finding_type" scripts/seed-compliance-mappings.py` returns >= 10
- `grep "COMPLIANCE_MAPPINGS" scripts/seed-compliance-mappings.py` succeeds
- `grep "defender_assessment" scripts/seed-compliance-mappings.py` succeeds
- `grep "policy" scripts/seed-compliance-mappings.py` succeeds
- `grep "advisor" scripts/seed-compliance-mappings.py` succeeds
- `grep "ON CONFLICT" scripts/seed-compliance-mappings.py` succeeds
- `python3 -c "exec(open('scripts/seed-compliance-mappings.py').read().split('if __name__')[0]); print(len(COMPLIANCE_MAPPINGS))"` outputs a number >= 150
- `grep "asb_control_id" scripts/seed-compliance-mappings.py` succeeds
- `grep "nist_control_id" scripts/seed-compliance-mappings.py` succeeds
- `grep "cis_control_id" scripts/seed-compliance-mappings.py` succeeds
</acceptance_criteria>
</task>

<task id="54-1-3" title="Migration and seed unit tests">
<read_first>
- services/api-gateway/migrations/004_create_compliance_mappings.py
- scripts/seed-compliance-mappings.py
- services/api-gateway/tests/test_finops_endpoints.py (test pattern)
</read_first>
<action>
Create `services/api-gateway/tests/test_compliance_migration.py` with the following tests:

```python
"""Tests for compliance_mappings migration and seed data integrity."""
from __future__ import annotations
import pytest

class TestComplianceMigrationDDL:
    def test_up_sql_creates_table(self):
        """UP_SQL contains CREATE TABLE compliance_mappings."""
        from services.api_gateway.migrations._004_create_compliance_mappings import UP_SQL
        assert "CREATE TABLE IF NOT EXISTS compliance_mappings" in UP_SQL

    def test_up_sql_has_all_framework_columns(self):
        from services.api_gateway.migrations._004_create_compliance_mappings import UP_SQL
        for col in ["cis_control_id", "nist_control_id", "asb_control_id",
                     "cis_title", "nist_title", "asb_title"]:
            assert col in UP_SQL, f"Missing column: {col}"

    def test_up_sql_has_indexes(self):
        from services.api_gateway.migrations._004_create_compliance_mappings import UP_SQL
        assert "idx_compliance_mappings_defender_rule_id" in UP_SQL
        assert "idx_compliance_mappings_asb" in UP_SQL
        assert "idx_compliance_mappings_nist" in UP_SQL
        assert "idx_compliance_mappings_cis" in UP_SQL

    def test_down_sql_drops_table(self):
        from services.api_gateway.migrations._004_create_compliance_mappings import DOWN_SQL
        assert "DROP TABLE IF EXISTS compliance_mappings" in DOWN_SQL

    def test_up_function_exists(self):
        from services.api_gateway.migrations._004_create_compliance_mappings import up
        assert callable(up)

    def test_down_function_exists(self):
        from services.api_gateway.migrations._004_create_compliance_mappings import down
        assert callable(down)


class TestComplianceSeedData:
    def test_seed_has_150_plus_mappings(self):
        """Seed data contains at least 150 rows."""
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location("seed", "scripts/seed-compliance-mappings.py")
        mod = importlib.util.module_from_spec(spec)
        # Only load the data, don't execute main
        source = open("scripts/seed-compliance-mappings.py").read()
        # Extract COMPLIANCE_MAPPINGS by exec-ing everything before if __name__
        code = source.split("if __name__")[0]
        ns = {}
        exec(code, ns)
        assert len(ns["COMPLIANCE_MAPPINGS"]) >= 150

    def test_every_row_has_at_least_one_framework(self):
        source = open("scripts/seed-compliance-mappings.py").read()
        code = source.split("if __name__")[0]
        ns = {}
        exec(code, ns)
        for i, row in enumerate(ns["COMPLIANCE_MAPPINGS"]):
            has_framework = (
                row.get("cis_control_id") or
                row.get("nist_control_id") or
                row.get("asb_control_id")
            )
            assert has_framework, f"Row {i} ({row.get('display_name')}) has no framework mapping"

    def test_finding_types_are_valid(self):
        source = open("scripts/seed-compliance-mappings.py").read()
        code = source.split("if __name__")[0]
        ns = {}
        exec(code, ns)
        valid_types = {"defender_assessment", "policy", "advisor"}
        for row in ns["COMPLIANCE_MAPPINGS"]:
            assert row["finding_type"] in valid_types

    def test_severity_values_are_valid(self):
        source = open("scripts/seed-compliance-mappings.py").read()
        code = source.split("if __name__")[0]
        ns = {}
        exec(code, ns)
        valid = {"High", "Medium", "Low"}
        for row in ns["COMPLIANCE_MAPPINGS"]:
            assert row["severity"] in valid

    def test_all_three_finding_types_present(self):
        source = open("scripts/seed-compliance-mappings.py").read()
        code = source.split("if __name__")[0]
        ns = {}
        exec(code, ns)
        types = {r["finding_type"] for r in ns["COMPLIANCE_MAPPINGS"]}
        assert "defender_assessment" in types
        assert "policy" in types
        assert "advisor" in types
```

The migration file import path will need adjustment based on the actual filename (whether it uses `_004` prefix or `004`). Adjust to match the exact filename created in task 54-1-1. If the filename is `004_create_compliance_mappings.py` (with leading digit), use `importlib` for import.
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/tests/test_compliance_migration.py`
- `grep "test_up_sql_creates_table" services/api-gateway/tests/test_compliance_migration.py` succeeds
- `grep "test_seed_has_150_plus_mappings" services/api-gateway/tests/test_compliance_migration.py` succeeds
- `grep "test_every_row_has_at_least_one_framework" services/api-gateway/tests/test_compliance_migration.py` succeeds
- `grep "test_finding_types_are_valid" services/api-gateway/tests/test_compliance_migration.py` succeeds
- `cd services/api-gateway && python -m pytest tests/test_compliance_migration.py -v` passes all tests
</acceptance_criteria>
</task>

## Verification

```bash
# 1. Migration file exists with correct DDL
grep "CREATE TABLE IF NOT EXISTS compliance_mappings" services/api-gateway/migrations/004_create_compliance_mappings.py

# 2. Seed script has 150+ rows
python3 -c "
source = open('scripts/seed-compliance-mappings.py').read()
code = source.split('if __name__')[0]
ns = {}
exec(code, ns)
n = len(ns['COMPLIANCE_MAPPINGS'])
print(f'Seed rows: {n}')
assert n >= 150, f'Only {n} rows, need 150+'
print('PASS')
"

# 3. All tests pass
cd services/api-gateway && python -m pytest tests/test_compliance_migration.py -v
```

## must_haves

- [ ] `compliance_mappings` table DDL has all 6 framework columns (cis_control_id, cis_title, nist_control_id, nist_title, asb_control_id, asb_title)
- [ ] Seed data contains >= 150 rows
- [ ] Every seed row has at least one non-null framework control ID
- [ ] All three finding_types present: defender_assessment, policy, advisor
- [ ] 4 indexes created on defender_rule_id, asb_control_id, nist_control_id, cis_control_id
- [ ] All migration + seed tests pass
