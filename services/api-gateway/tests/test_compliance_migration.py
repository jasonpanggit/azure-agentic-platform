from __future__ import annotations
"""Tests for compliance_mappings migration DDL and seed data integrity (Phase 54)."""

import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.parent  # workspace root
_MIGRATION_PATH = _REPO_ROOT / "services" / "api-gateway" / "migrations" / "004_create_compliance_mappings.py"
_SEED_PATH = _REPO_ROOT / "scripts" / "seed-compliance-mappings.py"


def _load_migration():
    """Load the migration module via importlib (filename starts with digit)."""
    spec = importlib.util.spec_from_file_location(
        "_004_create_compliance_mappings", str(_MIGRATION_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_seed_mappings() -> list[dict]:
    """Exec the seed script up to 'if __name__' to extract COMPLIANCE_MAPPINGS."""
    source = _SEED_PATH.read_text()
    code = source.split("if __name__")[0]
    ns: dict = {}
    exec(code, ns)  # noqa: S102
    return ns["COMPLIANCE_MAPPINGS"]


# ---------------------------------------------------------------------------
# Migration DDL tests
# ---------------------------------------------------------------------------


class TestComplianceMigrationDDL:
    def test_up_sql_creates_table(self):
        """UP_SQL contains CREATE TABLE compliance_mappings."""
        mod = _load_migration()
        assert "CREATE TABLE IF NOT EXISTS compliance_mappings" in mod.UP_SQL

    def test_up_sql_has_all_framework_columns(self):
        """All 6 cross-framework columns are present in DDL."""
        mod = _load_migration()
        for col in [
            "cis_control_id",
            "nist_control_id",
            "asb_control_id",
            "cis_title",
            "nist_title",
            "asb_title",
        ]:
            assert col in mod.UP_SQL, f"Missing column: {col}"

    def test_up_sql_has_required_columns(self):
        """Core columns (finding_type, defender_rule_id, display_name) present."""
        mod = _load_migration()
        for col in ["finding_type", "defender_rule_id", "display_name", "severity", "remediation_sop_id"]:
            assert col in mod.UP_SQL, f"Missing column: {col}"

    def test_up_sql_has_indexes(self):
        """All 4 required indexes present."""
        mod = _load_migration()
        assert "idx_compliance_mappings_defender_rule_id" in mod.UP_SQL
        assert "idx_compliance_mappings_asb" in mod.UP_SQL
        assert "idx_compliance_mappings_nist" in mod.UP_SQL
        assert "idx_compliance_mappings_cis" in mod.UP_SQL

    def test_up_sql_has_unique_index(self):
        """Unique constraint index for idempotent seeding is present."""
        mod = _load_migration()
        assert "idx_compliance_mappings_unique_finding" in mod.UP_SQL

    def test_down_sql_drops_table(self):
        """DOWN_SQL drops the compliance_mappings table."""
        mod = _load_migration()
        assert "DROP TABLE IF EXISTS compliance_mappings" in mod.DOWN_SQL

    def test_up_function_exists(self):
        """Module exports a callable `up` coroutine."""
        mod = _load_migration()
        assert callable(mod.up)

    def test_down_function_exists(self):
        """Module exports a callable `down` coroutine."""
        mod = _load_migration()
        assert callable(mod.down)

    def test_migration_has_docstring(self):
        """Migration module has a descriptive docstring."""
        mod = _load_migration()
        assert mod.__doc__ is not None
        assert "compliance_mappings" in mod.__doc__.lower()

    def test_up_sql_has_timestamptz_columns(self):
        """created_at and updated_at columns use TIMESTAMPTZ."""
        mod = _load_migration()
        assert "created_at" in mod.UP_SQL
        assert "updated_at" in mod.UP_SQL
        assert "TIMESTAMPTZ" in mod.UP_SQL


# ---------------------------------------------------------------------------
# Seed data tests
# ---------------------------------------------------------------------------


class TestComplianceSeedData:
    def test_seed_has_150_plus_mappings(self):
        """Seed data contains at least 150 rows."""
        mappings = _load_seed_mappings()
        assert len(mappings) >= 150, f"Only {len(mappings)} rows, need 150+"

    def test_every_row_has_at_least_one_framework(self):
        """Every seed row has at least one non-null framework control ID."""
        mappings = _load_seed_mappings()
        for i, row in enumerate(mappings):
            has_framework = (
                row.get("cis_control_id")
                or row.get("nist_control_id")
                or row.get("asb_control_id")
            )
            assert has_framework, (
                f"Row {i} ({row.get('display_name')!r}) has no framework mapping"
            )

    def test_finding_types_are_valid(self):
        """All finding_type values are from the allowed set."""
        mappings = _load_seed_mappings()
        valid_types = {"defender_assessment", "policy", "advisor"}
        invalid = [
            (i, r["finding_type"])
            for i, r in enumerate(mappings)
            if r["finding_type"] not in valid_types
        ]
        assert not invalid, f"Invalid finding_types at rows: {invalid}"

    def test_severity_values_are_valid(self):
        """All severity values are High, Medium, or Low."""
        mappings = _load_seed_mappings()
        valid = {"High", "Medium", "Low"}
        invalid = [
            (i, r["severity"])
            for i, r in enumerate(mappings)
            if r.get("severity") not in valid
        ]
        assert not invalid, f"Invalid severities at rows: {invalid}"

    def test_all_three_finding_types_present(self):
        """Seed data covers all 3 finding types."""
        mappings = _load_seed_mappings()
        types = {r["finding_type"] for r in mappings}
        assert "defender_assessment" in types, "No defender_assessment rows"
        assert "policy" in types, "No policy rows"
        assert "advisor" in types, "No advisor rows"

    def test_defender_assessment_count(self):
        """At least 80 Defender assessment rows present."""
        mappings = _load_seed_mappings()
        count = sum(1 for r in mappings if r["finding_type"] == "defender_assessment")
        assert count >= 80, f"Only {count} defender_assessment rows, expected 80+"

    def test_policy_count(self):
        """At least 30 policy rows present."""
        mappings = _load_seed_mappings()
        count = sum(1 for r in mappings if r["finding_type"] == "policy")
        assert count >= 30, f"Only {count} policy rows, expected 30+"

    def test_advisor_count(self):
        """At least 15 advisor rows present."""
        mappings = _load_seed_mappings()
        count = sum(1 for r in mappings if r["finding_type"] == "advisor")
        assert count >= 15, f"Only {count} advisor rows, expected 15+"

    def test_display_names_are_unique(self):
        """All display_name + finding_type combinations are unique (no duplicates)."""
        mappings = _load_seed_mappings()
        seen: set[tuple[str, str]] = set()
        duplicates: list[tuple[int, str]] = []
        for i, row in enumerate(mappings):
            key = (row["finding_type"], row["display_name"])
            if key in seen:
                duplicates.append((i, row["display_name"]))
            seen.add(key)
        assert not duplicates, f"Duplicate display_names: {duplicates}"

    def test_all_rows_have_display_name(self):
        """Every row has a non-empty display_name."""
        mappings = _load_seed_mappings()
        missing = [i for i, r in enumerate(mappings) if not r.get("display_name")]
        assert not missing, f"Rows missing display_name: {missing}"

    def test_asb_mappings_present(self):
        """At least 100 rows have an ASB control ID."""
        mappings = _load_seed_mappings()
        count = sum(1 for r in mappings if r.get("asb_control_id"))
        assert count >= 100, f"Only {count} rows with asb_control_id"

    def test_nist_mappings_present(self):
        """At least 100 rows have a NIST control ID."""
        mappings = _load_seed_mappings()
        count = sum(1 for r in mappings if r.get("nist_control_id"))
        assert count >= 100, f"Only {count} rows with nist_control_id"

    def test_cis_mappings_present(self):
        """At least 100 rows have a CIS control ID."""
        mappings = _load_seed_mappings()
        count = sum(1 for r in mappings if r.get("cis_control_id"))
        assert count >= 100, f"Only {count} rows with cis_control_id"

    def test_high_severity_count(self):
        """At least 30 High severity rows."""
        mappings = _load_seed_mappings()
        count = sum(1 for r in mappings if r.get("severity") == "High")
        assert count >= 30, f"Only {count} High severity rows"

    def test_seed_on_conflict_do_nothing(self):
        """Seed script uses ON CONFLICT DO NOTHING for idempotent inserts."""
        source = _SEED_PATH.read_text()
        assert "ON CONFLICT DO NOTHING" in source

    def test_seed_uses_asyncpg(self):
        """Seed script imports asyncpg for database operations."""
        source = _SEED_PATH.read_text()
        assert "asyncpg" in source

    def test_insert_sql_has_all_columns(self):
        """INSERT_SQL in seed script covers all framework columns."""
        source = _SEED_PATH.read_text()
        code = source.split("if __name__")[0]
        ns: dict = {}
        exec(code, ns)  # noqa: S102
        insert_sql = ns.get("INSERT_SQL", "")
        for col in ["cis_control_id", "nist_control_id", "asb_control_id"]:
            assert col in insert_sql, f"INSERT_SQL missing column: {col}"
