"""Integration tests for domain agent triage workflow (TRIAGE-001 through TRIAGE-004).

Wave 0 stubs — implementations in Plan 02-05.
"""
import pytest


@pytest.mark.integration
class TestTriageWorkflow:
    @pytest.mark.skip(reason="Wave 4 — depends on agent implementations (02-04)")
    def test_orchestrator_classifies_by_domain(self):
        """Orchestrator classifies incident by domain with typed handoff (TRIAGE-001)."""
        pass

    @pytest.mark.skip(reason="Wave 4 — depends on agent implementations (02-04)")
    def test_domain_agent_queries_log_analytics_and_resource_health(self):
        """Domain agent queries both Log Analytics AND Resource Health (TRIAGE-002)."""
        pass

    @pytest.mark.skip(reason="Wave 4 — depends on agent implementations (02-04)")
    def test_domain_agent_checks_activity_log(self):
        """Domain agent checks Activity Log for prior 2h changes (TRIAGE-003)."""
        pass

    @pytest.mark.skip(reason="Wave 4 — depends on agent implementations (02-04)")
    def test_diagnosis_contains_hypothesis_evidence_confidence(self):
        """Diagnosis includes hypothesis, evidence, and confidence_score (TRIAGE-004)."""
        pass
