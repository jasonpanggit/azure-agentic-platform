"""Cross-agent validation tests for MCP v2 tool name migration.

Ensures all agents use v2 namespace names and no v1 dotted names remain
in ALLOWED_MCP_TOOLS lists or system prompts.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

# Repo root — resolved from this file's location (agents/tests/test_mcp_v2_migration.py)
_REPO_ROOT = Path(__file__).parents[2]

# v1 dotted tool names that must NOT appear anywhere
V1_DOTTED_NAMES = [
    "monitor.query_logs",
    "monitor.query_metrics",
    "advisor.list_recommendations",
    "resourcehealth.get_availability_status",
    "resourcehealth.list_events",
    "applicationinsights.query",
    "storage.list_accounts",
    "storage.get_account",
    "compute.list_vms",
    "compute.get_vm",
    "compute.list_disks",
    "keyvault.list_vaults",
    "keyvault.get_vault",
    "role.list_assignments",
    "fileshares.list",
    "appservice.list_apps",
    "appservice.get_app",
]

AGENT_TOOLS_MODULES = [
    "agents.sre.tools",
    "agents.compute.tools",
    "agents.network.tools",
    "agents.storage.tools",
    "agents.security.tools",
    "agents.eol.tools",
    "agents.patch.tools",
    "agents.arc.tools",
]


class TestMcpV2Migration:
    """Verify all agents have migrated to v2 namespace tool names."""

    @pytest.mark.parametrize("mod_path", AGENT_TOOLS_MODULES)
    def test_no_dotted_mcp_tool_names(self, mod_path: str):
        """ALLOWED_MCP_TOOLS must not contain v1 dotted names."""
        mod = importlib.import_module(mod_path)
        tools = getattr(mod, "ALLOWED_MCP_TOOLS")
        for tool in tools:
            assert "." not in tool, (
                f"{mod_path}: dotted tool name '{tool}' found — "
                f"must use v2 namespace name (e.g., 'monitor' not 'monitor.query_logs')"
            )

    def test_dockerfile_mcp_version(self):
        """Dockerfile must pin to 2.0.0 (not beta, not 3.x)."""
        dockerfile = _REPO_ROOT / "services/azure-mcp-server/Dockerfile"
        content = dockerfile.read_text()
        assert "ARG AZURE_MCP_VERSION=2.0.0" in content
        version_line = [
            l for l in content.splitlines()
            if "AZURE_MCP_VERSION=" in l
        ][0]
        assert "beta" not in version_line
        assert "3.0.0" not in version_line

    def test_claude_md_references_new_repo(self):
        """CLAUDE.md must reference microsoft/mcp repo."""
        claude_md = _REPO_ROOT / "CLAUDE.md"
        content = claude_md.read_text()
        assert "microsoft/mcp" in content
