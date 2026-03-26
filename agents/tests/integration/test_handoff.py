"""Integration tests for HandoffOrchestrator routing (AGENT-001).

Wave 0 stubs — implementations in Plan 02-05.
"""
import pytest


@pytest.mark.integration
class TestHandoffOrchestrator:
    @pytest.mark.skip(reason="Wave 4 — depends on agent implementations (02-04)")
    def test_incident_routes_to_correct_domain_agent(self):
        """POST synthetic incident -> Orchestrator routes to compute-agent."""
        pass

    @pytest.mark.skip(reason="Wave 4 — depends on agent implementations (02-04)")
    def test_cross_domain_rerouting(self):
        """Domain agent returns needs_cross_domain -> Orchestrator re-routes."""
        pass

    @pytest.mark.skip(reason="Wave 4 — depends on agent implementations (02-04)")
    def test_handoff_completes_within_5_seconds(self):
        """Full handoff chain completes within 5s end-to-end."""
        pass
