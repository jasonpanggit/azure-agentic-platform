"""Tests for remediation rate limiting and safety guards (REMEDI-005, REMEDI-006)."""
import pytest
from unittest.mock import patch


class TestRateLimiting:
    """Tests for remediation action rate limiting and safety guards."""

    def test_within_limit_allowed(self, client):
        """5 remediation actions within 1 minute are all allowed."""
        from services.api_gateway.rate_limiter import RateLimiter

        limiter = RateLimiter(max_per_minute=5)

        # 5 checks+records should all succeed without exception
        for _ in range(5):
            limiter.check(agent_name="compute", subscription_id="sub-1")
            limiter.record(agent_name="compute", subscription_id="sub-1")

    def test_exceeds_limit_rejected(self, client):
        """6th remediation action within 1 minute is rejected with RateLimitExceededError."""
        from services.api_gateway.rate_limiter import RateLimiter, RateLimitExceededError

        limiter = RateLimiter(max_per_minute=5)

        # Fill the bucket to capacity
        for _ in range(5):
            limiter.check(agent_name="compute", subscription_id="sub-1")
            limiter.record(agent_name="compute", subscription_id="sub-1")

        # 6th check should raise
        with pytest.raises(RateLimitExceededError):
            limiter.check(agent_name="compute", subscription_id="sub-1")

    def test_protected_tag_blocks_action(self, client):
        """Resource tagged protected:true raises ProtectedResourceError."""
        from services.api_gateway.rate_limiter import ProtectedResourceError, check_protected_tag

        with pytest.raises(ProtectedResourceError):
            check_protected_tag({"protected": "true"})

    def test_prod_requires_scope_confirmation(self, client):
        """Production subscription without scope_confirmed=True raises ValueError."""
        import asyncio
        from services.api_gateway.approvals import process_approval_decision

        prod_sub_id = "sub-prod-001"
        resource_id = f"/subscriptions/{prod_sub_id}/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1"

        mock_record = {
            "id": "appr_test-001",
            "action_id": "act_test-001",
            "thread_id": "thread-test-001",
            "incident_id": "inc-test-001",
            "agent_name": "compute",
            "status": "pending",
            "risk_level": "high",
            "proposed_at": "2026-03-27T14:30:00Z",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "decided_at": None,
            "decided_by": None,
            "executed_at": None,
            "abort_reason": None,
            "resource_snapshot": {
                "resource_id": resource_id,
                "provisioning_state": "Succeeded",
                "tags": {},
                "resource_health": "Available",
                "snapshot_hash": "a" * 64,
            },
            "proposal": {
                "description": "Restart prod VM",
                "target_resources": [resource_id],
                "estimated_impact": "downtime",
                "risk_level": "high",
                "reversibility": "reversible",
                "action_type": "restart",
            },
            "_etag": '"etag-001"',
        }

        mock_container = type("C", (), {
            "read_item": lambda self, item, partition_key: mock_record,
            "replace_item": lambda self, *a, **kw: mock_record,
        })()

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_container,
        ), patch.dict("os.environ", {"PROD_SUBSCRIPTION_IDS": prod_sub_id}):
            with pytest.raises(ValueError) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    process_approval_decision(
                        approval_id="appr_test-001",
                        thread_id="thread-test-001",
                        decision="approved",
                        decided_by="operator@contoso.com",
                        scope_confirmed=None,  # not confirmed
                    )
                )

        assert "scope_confirmation" in str(exc_info.value)
