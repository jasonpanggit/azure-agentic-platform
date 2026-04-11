"""Tests for agent_evaluators.py -- standard azure-ai-evaluation wrappers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestBuildEvalConfig:
    """Verify build_eval_config returns correct evaluator dict."""

    def test_returns_dict_with_standard_evaluators(self):
        from services.api_gateway.evaluation.agent_evaluators import build_eval_config

        mock_model_config = MagicMock()
        mock_credential = MagicMock()
        mock_project_config = MagicMock()

        with patch("services.api_gateway.evaluation.agent_evaluators.TaskAdherenceEvaluator"), \
             patch("services.api_gateway.evaluation.agent_evaluators.ToolCallAccuracyEvaluator"), \
             patch("services.api_gateway.evaluation.agent_evaluators.IntentResolutionEvaluator"):

            config = build_eval_config(
                model_config=mock_model_config,
                credential=mock_credential,
                azure_ai_project=mock_project_config,
                include_safety=False,
            )

        assert "task_adherence" in config
        assert "tool_accuracy" in config
        assert "sop_adherence" in config
        assert "triage_completeness" in config

    def test_includes_safety_evaluators_when_flag_set(self):
        from services.api_gateway.evaluation.agent_evaluators import build_eval_config

        with patch("services.api_gateway.evaluation.agent_evaluators.TaskAdherenceEvaluator"), \
             patch("services.api_gateway.evaluation.agent_evaluators.ToolCallAccuracyEvaluator"), \
             patch("services.api_gateway.evaluation.agent_evaluators.IntentResolutionEvaluator"), \
             patch("services.api_gateway.evaluation.agent_evaluators.ContentSafetyEvaluator"), \
             patch("services.api_gateway.evaluation.agent_evaluators.IndirectAttackEvaluator"):

            config = build_eval_config(
                model_config=MagicMock(),
                credential=MagicMock(),
                azure_ai_project=MagicMock(),
                include_safety=True,
            )

        assert "content_safety" in config
        assert "indirect_attack" in config


class TestExtractEvalScore:
    """Verify safe metric key extraction with fallback chain."""

    def test_extracts_prefixed_key(self):
        from services.api_gateway.evaluation.agent_evaluators import extract_eval_score

        metrics = {"task_adherence.task_adherence": 4.2}
        score = extract_eval_score(metrics, "task_adherence")
        assert score == 4.2

    def test_extracts_score_suffix_key(self):
        from services.api_gateway.evaluation.agent_evaluators import extract_eval_score

        metrics = {"task_adherence.score": 3.8}
        score = extract_eval_score(metrics, "task_adherence")
        assert score == 3.8

    def test_extracts_flat_key(self):
        from services.api_gateway.evaluation.agent_evaluators import extract_eval_score

        metrics = {"task_adherence": 4.0}
        score = extract_eval_score(metrics, "task_adherence")
        assert score == 4.0

    def test_returns_none_when_key_missing(self):
        from services.api_gateway.evaluation.agent_evaluators import extract_eval_score

        score = extract_eval_score({}, "nonexistent_metric")
        assert score is None
