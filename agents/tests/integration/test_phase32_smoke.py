"""Phase 32 smoke tests — all new tool functions importable and callable."""
from __future__ import annotations

import inspect

import pytest


class TestPhase32Smoke:
    def test_all_new_compute_tools_importable(self):
        from agents.compute.tools import (
            propose_aks_node_pool_scale,
            propose_vm_redeploy,
            propose_vm_resize,
            propose_vm_restart,
            propose_vmss_scale,
            query_aks_cluster_health,
            query_aks_node_pools,
            query_aks_upgrade_profile,
            query_boot_diagnostics,
            query_disk_health,
            query_vm_extensions,
            query_vm_sku_options,
            query_vmss_autoscale,
            query_vmss_instances,
            query_vmss_rolling_upgrade,
        )
        assert all([
            query_vm_extensions, query_boot_diagnostics, query_vm_sku_options, query_disk_health,
            propose_vm_restart, propose_vm_resize, propose_vm_redeploy,
            query_vmss_instances, query_vmss_autoscale, query_vmss_rolling_upgrade, propose_vmss_scale,
            query_aks_cluster_health, query_aks_node_pools, query_aks_upgrade_profile,
            propose_aks_node_pool_scale,
        ])

    def test_all_new_arc_tools_importable(self):
        from agents.arc.tools import (
            propose_arc_assessment,
            query_arc_connectivity,
            query_arc_extension_health,
            query_arc_guest_config,
        )
        assert all([
            query_arc_extension_health, query_arc_guest_config,
            query_arc_connectivity, propose_arc_assessment,
        ])

    def test_patch_stubs_fixed(self):
        from agents.patch.tools import query_activity_log, query_resource_health

        src_al = inspect.getsource(query_activity_log)
        src_rh = inspect.getsource(query_resource_health)
        # Real implementations reference the Azure SDK, not "stub" or "not implemented"
        assert "MonitorManagementClient" in src_al or "activity_logs" in src_al
        assert "MicrosoftResourceHealth" in src_rh or "availability_statuses" in src_rh

    def test_eol_stubs_fixed(self):
        from agents.eol.tools import query_activity_log, query_resource_health, query_software_inventory

        src_al = inspect.getsource(query_activity_log)
        src_rh = inspect.getsource(query_resource_health)
        src_si = inspect.getsource(query_software_inventory)
        assert "MonitorManagementClient" in src_al or "activity_logs" in src_al
        assert "MicrosoftResourceHealth" in src_rh or "availability_statuses" in src_rh
        assert "LogsQueryClient" in src_si or "query_workspace" in src_si

    def test_propose_tools_no_arm_calls(self):
        from agents.compute import tools as t

        for fn_name in ["propose_vm_restart", "propose_vm_resize", "propose_vm_redeploy"]:
            src = inspect.getsource(getattr(t, fn_name))
            assert "begin_restart" not in src, f"{fn_name} must not contain begin_restart"
            assert "begin_update" not in src, f"{fn_name} must not contain begin_update"
            assert "begin_redeploy" not in src, f"{fn_name} must not contain begin_redeploy"

    def test_arc_guest_config_uses_correct_sdk(self):
        from agents.arc import tools as arc_tools

        src = inspect.getsource(arc_tools.query_arc_guest_config)
        assert "GuestConfigurationClient" in src
        assert "machine_run_commands" not in src

    def test_total_new_tools_count_at_least_17(self):
        """Verify at least 17 new tools were added (spec target)."""
        from agents.compute import tools as compute_tools
        from agents.arc import tools as arc_tools

        compute_new = [
            "query_vm_extensions", "query_boot_diagnostics", "query_vm_sku_options",
            "query_disk_health", "propose_vm_restart", "propose_vm_resize",
            "propose_vm_redeploy", "query_vmss_instances", "query_vmss_autoscale",
            "query_vmss_rolling_upgrade", "propose_vmss_scale",
            "query_aks_cluster_health", "query_aks_node_pools",
            "query_aks_upgrade_profile", "propose_aks_node_pool_scale",
        ]
        arc_new = [
            "query_arc_extension_health", "query_arc_guest_config",
            "query_arc_connectivity", "propose_arc_assessment",
        ]

        for name in compute_new:
            assert hasattr(compute_tools, name), f"Missing compute tool: {name}"
        for name in arc_new:
            assert hasattr(arc_tools, name), f"Missing arc tool: {name}"

        total = len(compute_new) + len(arc_new)
        assert total >= 17, f"Expected >= 17 new tools, got {total}"
