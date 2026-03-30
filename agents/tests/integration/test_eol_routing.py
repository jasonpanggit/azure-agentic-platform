"""Integration tests for EOL domain routing in the orchestrator (Phase 12)."""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# DOMAIN_AGENT_MAP
# ---------------------------------------------------------------------------


class TestEolDomainAgentMap:
    """Verify DOMAIN_AGENT_MAP contains the eol domain entry."""

    def test_eol_in_domain_agent_map(self):
        from agents.orchestrator.agent import DOMAIN_AGENT_MAP

        assert "eol" in DOMAIN_AGENT_MAP

    def test_eol_maps_to_eol_agent(self):
        from agents.orchestrator.agent import DOMAIN_AGENT_MAP

        # eol_agent uses underscore format (Foundry connected-agent name pattern)
        assert DOMAIN_AGENT_MAP["eol"] == "eol_agent"

    def test_domain_agent_map_has_8_entries(self):
        from agents.orchestrator.agent import DOMAIN_AGENT_MAP

        assert len(DOMAIN_AGENT_MAP) == 8


# ---------------------------------------------------------------------------
# RESOURCE_TYPE_TO_DOMAIN
# ---------------------------------------------------------------------------


class TestEolResourceTypeToDomain:
    """Verify RESOURCE_TYPE_TO_DOMAIN maps microsoft.lifecycle to eol."""

    def test_microsoft_lifecycle_maps_to_eol(self):
        from agents.orchestrator.agent import RESOURCE_TYPE_TO_DOMAIN

        assert RESOURCE_TYPE_TO_DOMAIN["microsoft.lifecycle"] == "eol"

    def test_resource_type_map_has_13_entries(self):
        from agents.orchestrator.agent import RESOURCE_TYPE_TO_DOMAIN

        assert len(RESOURCE_TYPE_TO_DOMAIN) == 13


# ---------------------------------------------------------------------------
# classify_query_text — EOL keyword routing
# ---------------------------------------------------------------------------


class TestEolQueryKeywords:
    """Verify classify_query_text routes EOL-related queries to the eol domain."""

    def test_end_of_life_routes_to_eol(self):
        from agents.shared.routing import classify_query_text

        result = classify_query_text("check end of life status")
        assert result["domain"] == "eol"

    def test_eol_routes_to_eol(self):
        from agents.shared.routing import classify_query_text

        result = classify_query_text("what is the eol date for ubuntu 18.04")
        assert result["domain"] == "eol"

    def test_outdated_software_routes_to_eol(self):
        from agents.shared.routing import classify_query_text

        result = classify_query_text("find outdated software in my estate")
        assert result["domain"] == "eol"

    def test_software_lifecycle_routes_to_eol(self):
        from agents.shared.routing import classify_query_text

        result = classify_query_text("software lifecycle check for production VMs")
        assert result["domain"] == "eol"

    def test_unsupported_version_routes_to_eol(self):
        from agents.shared.routing import classify_query_text

        result = classify_query_text("identify unsupported version servers")
        assert result["domain"] == "eol"

    def test_deprecated_version_routes_to_eol(self):
        from agents.shared.routing import classify_query_text

        result = classify_query_text("list deprecated version databases")
        assert result["domain"] == "eol"

    def test_lifecycle_status_routes_to_eol(self):
        from agents.shared.routing import classify_query_text

        result = classify_query_text("lifecycle status of windows server")
        assert result["domain"] == "eol"
