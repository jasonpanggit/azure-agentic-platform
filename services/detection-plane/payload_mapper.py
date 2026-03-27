"""Map Fabric DetectionResults rows to API gateway IncidentPayload (DETECT-003).

This module is used by the Fabric User Data Function to transform classified
alerts from the Eventhouse DetectionResults table into the IncidentPayload
schema expected by POST /api/v1/incidents.

The IncidentPayload schema is defined in services/api-gateway/models.py:
  - incident_id: str (min_length=1)
  - severity: str (pattern=^Sev[0-3]$)
  - domain: str (pattern=^(compute|network|storage|security|arc|sre)$)
  - affected_resources: list[AffectedResource] (min_length=1)
  - detection_rule: str
  - kql_evidence: Optional[str]
  - title: Optional[str]
  - description: Optional[str]
"""
from __future__ import annotations

from typing import Any, Optional


def map_detection_result_to_incident_payload(
    detection_result: dict[str, Any],
) -> dict[str, Any]:
    """Transform a DetectionResults row into an IncidentPayload dict.

    Args:
        detection_result: Dict with keys matching DetectionResults schema:
            alert_id, severity, domain, fired_at, resource_id, resource_type,
            subscription_id, resource_name, alert_rule, description, kql_evidence,
            classified_at.

    Returns:
        Dict matching the IncidentPayload schema for POST /api/v1/incidents.

    Raises:
        ValueError: If required fields are missing.
    """
    alert_id = detection_result.get("alert_id")
    if not alert_id:
        raise ValueError("detection_result must have a non-empty 'alert_id'")

    severity = detection_result.get("severity", "")
    domain = detection_result.get("domain", "")
    resource_id = detection_result.get("resource_id", "")
    resource_type = detection_result.get("resource_type", "")
    subscription_id = detection_result.get("subscription_id", "")
    resource_name = detection_result.get("resource_name", "")
    alert_rule = detection_result.get("alert_rule", "")
    description = detection_result.get("description")
    kql_evidence = detection_result.get("kql_evidence")

    if not resource_id:
        raise ValueError("detection_result must have a non-empty 'resource_id'")

    # Build the incident_id with det- prefix for traceability
    incident_id = f"det-{alert_id}"

    # Build human-readable title from alert_rule and resource_name
    title = f"{alert_rule} on {resource_name}" if alert_rule and resource_name else alert_rule or alert_id

    return {
        "incident_id": incident_id,
        "severity": severity,
        "domain": domain,
        "affected_resources": [
            {
                "resource_id": resource_id,
                "subscription_id": subscription_id or _extract_subscription_id(resource_id),
                "resource_type": resource_type,
            }
        ],
        "detection_rule": alert_rule,
        "kql_evidence": kql_evidence,
        "title": title,
        "description": description,
    }


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription_id from an ARM resource ID.

    Args:
        resource_id: Full ARM resource ID (e.g., /subscriptions/xxx/...).

    Returns:
        Subscription ID string, or empty string if not extractable.
    """
    parts = resource_id.split("/")
    try:
        idx = parts.index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return ""
