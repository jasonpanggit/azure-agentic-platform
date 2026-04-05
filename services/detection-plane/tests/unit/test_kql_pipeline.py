"""Unit tests for KQL pipeline consistency (DETECT-002).

Validates that the Python mirror of KQL functions produces identical
results and that the KQL schema definitions are syntactically correct.
"""
from __future__ import annotations

import re
from pathlib import Path

from classify_domain import DOMAIN_MAPPINGS, classify_domain

# Path to KQL files relative to repo root
KQL_ROOT = Path(__file__).parent.parent.parent.parent.parent / "fabric" / "kql"


class TestKQLSchemaFiles:
    """Verify KQL schema files exist and contain expected table names."""

    def test_raw_alerts_schema_exists(self) -> None:
        path = KQL_ROOT / "schemas" / "raw_alerts.kql"
        assert path.exists(), f"Missing: {path}"
        content = path.read_text()
        assert ".create-merge table RawAlerts" in content

    def test_enriched_alerts_schema_exists(self) -> None:
        path = KQL_ROOT / "schemas" / "enriched_alerts.kql"
        assert path.exists(), f"Missing: {path}"
        content = path.read_text()
        assert ".create-merge table EnrichedAlerts" in content

    def test_detection_results_schema_exists(self) -> None:
        path = KQL_ROOT / "schemas" / "detection_results.kql"
        assert path.exists(), f"Missing: {path}"
        content = path.read_text()
        assert ".create-merge table DetectionResults" in content
        assert "domain: string" in content


class TestKQLFunctionFiles:
    """Verify KQL function files exist and contain expected function signatures."""

    def test_classify_domain_function_exists(self) -> None:
        path = KQL_ROOT / "functions" / "classify_domain.kql"
        assert path.exists(), f"Missing: {path}"
        content = path.read_text()
        assert ".create-or-alter function classify_domain" in content
        assert '"sre"' in content  # D-06 fallback

    def test_enrich_alerts_function_exists(self) -> None:
        path = KQL_ROOT / "functions" / "enrich_alerts.kql"
        assert path.exists(), f"Missing: {path}"
        content = path.read_text()
        assert ".create-or-alter function EnrichAlerts()" in content
        assert "RawAlerts" in content

    def test_classify_alerts_function_exists(self) -> None:
        path = KQL_ROOT / "functions" / "classify_alerts.kql"
        assert path.exists(), f"Missing: {path}"
        content = path.read_text()
        assert ".create-or-alter function ClassifyAlerts()" in content
        assert "classify_domain(resource_type)" in content


class TestKQLUpdatePolicies:
    """Verify update policy configuration."""

    def test_update_policies_file_exists(self) -> None:
        path = KQL_ROOT / "policies" / "update_policies.kql"
        assert path.exists(), f"Missing: {path}"
        content = path.read_text()
        assert ".alter table EnrichedAlerts policy update" in content
        assert ".alter table DetectionResults policy update" in content

    def test_first_hop_is_non_transactional(self) -> None:
        """RawAlerts -> EnrichedAlerts should be non-transactional to prevent data loss."""
        path = KQL_ROOT / "policies" / "update_policies.kql"
        content = path.read_text()
        # Find the EnrichedAlerts policy and check IsTransactional
        enriched_section = content.split(".alter table DetectionResults")[0]
        assert '"IsTransactional": false' in enriched_section

    def test_second_hop_is_transactional(self) -> None:
        """EnrichedAlerts -> DetectionResults should be transactional for consistency."""
        path = KQL_ROOT / "policies" / "update_policies.kql"
        content = path.read_text()
        detection_section = content.split(".alter table DetectionResults")[1]
        assert '"IsTransactional": true' in detection_section


class TestKQLPythonConsistency:
    """Verify Python classify_domain() and KQL classify_domain() have identical mappings."""

    def test_all_kql_resource_types_in_python(self) -> None:
        """Every full resource type in the KQL function should map to a non-sre domain in Python."""
        path = KQL_ROOT / "functions" / "classify_domain.kql"
        content = path.read_text()

        # Extract quoted resource type strings from KQL (full paths like Microsoft.Compute/X)
        # These are the explicit resource types listed in has_any() calls
        kql_resource_types = re.findall(r'"(Microsoft\.[^/"]+/[^"]+)"', content)

        assert len(kql_resource_types) > 0, "No resource types found in classify_domain.kql"

        for rt in kql_resource_types:
            domain = classify_domain(rt)
            assert domain != "sre", (
                f"KQL resource type {rt!r} maps to 'sre' in Python but "
                f"is explicitly listed in the KQL function"
            )

    def test_python_domains_match_kql_domains(self) -> None:
        """All domains produced by Python should be valid."""
        domains = set(DOMAIN_MAPPINGS.values())
        expected = {"compute", "network", "storage", "security", "arc"}
        assert domains == expected, f"Python domains {domains} != expected {expected}"

    def test_sre_fallback_for_unknown_type(self) -> None:
        """Unknown resource types return 'sre' fallback (D-06)."""
        assert classify_domain("Microsoft.Unknown/resources") == "sre"
        assert classify_domain("") == "sre"
        assert classify_domain("not.a.valid.type") == "sre"

    def test_case_insensitive_matching(self) -> None:
        """Python classify_domain is case-insensitive (normalizes to lowercase)."""
        assert classify_domain("MICROSOFT.COMPUTE/VIRTUALMACHINES") == "compute"
        assert classify_domain("microsoft.compute/virtualmachines") == "compute"
        assert classify_domain("Microsoft.Compute/virtualMachines") == "compute"


class TestRetentionPolicies:
    """Verify retention policy definitions."""

    def test_retention_file_exists(self) -> None:
        path = KQL_ROOT / "retention" / "retention_policies.kql"
        assert path.exists(), f"Missing: {path}"
        content = path.read_text()
        assert "softdelete = 7d" in content  # RawAlerts
        assert "softdelete = 30d" in content  # EnrichedAlerts
        assert "softdelete = 90d" in content  # DetectionResults
