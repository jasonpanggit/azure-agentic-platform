from __future__ import annotations
"""Phase 33 smoke tests -- evaluation package importable and wired."""

import pytest


class TestPhase33Smoke:
    def test_custom_evaluators_importable(self):
        from services.api_gateway.evaluation.custom_evaluators import (
            DiagnosisGroundingEvaluator,
            RemediationSafetyEvaluator,
            SopAdherenceEvaluator,
            TriageCompletenessEvaluator,
        )
        assert all([SopAdherenceEvaluator, TriageCompletenessEvaluator,
                    RemediationSafetyEvaluator, DiagnosisGroundingEvaluator])

    def test_agent_evaluators_importable(self):
        from services.api_gateway.evaluation.agent_evaluators import (
            build_eval_config,
            extract_eval_score,
        )
        assert build_eval_config and extract_eval_score

    def test_eval_pipeline_importable(self):
        from services.api_gateway.evaluation.eval_pipeline import run_eval_pipeline
        assert run_eval_pipeline

    def test_sample_trace_file_exists(self):
        import os
        assert os.path.exists("tests/eval/agent_traces_sample.jsonl")

    def test_eval_workflow_file_exists(self):
        import os
        assert os.path.exists(".github/workflows/agent-eval.yml")

    def test_all_4_evaluators_produce_scores(self):
        from services.api_gateway.evaluation.custom_evaluators import (
            DiagnosisGroundingEvaluator,
            RemediationSafetyEvaluator,
            SopAdherenceEvaluator,
            TriageCompletenessEvaluator,
        )

        trace = {
            "conversation": [
                {
                    "role": "assistant",
                    "content": "Triage complete.",
                    "tool_calls": [
                        {"name": "query_activity_log"},
                        {"name": "query_resource_health"},
                        {"name": "query_log_analytics"},
                        {"name": "sop_notify"},
                        {"name": "propose_vm_restart"},
                    ],
                }
            ],
            "sop_steps": ["query_activity_log", "query_resource_health", "sop_notify"],
        }

        for EvalClass in [SopAdherenceEvaluator, TriageCompletenessEvaluator,
                          RemediationSafetyEvaluator, DiagnosisGroundingEvaluator]:
            evaluator = EvalClass()
            result = evaluator(trace)
            assert isinstance(result, dict)
            assert len(result) == 1
            score = list(result.values())[0]
            assert isinstance(score, float)
