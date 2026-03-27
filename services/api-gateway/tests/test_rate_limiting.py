"""Stub: Rate limiting and safety guard tests (REMEDI-005, REMEDI-006)."""
import pytest


class TestRateLimiting:
    """Tests for remediation action rate limiting and safety guards."""

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_within_limit_allowed(self, client):
        """5 remediation actions within 1 minute are all allowed."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_exceeds_limit_rejected(self, client):
        """6th remediation action within 1 minute is rejected with 429."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_protected_tag_blocks_action(self, client):
        """Resource tagged protected:true returns 403 Forbidden."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_prod_requires_scope_confirmation(self, client):
        """Production subscription without scope_confirmed returns 403 Forbidden."""
        pass
