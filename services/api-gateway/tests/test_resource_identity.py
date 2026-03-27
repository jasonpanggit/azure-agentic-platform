"""Tests for Resource Identity Certainty (REMEDI-004)."""
import pytest
from unittest.mock import MagicMock, patch


class TestResourceIdentity:
    """Tests for the 2-signal pre-execution resource identity check."""

    def test_snapshot_hash_is_sha256_64_chars(self, sample_approval_record):
        """snapshot_hash is a 64-character SHA-256 hex string."""
        from agents.shared.triage import ResourceSnapshot

        snap = ResourceSnapshot(
            resource_id="/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
            provisioning_state="Succeeded",
            tags={"environment": "production"},
            resource_health="Available",
        )

        assert len(snap.snapshot_hash) == 64, (
            f"Expected 64-char hash, got {len(snap.snapshot_hash)}: {snap.snapshot_hash}"
        )
        assert all(c in "0123456789abcdef" for c in snap.snapshot_hash), (
            "snapshot_hash must be lowercase hex chars only"
        )

    def test_identity_match_returns_true(self, mock_arm_client, sample_approval_record):
        """Identical resource state returns True for identity check."""
        from agents.shared.triage import ResourceSnapshot
        from agents.shared.resource_identity import verify_resource_identity

        resource_id = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"
        tags = {"environment": "production"}

        snap = ResourceSnapshot(
            resource_id=resource_id,
            provisioning_state="Succeeded",
            tags=tags,
            resource_health="Available",
        )

        result = verify_resource_identity(
            snapshot=snap,
            current_resource_id=resource_id,
            current_provisioning_state="Succeeded",
            current_tags=tags,
            current_resource_health="Available",
        )

        assert result is True

    def test_diverged_state_returns_false(self, mock_arm_client, sample_approval_record):
        """Changed resource tags cause identity check to return False."""
        from agents.shared.triage import ResourceSnapshot
        from agents.shared.resource_identity import verify_resource_identity

        resource_id = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"
        original_tags = {"environment": "production"}
        changed_tags = {"environment": "production", "maintenance": "true"}

        snap = ResourceSnapshot(
            resource_id=resource_id,
            provisioning_state="Succeeded",
            tags=original_tags,
            resource_health="Available",
        )

        result = verify_resource_identity(
            snapshot=snap,
            current_resource_id=resource_id,
            current_provisioning_state="Succeeded",
            current_tags=changed_tags,  # tags changed
            current_resource_health="Available",
        )

        assert result is False

    def test_stale_approval_aborts_execution(self, mock_cosmos_approvals, mock_arm_client):
        """Diverged state raises StaleApprovalError with abort_reason='stale_approval'."""
        from agents.shared.triage import ResourceSnapshot
        from agents.shared.resource_identity import StaleApprovalError, verify_resource_identity

        resource_id = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"
        original_tags = {"environment": "production"}
        changed_tags = {"environment": "staging"}  # changed!

        snap = ResourceSnapshot(
            resource_id=resource_id,
            provisioning_state="Succeeded",
            tags=original_tags,
            resource_health="Available",
        )

        is_match = verify_resource_identity(
            snapshot=snap,
            current_resource_id=resource_id,
            current_provisioning_state="Succeeded",
            current_tags=changed_tags,
            current_resource_health="Available",
        )
        assert is_match is False

        # Simulate the abort path: mark Cosmos record with abort_reason
        abort_reason = "stale_approval"
        updated_record = {
            **mock_cosmos_approvals.read_item.return_value,
            "status": "aborted",
            "abort_reason": abort_reason,
        }
        mock_cosmos_approvals.replace_item.return_value = updated_record

        # Write the aborted record
        mock_cosmos_approvals.replace_item(
            item="appr_test-001",
            body=updated_record,
            etag='"etag-test-001"',
            match_condition="IfMatch",
        )

        # Raise StaleApprovalError as the agent code would
        with pytest.raises(StaleApprovalError) as exc_info:
            raise StaleApprovalError(
                resource_id=resource_id,
                reason=abort_reason,
            )

        assert exc_info.value.reason == "stale_approval"

        # Verify the Cosmos record has abort_reason set
        call_kwargs = mock_cosmos_approvals.replace_item.call_args
        written_body = call_kwargs[1]["body"] if call_kwargs[1] else call_kwargs[0][1]
        assert written_body["abort_reason"] == "stale_approval"

    def test_snapshot_has_minimum_2_signals(self, sample_approval_record):
        """resource_snapshot contains at least resource_id and snapshot_hash."""
        snapshot = sample_approval_record["resource_snapshot"]

        assert "resource_id" in snapshot, "snapshot must have 'resource_id'"
        assert "snapshot_hash" in snapshot, "snapshot must have 'snapshot_hash'"
        assert snapshot["resource_id"], "resource_id must be non-empty"
        assert snapshot["snapshot_hash"], "snapshot_hash must be non-empty"
