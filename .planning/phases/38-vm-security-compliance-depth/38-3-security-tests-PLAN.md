---
plan: 38-3
title: "Unit Tests — 20 tests across 5 classes in test_compute_security.py"
wave: 2
depends_on:
  - 38-1
creates:
  - agents/tests/compute/test_compute_security.py
must_haves:
  - 20 tests passing (pytest -q agents/tests/compute/test_compute_security.py == 20 passed)
  - TestQueryDefenderTvmCveCount with 4 tests
  - TestQueryJitAccessStatus with 4 tests
  - TestQueryEffectiveNsgRules with 4 tests
  - TestQueryBackupRpo with 4 tests
  - TestQueryAsrReplicationHealth with 4 tests
  - All tests follow @patch("agents.compute.tools.X") pattern from test_compute_performance.py
  - _instrument_mock() helper function present
---

# Plan 38-3: Unit Tests

## Goal

Create `agents/tests/compute/test_compute_security.py` with 20 tests covering
all 5 new security tools. Follow the exact pattern from
`agents/tests/compute/test_compute_performance.py` — class per tool, 4 tests
per class, `_instrument_mock()` helper, `@patch("agents.compute.tools.X")` style.

---

## Read First

<read_first>
- `agents/tests/compute/test_compute_performance.py` — full file (follow this pattern exactly)
- `agents/compute/tools.py` — the 5 new function bodies (understand return shapes + error paths)
- `.planning/phases/38-vm-security-compliance-depth/38-CONTEXT.md` — decisions section (test scenarios)
</read_first>

---

## Acceptance Criteria

```bash
cd agents && python -m pytest tests/compute/test_compute_security.py -q
# 20 passed, 0 failed, 0 errors

# 5 test classes present
grep -c "^class Test" agents/tests/compute/test_compute_security.py  # == 5

# 20 test methods
grep -c "def test_" agents/tests/compute/test_compute_security.py    # == 20

# All tools covered
grep "query_defender_tvm_cve_count" agents/tests/compute/test_compute_security.py
grep "query_jit_access_status" agents/tests/compute/test_compute_security.py
grep "query_effective_nsg_rules" agents/tests/compute/test_compute_security.py
grep "query_backup_rpo" agents/tests/compute/test_compute_security.py
grep "query_asr_replication_health" agents/tests/compute/test_compute_security.py
```

---

## Action

Create `agents/tests/compute/test_compute_security.py` with the content below.

### File structure

```
module docstring
_instrument_mock() helper

class TestQueryDefenderTvmCveCount (4 tests)
class TestQueryJitAccessStatus (4 tests)
class TestQueryEffectiveNsgRules (4 tests)
class TestQueryBackupRpo (4 tests)
class TestQueryAsrReplicationHealth (4 tests)
```

### Complete file content

```python
"""Tests for Phase 38 VM security & compliance tool functions.

Covers: query_defender_tvm_cve_count, query_jit_access_status,
query_effective_nsg_rules, query_backup_rpo, query_asr_replication_health.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _instrument_mock():
    """Return a context-manager-compatible MagicMock."""
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


# ---------------------------------------------------------------------------
# TestQueryDefenderTvmCveCount
# ---------------------------------------------------------------------------


class TestQueryDefenderTvmCveCount:
    """Tests for query_defender_tvm_cve_count."""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.QueryRequest")
    @patch("agents.compute.tools.QueryRequestOptions")
    @patch("agents.compute.tools.get_credential")
    def test_cve_count_success_mixed_severities(
        self,
        mock_cred,
        mock_qro,
        mock_qr,
        mock_arg_cls,
        mock_identity,
        mock_instr,
    ):
        """ARG returns rows for multiple severities → counts + vm_risk_score correct."""
        mock_instr.return_value = _instrument_mock()

        mock_response = MagicMock()
        mock_response.data = [
            {"severity": "Critical", "count_": 3},
            {"severity": "High", "count_": 7},
            {"severity": "Medium", "count_": 12},
            {"severity": "Low", "count_": 5},
        ]
        mock_arg_client = MagicMock()
        mock_arg_client.resources.return_value = mock_response
        mock_arg_cls.return_value = mock_arg_client

        from agents.compute.tools import query_defender_tvm_cve_count

        result = query_defender_tvm_cve_count(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["critical"] == 3
        assert result["high"] == 7
        assert result["medium"] == 12
        assert result["low"] == 5
        assert result["total"] == 27
        # vm_risk_score = 3*10 + 7*5 + 12*2 + 5*1 = 30+35+24+5 = 94
        assert result["vm_risk_score"] == 94.0
        assert "duration_ms" in result
        assert result["vm_name"] == "vm-prod"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.QueryRequest")
    @patch("agents.compute.tools.QueryRequestOptions")
    @patch("agents.compute.tools.get_credential")
    def test_cve_count_no_cves_score_zero(
        self,
        mock_cred,
        mock_qro,
        mock_qr,
        mock_arg_cls,
        mock_identity,
        mock_instr,
    ):
        """ARG returns empty data → all counts 0, vm_risk_score == 0.0."""
        mock_instr.return_value = _instrument_mock()

        mock_response = MagicMock()
        mock_response.data = []
        mock_arg_client = MagicMock()
        mock_arg_client.resources.return_value = mock_response
        mock_arg_cls.return_value = mock_arg_client

        from agents.compute.tools import query_defender_tvm_cve_count

        result = query_defender_tvm_cve_count(
            resource_group="rg1",
            vm_name="vm-clean",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["critical"] == 0
        assert result["high"] == 0
        assert result["medium"] == 0
        assert result["low"] == 0
        assert result["total"] == 0
        assert result["vm_risk_score"] == 0.0
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ResourceGraphClient", None)
    @patch("agents.compute.tools.get_credential")
    def test_cve_count_sdk_unavailable(
        self, mock_cred, mock_identity, mock_instr
    ):
        """ResourceGraphClient is None (ImportError path) → error dict returned."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_defender_tvm_cve_count

        result = query_defender_tvm_cve_count(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.QueryRequest")
    @patch("agents.compute.tools.QueryRequestOptions")
    @patch("agents.compute.tools.get_credential")
    def test_cve_count_sdk_exception(
        self,
        mock_cred,
        mock_qro,
        mock_qr,
        mock_arg_cls,
        mock_identity,
        mock_instr,
    ):
        """ARG client.resources() raises → error dict returned, no re-raise."""
        mock_instr.return_value = _instrument_mock()

        mock_arg_client = MagicMock()
        mock_arg_client.resources.side_effect = RuntimeError("ARG quota exceeded")
        mock_arg_cls.return_value = mock_arg_client

        from agents.compute.tools import query_defender_tvm_cve_count

        result = query_defender_tvm_cve_count(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "ARG quota exceeded" in result["error"]
        assert "duration_ms" in result


# ---------------------------------------------------------------------------
# TestQueryJitAccessStatus
# ---------------------------------------------------------------------------


class TestQueryJitAccessStatus:
    """Tests for query_jit_access_status."""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.SecurityCenter")
    @patch("agents.compute.tools.get_credential")
    def test_jit_enabled_with_active_session(
        self, mock_cred, mock_sc_cls, mock_identity, mock_instr
    ):
        """JIT policy found for VM with one active session → jit_enabled True."""
        mock_instr.return_value = _instrument_mock()

        vm_resource_id = (
            "/subscriptions/sub-1/resourceGroups/rg1"
            "/providers/Microsoft.Compute/virtualMachines/vm-prod"
        )

        # Build mock port config
        mock_port = MagicMock()
        mock_port.number = 22
        mock_port.protocol = "TCP"
        mock_port.max_request_access_duration = "PT3H"

        # Build mock VM entry in JIT policy
        mock_vm_entry = MagicMock()
        mock_vm_entry.id = vm_resource_id
        mock_vm_entry.ports = [mock_port]

        # Build mock active request for this VM
        mock_req_vm = MagicMock()
        mock_req_vm.id = vm_resource_id
        mock_request = MagicMock()
        mock_request.requestor = "user@contoso.com"
        mock_request.start_time_utc = "2026-04-11T10:00:00Z"
        mock_request.justification = "Maintenance"
        mock_request.virtual_machines = [mock_req_vm]

        # Build mock JIT policy
        mock_policy = MagicMock()
        mock_policy.name = "default"
        mock_policy.virtual_machines = [mock_vm_entry]
        mock_policy.requests = [mock_request]

        mock_sc = MagicMock()
        mock_sc.jit_network_access_policies.list_by_resource_group.return_value = [
            mock_policy
        ]
        mock_sc_cls.return_value = mock_sc

        from agents.compute.tools import query_jit_access_status

        result = query_jit_access_status(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["jit_enabled"] is True
        assert result["policy_name"] == "default"
        assert len(result["allowed_ports"]) == 1
        assert result["allowed_ports"][0]["port"] == 22
        assert len(result["active_sessions"]) == 1
        assert result["active_sessions"][0]["requestor"] == "user@contoso.com"
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.SecurityCenter")
    @patch("agents.compute.tools.get_credential")
    def test_jit_not_configured_graceful(
        self, mock_cred, mock_sc_cls, mock_identity, mock_instr
    ):
        """No JIT policies in resource group → jit_enabled False, query_status success."""
        mock_instr.return_value = _instrument_mock()

        mock_sc = MagicMock()
        mock_sc.jit_network_access_policies.list_by_resource_group.return_value = []
        mock_sc_cls.return_value = mock_sc

        from agents.compute.tools import query_jit_access_status

        result = query_jit_access_status(
            resource_group="rg-no-jit",
            vm_name="vm-nojit",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["jit_enabled"] is False
        assert result["allowed_ports"] == []
        assert result["active_sessions"] == []
        assert result["policy_name"] == ""
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.SecurityCenter", None)
    @patch("agents.compute.tools.get_credential")
    def test_jit_sdk_unavailable(
        self, mock_cred, mock_identity, mock_instr
    ):
        """SecurityCenter is None (ImportError path) → error dict returned."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_jit_access_status

        result = query_jit_access_status(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]
        assert result["jit_enabled"] is False
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.SecurityCenter")
    @patch("agents.compute.tools.get_credential")
    def test_jit_sdk_exception(
        self, mock_cred, mock_sc_cls, mock_identity, mock_instr
    ):
        """SecurityCenter.jit_network_access_policies raises → error dict, no re-raise."""
        mock_instr.return_value = _instrument_mock()

        mock_sc = MagicMock()
        mock_sc.jit_network_access_policies.list_by_resource_group.side_effect = (
            RuntimeError("Security Center unavailable")
        )
        mock_sc_cls.return_value = mock_sc

        from agents.compute.tools import query_jit_access_status

        result = query_jit_access_status(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "Security Center unavailable" in result["error"]
        assert result["jit_enabled"] is False
        assert "duration_ms" in result


# ---------------------------------------------------------------------------
# TestQueryEffectiveNsgRules
# ---------------------------------------------------------------------------


class TestQueryEffectiveNsgRules:
    """Tests for query_effective_nsg_rules."""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.NetworkManagementClient")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_nsg_rules_returned_with_high_priority_flag(
        self, mock_cred, mock_compute_cls, mock_network_cls, mock_identity, mock_instr
    ):
        """NSG rules returned including one with priority < 200 → high_priority=True."""
        mock_instr.return_value = _instrument_mock()

        # Mock VM with NIC
        mock_nic_ref = MagicMock()
        mock_nic_ref.id = (
            "/subscriptions/sub-1/resourceGroups/rg1"
            "/providers/Microsoft.Network/networkInterfaces/vm-prod-nic"
        )
        mock_network_profile = MagicMock()
        mock_network_profile.network_interfaces = [mock_nic_ref]
        mock_vm = MagicMock()
        mock_vm.network_profile = mock_network_profile

        mock_compute = MagicMock()
        mock_compute.virtual_machines.get.return_value = mock_vm
        mock_compute_cls.return_value = mock_compute

        # Mock effective NSG rules
        def _make_rule(name, direction, access, priority, protocol="TCP"):
            r = MagicMock()
            r.name = name
            r.direction = direction
            r.access = access
            r.priority = priority
            r.protocol = protocol
            r.source_port_range = "*"
            r.destination_port_range = str(priority)
            return r

        mock_assoc = MagicMock()
        mock_assoc.effective_security_rules = [
            _make_rule("AllowSSH", "Inbound", "Allow", 100),   # high_priority: True
            _make_rule("DenyAll", "Inbound", "Deny", 65000),
            _make_rule("AllowOutbound", "Outbound", "Allow", 300),
        ]
        mock_lro_result = MagicMock()
        mock_lro_result.value = [mock_assoc]

        mock_poller = MagicMock()
        mock_poller.result.return_value = mock_lro_result

        mock_network = MagicMock()
        mock_network.network_interfaces.begin_list_effective_network_security_groups.return_value = (
            mock_poller
        )
        mock_network_cls.return_value = mock_network

        from agents.compute.tools import query_effective_nsg_rules

        result = query_effective_nsg_rules(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["nic_name"] == "vm-prod-nic"
        assert len(result["effective_rules"]) == 3
        high_p_rules = [r for r in result["effective_rules"] if r["high_priority"]]
        assert len(high_p_rules) == 1
        assert high_p_rules[0]["name"] == "AllowSSH"
        assert result["inbound_deny_count"] == 1
        assert result["outbound_deny_count"] == 0
        assert result["high_priority_count"] == 1
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.NetworkManagementClient")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_nsg_empty_rules(
        self, mock_cred, mock_compute_cls, mock_network_cls, mock_identity, mock_instr
    ):
        """NSG effective rules returns empty list → counts 0, status success."""
        mock_instr.return_value = _instrument_mock()

        mock_nic_ref = MagicMock()
        mock_nic_ref.id = (
            "/subscriptions/sub-1/resourceGroups/rg1"
            "/providers/Microsoft.Network/networkInterfaces/vm-nic"
        )
        mock_network_profile = MagicMock()
        mock_network_profile.network_interfaces = [mock_nic_ref]
        mock_vm = MagicMock()
        mock_vm.network_profile = mock_network_profile

        mock_compute = MagicMock()
        mock_compute.virtual_machines.get.return_value = mock_vm
        mock_compute_cls.return_value = mock_compute

        mock_assoc = MagicMock()
        mock_assoc.effective_security_rules = []
        mock_lro_result = MagicMock()
        mock_lro_result.value = [mock_assoc]
        mock_poller = MagicMock()
        mock_poller.result.return_value = mock_lro_result

        mock_network = MagicMock()
        mock_network.network_interfaces.begin_list_effective_network_security_groups.return_value = (
            mock_poller
        )
        mock_network_cls.return_value = mock_network

        from agents.compute.tools import query_effective_nsg_rules

        result = query_effective_nsg_rules(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["effective_rules"] == []
        assert result["inbound_deny_count"] == 0
        assert result["outbound_deny_count"] == 0
        assert result["high_priority_count"] == 0
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.NetworkManagementClient", None)
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_nsg_sdk_unavailable(
        self, mock_cred, mock_compute_cls, mock_identity, mock_instr
    ):
        """NetworkManagementClient is None → error dict returned."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_effective_nsg_rules

        result = query_effective_nsg_rules(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.NetworkManagementClient")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_nsg_sdk_exception(
        self, mock_cred, mock_compute_cls, mock_network_cls, mock_identity, mock_instr
    ):
        """ComputeManagementClient.virtual_machines.get raises → error dict, no re-raise."""
        mock_instr.return_value = _instrument_mock()

        mock_compute = MagicMock()
        mock_compute.virtual_machines.get.side_effect = RuntimeError("compute timeout")
        mock_compute_cls.return_value = mock_compute

        from agents.compute.tools import query_effective_nsg_rules

        result = query_effective_nsg_rules(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "compute timeout" in result["error"]
        assert "duration_ms" in result


# ---------------------------------------------------------------------------
# TestQueryBackupRpo
# ---------------------------------------------------------------------------


class TestQueryBackupRpo:
    """Tests for query_backup_rpo."""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.RecoveryServicesBackupClient")
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.QueryRequest")
    @patch("agents.compute.tools.QueryRequestOptions")
    @patch("agents.compute.tools.get_credential")
    def test_backup_configured_with_last_backup_time(
        self,
        mock_cred,
        mock_qro,
        mock_qr,
        mock_arg_cls,
        mock_backup_cls,
        mock_identity,
        mock_instr,
    ):
        """Backup vault + protected item found → backup_enabled True with RPO."""
        from datetime import datetime, timedelta, timezone

        mock_instr.return_value = _instrument_mock()

        # ARG returns one vault
        mock_vault_response = MagicMock()
        mock_vault_response.data = [{"name": "rsv-prod", "resourceGroup": "rg-backup"}]
        mock_arg_client = MagicMock()
        mock_arg_client.resources.return_value = mock_vault_response
        mock_arg_cls.return_value = mock_arg_client

        # Backup client returns one protected item matching the VM
        last_backup = datetime.now(timezone.utc) - timedelta(hours=12)
        mock_props = MagicMock()
        mock_props.virtual_machine_id = (
            "/subscriptions/sub-1/resourceGroups/rg1"
            "/providers/Microsoft.Compute/virtualMachines/vm-prod"
        )
        mock_props.last_backup_time = last_backup
        mock_props.last_backup_status = "Completed"

        mock_item = MagicMock()
        mock_item.properties = mock_props

        mock_backup = MagicMock()
        mock_backup.backup_protected_items.list.return_value = [mock_item]
        mock_backup_cls.return_value = mock_backup

        from agents.compute.tools import query_backup_rpo

        result = query_backup_rpo(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["backup_enabled"] is True
        assert result["vault_name"] == "rsv-prod"
        assert result["last_backup_status"] == "Completed"
        assert result["rpo_minutes"] > 0   # 12 hours = 720 minutes
        assert result["last_backup_time"] != ""
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.RecoveryServicesBackupClient")
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.QueryRequest")
    @patch("agents.compute.tools.QueryRequestOptions")
    @patch("agents.compute.tools.get_credential")
    def test_backup_not_configured_graceful(
        self,
        mock_cred,
        mock_qro,
        mock_qr,
        mock_arg_cls,
        mock_backup_cls,
        mock_identity,
        mock_instr,
    ):
        """No Recovery Services vaults in subscription → backup_enabled False, status success."""
        mock_instr.return_value = _instrument_mock()

        mock_vault_response = MagicMock()
        mock_vault_response.data = []
        mock_arg_client = MagicMock()
        mock_arg_client.resources.return_value = mock_vault_response
        mock_arg_cls.return_value = mock_arg_client

        from agents.compute.tools import query_backup_rpo

        result = query_backup_rpo(
            resource_group="rg1",
            vm_name="vm-nobackup",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["backup_enabled"] is False
        assert result["vault_name"] == ""
        assert result["last_backup_time"] == ""
        assert result["rpo_minutes"] == -1
        assert "duration_ms" in result
        # Backup client should never be called when no vaults found
        mock_backup_cls.assert_not_called()

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.RecoveryServicesBackupClient", None)
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential")
    def test_backup_sdk_unavailable(
        self, mock_cred, mock_arg_cls, mock_identity, mock_instr
    ):
        """RecoveryServicesBackupClient is None (ImportError path) → error dict."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_backup_rpo

        result = query_backup_rpo(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]
        assert result["backup_enabled"] is False
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.RecoveryServicesBackupClient")
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.QueryRequest")
    @patch("agents.compute.tools.QueryRequestOptions")
    @patch("agents.compute.tools.get_credential")
    def test_backup_sdk_exception(
        self,
        mock_cred,
        mock_qro,
        mock_qr,
        mock_arg_cls,
        mock_backup_cls,
        mock_identity,
        mock_instr,
    ):
        """ARG client.resources() raises → error dict returned, no re-raise."""
        mock_instr.return_value = _instrument_mock()

        mock_arg_client = MagicMock()
        mock_arg_client.resources.side_effect = RuntimeError("ARG throttled")
        mock_arg_cls.return_value = mock_arg_client

        from agents.compute.tools import query_backup_rpo

        result = query_backup_rpo(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "ARG throttled" in result["error"]
        assert result["backup_enabled"] is False
        assert "duration_ms" in result


# ---------------------------------------------------------------------------
# TestQueryAsrReplicationHealth
# ---------------------------------------------------------------------------


class TestQueryAsrReplicationHealth:
    """Tests for query_asr_replication_health."""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.SiteRecoveryManagementClient")
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.QueryRequest")
    @patch("agents.compute.tools.QueryRequestOptions")
    @patch("agents.compute.tools.get_credential")
    def test_asr_configured_with_health_status(
        self,
        mock_cred,
        mock_qro,
        mock_qr,
        mock_arg_cls,
        mock_asr_cls,
        mock_identity,
        mock_instr,
    ):
        """ASR vault + protected item found → asr_enabled True, health and RPO present."""
        mock_instr.return_value = _instrument_mock()

        # ARG returns one vault
        mock_vault_response = MagicMock()
        mock_vault_response.data = [{"name": "rsv-asr", "resourceGroup": "rg-dr"}]
        mock_arg_client = MagicMock()
        mock_arg_client.resources.return_value = mock_vault_response
        mock_arg_cls.return_value = mock_arg_client

        # Build mock ASR protected item matching the VM
        vm_resource_id = (
            "/subscriptions/sub-1/resourceGroups/rg1"
            "/providers/Microsoft.Compute/virtualMachines/vm-prod"
        )
        mock_prov_details = MagicMock()
        mock_prov_details.fabric_object_id = vm_resource_id

        mock_scenario = MagicMock()
        mock_scenario.recovery_point_objective_in_seconds = 300

        mock_props = MagicMock()
        mock_props.provider_specific_details = mock_prov_details
        mock_props.replication_health = "Normal"
        mock_props.failover_readiness = "Ready"
        mock_props.current_scenario = mock_scenario
        mock_props.primary_fabric_friendly_name = "East US"

        mock_item = MagicMock()
        mock_item.properties = mock_props
        mock_item.name = "vm-prod-protection"

        mock_asr = MagicMock()
        mock_asr.replication_protected_items.list.return_value = [mock_item]
        mock_asr_cls.return_value = mock_asr

        from agents.compute.tools import query_asr_replication_health

        result = query_asr_replication_health(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["asr_enabled"] is True
        assert result["replication_health"] == "Normal"
        assert result["failover_readiness"] == "Ready"
        assert result["rpo_seconds"] == 300
        assert result["primary_fabric"] == "East US"
        assert result["vault_name"] == "rsv-asr"
        assert result["protected_item_name"] == "vm-prod-protection"
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.SiteRecoveryManagementClient")
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.QueryRequest")
    @patch("agents.compute.tools.QueryRequestOptions")
    @patch("agents.compute.tools.get_credential")
    def test_asr_not_configured_graceful(
        self,
        mock_cred,
        mock_qro,
        mock_qr,
        mock_arg_cls,
        mock_asr_cls,
        mock_identity,
        mock_instr,
    ):
        """No ASR vaults in subscription → asr_enabled False, replication_health not_configured."""
        mock_instr.return_value = _instrument_mock()

        mock_vault_response = MagicMock()
        mock_vault_response.data = []
        mock_arg_client = MagicMock()
        mock_arg_client.resources.return_value = mock_vault_response
        mock_arg_cls.return_value = mock_arg_client

        from agents.compute.tools import query_asr_replication_health

        result = query_asr_replication_health(
            resource_group="rg1",
            vm_name="vm-noasr",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["asr_enabled"] is False
        assert result["replication_health"] == "not_configured"
        assert result["rpo_seconds"] == -1
        assert result["vault_name"] == ""
        assert "duration_ms" in result
        mock_asr_cls.assert_not_called()

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.SiteRecoveryManagementClient", None)
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential")
    def test_asr_sdk_unavailable(
        self, mock_cred, mock_arg_cls, mock_identity, mock_instr
    ):
        """SiteRecoveryManagementClient is None (ImportError path) → error dict."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_asr_replication_health

        result = query_asr_replication_health(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]
        assert result["asr_enabled"] is False
        assert result["replication_health"] == "not_configured"
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.SiteRecoveryManagementClient")
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.QueryRequest")
    @patch("agents.compute.tools.QueryRequestOptions")
    @patch("agents.compute.tools.get_credential")
    def test_asr_sdk_exception(
        self,
        mock_cred,
        mock_qro,
        mock_qr,
        mock_arg_cls,
        mock_asr_cls,
        mock_identity,
        mock_instr,
    ):
        """ARG client.resources() raises → error dict returned, no re-raise."""
        mock_instr.return_value = _instrument_mock()

        mock_arg_client = MagicMock()
        mock_arg_client.resources.side_effect = RuntimeError("network error")
        mock_arg_cls.return_value = mock_arg_client

        from agents.compute.tools import query_asr_replication_health

        result = query_asr_replication_health(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "network error" in result["error"]
        assert result["asr_enabled"] is False
        assert "duration_ms" in result
```

---

## Verification

```bash
# Run all 20 tests
cd agents && python -m pytest tests/compute/test_compute_security.py -v

# Counts
grep -c "^class Test" agents/tests/compute/test_compute_security.py   # == 5
grep -c "    def test_" agents/tests/compute/test_compute_security.py  # == 20

# No imports of real Azure SDKs at module level (all patched via @patch)
python -c "
import ast, sys
tree = ast.parse(open('agents/tests/compute/test_compute_security.py').read())
imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
azure_top = [i for i in imports if any(
    getattr(a, 'name', getattr(i, 'module', '')).startswith('azure') for a in getattr(i, 'names', [])
)]
print('Azure top-level imports:', len(azure_top))  # Should be 0
"
```
