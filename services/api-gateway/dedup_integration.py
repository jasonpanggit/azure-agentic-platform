from __future__ import annotations
"""Thin integration layer connecting the API gateway to the detection-plane dedup logic.

The gateway remains a thin router — this module provides the dedup check
as a dependency that runs before Foundry dispatch. If dedup detects a
duplicate, it short-circuits the response without creating a new Foundry thread.
"""
import os

import logging
import os
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Add detection-plane to Python path for imports
_DETECTION_PLANE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "services", "detection-plane"
)
if _DETECTION_PLANE_PATH not in sys.path:
    sys.path.insert(0, os.path.abspath(_DETECTION_PLANE_PATH))


async def check_dedup(
    incident_id: str,
    resource_id: str,
    severity: str,
    domain: str,
    detection_rule: str,
    affected_resources: list[dict[str, Any]],
    kql_evidence: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Check for duplicate incidents before Foundry dispatch.

    Returns:
        None if no duplicate — proceed with new incident.
        Dict with existing incident info if duplicate detected.
    """
    try:
        from dedup import (
            collapse_duplicate,
            correlate_alert,
            create_incident_record,
            dedup_layer1,
            dedup_layer2,
        )
    except ImportError:
        logger.warning(
            "detection-plane dedup module not available; skipping dedup check"
        )
        return None

    cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT")
    cosmos_database = os.environ.get("COSMOS_DATABASE_NAME")

    if not cosmos_endpoint or not cosmos_database:
        logger.warning("COSMOS_ENDPOINT or COSMOS_DATABASE_NAME not set; skipping dedup")
        return None

    try:
        from azure.cosmos import CosmosClient
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        client = CosmosClient(url=cosmos_endpoint, credential=credential)
        database = client.get_database_client(cosmos_database)
        container = database.get_container_client("incidents")

        # Layer 1: Time-window collapse
        result = await dedup_layer1(resource_id, detection_rule, container)
        if result.is_duplicate and result.existing_record:
            updated = await collapse_duplicate(result.existing_record, container)
            logger.info(
                "Layer 1 dedup: collapsed duplicate for %s (count=%d)",
                resource_id,
                updated.get("duplicate_count", 0),
            )
            return {
                "thread_id": updated.get("thread_id", ""),
                "status": "deduplicated",
                "layer": "layer1",
                "duplicate_count": updated.get("duplicate_count", 0),
            }

        # Layer 2: Open-incident correlation
        result = await dedup_layer2(resource_id, container)
        if result.is_duplicate and result.existing_record:
            updated = await correlate_alert(
                result.existing_record,
                alert_id=incident_id,
                severity=severity,
                detection_rule=detection_rule,
                container=container,
            )
            logger.info(
                "Layer 2 dedup: correlated alert %s to incident %s",
                incident_id,
                updated.get("incident_id"),
            )
            return {
                "thread_id": updated.get("thread_id", ""),
                "status": "correlated",
                "layer": "layer2",
                "parent_incident_id": updated.get("incident_id"),
            }

        # No duplicate — create new incident record
        await create_incident_record(
            incident_id=incident_id,
            resource_id=resource_id,
            severity=severity,
            domain=domain,
            detection_rule=detection_rule,
            affected_resources=affected_resources,
            container=container,
            kql_evidence=kql_evidence,
            title=title,
            description=description,
        )
        logger.info("Created new incident record: %s", incident_id)

    except Exception as exc:
        logger.error("Dedup check failed (non-blocking): %s", exc)
        return None

    return None
