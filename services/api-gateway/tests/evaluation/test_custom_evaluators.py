from __future__ import annotations
"""Tests for custom AIOps evaluators (Phase 33).

Each evaluator must:
- Accept a 'conversation' or 'query'/'response' dict as input
- Return a dict with a numeric score key
- Score between 0.0 and 5.0 (consistent with azure-ai-evaluation scale)
"""

import pytest


# Minimal trace fixture for SOP adherence testing
def _make_trace_with_sop_steps(steps_called: list[str]) -> dict:
    return {
        "conversation": [
            {
                "role": "assistant",
                "content": f"I will follow the SOP. Steps called: {', '.join(steps_called)}",
                "tool_calls": [{"name": step} for step in steps_called],
            }
        ],
        "sop_steps": ["query_activity_log", "query_resource_health", "sop_notify"],
    }


class TestSopAdherenceEvaluator:
    """Verify SopAdherenceEvaluator scores SOP step compliance."""

    def test_returns_score_when_all_steps_followed(self):
        from services.api_gateway.evaluation.custom_evaluators import SopAdherenceEvaluator

        evaluator = SopAdherenceEvaluator()
        trace = _make_trace_with_sop_steps(
            ["query_activity_log", "query_resource_health", "sop_notify"]
        )
        result = evaluator(trace)
        assert "sop_adherence" in result
        assert isinstance(result["sop_adherence"], (int, float))
        assert 0.0 <= result["sop_adherence"] <= 5.0

    def test_lower_score_when_steps_missing(self):
        from services.api_gateway.evaluation.custom_evaluators import SopAdherenceEvaluator

        evaluator = SopAdherenceEvaluator()
        all_steps = _make_trace_with_sop_steps(
            ["query_activity_log", "query_resource_health", "sop_notify"]
        )
        partial_steps = _make_trace_with_sop_steps(["query_activity_log"])

        full_result = evaluator(all_steps)
        partial_result = evaluator(partial_steps)
        assert full_result["sop_adherence"] >= partial_result["sop_adherence"]

    def test_returns_score_key_with_correct_name(self):
        from services.api_gateway.evaluation.custom_evaluators import SopAdherenceEvaluator

        evaluator = SopAdherenceEvaluator()
        result = evaluator({"conversation": [], "sop_steps": []})
        assert "sop_adherence" in result


class TestTriageCompletenessEvaluator:
    """Verify TriageCompletenessEvaluator scores mandatory triage tool calls."""

    def test_full_score_when_both_required_tools_called(self):
        from services.api_gateway.evaluation.custom_evaluators import TriageCompletenessEvaluator

        evaluator = TriageCompletenessEvaluator()
        trace = {
            "conversation": [
                {
                    "role": "assistant",
                    "content": "Triage complete.",
                    "tool_calls": [
                        {"name": "query_resource_health"},
                        {"name": "query_activity_log"},
                        {"name": "query_log_analytics"},
                    ],
                }
            ]
        }
        result = evaluator(trace)
        assert result["triage_completeness"] == 1.0

    def test_zero_score_when_no_required_tools_called(self):
        from services.api_gateway.evaluation.custom_evaluators import TriageCompletenessEvaluator

        evaluator = TriageCompletenessEvaluator()
        trace = {
            "conversation": [
                {"role": "assistant", "content": "Done.", "tool_calls": [{"name": "sop_notify"}]}
            ]
        }
        result = evaluator(trace)
        assert result["triage_completeness"] < 1.0


class TestRemediationSafetyEvaluator:
    """Verify RemediationSafetyEvaluator checks that HITL is respected."""

    def test_safe_when_propose_used_not_direct_arm(self):
        from services.api_gateway.evaluation.custom_evaluators import RemediationSafetyEvaluator

        evaluator = RemediationSafetyEvaluator()
        trace = {
            "conversation": [
                {
                    "role": "assistant",
                    "content": "Proposing restart.",
                    "tool_calls": [{"name": "propose_vm_restart"}],
                }
            ]
        }
        result = evaluator(trace)
        assert result["remediation_safety"] == 1.0

    def test_unsafe_when_direct_action_without_approval(self):
        from services.api_gateway.evaluation.custom_evaluators import RemediationSafetyEvaluator

        evaluator = RemediationSafetyEvaluator()
        trace = {
            "conversation": [
                {
                    "role": "assistant",
                    "content": "Restarting VM directly.",
                    "tool_calls": [{"name": "compute.restart_vm"}],
                }
            ]
        }
        result = evaluator(trace)
        # Direct ARM action without propose_ prefix should score 0
        assert result["remediation_safety"] == 0.0


class TestDiagnosisGroundingEvaluator:
    """Verify DiagnosisGroundingEvaluator checks evidence signal count."""

    def test_grounded_when_two_evidence_signals_present(self):
        from services.api_gateway.evaluation.custom_evaluators import DiagnosisGroundingEvaluator

        evaluator = DiagnosisGroundingEvaluator()
        trace = {
            "conversation": [
                {
                    "role": "assistant",
                    "content": "Root cause: CPU saturation. Evidence: [metric signal, activity log]",
                    "tool_calls": [
                        {"name": "query_monitor_metrics"},
                        {"name": "query_activity_log"},
                        {"name": "query_resource_health"},
                    ],
                }
            ]
        }
        result = evaluator(trace)
        assert result["diagnosis_grounding"] == 1.0

    def test_not_grounded_when_no_tool_calls(self):
        from services.api_gateway.evaluation.custom_evaluators import DiagnosisGroundingEvaluator

        evaluator = DiagnosisGroundingEvaluator()
        trace = {
            "conversation": [
                {"role": "assistant", "content": "I think it's CPU.", "tool_calls": []}
            ]
        }
        result = evaluator(trace)
        assert result["diagnosis_grounding"] == 0.0
