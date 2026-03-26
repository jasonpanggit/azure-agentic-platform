"""Fabric User Data Function — Activator trigger handler (DETECT-003).

Receives DetectionResults rows from Fabric Activator, maps to IncidentPayload,
authenticates via Service Principal (D-08), and POSTs to the API gateway.

This function runs inside the Fabric runtime. It is triggered by Activator
when new rows appear in the DetectionResults table where domain IS NOT NULL.

Authentication (D-08):
    Uses MSAL ConfidentialClientApplication with client_id + client_secret
    from Key Vault (injected as environment variables at deploy time).
    Acquires a Bearer token for the gateway's Entra app audience.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import msal
import requests

logger = logging.getLogger(__name__)


def get_access_token() -> str:
    """Acquire a Bearer token for the API gateway using client credentials.

    Environment variables (from Key Vault):
        FABRIC_SP_CLIENT_ID: Service Principal client ID
        FABRIC_SP_CLIENT_SECRET: Service Principal client secret
        FABRIC_SP_TENANT_ID: Entra tenant ID
        GATEWAY_APP_SCOPE: API gateway scope (e.g., api://{client_id}/.default)

    Returns:
        Bearer token string.

    Raises:
        RuntimeError: If token acquisition fails.
    """
    client_id = os.environ["FABRIC_SP_CLIENT_ID"]
    client_secret = os.environ["FABRIC_SP_CLIENT_SECRET"]
    tenant_id = os.environ["FABRIC_SP_TENANT_ID"]
    scope = os.environ["GATEWAY_APP_SCOPE"]

    authority = f"https://login.microsoftonline.com/{tenant_id}"

    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )

    result = app.acquire_token_for_client(scopes=[scope])

    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "unknown"))
        raise RuntimeError(f"Token acquisition failed: {error}")

    return result["access_token"]


def map_detection_result_to_payload(detection_result: dict[str, Any]) -> dict[str, Any]:
    """Map a DetectionResults row to an IncidentPayload dict.

    This is a self-contained copy of the mapping logic to avoid
    import dependencies on the detection-plane package within Fabric runtime.
    The canonical implementation is in services/detection-plane/payload_mapper.py.

    Args:
        detection_result: Dict from Activator trigger with DetectionResults fields.

    Returns:
        Dict matching POST /api/v1/incidents IncidentPayload schema.
    """
    alert_id = detection_result.get("alert_id", "")
    resource_id = detection_result.get("resource_id", "")
    parts = resource_id.split("/")
    try:
        sub_idx = parts.index("subscriptions")
        subscription_id = parts[sub_idx + 1]
    except (ValueError, IndexError):
        subscription_id = detection_result.get("subscription_id", "")

    resource_name = detection_result.get("resource_name", "unknown")
    alert_rule = detection_result.get("alert_rule", "")

    return {
        "incident_id": f"det-{alert_id}",
        "severity": detection_result.get("severity", "Sev3"),
        "domain": detection_result.get("domain", "sre"),
        "affected_resources": [
            {
                "resource_id": resource_id,
                "subscription_id": subscription_id,
                "resource_type": detection_result.get("resource_type", ""),
            }
        ],
        "detection_rule": alert_rule,
        "kql_evidence": detection_result.get("kql_evidence"),
        "title": f"{alert_rule} on {resource_name}" if alert_rule else alert_id,
        "description": detection_result.get("description"),
    }


def handle_activator_trigger(detection_result: dict[str, Any]) -> dict[str, Any]:
    """Entry point for the Fabric User Data Function.

    Called by Fabric Activator when a new DetectionResults row is detected.

    Args:
        detection_result: The DetectionResults row as a dict.

    Returns:
        Dict with status and incident details.
    """
    gateway_url = os.environ["API_GATEWAY_URL"]
    endpoint = f"{gateway_url}/api/v1/incidents"

    logger.info(
        "Processing detection result: alert_id=%s, domain=%s, severity=%s",
        detection_result.get("alert_id"),
        detection_result.get("domain"),
        detection_result.get("severity"),
    )

    # Map to IncidentPayload
    payload = map_detection_result_to_payload(detection_result)

    # Acquire auth token
    token = get_access_token()

    # POST to API gateway
    response = requests.post(
        endpoint,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    if response.status_code == 202:
        result = response.json()
        logger.info(
            "Incident dispatched: incident_id=%s, thread_id=%s",
            payload["incident_id"],
            result.get("thread_id"),
        )
        return {"status": "dispatched", "thread_id": result.get("thread_id")}

    logger.error(
        "Gateway returned %d: %s", response.status_code, response.text
    )
    return {"status": "error", "status_code": response.status_code, "detail": response.text}
