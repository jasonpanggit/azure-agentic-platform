"""Stub: Audit trail tests (AUDIT-002, AUDIT-004)."""
import pytest


class TestAuditTrail:
    """Tests for dual-write audit trail (Cosmos DB + OneLake)."""

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-05")
    def test_approval_written_to_cosmos(self, mock_cosmos_approvals):
        """Cosmos create_item is called when an approval record is created."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-05")
    def test_approval_written_to_onelake(self, mock_cosmos_approvals):
        """OneLake write fires after Cosmos write for audit durability."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-05")
    def test_onelake_failure_non_blocking(self, mock_cosmos_approvals):
        """OneLake write error is logged but does not raise an exception."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-05")
    def test_audit_query_filters_by_agent(self, client):
        """Audit log query with agent=compute returns only compute actions."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-05")
    def test_audit_query_filters_by_time_range(self, client):
        """Audit log query with from/to parameters applies time range filter."""
        pass
