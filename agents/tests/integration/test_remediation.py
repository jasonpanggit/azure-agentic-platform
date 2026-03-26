"""Integration tests for remediation safety (REMEDI-001).

Wave 0 stubs — implementations in Plan 02-05.
"""
import pytest


@pytest.mark.integration
class TestRemediationSafety:
    @pytest.mark.skip(reason="Wave 4 — depends on agent implementations (02-04)")
    def test_sre_agent_generates_proposal_without_executing(self):
        """SRE agent proposes remediation, no ARM writes made (REMEDI-001)."""
        pass

    @pytest.mark.skip(reason="Wave 4 — depends on agent implementations (02-04)")
    def test_proposal_includes_required_fields(self):
        """Proposal includes description, target resources, impact, risk, reversibility."""
        pass
