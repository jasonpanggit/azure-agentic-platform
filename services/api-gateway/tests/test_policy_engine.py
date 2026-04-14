"""Unit tests for policy_engine.py — all guard paths for evaluate_auto_approval()."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RESOURCE_ID = "/subscriptions/sub-1/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm1"
_ACTION_CLASS = "restart_vm"
_POLICY_ID = "pol-11111111-1111-1111-1111-111111111111"

def _make_policy(
    policy_id: str = _POLICY_ID,
    action_class: str = _ACTION_CLASS,
    resource_tag_filter: dict | None = None,
    max_blast_radius: int = 10,
    max_daily_executions: int = 20,
    require_slo_healthy: bool = True,
    enabled: bool = True,
) -> dict:
    """Build a minimal policy dict as asyncpg would return."""
    return {
        "id": policy_id,
        "name": "Test policy",
        "action_class": action_class,
        "resource_tag_filter": resource_tag_filter or {},
        "max_blast_radius": max_blast_radius,
        "max_daily_executions": max_daily_executions,
        "require_slo_healthy": require_slo_healthy,
        "enabled": enabled,
    }


def _make_cosmos_client(daily_count: int = 0) -> MagicMock:
    """Build a mock Cosmos client that returns `daily_count` from the cap query."""
    mock_container = MagicMock()
    mock_container.query_items.return_value = [daily_count]
    mock_cosmos = MagicMock()
    mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container
    return mock_cosmos


def _make_topology_client(total_affected: int = 0) -> MagicMock:
    """Build a mock topology client with get_blast_radius."""
    mock_topo = MagicMock()
    mock_topo.get_blast_radius.return_value = {"total_affected": total_affected}
    return mock_topo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEvaluateAutoApproval:
    """Tests for evaluate_auto_approval() covering all guard paths."""

    # -----------------------------------------------------------------------
    # 1. aap-protected tag always blocks
    # -----------------------------------------------------------------------
    async def test_aap_protected_always_blocks(self):
        """Resource tagged aap-protected:true is ALWAYS blocked, regardless of policies."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        resource_tags = {"aap-protected": "true", "tier": "dev"}

        # Even with a valid policy in the DB, should be blocked immediately
        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[_make_policy()]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags=resource_tags,
                topology_client=None,
                cosmos_client=None,
                credential=None,
            )

        assert auto_approved is False
        assert policy_id is None
        assert reason == "resource_tagged_aap_protected"

    async def test_aap_protected_false_value_does_not_block(self):
        """aap-protected:false does NOT trigger the emergency brake."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        resource_tags = {"aap-protected": "false"}
        cosmos = _make_cosmos_client(daily_count=0)
        topo = _make_topology_client(total_affected=0)

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[_make_policy(require_slo_healthy=False)]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags=resource_tags,
                topology_client=topo,
                cosmos_client=cosmos,
                credential=None,
            )

        assert auto_approved is True
        assert policy_id == _POLICY_ID

    # -----------------------------------------------------------------------
    # 2. No matching policy
    # -----------------------------------------------------------------------
    async def test_no_matching_policy(self):
        """Returns (False, None, 'no_matching_policy') when no enabled policy exists."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={},
                topology_client=None,
                cosmos_client=None,
                credential=None,
            )

        assert auto_approved is False
        assert policy_id is None
        assert reason == "no_matching_policy"

    # -----------------------------------------------------------------------
    # 3. All guards pass → auto-approved
    # -----------------------------------------------------------------------
    async def test_policy_match_all_guards_pass(self):
        """Returns (True, policy_id, 'policy_match') when all guards pass."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        cosmos = _make_cosmos_client(daily_count=5)   # under cap of 20
        topo = _make_topology_client(total_affected=3)  # under cap of 10

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[_make_policy(require_slo_healthy=False)]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={"tier": "dev"},
                topology_client=topo,
                cosmos_client=cosmos,
                credential=None,
            )

        assert auto_approved is True
        assert policy_id == _POLICY_ID
        assert reason == "policy_match"

    # -----------------------------------------------------------------------
    # 4. Tag filter mismatch
    # -----------------------------------------------------------------------
    async def test_tag_filter_mismatch(self):
        """Policy requires tier:dev but resource has tier:prod — skips that policy."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        policy = _make_policy(
            resource_tag_filter={"tier": "dev"},
            require_slo_healthy=False,
        )
        cosmos = _make_cosmos_client(daily_count=0)
        topo = _make_topology_client(total_affected=0)

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[policy]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={"tier": "prod"},   # mismatch
                topology_client=topo,
                cosmos_client=cosmos,
                credential=None,
            )

        assert auto_approved is False
        assert reason == "guards_failed"

    # -----------------------------------------------------------------------
    # 5. Blast radius exceeds cap
    # -----------------------------------------------------------------------
    async def test_blast_radius_exceeds_cap(self):
        """topology returns blast_radius > max_blast_radius — skips policy."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        policy = _make_policy(max_blast_radius=5, require_slo_healthy=False)
        cosmos = _make_cosmos_client(daily_count=0)
        topo = _make_topology_client(total_affected=6)  # exceeds cap of 5

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[policy]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={},
                topology_client=topo,
                cosmos_client=cosmos,
                credential=None,
            )

        assert auto_approved is False
        assert reason == "guards_failed"

    # -----------------------------------------------------------------------
    # 6. No topology client → blast radius passes (size=0)
    # -----------------------------------------------------------------------
    async def test_blast_radius_no_topology(self):
        """topology_client=None means blast_radius_size=0, check always passes."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        cosmos = _make_cosmos_client(daily_count=0)
        policy = _make_policy(max_blast_radius=1, require_slo_healthy=False)

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[policy]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={},
                topology_client=None,  # no topology client
                cosmos_client=cosmos,
                credential=None,
            )

        assert auto_approved is True
        assert policy_id == _POLICY_ID

    # -----------------------------------------------------------------------
    # 7. Daily cap exceeded
    # -----------------------------------------------------------------------
    async def test_daily_cap_exceeded(self):
        """Cosmos returns count >= max_daily_executions — skips policy."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        policy = _make_policy(max_daily_executions=10, require_slo_healthy=False)
        cosmos = _make_cosmos_client(daily_count=10)  # exactly at cap
        topo = _make_topology_client(total_affected=0)

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[policy]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={},
                topology_client=topo,
                cosmos_client=cosmos,
                credential=None,
            )

        assert auto_approved is False
        assert reason == "guards_failed"

    # -----------------------------------------------------------------------
    # 8. Daily cap not exceeded
    # -----------------------------------------------------------------------
    async def test_daily_cap_not_exceeded(self):
        """Cosmos returns count < max_daily_executions — passes the cap guard."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        policy = _make_policy(max_daily_executions=10, require_slo_healthy=False)
        cosmos = _make_cosmos_client(daily_count=9)  # one under cap
        topo = _make_topology_client(total_affected=0)

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[policy]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={},
                topology_client=topo,
                cosmos_client=cosmos,
                credential=None,
            )

        assert auto_approved is True
        assert policy_id == _POLICY_ID

    # -----------------------------------------------------------------------
    # 9. SLO health unavailable blocks
    # -----------------------------------------------------------------------
    async def test_slo_health_unavailable(self):
        """Resource Health returns Unavailable — skips policy when require_slo_healthy=True."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        policy = _make_policy(require_slo_healthy=True)
        cosmos = _make_cosmos_client(daily_count=0)
        topo = _make_topology_client(total_affected=0)
        mock_credential = MagicMock()

        with (
            patch(
                "services.api_gateway.policy_engine._query_matching_policies",
                new=AsyncMock(return_value=[policy]),
            ),
            patch(
                "services.api_gateway.policy_engine._check_resource_health",
                new=AsyncMock(return_value=False),  # Unavailable
            ),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={},
                topology_client=topo,
                cosmos_client=cosmos,
                credential=mock_credential,
            )

        assert auto_approved is False
        assert reason == "guards_failed"

    # -----------------------------------------------------------------------
    # 10. SLO health check disabled
    # -----------------------------------------------------------------------
    async def test_slo_health_check_disabled(self):
        """require_slo_healthy=False — SLO gate skipped regardless of health status."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        policy = _make_policy(require_slo_healthy=False)
        cosmos = _make_cosmos_client(daily_count=0)
        topo = _make_topology_client(total_affected=0)

        # _check_resource_health should NOT be called at all
        with (
            patch(
                "services.api_gateway.policy_engine._query_matching_policies",
                new=AsyncMock(return_value=[policy]),
            ),
            patch(
                "services.api_gateway.policy_engine._check_resource_health",
                new=AsyncMock(return_value=False),  # would block if called
            ) as mock_health,
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={},
                topology_client=topo,
                cosmos_client=cosmos,
                credential=None,  # also None — no credential
            )

        assert auto_approved is True
        assert policy_id == _POLICY_ID
        mock_health.assert_not_called()

    # -----------------------------------------------------------------------
    # 11. First policy wins
    # -----------------------------------------------------------------------
    async def test_first_policy_wins(self):
        """Two policies match; first one passes all guards — returns first policy's ID."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        policy_a = _make_policy(policy_id="pol-aaaa", require_slo_healthy=False)
        policy_b = _make_policy(policy_id="pol-bbbb", require_slo_healthy=False)

        cosmos = _make_cosmos_client(daily_count=0)
        topo = _make_topology_client(total_affected=0)

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[policy_a, policy_b]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={},
                topology_client=topo,
                cosmos_client=cosmos,
                credential=None,
            )

        assert auto_approved is True
        assert policy_id == "pol-aaaa"   # first policy wins

    # -----------------------------------------------------------------------
    # 12. Exception in guard treated as guard failure (conservative)
    # -----------------------------------------------------------------------
    async def test_exception_in_guard_rejects(self):
        """Exception during blast-radius check is treated as guard failure — no auto-approve."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        policy = _make_policy(require_slo_healthy=False)
        cosmos = _make_cosmos_client(daily_count=0)

        # topology_client raises on get_blast_radius
        mock_topo = MagicMock()
        mock_topo.get_blast_radius.side_effect = RuntimeError("topology service unavailable")

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[policy]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={},
                topology_client=mock_topo,
                cosmos_client=cosmos,
                credential=None,
            )

        assert auto_approved is False
        assert reason == "guards_failed"

    # -----------------------------------------------------------------------
    # 13. Second policy succeeds when first fails a guard
    # -----------------------------------------------------------------------
    async def test_second_policy_used_when_first_fails(self):
        """First policy fails tag filter; second policy (no filter) passes — returns second."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        policy_a = _make_policy(
            policy_id="pol-strict",
            resource_tag_filter={"environment": "dev"},
            require_slo_healthy=False,
        )
        policy_b = _make_policy(
            policy_id="pol-loose",
            resource_tag_filter={},  # no tag filter
            require_slo_healthy=False,
        )

        cosmos = _make_cosmos_client(daily_count=0)
        topo = _make_topology_client(total_affected=0)

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[policy_a, policy_b]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={"environment": "prod"},  # fails policy_a tag filter
                topology_client=topo,
                cosmos_client=cosmos,
                credential=None,
            )

        assert auto_approved is True
        assert policy_id == "pol-loose"

    # -----------------------------------------------------------------------
    # 14. No cosmos client — daily cap check skipped (passes)
    # -----------------------------------------------------------------------
    async def test_daily_cap_no_cosmos_passes(self):
        """cosmos_client=None — daily cap check is skipped and treated as pass."""
        from services.api_gateway.policy_engine import evaluate_auto_approval

        policy = _make_policy(max_daily_executions=1, require_slo_healthy=False)
        topo = _make_topology_client(total_affected=0)

        with patch(
            "services.api_gateway.policy_engine._query_matching_policies",
            new=AsyncMock(return_value=[policy]),
        ):
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=_ACTION_CLASS,
                resource_id=_RESOURCE_ID,
                resource_tags={},
                topology_client=topo,
                cosmos_client=None,  # no cosmos
                credential=None,
            )

        assert auto_approved is True
        assert policy_id == _POLICY_ID
