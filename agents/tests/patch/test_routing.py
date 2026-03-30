"""Unit tests for patch domain routing (Phase 11, D-12)."""
from __future__ import annotations

import pytest

from agents.shared.routing import QUERY_DOMAIN_KEYWORDS, classify_query_text


class TestQueryDomainKeywordsStructure:
    """Validate QUERY_DOMAIN_KEYWORDS tuple structure after patch addition."""

    def test_has_seven_entries(self):
        """QUERY_DOMAIN_KEYWORDS must have exactly 7 entries (arc, patch, eol, compute, network, storage, security)."""
        assert len(QUERY_DOMAIN_KEYWORDS) == 7

    def test_domain_ordering(self):
        """Domains must be in order: arc, patch, eol, compute, network, storage, security."""
        domain_names = [entry[0] for entry in QUERY_DOMAIN_KEYWORDS]
        assert domain_names == ["arc", "patch", "eol", "compute", "network", "storage", "security"]

    def test_patch_entry_has_twelve_keywords(self):
        """The patch entry must have exactly 12 keywords."""
        patch_entry = next(
            (entry for entry in QUERY_DOMAIN_KEYWORDS if entry[0] == "patch"), None
        )
        assert patch_entry is not None, "No 'patch' entry found in QUERY_DOMAIN_KEYWORDS"
        assert len(patch_entry[1]) == 12

    def test_patch_first_keyword_is_patch(self):
        """The first keyword in the patch entry must be 'patch'."""
        patch_entry = next(
            entry for entry in QUERY_DOMAIN_KEYWORDS if entry[0] == "patch"
        )
        assert patch_entry[1][0] == "patch"

    def test_patch_contains_all_d12_keywords(self):
        """All 12 D-12 keywords must be present in the patch entry."""
        expected_keywords = {
            "patch",
            "patches",
            "patching",
            "update manager",
            "windows update",
            "security patch",
            "patch compliance",
            "patch status",
            "missing patches",
            "pending patches",
            "kb article",
            "hotfix",
        }
        patch_entry = next(
            entry for entry in QUERY_DOMAIN_KEYWORDS if entry[0] == "patch"
        )
        actual_keywords = set(patch_entry[1])
        assert actual_keywords == expected_keywords

    def test_no_standalone_update_keyword(self):
        """Generic 'update' must NOT appear as a standalone keyword (D-12 exclusion)."""
        patch_entry = next(
            entry for entry in QUERY_DOMAIN_KEYWORDS if entry[0] == "patch"
        )
        for keyword in patch_entry[1]:
            # "update" as standalone, not as part of "update manager" or "windows update"
            assert keyword != "update", (
                "Standalone 'update' found in patch keywords — violates D-12 exclusion"
            )
            assert keyword != "updates", (
                "Standalone 'updates' found in patch keywords — violates D-12 exclusion"
            )


class TestClassifyPatchKeywords:
    """Verify classify_query_text routes patch keywords correctly."""

    @pytest.mark.parametrize(
        "query,expected_domain",
        [
            ("show patch compliance", "patch"),
            ("list missing patches on my servers", "patch"),
            ("check windows update status", "patch"),
            ("review update manager results", "patch"),
            ("find hotfix KB5034441", "patch"),
            ("what is the patch status of vm-prod-01", "patch"),
            ("show pending patches", "patch"),
            ("check security patch compliance", "patch"),
            ("review kb article results", "patch"),
        ],
    )
    def test_classify_patch_keywords(self, query: str, expected_domain: str):
        """Patch-related queries must classify to patch domain."""
        result = classify_query_text(query)
        assert result["domain"] == expected_domain

    @pytest.mark.parametrize(
        "query",
        [
            "update my vm size",
            "update storage account settings",
            "show recent updates to the network",
        ],
    )
    def test_generic_update_not_patch(self, query: str):
        """Generic 'update' queries must NOT classify as patch (D-12 exclusion)."""
        result = classify_query_text(query)
        assert result["domain"] != "patch"


class TestOtherDomainsUnaffected:
    """Verify patch keywords do not collide with other domains."""

    @pytest.mark.parametrize(
        "query,expected_domain",
        [
            ("show my virtual machines", "compute"),
            ("list arc servers", "arc"),
            ("check storage blob access", "storage"),
            ("review nsg rules", "network"),
            ("check defender alerts", "security"),
        ],
    )
    def test_other_domains_unaffected(self, query: str, expected_domain: str):
        """Existing domain queries must still route correctly after patch addition."""
        result = classify_query_text(query)
        assert result["domain"] == expected_domain


class TestPatchPrecedence:
    """Verify patch takes precedence over compute for patch-specific terms."""

    def test_patch_over_compute_when_both_match(self):
        """'patch status on virtual machines' should route to patch, not compute.

        The patch entry is checked before compute in QUERY_DOMAIN_KEYWORDS,
        so 'patch' keyword matches first.
        """
        result = classify_query_text("check patch status on my virtual machines")
        assert result["domain"] == "patch"
