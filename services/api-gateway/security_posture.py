"""Security Posture Service — Defender secure score, policy compliance, composite scoring (Phase 59).

Architecture:
- SecurityPostureClient: Defender score + policy compliance + Cosmos persistence
- Composite score: 50% secure score + 30% policy compliance + 20% custom controls
- All Azure SDK calls never raise — structured error dicts returned instead
- TTL annotation on Cosmos docs (3600s = 1h)
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDK availability guards (module-level lazy imports)
# ---------------------------------------------------------------------------

try:
    from azure.mgmt.security import SecurityCenter
    _SECURITY_IMPORT_ERROR: str = ""
except Exception as _e:
    SecurityCenter = None  # type: ignore[assignment,misc]
    _SECURITY_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.policyinsights import PolicyInsightsClient
    _POLICY_IMPORT_ERROR: str = ""
except Exception as _e:
    PolicyInsightsClient = None  # type: ignore[assignment,misc]
    _POLICY_IMPORT_ERROR = str(_e)


def _log_sdk_availability() -> None:
    """Log SDK availability status at module load time."""
    if _SECURITY_IMPORT_ERROR:
        logger.warning("security_posture: azure-mgmt-security unavailable: %s", _SECURITY_IMPORT_ERROR)
    else:
        logger.debug("security_posture: azure-mgmt-security available")
    if _POLICY_IMPORT_ERROR:
        logger.warning("security_posture: azure-mgmt-policyinsights unavailable: %s", _POLICY_IMPORT_ERROR)
    else:
        logger.debug("security_posture: azure-mgmt-policyinsights available")


_log_sdk_availability()

# ---------------------------------------------------------------------------
# Environment config
# ---------------------------------------------------------------------------

COSMOS_DATABASE: str = os.environ.get("COSMOS_DATABASE", "aap")
COSMOS_POSTURE_CONTAINER: str = os.environ.get("COSMOS_SECURITY_POSTURE_CONTAINER", "security_posture")
POSTURE_TTL_SECONDS: int = int(os.environ.get("POSTURE_TTL_SECONDS", "3600"))

# Score weights
WEIGHT_SECURE_SCORE: float = 0.50
WEIGHT_POLICY_COMPLIANCE: float = 0.30
WEIGHT_CUSTOM_CONTROLS: float = 0.20

# Severity ordering for findings sort
_SEVERITY_ORDER: Dict[str, int] = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Unknown": 4}


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


def _score_color(score: float) -> str:
    """Return traffic-light color based on score."""
    if score >= 75:
        return "green"
    if score >= 50:
        return "yellow"
    return "red"


def _compute_composite(
    secure_score_pct: Optional[float],
    policy_compliance_pct: Optional[float],
    custom_controls_pct: Optional[float],
) -> Dict[str, Any]:
    """Compute composite 0-100 score from sub-scores.

    Missing sub-scores (None) are replaced with 0 and flagged in warnings.

    Args:
        secure_score_pct: Defender Secure Score 0-100, or None.
        policy_compliance_pct: Policy compliance % 0-100, or None.
        custom_controls_pct: Custom controls score 0-100, or None.

    Returns:
        Dict with composite_score, sub_scores, color, warnings.
    """
    warnings: List[str] = []
    ss = secure_score_pct if secure_score_pct is not None else 0.0
    pc = policy_compliance_pct if policy_compliance_pct is not None else 0.0
    cc = custom_controls_pct if custom_controls_pct is not None else 0.0

    if secure_score_pct is None:
        warnings.append("Defender Secure Score unavailable — contributing 0 to composite")
    if policy_compliance_pct is None:
        warnings.append("Policy compliance unavailable — contributing 0 to composite")
    if custom_controls_pct is None:
        warnings.append("Custom controls score unavailable — using default 0")

    composite = _clamp(
        WEIGHT_SECURE_SCORE * ss
        + WEIGHT_POLICY_COMPLIANCE * pc
        + WEIGHT_CUSTOM_CONTROLS * cc
    )

    return {
        "composite_score": round(composite, 1),
        "color": _score_color(composite),
        "sub_scores": {
            "defender_secure_score": round(ss, 1),
            "policy_compliance": round(pc, 1),
            "custom_controls": round(cc, 1),
        },
        "weights": {
            "defender_secure_score": WEIGHT_SECURE_SCORE,
            "policy_compliance": WEIGHT_POLICY_COMPLIANCE,
            "custom_controls": WEIGHT_CUSTOM_CONTROLS,
        },
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# SecurityPostureClient
# ---------------------------------------------------------------------------

class SecurityPostureClient:
    """Aggregates Defender secure score, policy compliance, and stores in Cosmos."""

    def __init__(
        self,
        cosmos_client: Any,
        credential: Any,
        subscription_id: str,
    ) -> None:
        self._cosmos = cosmos_client
        self.credential = credential
        self.subscription_id = subscription_id
        self._container: Optional[Any] = None

    def _get_container(self) -> Any:
        """Return Cosmos security_posture container client (lazy init)."""
        if self._container is None:
            db = self._cosmos.get_database_client(COSMOS_DATABASE)
            self._container = db.get_container_client(COSMOS_POSTURE_CONTAINER)
        return self._container

    def _upsert_posture(self, doc: Dict[str, Any]) -> None:
        """Upsert posture document to Cosmos. Non-fatal on error."""
        if self._cosmos is None:
            return
        try:
            container = self._get_container()
            container.upsert_item(doc)
        except Exception as exc:
            logger.warning(
                "security_posture: _upsert_posture failed (non-fatal) | id=%s error=%s",
                doc.get("id", "?"), exc,
            )

    def _get_defender_secure_score(self) -> Optional[float]:
        """Fetch Defender Secure Score for the subscription.

        Returns:
            Score as 0-100 percentage, or None on error/unavailability.
        """
        if SecurityCenter is None:
            logger.debug("security_posture: SecurityCenter SDK unavailable")
            return None
        try:
            client = SecurityCenter(self.credential, self.subscription_id)
            scores = list(client.secure_scores.list())
            if not scores:
                return None
            # Use "ascScore" if available (overall score)
            for score in scores:
                if score.name == "ascScore":
                    current = getattr(score, "current", None)
                    maximum = getattr(score, "max", None)
                    if current is not None and maximum and maximum > 0:
                        return round(current / maximum * 100, 2)
            # Fallback: use first score
            score = scores[0]
            current = getattr(score, "current", None)
            maximum = getattr(score, "max", None)
            if current is not None and maximum and maximum > 0:
                return round(current / maximum * 100, 2)
            return None
        except Exception as exc:
            logger.warning("security_posture: _get_defender_secure_score error | error=%s", exc)
            return None

    def _get_policy_compliance_pct(self) -> Optional[float]:
        """Fetch policy compliance % for the subscription.

        Returns:
            Compliance percentage 0-100, or None on error/unavailability.
        """
        if PolicyInsightsClient is None:
            logger.debug("security_posture: PolicyInsightsClient SDK unavailable")
            return None
        try:
            client = PolicyInsightsClient(self.credential)
            # Get summary for the subscription scope
            scope = f"/subscriptions/{self.subscription_id}"
            summaries = client.policy_states.summarize_for_subscription(
                subscription_id=self.subscription_id
            )
            summary = summaries.value[0] if summaries.value else None
            if summary is None:
                return None
            results = getattr(summary, "results", None)
            if results is None:
                return None
            non_compliant = getattr(results, "non_compliant_resources", 0) or 0
            # Try to get total from policy assignments
            total_resources = getattr(results, "resource_details", None)
            # Fallback: compute from non-compliant vs compliant
            compliant_resources = 0
            if hasattr(results, "resource_details") and results.resource_details:
                for detail in results.resource_details:
                    if getattr(detail, "compliance_state", "") == "compliant":
                        compliant_resources = getattr(detail, "count", 0) or 0
            total = non_compliant + compliant_resources
            if total <= 0:
                return 100.0 if non_compliant == 0 else None
            return round(compliant_resources / total * 100, 2)
        except Exception as exc:
            logger.warning("security_posture: _get_policy_compliance_pct error | error=%s", exc)
            return None

    def _get_custom_controls_score(self) -> Optional[float]:
        """Compute custom controls score — currently returns None (placeholder).

        Future: integrate exposure management, regulatory compliance, etc.

        Returns:
            Score 0-100, or None.
        """
        return None

    def _get_top_findings_raw(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Fetch top high/critical Defender recommendations.

        Args:
            limit: Maximum number of findings to return.

        Returns:
            List of finding dicts, empty on error.
        """
        if SecurityCenter is None:
            return []
        try:
            client = SecurityCenter(self.credential, self.subscription_id)
            tasks = list(client.tasks.list())
            findings: List[Dict[str, Any]] = []
            for task in tasks:
                props = getattr(task, "security_task_parameters", None)
                name = getattr(props, "name", None) or getattr(task, "name", "Unknown finding")
                severity_raw = getattr(props, "severity", None) or "Unknown"
                resource_id = getattr(task, "resource_id", None) or ""
                resource_name = resource_id.split("/")[-1] if resource_id else ""
                recommendation = getattr(props, "remediation_description", None) or ""
                control = getattr(props, "category", None) or ""

                severity = str(severity_raw).capitalize()
                if severity not in _SEVERITY_ORDER:
                    severity = "Unknown"

                findings.append({
                    "finding": str(name),
                    "severity": severity,
                    "resource_id": resource_id,
                    "resource_name": resource_name,
                    "recommendation": str(recommendation),
                    "control": str(control),
                })

            # Sort by severity then name
            findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f["severity"], 99), f["finding"]))

            # Filter to high/critical only
            priority = [f for f in findings if f["severity"] in ("Critical", "High")]
            others = [f for f in findings if f["severity"] not in ("Critical", "High")]
            combined = (priority + others)[:limit]
            return combined
        except Exception as exc:
            logger.warning("security_posture: _get_top_findings_raw error | error=%s", exc)
            return []

    def get_composite_score(self) -> Dict[str, Any]:
        """Return composite security posture score for the subscription.

        Aggregates Defender secure score + policy compliance + custom controls.
        Stores result in Cosmos with 1h TTL.

        Returns:
            Dict with composite_score, sub_scores, color, subscription_id, generated_at, duration_ms.
            Never raises.
        """
        start_time = time.monotonic()
        try:
            secure_score = self._get_defender_secure_score()
            policy_compliance = self._get_policy_compliance_pct()
            custom_controls = self._get_custom_controls_score()

            result = _compute_composite(secure_score, policy_compliance, custom_controls)
            generated_at = datetime.now(timezone.utc).isoformat()

            doc: Dict[str, Any] = {
                "id": f"{self.subscription_id}:posture:{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H')}",
                "subscription_id": self.subscription_id,
                "composite_score": result["composite_score"],
                "sub_scores": result["sub_scores"],
                "color": result["color"],
                "generated_at": generated_at,
                "ttl": POSTURE_TTL_SECONDS,
            }
            self._upsert_posture(doc)

            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            return {
                **result,
                "subscription_id": self.subscription_id,
                "generated_at": generated_at,
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            logger.warning("security_posture: get_composite_score error | error=%s", exc)
            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            return {
                "error": str(exc),
                "composite_score": 0.0,
                "color": "red",
                "sub_scores": {},
                "subscription_id": self.subscription_id,
                "duration_ms": duration_ms,
            }

    def get_posture_trend(self, days: int = 30) -> Dict[str, Any]:
        """Return 30-day trend of composite posture scores from Cosmos.

        Args:
            days: Number of days of history.

        Returns:
            Dict with trend list (date, score), subscription_id, duration_ms.
            Never raises.
        """
        start_time = time.monotonic()
        try:
            if self._cosmos is None:
                return {
                    "trend": [],
                    "subscription_id": self.subscription_id,
                    "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                    "warning": "Cosmos unavailable",
                }
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            container = self._get_container()
            query = (
                "SELECT c.generated_at, c.composite_score FROM c "
                "WHERE c.subscription_id = @sub AND c.generated_at >= @cutoff "
                "ORDER BY c.generated_at ASC"
            )
            params = [
                {"name": "@sub", "value": self.subscription_id},
                {"name": "@cutoff", "value": cutoff},
            ]
            items = list(container.query_items(
                query=query,
                parameters=params,
                partition_key=self.subscription_id,
            ))
            trend = [
                {
                    "date": item.get("generated_at", "")[:10],
                    "score": item.get("composite_score", 0.0),
                }
                for item in items
            ]
            return {
                "trend": trend,
                "subscription_id": self.subscription_id,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }
        except Exception as exc:
            logger.warning("security_posture: get_posture_trend error | error=%s", exc)
            return {
                "error": str(exc),
                "trend": [],
                "subscription_id": self.subscription_id,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }

    def get_top_findings(self, limit: int = 25) -> Dict[str, Any]:
        """Return top-N high/critical security findings.

        Args:
            limit: Maximum findings to return (default 25).

        Returns:
            Dict with findings list, subscription_id, duration_ms.
            Never raises.
        """
        start_time = time.monotonic()
        try:
            findings = self._get_top_findings_raw(limit)
            return {
                "findings": findings,
                "total": len(findings),
                "subscription_id": self.subscription_id,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }
        except Exception as exc:
            logger.warning("security_posture: get_top_findings error | error=%s", exc)
            return {
                "error": str(exc),
                "findings": [],
                "total": 0,
                "subscription_id": self.subscription_id,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }
