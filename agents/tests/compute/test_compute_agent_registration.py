"""Phase 34 tests — verify all 20 compute tools are registered in the agent.

Strategy: since @ai_function is mocked (returns a MagicMock with no __name__),
we directly verify that the function objects imported from compute.tools are
the exact same objects passed to ChatAgent(tools=[...]). Object identity is
the correct test — it proves the agent.py import block and tools= list are
consistent.

Important: each test captures the pre-test sys.modules state and restores it
after, so compute module cache eviction doesn't pollute other test files.
"""
from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_TOOL_NAMES = [
    "query_activity_log",
    "query_log_analytics",
    "query_resource_health",
    "query_monitor_metrics",
    "query_os_version",
    "query_vm_extensions",
    "query_boot_diagnostics",
    "query_vm_sku_options",
    "query_disk_health",
    "propose_vm_restart",
    "propose_vm_resize",
    "propose_vm_redeploy",
    "query_vmss_instances",
    "query_vmss_autoscale",
    "query_vmss_rolling_upgrade",
    "propose_vmss_scale",
    "query_aks_cluster_health",
    "query_aks_node_pools",
    "query_aks_upgrade_profile",
    "propose_aks_node_pool_scale",
]

_PHASE_32_TOOL_NAMES = [
    "query_vm_extensions",
    "query_boot_diagnostics",
    "query_vm_sku_options",
    "query_disk_health",
    "propose_vm_restart",
    "propose_vm_resize",
    "propose_vm_redeploy",
    "query_vmss_instances",
    "query_vmss_autoscale",
    "query_vmss_rolling_upgrade",
    "propose_vmss_scale",
    "query_aks_cluster_health",
    "query_aks_node_pools",
    "query_aks_upgrade_profile",
    "propose_aks_node_pool_scale",
]

_ORIGINAL_TOOL_NAMES = [
    "query_activity_log",
    "query_log_analytics",
    "query_resource_health",
    "query_monitor_metrics",
    "query_os_version",
]


def _load_compute_tools_and_agent():
    """
    Import compute.tools and compute.agent with mocked dependencies.
    Saves and restores sys.modules so that module cache eviction is scoped
    to this function and does not affect other test files.

    Returns:
        (tools_module, registered_tools_list)
    """
    # Snapshot modules before we tamper with them
    saved_modules = {
        k: v for k, v in sys.modules.items()
        if k == "compute" or k.startswith("compute.")
    }

    # Evict compute modules for a fresh import
    for key in list(sys.modules.keys()):
        if key == "compute" or key.startswith("compute."):
            del sys.modules[key]

    mock_af = MagicMock()
    captured_tools: list[Any] = []

    def _chat_agent_side_effect(**kwargs: Any) -> MagicMock:
        captured_tools.extend(kwargs.get("tools", []))
        return MagicMock()

    mock_af.ChatAgent.side_effect = _chat_agent_side_effect
    mock_shared = MagicMock()
    env_patch = {
        "AZURE_PROJECT_ENDPOINT": "https://fake.endpoint",
        "AZURE_CLIENT_ID": "fake-id",
        "AZURE_TENANT_ID": "fake-tenant",
        "AZURE_CLIENT_SECRET": "fake-secret",
    }

    try:
        with (
            patch.dict("sys.modules", {
                "agent_framework": mock_af,
                "azure.ai.projects": MagicMock(),
                "azure.ai.projects.models": MagicMock(),
                "shared.auth": mock_shared,
                "shared.otel": mock_shared,
            }),
            patch.dict(os.environ, env_patch),
        ):
            import compute.tools as tools_mod
            import compute.agent as agent_mod

            try:
                agent_mod.create_compute_agent()
            except Exception:
                pass

        return tools_mod, captured_tools
    finally:
        # Restore original compute modules (may be empty dict — that's fine)
        for key in list(sys.modules.keys()):
            if key == "compute" or key.startswith("compute."):
                del sys.modules[key]
        sys.modules.update(saved_modules)


class TestComputeAgentToolRegistration:

    def test_all_20_tools_registered_by_identity(self):
        tools_mod, registered = _load_compute_tools_and_agent()
        assert len(registered) > 0, "ChatAgent was never called with any tools"
        for name in _TOOL_NAMES:
            expected_fn = getattr(tools_mod, name)
            assert expected_fn in registered, (
                f"Tool '{name}' not found in ChatAgent tools= list. "
                f"Registered {len(registered)} tool(s)."
            )

    def test_exactly_20_tools_registered(self):
        _, registered = _load_compute_tools_and_agent()
        assert len(registered) == 20, f"Expected 20 tools, got {len(registered)}"

    def test_phase_32_tools_now_registered(self):
        tools_mod, registered = _load_compute_tools_and_agent()
        missing = [
            name for name in _PHASE_32_TOOL_NAMES
            if getattr(tools_mod, name) not in registered
        ]
        assert not missing, f"Phase 32 tools still missing: {missing}"

    def test_original_5_tools_still_registered(self):
        tools_mod, registered = _load_compute_tools_and_agent()
        missing = [
            name for name in _ORIGINAL_TOOL_NAMES
            if getattr(tools_mod, name) not in registered
        ]
        assert not missing, f"Original triage tools accidentally removed: {missing}"

    def test_system_prompt_mentions_phase_32_tools(self):
        saved = {k: v for k, v in sys.modules.items()
                 if k == "compute" or k.startswith("compute.")}
        for key in list(sys.modules.keys()):
            if key == "compute" or key.startswith("compute."):
                del sys.modules[key]
        try:
            mock_shared = MagicMock()
            with patch.dict("sys.modules", {
                "agent_framework": MagicMock(),
                "azure.ai.projects": MagicMock(),
                "azure.ai.projects.models": MagicMock(),
                "shared.auth": mock_shared,
                "shared.otel": mock_shared,
            }):
                import compute.agent as agent_mod

            prompt = agent_mod.COMPUTE_AGENT_SYSTEM_PROMPT
            for tool_name in ["query_vm_extensions", "propose_vm_restart",
                               "query_aks_cluster_health", "propose_vmss_scale"]:
                assert tool_name in prompt, (
                    f"Tool '{tool_name}' not in COMPUTE_AGENT_SYSTEM_PROMPT"
                )
        finally:
            for key in list(sys.modules.keys()):
                if key == "compute" or key.startswith("compute."):
                    del sys.modules[key]
            sys.modules.update(saved)
