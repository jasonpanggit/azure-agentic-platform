"""Resource Identity Certainty — pre-execution verification (REMEDI-004).

Before executing any remediation, agents call verify_resource_identity()
to compare the current resource state against the snapshot captured at
proposal time. If any signal has diverged, the action is aborted with
stale_approval.
"""
from __future__ import annotations

import logging
from typing import Any

from agents.shared.triage import ResourceSnapshot

logger = logging.getLogger(__name__)


class StaleApprovalError(Exception):
    """Raised when resource state has diverged since approval was granted."""

    def __init__(self, resource_id: str, reason: str):
        self.resource_id = resource_id
        self.reason = reason
        super().__init__(
            f"Stale approval for {resource_id}: {reason}"
        )


def capture_resource_snapshot(
    resource_id: str,
    provisioning_state: str,
    tags: dict,
    resource_health: str,
) -> ResourceSnapshot:
    """Capture a resource state snapshot at proposal time."""
    return ResourceSnapshot(
        resource_id=resource_id,
        provisioning_state=provisioning_state,
        tags=tags,
        resource_health=resource_health,
    )


def verify_resource_identity(
    snapshot: ResourceSnapshot,
    current_resource_id: str,
    current_provisioning_state: str,
    current_tags: dict,
    current_resource_health: str,
) -> bool:
    """Verify that the resource has not diverged since the snapshot was captured.

    Checks 2 independent signals:
    1. Resource ID exact match
    2. State hash match (provisioning_state + tags + resource_health)
    """
    # Signal 1: Resource ID match
    if snapshot.resource_id != current_resource_id:
        logger.warning(
            "Resource ID mismatch: expected %s, got %s",
            snapshot.resource_id,
            current_resource_id,
        )
        return False

    # Signal 2: State hash match
    current_snapshot = ResourceSnapshot(
        resource_id=current_resource_id,
        provisioning_state=current_provisioning_state,
        tags=current_tags,
        resource_health=current_resource_health,
    )
    if snapshot.snapshot_hash != current_snapshot.snapshot_hash:
        logger.warning(
            "Resource state diverged for %s: hash %s != %s",
            snapshot.resource_id,
            snapshot.snapshot_hash,
            current_snapshot.snapshot_hash,
        )
        return False

    return True
