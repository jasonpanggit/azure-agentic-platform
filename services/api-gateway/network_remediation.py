from __future__ import annotations
"""Network remediation executor — auto-fix + WAL audit for network topology issues.

Safe auto-fix actions (no approval required):
  - firewall_threatintel_off  → sets threat_intel_mode = "Alert"
  - pe_not_approved           → approves the pending private endpoint connection

All other issue types return {"status": "requires_approval"}.

WAL pattern: pre-execution record written before ARM call; updated after.
Never raises from public functions — returns structured error dicts.
"""

import logging
import os
import time
import uuid
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

try:
    from azure.mgmt.network import NetworkManagementClient
    from azure.mgmt.network.models import (  # type: ignore[assignment]
        PrivateEndpointConnection,
        PrivateLinkServiceConnectionState,
    )
except ImportError:
    NetworkManagementClient = None  # type: ignore[assignment,misc]
    PrivateEndpointConnection = None  # type: ignore[assignment,misc]
    PrivateLinkServiceConnectionState = None  # type: ignore[assignment,misc]


COSMOS_DATABASE_NAME = os.environ.get("COSMOS_DATABASE_NAME", "aap")
COSMOS_REMEDIATION_AUDIT_CONTAINER = os.environ.get(
    "COSMOS_REMEDIATION_AUDIT_CONTAINER", "remediation_audit"
)


# ---------------------------------------------------------------------------
# WAL helpers
# ---------------------------------------------------------------------------

def _get_audit_container(cosmos_client: Optional[Any]) -> Any:
    """Return Cosmos remediation_audit container proxy, or None if unavailable."""
    if cosmos_client is None:
        endpoint = os.environ.get("COSMOS_ENDPOINT", "")
        if not endpoint:
            return None
        try:
            from azure.cosmos import CosmosClient as _CosmosClient
            from azure.identity import DefaultAzureCredential
            cosmos_client = _CosmosClient(endpoint, credential=DefaultAzureCredential())
        except Exception as exc:
            logger.warning("network_remediation: cannot build Cosmos client: %s", exc)
            return None
    try:
        return (
            cosmos_client
            .get_database_client(COSMOS_DATABASE_NAME)
            .get_container_client(COSMOS_REMEDIATION_AUDIT_CONTAINER)
        )
    except Exception as exc:
        logger.warning("network_remediation: cannot get audit container: %s", exc)
        return None


def _write_wal(
    execution_id: str,
    cosmos_client: Optional[Any],
    *,
    status: str,
    record: Optional[dict] = None,
    update_fields: Optional[dict] = None,
) -> None:
    """Write or update a WAL audit record. Never raises."""
    try:
        container = _get_audit_container(cosmos_client)
        if container is None:
            return
        if record is not None:
            doc = dict(record)
            doc["id"] = execution_id
            doc["status"] = status
            container.upsert_item(doc)
        elif update_fields is not None:
            existing = container.read_item(item=execution_id, partition_key=execution_id)
            updated = {**existing, **update_fields, "status": status}
            container.replace_item(item=execution_id, body=updated)
    except Exception as exc:
        logger.warning("network_remediation: WAL write failed (non-blocking): %s", exc)


# ---------------------------------------------------------------------------
# Fix: firewall_threatintel_off
# ---------------------------------------------------------------------------

async def _fix_firewall_threatintel(
    issue: dict,
    subscription_id: str,
    credential: Any,
    cosmos_client: Optional[Any] = None,
) -> dict:
    """Set Azure Firewall threat_intel_mode to 'Alert'.

    Never raises. Returns structured success/error dict.
    """
    execution_id = str(uuid.uuid4())
    start_time = time.monotonic()
    resource_id: str = issue.get("affected_resource_id", "")

    # Parse /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/azureFirewalls/{name}
    parts = resource_id.split("/")
    try:
        rg_idx = parts.index("resourceGroups") + 1
        fw_idx = parts.index("azureFirewalls") + 1
        resource_group = parts[rg_idx]
        firewall_name = parts[fw_idx]
    except (ValueError, IndexError):
        duration_ms = (time.monotonic() - start_time) * 1000
        return {
            "status": "error",
            "execution_id": execution_id,
            "message": f"Cannot parse firewall resource ID: {resource_id}",
            "duration_ms": round(duration_ms, 1),
        }

    # Pre-execution WAL record
    wal_record = {
        "execution_id": execution_id,
        "issue_type": "firewall_threatintel_off",
        "resource_id": resource_id,
        "action": "set_threat_intel_alert",
        "subscription_id": subscription_id,
    }
    _write_wal(execution_id, cosmos_client, status="pending", record=wal_record)

    if NetworkManagementClient is None:
        duration_ms = (time.monotonic() - start_time) * 1000
        _write_wal(execution_id, cosmos_client, status="failed",
                   update_fields={"error": "NetworkManagementClient not available"})
        return {
            "status": "error",
            "execution_id": execution_id,
            "message": "azure-mgmt-network not installed",
            "duration_ms": round(duration_ms, 1),
        }

    try:
        client = NetworkManagementClient(credential, subscription_id)
        firewall = client.azure_firewalls.get(resource_group, firewall_name)
        firewall.threat_intel_mode = "Alert"
        poller = client.azure_firewalls.begin_create_or_update(
            resource_group, firewall_name, firewall
        )
        poller.result()  # wait for completion
        duration_ms = (time.monotonic() - start_time) * 1000
        _write_wal(execution_id, cosmos_client, status="complete",
                   update_fields={"duration_ms": round(duration_ms, 1)})
        logger.info(
            "network_remediation: firewall ThreatIntel set to Alert | "
            "fw=%s rg=%s execution_id=%s (%.0fms)",
            firewall_name, resource_group, execution_id, duration_ms,
        )
        return {
            "status": "executed",
            "execution_id": execution_id,
            "message": f"Firewall '{firewall_name}' threat intelligence mode set to Alert.",
            "duration_ms": round(duration_ms, 1),
        }
    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        _write_wal(execution_id, cosmos_client, status="failed",
                   update_fields={"error": str(exc), "duration_ms": round(duration_ms, 1)})
        logger.error(
            "network_remediation: firewall ThreatIntel fix failed | "
            "fw=%s error=%s (%.0fms)",
            firewall_name, exc, duration_ms,
        )
        return {
            "status": "error",
            "execution_id": execution_id,
            "message": str(exc),
            "duration_ms": round(duration_ms, 1),
        }


# ---------------------------------------------------------------------------
# Fix: pe_not_approved
# ---------------------------------------------------------------------------

async def _fix_pe_approve(
    issue: dict,
    subscription_id: str,
    credential: Any,
    cosmos_client: Optional[Any] = None,
) -> dict:
    """Approve a pending Private Endpoint connection.

    Expected affected_resource_id format:
      /subscriptions/{sub}/resourceGroups/{rg}/providers/
        Microsoft.Network/privateEndpoints/{pe_name}
    The issue data should include the service resource ID in related_resource_ids[0].

    Never raises. Returns structured success/error dict.
    """
    execution_id = str(uuid.uuid4())
    start_time = time.monotonic()
    resource_id: str = issue.get("affected_resource_id", "")

    parts = resource_id.split("/")
    try:
        sub_idx = parts.index("subscriptions") + 1
        rg_idx = parts.index("resourceGroups") + 1
        pe_idx = parts.index("privateEndpoints") + 1
        resource_subscription_id = parts[sub_idx]
        resource_group = parts[rg_idx]
        pe_name = parts[pe_idx]
    except (ValueError, IndexError):
        duration_ms = (time.monotonic() - start_time) * 1000
        return {
            "status": "error",
            "execution_id": execution_id,
            "message": f"Cannot parse private endpoint resource ID: {resource_id}",
            "duration_ms": round(duration_ms, 1),
        }

    # Verify the PE belongs to the caller-supplied subscription to prevent cross-subscription approval
    if resource_subscription_id.lower() != subscription_id.lower():
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.warning(
            "network_remediation: PE approve rejected — resource subscription %s does not match "
            "caller subscription %s | pe=%s execution_id=%s",
            resource_subscription_id, subscription_id, pe_name, execution_id,
        )
        return {
            "status": "error",
            "execution_id": execution_id,
            "message": (
                f"Resource subscription '{resource_subscription_id}' does not match "
                f"caller subscription '{subscription_id}'. Approval rejected."
            ),
            "duration_ms": round(duration_ms, 1),
        }

    wal_record = {
        "execution_id": execution_id,
        "issue_type": "pe_not_approved",
        "resource_id": resource_id,
        "action": "approve_pe_connection",
        "subscription_id": subscription_id,
    }
    _write_wal(execution_id, cosmos_client, status="pending", record=wal_record)

    if NetworkManagementClient is None:
        duration_ms = (time.monotonic() - start_time) * 1000
        _write_wal(execution_id, cosmos_client, status="failed",
                   update_fields={"error": "NetworkManagementClient not available"})
        return {
            "status": "error",
            "execution_id": execution_id,
            "message": "azure-mgmt-network not installed",
            "duration_ms": round(duration_ms, 1),
        }

    try:
        client = NetworkManagementClient(credential, subscription_id)
        # List all PE connections and approve the first pending one
        if not hasattr(client, "private_endpoint_connections"):
            duration_ms = (time.monotonic() - start_time) * 1000
            _write_wal(execution_id, cosmos_client, status="failed",
                       update_fields={"error": "private_endpoint_connections API not available", "duration_ms": round(duration_ms, 1)})
            return {
                "status": "error",
                "execution_id": execution_id,
                "message": "private_endpoint_connections API not available in this SDK version",
                "duration_ms": round(duration_ms, 1),
            }

        connections = list(client.private_endpoint_connections.list(resource_group, pe_name))

        if not connections:
            duration_ms = (time.monotonic() - start_time) * 1000
            _write_wal(execution_id, cosmos_client, status="failed",
                       update_fields={"error": "no PE connections found", "duration_ms": round(duration_ms, 1)})
            return {
                "status": "error",
                "execution_id": execution_id,
                "message": f"No private endpoint connections found for '{pe_name}'. Cannot approve.",
                "duration_ms": round(duration_ms, 1),
            }

        approved_any = False
        for conn in connections:
            state = conn.private_link_service_connection_state
            if state and state.status in ("Pending", "pending"):
                conn.private_link_service_connection_state.status = "Approved"
                conn.private_link_service_connection_state.description = (
                    "Auto-approved by AAP remediation engine"
                )
                client.private_endpoint_connections.update(
                    resource_group, pe_name, conn.name, conn
                )
                logger.info(
                    "network_remediation: PE connection approved | "
                    "pe=%s conn=%s rg=%s execution_id=%s",
                    pe_name, conn.name, resource_group, execution_id,
                )
                approved_any = True
                break

        if not approved_any:
            duration_ms = (time.monotonic() - start_time) * 1000
            _write_wal(execution_id, cosmos_client, status="failed",
                       update_fields={"error": "no pending connections found", "duration_ms": round(duration_ms, 1)})
            return {
                "status": "error",
                "execution_id": execution_id,
                "message": f"No pending connections found for private endpoint '{pe_name}'.",
                "duration_ms": round(duration_ms, 1),
            }

        duration_ms = (time.monotonic() - start_time) * 1000
        _write_wal(execution_id, cosmos_client, status="complete",
                   update_fields={"duration_ms": round(duration_ms, 1)})
        logger.info(
            "network_remediation: PE connection approved | "
            "pe=%s rg=%s execution_id=%s (%.0fms)",
            pe_name, resource_group, execution_id, duration_ms,
        )
        return {
            "status": "executed",
            "execution_id": execution_id,
            "message": f"Private endpoint '{pe_name}' connection approved.",
            "duration_ms": round(duration_ms, 1),
        }
    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        _write_wal(execution_id, cosmos_client, status="failed",
                   update_fields={"error": str(exc), "duration_ms": round(duration_ms, 1)})
        logger.error(
            "network_remediation: PE approve failed | pe=%s error=%s (%.0fms)",
            pe_name, exc, duration_ms,
        )
        return {
            "status": "error",
            "execution_id": execution_id,
            "message": str(exc),
            "duration_ms": round(duration_ms, 1),
        }


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

SAFE_NETWORK_ACTIONS: dict[str, Callable] = {
    "firewall_threatintel_off": _fix_firewall_threatintel,
    "pe_not_approved": _fix_pe_approve,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def execute_network_remediation(
    issue: dict,
    subscription_id: str,
    credential: Any,
    cosmos_client: Optional[Any] = None,
) -> dict:
    """Execute auto-fix for a network issue, or return requires_approval.

    Args:
        issue: NetworkIssue dict from fetch_network_topology.
        subscription_id: Azure subscription to operate in.
        credential: Azure credential (DefaultAzureCredential or similar).
        cosmos_client: Optional Cosmos client for WAL audit writes.

    Returns:
        dict with "status" key:
          - "executed"           → fix applied successfully
          - "requires_approval"  → issue type not in SAFE_NETWORK_ACTIONS
          - "error"              → fix attempted but failed
    """
    issue_type: str = issue.get("type", "")
    fix_fn = SAFE_NETWORK_ACTIONS.get(issue_type)

    if fix_fn is None:
        logger.info(
            "network_remediation: issue_type=%s not in SAFE_NETWORK_ACTIONS → requires_approval",
            issue_type,
        )
        return {"status": "requires_approval", "issue_type": issue_type}

    try:
        return await fix_fn(issue, subscription_id, credential, cosmos_client)
    except Exception as exc:
        # Belt-and-suspenders: fix functions should never raise, but guard here too
        logger.error("network_remediation: unexpected error in %s: %s", issue_type, exc)
        return {
            "status": "error",
            "message": str(exc),
            "issue_type": issue_type,
        }
