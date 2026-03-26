"""Alert state lifecycle management (DETECT-006).

Tracks alert state transitions (New -> Acknowledged -> Closed) in Cosmos DB
with actor and timestamp per transition. Bidirectionally syncs state back
to Azure Monitor via the AlertsManagement REST API.

State machine (D-14):
  new -> acknowledged -> closed
  new -> closed (direct close)
  closed is terminal (no transitions out)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from azure.cosmos import ContainerProxy

from models import VALID_TRANSITIONS, AlertStatus, StatusHistoryEntry

logger = logging.getLogger(__name__)

# Mapping from our status to Azure Monitor alert state names
_AZURE_MONITOR_STATE_MAP: dict[AlertStatus, str] = {
    AlertStatus.ACKNOWLEDGED: "Acknowledged",
    AlertStatus.CLOSED: "Closed",
}


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, current: AlertStatus, target: AlertStatus):
        self.current = current
        self.target = target
        super().__init__(
            f"Invalid transition: {current.value} -> {target.value}. "
            f"Valid targets from {current.value}: "
            f"{', '.join(s.value for s in VALID_TRANSITIONS.get(current, set()))}"
        )


async def transition_alert_state(
    incident_id: str,
    resource_id: str,
    new_status: AlertStatus,
    actor: str,
    container: ContainerProxy,
) -> dict[str, Any]:
    """Transition an incident's alert state in Cosmos DB.

    Validates the transition against the state machine, appends to
    status_history, and uses ETag optimistic concurrency.

    Args:
        incident_id: Cosmos DB document ID.
        resource_id: ARM resource ID (partition key).
        new_status: Target status.
        actor: Agent ID or operator UPN performing the transition.
        container: Cosmos DB incidents container proxy.

    Returns:
        Updated Cosmos DB record.

    Raises:
        InvalidTransitionError: If the transition is not valid.
    """
    record = container.read_item(item=incident_id, partition_key=resource_id)
    etag = record["_etag"]

    current_status = AlertStatus(record["status"])
    valid_targets = VALID_TRANSITIONS.get(current_status, set())

    if new_status not in valid_targets:
        raise InvalidTransitionError(current_status, new_status)

    now = datetime.now(timezone.utc).isoformat()
    new_history_entry = StatusHistoryEntry(
        status=new_status,
        actor=actor,
        timestamp=now,
    )

    updated = {
        **record,
        "status": new_status.value,
        "status_history": [
            *record.get("status_history", []),
            new_history_entry.model_dump(),
        ],
        "updated_at": now,
    }

    result = container.replace_item(
        item=incident_id,
        body=updated,
        etag=etag,
        match_condition="IfMatch",
    )

    return result


async def sync_alert_state_to_azure_monitor(
    alert_id: str,
    new_status: AlertStatus,
    subscription_id: str,
    credential: Any,
) -> bool:
    """Sync alert state back to Azure Monitor (D-14 bidirectional sync).

    Fire-and-forget: Azure Monitor sync failure MUST NOT block the
    platform state transition. Errors are logged but not raised.

    Args:
        alert_id: Azure Monitor alert ID.
        new_status: Target status to sync.
        subscription_id: Azure subscription ID containing the alert.
        credential: Azure credential (DefaultAzureCredential).

    Returns:
        True if sync succeeded, False if it failed.
    """
    azure_state = _AZURE_MONITOR_STATE_MAP.get(new_status)
    if azure_state is None:
        logger.debug(
            "No Azure Monitor state mapping for %s; skipping sync", new_status.value
        )
        return True

    try:
        from azure.mgmt.alertsmanagement import AlertsManagementClient

        client = AlertsManagementClient(credential, subscription_id)
        client.alerts.change_state(
            alert_id=alert_id,
            new_state=azure_state,
        )
        logger.info(
            "Synced alert %s to Azure Monitor state %s", alert_id, azure_state
        )
        return True
    except ImportError:
        logger.warning(
            "azure-mgmt-alertsmanagement not installed; skipping Azure Monitor sync"
        )
        return False
    except Exception as exc:
        logger.error(
            "Failed to sync alert %s to Azure Monitor (non-blocking): %s",
            alert_id,
            exc,
        )
        return False
