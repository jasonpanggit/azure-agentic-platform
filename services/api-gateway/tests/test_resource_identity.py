"""Stub: Resource Identity Certainty tests (REMEDI-004)."""
import pytest


class TestResourceIdentity:
    """Tests for the 2-signal pre-execution resource identity check."""

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_snapshot_hash_is_sha256_64_chars(self, sample_approval_record):
        """snapshot_hash is a 64-character SHA-256 hex string."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_identity_match_returns_true(self, mock_arm_client, sample_approval_record):
        """Identical resource state returns True for identity check."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_diverged_state_returns_false(self, mock_arm_client, sample_approval_record):
        """Changed resource tags cause identity check to return False."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_stale_approval_aborts_execution(self, mock_cosmos_approvals, mock_arm_client):
        """Diverged state sets Cosmos record abort_reason = 'stale_approval'."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_snapshot_has_minimum_2_signals(self, sample_approval_record):
        """resource_snapshot contains at least resource_id and snapshot_hash."""
        pass
