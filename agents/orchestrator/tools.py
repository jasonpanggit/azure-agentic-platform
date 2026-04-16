"""Orchestrator tool functions — domain classification + multi-domain correlation.

Tool functions in this module are decorated with @ai_function so they can be
called by the LLM as part of Foundry agent tool use.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

try:
    from agent_framework import ai_function
except ImportError:  # type: ignore[assignment]
    # Fallback for environments without agent_framework installed (e.g. unit tests)
    def ai_function(fn):  # type: ignore[misc]
        return fn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cross-domain correlation patterns
# ---------------------------------------------------------------------------

# Known cross-domain error code clusters that indicate correlated failures
_CORRELATED_ERROR_CODES: list[frozenset[str]] = [
    frozenset({"NsgRuleBlocking", "TcpConnectionRefused", "DnsResolutionFailed"}),
    frozenset({"HighCpuAlert", "MemoryPressure", "DiskIoSaturation"}),
    frozenset({"UnauthorizedAccess", "RbacDrift", "AnomalousSignIn"}),
]


def _extract_resource_groups(findings_text: str) -> list[str]:
    """Extract resource group names from a findings text blob.

    Looks for patterns like 'resourceGroups/rg-name' or 'resource group rg-name'.
    """
    import re
    rg_pattern = re.compile(
        r"resourceGroups?[/: ]+([a-zA-Z0-9_\-]+)",
        re.IGNORECASE,
    )
    return list(dict.fromkeys(m.group(1).lower() for m in rg_pattern.finditer(findings_text)))


def _extract_error_codes(findings_text: str) -> list[str]:
    """Extract PascalCase error codes from findings text (e.g. NsgRuleBlocking)."""
    import re
    return re.findall(r"\b[A-Z][a-zA-Z0-9]{3,}\b", findings_text)


@ai_function
def correlate_multi_domain(domain_findings: List[dict]) -> dict:
    """Correlate findings from multiple domain agents into ranked hypotheses.

    Analyses per-domain findings for shared resource groups, overlapping error
    codes, and timing patterns to surface cross-domain signals and produce a
    ranked list of root-cause hypotheses.

    Args:
        domain_findings: List of per-domain result dicts, each containing at
            least 'domain' (str) and 'findings' (str | None).

    Returns:
        Dict with keys:
            hypotheses (list[dict]): Ranked hypotheses, each with:
                rank (int), description (str), evidence (list[str]),
                confidence (float 0.0–1.0).
            cross_domain_signals (list[str]): Observations spanning ≥2 domains.
    """
    if not domain_findings:
        return {"hypotheses": [], "cross_domain_signals": []}

    successful = [f for f in domain_findings if f.get("findings")]

    # --- Gather per-domain resource groups and error codes ---
    domain_rgs: dict[str, list[str]] = {}
    domain_codes: dict[str, list[str]] = {}

    for f in successful:
        domain = f.get("domain", "unknown")
        text = str(f.get("findings", ""))
        domain_rgs[domain] = _extract_resource_groups(text)
        domain_codes[domain] = _extract_error_codes(text)

    # --- Cross-domain signals ---
    cross_domain_signals: list[str] = []

    # Shared resource groups across ≥2 domains
    all_rg_sets = list(domain_rgs.items())
    for i in range(len(all_rg_sets)):
        for j in range(i + 1, len(all_rg_sets)):
            d1, rg1 = all_rg_sets[i]
            d2, rg2 = all_rg_sets[j]
            shared = set(rg1) & set(rg2)
            if shared:
                cross_domain_signals.append(
                    f"Shared resource group(s) {sorted(shared)} appear in both {d1} and {d2} findings."
                )

    # Correlated error code clusters
    all_codes: set[str] = {c for codes in domain_codes.values() for c in codes}
    for cluster in _CORRELATED_ERROR_CODES:
        matched = cluster & all_codes
        if len(matched) >= 2:
            cross_domain_signals.append(
                f"Correlated error pattern detected: {sorted(matched)}."
            )

    # --- Build hypotheses ---
    hypotheses: list[dict] = []

    # Hypothesis 1: correlated failure across all investigated domains
    if len(successful) >= 2:
        domains_str = " + ".join(f["domain"] for f in successful)
        evidence = [f"[{f['domain']}] {str(f['findings'])[:200]}" for f in successful]
        hypotheses.append({
            "rank": 1,
            "description": f"Correlated failure spanning {domains_str} — likely a shared dependency or cascading fault.",
            "evidence": evidence + cross_domain_signals,
            "confidence": min(0.5 + 0.1 * len(successful) + 0.15 * len(cross_domain_signals), 0.95),
        })

    # Hypothesis 2: isolated domain failure for highest-confidence individual finding
    best = max(successful, key=lambda f: float(f.get("confidence", 0))) if successful else None
    if best:
        hypotheses.append({
            "rank": 2,
            "description": f"Isolated {best['domain']} fault — other domains may be secondary effects.",
            "evidence": [str(best.get("findings", ""))[:300]],
            "confidence": float(best.get("confidence", 0)) * 0.8,
        })

    # Hypothesis 3: infrastructure-wide event (all domains equally affected)
    confidences = [float(f.get("confidence", 0)) for f in successful]
    if len(confidences) >= 2:
        avg = sum(confidences) / len(confidences)
        spread = max(confidences) - min(confidences)
        if spread < 0.2:
            hypotheses.append({
                "rank": 3,
                "description": "Infrastructure-wide event — uniform impact across all investigated domains suggests platform or region-level disruption.",
                "evidence": [f"Confidence spread: {spread:.2f} across {len(successful)} domains"],
                "confidence": avg * 0.6,
            })

    hypotheses.sort(key=lambda h: h["rank"])

    logger.info(
        "correlate_multi_domain: produced %d hypotheses, %d cross-domain signals",
        len(hypotheses),
        len(cross_domain_signals),
    )
    return {
        "hypotheses": hypotheses,
        "cross_domain_signals": cross_domain_signals,
    }
