"""Stub: Approval lifecycle tests (REMEDI-002, REMEDI-003, REMEDI-004, REMEDI-005, REMEDI-006)."""
import pytest


class TestApprovalLifecycle:
    """Tests for the human-in-the-loop approval lifecycle (D-12 schema)."""

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_create_pending_approval(self, mock_cosmos_approvals, sample_approval_record):
        """Creates approval record with status=pending."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_approve_pending_sets_approved(self, client, mock_cosmos_approvals):
        """Pending approval transitions to approved status."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_reject_pending_sets_rejected(self, client, mock_cosmos_approvals):
        """Pending approval transitions to rejected status."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_expired_approval_returns_410(self, client, mock_cosmos_approvals):
        """Expired proposal returns 410 Gone."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_expired_never_executed(self, mock_cosmos_approvals):
        """Approved record past expires_at is never executed."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_thread_not_polled_after_park(self, mock_foundry_client):
        """create_run not called after proposal is parked awaiting approval."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_thread_resume_on_webhook(self, client, mock_foundry_client, mock_cosmos_approvals):
        """Approval webhook resumes the Foundry thread."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_etag_concurrency_on_write(self, mock_cosmos_approvals):
        """replace_item is called with match_condition for ETag optimistic concurrency."""
        pass
