"""Standard azure-ai-evaluation agentic evaluator configuration (Phase 33).

Provides build_eval_config() for assembling the evaluator dict used in
CI eval pipeline and extract_eval_score() for safe metric key access.

Note on metric key format (azure-ai-evaluation SDK):
    The SDK returns metrics with evaluator-name prefix:
    e.g. "task_adherence.task_adherence" or "task_adherence.score"
    Use extract_eval_score() to safely access these with fallback.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from azure.ai.evaluation import (
        ContentSafetyEvaluator,
        GroundednessEvaluator,
        IndirectAttackEvaluator,
        IntentResolutionEvaluator,
        TaskAdherenceEvaluator,
        ToolCallAccuracyEvaluator,
    )
except ImportError:
    # Azure AI evaluation SDK not installed -- CI will fail appropriately
    TaskAdherenceEvaluator = None  # type: ignore[assignment,misc]
    ToolCallAccuracyEvaluator = None  # type: ignore[assignment,misc]
    IntentResolutionEvaluator = None  # type: ignore[assignment,misc]
    ContentSafetyEvaluator = None  # type: ignore[assignment,misc]
    IndirectAttackEvaluator = None  # type: ignore[assignment,misc]
    GroundednessEvaluator = None  # type: ignore[assignment,misc]

from services.api_gateway.evaluation.custom_evaluators import (
    DiagnosisGroundingEvaluator,
    RemediationSafetyEvaluator,
    SopAdherenceEvaluator,
    TriageCompletenessEvaluator,
)


def build_eval_config(
    model_config: Any,
    credential: Any,
    azure_ai_project: Any,
    include_safety: bool = False,
) -> dict[str, Any]:
    """Build the evaluator configuration dict for azure-ai-evaluation.evaluate().

    Args:
        model_config: AzureOpenAIModelConfiguration for LLM-based evaluators.
        credential: Azure credential for safety evaluators.
        azure_ai_project: Azure AI project config dict.
        include_safety: Whether to include ContentSafety and IndirectAttack evaluators.
            Adds ~30s per evaluation run. Enable in CI but keep optional for fast dev runs.

    Returns:
        Dict mapping evaluator names to evaluator instances.

    Raises:
        ImportError: If azure-ai-evaluation is not installed.
    """
    if TaskAdherenceEvaluator is None:
        raise ImportError(
            "azure-ai-evaluation not installed. "
            "Install with: pip install azure-ai-evaluation"
        )

    config: dict[str, Any] = {
        # Standard agentic evaluators
        "task_adherence": TaskAdherenceEvaluator(model_config),
        "tool_accuracy": ToolCallAccuracyEvaluator(model_config),
        "intent_resolution": IntentResolutionEvaluator(model_config),
        # Custom AIOps evaluators
        "sop_adherence": SopAdherenceEvaluator(),
        "triage_completeness": TriageCompletenessEvaluator(),
        "remediation_safety": RemediationSafetyEvaluator(),
        "diagnosis_grounding": DiagnosisGroundingEvaluator(),
    }

    if include_safety and ContentSafetyEvaluator is not None:
        config["content_safety"] = ContentSafetyEvaluator(
            credential=credential,
            azure_ai_project=azure_ai_project,
        )
        config["indirect_attack"] = IndirectAttackEvaluator(
            credential=credential,
            azure_ai_project=azure_ai_project,
        )

    return config


def extract_eval_score(metrics: dict[str, Any], evaluator_name: str) -> Optional[float]:
    """Safely extract an evaluator score from azure-ai-evaluation metrics dict.

    The SDK uses prefixed keys with different suffixes depending on version.
    This function tries all known key formats and returns the first match.

    Key formats tried in order:
    1. "{evaluator_name}.{evaluator_name}"  (standard prefixed)
    2. "{evaluator_name}.score"             (alternative suffix)
    3. "{evaluator_name}"                   (flat key, older SDK)

    Args:
        metrics: Metrics dict from evaluate() result.
        evaluator_name: Base evaluator name (e.g. "task_adherence").

    Returns:
        Float score, or None if no matching key found.
    """
    candidates = [
        f"{evaluator_name}.{evaluator_name}",
        f"{evaluator_name}.score",
        evaluator_name,
    ]
    for key in candidates:
        if key in metrics:
            return float(metrics[key])
    return None
