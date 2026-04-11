"""Tests for eval_pipeline.py -- CI quality gate runner."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRunEvalPipeline:
    """Verify run_eval_pipeline applies quality gates correctly."""

    @patch("services.api_gateway.evaluation.eval_pipeline.evaluate")
    def test_passes_when_all_scores_above_threshold(self, mock_evaluate):
        mock_evaluate.return_value = {
            "metrics": {
                "task_adherence.task_adherence": 4.5,
                "triage_completeness.triage_completeness": 1.0,
                "remediation_safety.remediation_safety": 1.0,
                "sop_adherence.sop_adherence": 4.2,
            }
        }

        from services.api_gateway.evaluation.eval_pipeline import run_eval_pipeline

        # Should not raise
        results = run_eval_pipeline(
            data_path="tests/eval/agent_traces_sample.jsonl",
            model_config=MagicMock(),
            dry_run=True,
        )
        assert results["passed"] is True

    @patch("services.api_gateway.evaluation.eval_pipeline.evaluate")
    def test_fails_when_task_adherence_below_threshold(self, mock_evaluate):
        mock_evaluate.return_value = {
            "metrics": {
                "task_adherence.task_adherence": 2.0,  # below 4.0 threshold
                "triage_completeness.triage_completeness": 1.0,
            }
        }

        from services.api_gateway.evaluation.eval_pipeline import run_eval_pipeline

        results = run_eval_pipeline(
            data_path="tests/eval/agent_traces_sample.jsonl",
            model_config=MagicMock(),
            dry_run=True,
        )
        assert results["passed"] is False
        assert "task_adherence" in str(results.get("failures", []))

    @patch("services.api_gateway.evaluation.eval_pipeline.evaluate")
    def test_fails_when_triage_completeness_below_threshold(self, mock_evaluate):
        mock_evaluate.return_value = {
            "metrics": {
                "task_adherence.task_adherence": 4.5,
                "triage_completeness.triage_completeness": 0.7,  # below 0.95
            }
        }

        from services.api_gateway.evaluation.eval_pipeline import run_eval_pipeline

        results = run_eval_pipeline(
            data_path="tests/eval/agent_traces_sample.jsonl",
            model_config=MagicMock(),
            dry_run=True,
        )
        assert results["passed"] is False

    @patch("services.api_gateway.evaluation.eval_pipeline.evaluate")
    def test_remediation_safety_gate(self, mock_evaluate):
        mock_evaluate.return_value = {
            "metrics": {
                "task_adherence.task_adherence": 4.2,
                "triage_completeness.triage_completeness": 0.96,
                "remediation_safety.remediation_safety": 0.5,  # below 1.0
            }
        }

        from services.api_gateway.evaluation.eval_pipeline import run_eval_pipeline

        results = run_eval_pipeline(
            data_path="tests/eval/agent_traces_sample.jsonl",
            model_config=MagicMock(),
            dry_run=True,
        )
        assert results["passed"] is False
