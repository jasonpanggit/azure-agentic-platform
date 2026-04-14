"""Messaging Agent tool functions — Service Bus and Event Hub diagnostics.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_metrics, monitor.query_logs
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry

# ---------------------------------------------------------------------------
# Lazy SDK imports — azure-mgmt-* packages may not be installed in all envs
# ---------------------------------------------------------------------------

try:
    from azure.mgmt.servicebus import ServiceBusManagementClient
except ImportError:
    ServiceBusManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.eventhub import EventHubManagementClient
except ImportError:
    EventHubManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-messaging-agent")
logger = logging.getLogger(__name__)

# Explicit MCP tool allowlist — no wildcards permitted.
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor.query_metrics",
    "monitor.query_logs",
]


def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {
        "azure-mgmt-servicebus": "azure.mgmt.servicebus",
        "azure-mgmt-eventhub": "azure.mgmt.eventhub",
        "azure-mgmt-monitor": "azure.mgmt.monitor",
    }
    for pkg, module in packages.items():
        try:
            __import__(module)
            logger.info("messaging_tools: sdk_available | package=%s", pkg)
        except ImportError:
            logger.warning(
                "messaging_tools: sdk_missing | package=%s — tool will return error", pkg
            )


_log_sdk_availability()


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from an Azure resource ID.

    Args:
        resource_id: Azure resource ID in the form
            /subscriptions/{sub}/resourceGroups/{rg}/providers/{type}/{name}

    Returns:
        Subscription ID string (lowercase).

    Raises:
        ValueError: If the subscription segment cannot be found.
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        raise ValueError(
            f"Cannot extract subscription_id from resource_id: {resource_id}"
        )


# ===========================================================================
# Service Bus tools
# ===========================================================================


@ai_function
def get_servicebus_namespace_health(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Retrieve health and configuration for an Azure Service Bus namespace (SB-HEALTH-001).

    Fetches ARM properties: SKU tier, capacity (messaging units for Premium),
    status, provisioning state, zone redundancy, and geo-replication status.
    Use as the first step when triaging Service Bus namespace incidents.

    Args:
        namespace_name: Service Bus namespace name.
        resource_group: Resource group containing the namespace.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            namespace_name (str): Namespace name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            sku_tier (str | None): SKU tier — "Basic", "Standard", or "Premium".
            sku_capacity (int | None): Messaging units (Premium only).
            status (str | None): Namespace status — "Active", "Creating", etc.
            provisioning_state (str | None): ARM provisioning state.
            zone_redundant (bool | None): Whether zone redundancy is enabled.
            geo_replication_enabled (bool | None): Whether geo-replication is configured.
            location (str | None): Azure region.
            query_status (str): "success" or "error".
            duration_ms (float): Query duration in milliseconds.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "namespace_name": namespace_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="messaging-agent",
        agent_id=agent_id,
        tool_name="get_servicebus_namespace_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if ServiceBusManagementClient is None:
                raise ImportError("azure-mgmt-servicebus is not installed")

            credential = get_credential()
            client = ServiceBusManagementClient(credential, subscription_id)
            ns = client.namespaces.get(resource_group, namespace_name)

            sku = getattr(ns, "sku", None)
            sku_tier = getattr(sku, "name", None) if sku else None
            sku_capacity = getattr(sku, "capacity", None) if sku else None
            geo_replication_enabled = getattr(ns, "geo_data_replication", None) is not None

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_servicebus_namespace_health: complete | ns=%s status=%s duration_ms=%.0f",
                namespace_name,
                getattr(ns, "status", None),
                duration_ms,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "sku_tier": sku_tier,
                "sku_capacity": sku_capacity,
                "status": getattr(ns, "status", None),
                "provisioning_state": getattr(ns, "provisioning_state", None),
                "zone_redundant": getattr(ns, "zone_redundant", None),
                "geo_replication_enabled": geo_replication_enabled,
                "location": getattr(ns, "location", None),
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_servicebus_namespace_health: failed | ns=%s error=%s duration_ms=%.0f",
                namespace_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "sku_tier": None,
                "sku_capacity": None,
                "status": None,
                "provisioning_state": None,
                "zone_redundant": None,
                "geo_replication_enabled": None,
                "location": None,
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


@ai_function
def list_servicebus_queues(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """List all queues in an Azure Service Bus namespace with message depth data (SB-QUEUES-001).

    Returns queue count, message counts (active, dead-letter, scheduled), lock duration,
    delivery settings, and entity size for each queue. DLQ depth is the primary triage
    signal for backlog or poison-message incidents.

    Note: Topics are not included in this tool (deferred per Phase 49 scope). For topic
    DLQ monitoring, use Azure Monitor metrics or a follow-on tool.

    Args:
        namespace_name: Service Bus namespace name.
        resource_group: Resource group containing the namespace.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            namespace_name (str): Namespace name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            queue_count (int): Total number of queues found.
            queues (list): Each entry contains queue_name, status, message_count,
                active_message_count, dead_letter_message_count, scheduled_message_count,
                max_delivery_count, lock_duration_seconds, dead_lettering_on_expiration,
                requires_session, size_in_bytes.
            query_status (str): "success" or "error".
            duration_ms (float): Query duration in milliseconds.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "namespace_name": namespace_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="messaging-agent",
        agent_id=agent_id,
        tool_name="list_servicebus_queues",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if ServiceBusManagementClient is None:
                raise ImportError("azure-mgmt-servicebus is not installed")

            credential = get_credential()
            client = ServiceBusManagementClient(credential, subscription_id)
            queues_iter = client.queues.list_by_namespace(resource_group, namespace_name)

            queues: List[Dict[str, Any]] = []
            for q in queues_iter:
                # count_details can be None when namespace is throttled
                cd = getattr(q, "count_details", None)
                active = getattr(cd, "active_message_count", None) if cd else None
                dlq = getattr(cd, "dead_letter_message_count", None) if cd else None
                scheduled = getattr(cd, "scheduled_message_count", None) if cd else None

                # lock_duration is a timedelta, convert to seconds
                ld = getattr(q, "lock_duration", None)
                lock_duration_seconds = ld.total_seconds() if ld else None

                queues.append({
                    "queue_name": getattr(q, "name", None),
                    "status": getattr(q, "status", None),
                    "message_count": getattr(q, "message_count", None),
                    "active_message_count": active,
                    "dead_letter_message_count": dlq,
                    "scheduled_message_count": scheduled,
                    "max_delivery_count": getattr(q, "max_delivery_count", None),
                    "lock_duration_seconds": lock_duration_seconds,
                    "dead_lettering_on_expiration": getattr(
                        q, "dead_lettering_on_message_expiration", None
                    ),
                    "requires_session": getattr(q, "requires_session", None),
                    "size_in_bytes": getattr(q, "size_in_bytes", None),
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "list_servicebus_queues: complete | ns=%s queue_count=%d duration_ms=%.0f",
                namespace_name,
                len(queues),
                duration_ms,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "queue_count": len(queues),
                "queues": queues,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "list_servicebus_queues: failed | ns=%s error=%s duration_ms=%.0f",
                namespace_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "queue_count": 0,
                "queues": [],
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


@ai_function
def get_servicebus_metrics(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
    hours: int = 4,
    entity_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Query Azure Monitor metrics for a Service Bus namespace (SB-METRICS-001).

    Retrieves incoming/outgoing message counts, active/dead-lettered message
    averages, server errors, throttled requests, and user errors via Azure Monitor.

    Args:
        namespace_name: Service Bus namespace name.
        resource_group: Resource group containing the namespace.
        subscription_id: Azure subscription ID.
        hours: Look-back window in hours (default: 4).
        entity_name: Optional filter to scope metrics to a specific queue or topic.

    Returns:
        Dict with keys:
            namespace_name (str): Namespace name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            timespan_hours (int): Look-back window applied.
            entity_name (str | None): Entity name filter applied (None = namespace-level).
            incoming_messages (float | None): Total incoming messages in window.
            outgoing_messages (float | None): Total outgoing messages in window.
            active_messages_avg (float | None): Average active messages.
            dead_lettered_messages_avg (float | None): Average dead-lettered messages.
            server_errors (int | None): Total server errors.
            throttled_requests (int | None): Total throttled requests.
            user_errors (int | None): Total user errors.
            data_points (list): Raw per-metric time-series data.
            query_status (str): "success" or "error".
            duration_ms (float): Query duration in milliseconds.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "namespace_name": namespace_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
        "hours": hours,
        "entity_name": entity_name,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="messaging-agent",
        agent_id=agent_id,
        tool_name="get_servicebus_metrics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            resource_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.ServiceBus/namespaces/{namespace_name}"
            )
            client = MonitorManagementClient(credential, subscription_id)

            timespan = f"PT{hours}H"
            metric_names = (
                "IncomingMessages,OutgoingMessages,ActiveMessages,"
                "DeadletteredMessages,ServerErrors,ThrottledRequests,UserErrors"
            )

            kwargs: Dict[str, Any] = {
                "resource_uri": resource_id,
                "metricnames": metric_names,
                "timespan": timespan,
                "interval": "PT5M",
                "aggregation": "Total,Average",
            }
            if entity_name is not None:
                kwargs["filter"] = f"EntityName eq '{entity_name}'"

            response = client.metrics.list(**kwargs)

            # Accumulators
            incoming_total: Optional[float] = None
            outgoing_total: Optional[float] = None
            active_avgs: List[float] = []
            dlq_avgs: List[float] = []
            server_errors_total: float = 0.0
            throttled_total: float = 0.0
            user_errors_total: float = 0.0
            data_points: List[Dict[str, Any]] = []

            for metric in response.value:
                metric_name_val = metric.name.value if metric.name else ""
                for ts in metric.timeseries:
                    for dp in ts.data:
                        ts_str = dp.time_stamp.isoformat() if dp.time_stamp else None
                        data_points.append({
                            "metric": metric_name_val,
                            "timestamp": ts_str,
                            "average": dp.average,
                            "total": dp.total,
                        })
                        if metric_name_val == "IncomingMessages":
                            if dp.total is not None:
                                incoming_total = (incoming_total or 0.0) + dp.total
                        elif metric_name_val == "OutgoingMessages":
                            if dp.total is not None:
                                outgoing_total = (outgoing_total or 0.0) + dp.total
                        elif metric_name_val == "ActiveMessages":
                            if dp.average is not None:
                                active_avgs.append(dp.average)
                        elif metric_name_val == "DeadletteredMessages":
                            if dp.average is not None:
                                dlq_avgs.append(dp.average)
                        elif metric_name_val == "ServerErrors":
                            if dp.total is not None:
                                server_errors_total += dp.total
                        elif metric_name_val == "ThrottledRequests":
                            if dp.total is not None:
                                throttled_total += dp.total
                        elif metric_name_val == "UserErrors":
                            if dp.total is not None:
                                user_errors_total += dp.total

            active_messages_avg: Optional[float] = (
                sum(active_avgs) / len(active_avgs) if active_avgs else None
            )
            dead_lettered_messages_avg: Optional[float] = (
                sum(dlq_avgs) / len(dlq_avgs) if dlq_avgs else None
            )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_servicebus_metrics: complete | ns=%s incoming=%.0f throttled=%d "
                "duration_ms=%.0f",
                namespace_name,
                incoming_total or 0.0,
                int(throttled_total),
                duration_ms,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "timespan_hours": hours,
                "entity_name": entity_name,
                "incoming_messages": incoming_total,
                "outgoing_messages": outgoing_total,
                "active_messages_avg": active_messages_avg,
                "dead_lettered_messages_avg": dead_lettered_messages_avg,
                "server_errors": int(server_errors_total),
                "throttled_requests": int(throttled_total),
                "user_errors": int(user_errors_total),
                "data_points": data_points,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_servicebus_metrics: failed | ns=%s error=%s duration_ms=%.0f",
                namespace_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "timespan_hours": hours,
                "entity_name": entity_name,
                "incoming_messages": None,
                "outgoing_messages": None,
                "active_messages_avg": None,
                "dead_lettered_messages_avg": None,
                "server_errors": None,
                "throttled_requests": None,
                "user_errors": None,
                "data_points": [],
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


@ai_function
def propose_servicebus_dlq_purge(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
    queue_name: str,
    reason: str,
) -> Dict[str, Any]:
    """Propose a Service Bus dead-letter queue purge for operator approval (SB-REMEDI-001).

    Generates a HITL approval request to purge the dead-letter queue (DLQ) for
    a specific queue. The Messaging Agent MUST NOT purge the DLQ directly —
    proposals only (REMEDI-001). Call only after confirming elevated DLQ depth
    via list_servicebus_queues and verifying messages have been inspected or archived.

    DLQ purge is low-risk from a system-stability perspective but is NOT reversible —
    all DLQ messages are permanently deleted. Operator must confirm intent.

    Args:
        namespace_name: Service Bus namespace name.
        resource_group: Resource group containing the namespace.
        subscription_id: Azure subscription ID.
        queue_name: Queue whose dead-letter sub-queue will be purged.
        reason: Human-readable justification for the purge.

    Returns:
        Dict with mandatory approval_required=True and all proposal fields.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "namespace_name": namespace_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
        "queue_name": queue_name,
        "reason": reason,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="messaging-agent",
        agent_id=agent_id,
        tool_name="propose_servicebus_dlq_purge",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "proposal_type": "servicebus_dlq_purge",
            "namespace_name": namespace_name,
            "resource_group": resource_group,
            "subscription_id": subscription_id,
            "queue_name": queue_name,
            "reason": reason,
            "risk_level": "low",
            "proposed_action": (
                f"Purge dead-letter queue '{queue_name}' on Service Bus namespace "
                f"'{namespace_name}' in resource group '{resource_group}' "
                f"(subscription: {subscription_id})"
            ),
            "reversibility": (
                "NOT reversible — DLQ messages are permanently deleted after purge. "
                "Ensure all DLQ messages have been inspected or archived before approving."
            ),
            # REMEDI-001: All proposals require explicit human approval before execution.
            "approval_required": True,
        }


# ===========================================================================
# Event Hub tools
# ===========================================================================


@ai_function
def get_eventhub_namespace_health(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """Retrieve health and configuration for an Azure Event Hubs namespace (EH-HEALTH-001).

    Fetches ARM properties: SKU name, capacity (throughput units), status,
    provisioning state, zone redundancy, Kafka enablement, and auto-inflate settings.
    Use as the first step when triaging Event Hub namespace incidents.

    Args:
        namespace_name: Event Hubs namespace name.
        resource_group: Resource group containing the namespace.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            namespace_name (str): Namespace name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            sku_name (str | None): SKU name — "Basic", "Standard", or "Premium".
            sku_capacity (int | None): Throughput units (Standard) or Processing units (Premium).
            status (str | None): Namespace status — "Active", "Creating", etc.
            provisioning_state (str | None): ARM provisioning state.
            zone_redundant (bool | None): Whether zone redundancy is enabled.
            kafka_enabled (bool | None): Whether Kafka protocol support is enabled.
            is_auto_inflate_enabled (bool | None): Whether auto-inflate is enabled.
            maximum_throughput_units (int | None): Maximum auto-inflate throughput units.
            location (str | None): Azure region.
            query_status (str): "success" or "error".
            duration_ms (float): Query duration in milliseconds.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "namespace_name": namespace_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="messaging-agent",
        agent_id=agent_id,
        tool_name="get_eventhub_namespace_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if EventHubManagementClient is None:
                raise ImportError("azure-mgmt-eventhub is not installed")

            credential = get_credential()
            client = EventHubManagementClient(credential, subscription_id)
            ns = client.namespaces.get(resource_group, namespace_name)

            sku = getattr(ns, "sku", None)
            sku_name = getattr(sku, "name", None) if sku else None
            sku_capacity = getattr(sku, "capacity", None) if sku else None

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_eventhub_namespace_health: complete | ns=%s status=%s duration_ms=%.0f",
                namespace_name,
                getattr(ns, "status", None),
                duration_ms,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "sku_name": sku_name,
                "sku_capacity": sku_capacity,
                "status": getattr(ns, "status", None),
                "provisioning_state": getattr(ns, "provisioning_state", None),
                "zone_redundant": getattr(ns, "zone_redundant", None),
                "kafka_enabled": getattr(ns, "kafka_enabled", None),
                "is_auto_inflate_enabled": getattr(ns, "is_auto_inflate_enabled", None),
                "maximum_throughput_units": getattr(ns, "maximum_throughput_units", None),
                "location": getattr(ns, "location", None),
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_eventhub_namespace_health: failed | ns=%s error=%s duration_ms=%.0f",
                namespace_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "sku_name": None,
                "sku_capacity": None,
                "status": None,
                "provisioning_state": None,
                "zone_redundant": None,
                "kafka_enabled": None,
                "is_auto_inflate_enabled": None,
                "maximum_throughput_units": None,
                "location": None,
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


@ai_function
def list_eventhub_consumer_groups(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
    """List all Event Hubs and their consumer groups in a namespace (EH-CONSUMER-001).

    For each Event Hub in the namespace, lists consumer groups with their metadata.
    Returns partition count and capture status per Event Hub.

    Note: Per-partition consumer lag is not available from the management plane SDK.
    The management SDK consumer group object only exposes name, created_at, updated_at,
    and user_metadata — no offset or sequence number. Use get_eventhub_metrics for
    aggregate lag estimation (incoming vs outgoing message delta).

    Args:
        namespace_name: Event Hubs namespace name.
        resource_group: Resource group containing the namespace.
        subscription_id: Azure subscription ID.

    Returns:
        Dict with keys:
            namespace_name (str): Namespace name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            eventhub_count (int): Total number of Event Hubs found.
            eventhubs (list): Each entry contains eventhub_name, partition_count,
                status, message_retention_in_days, capture_enabled,
                consumer_group_count, consumer_groups (list of {consumer_group_name,
                created_at, updated_at, user_metadata}).
            query_status (str): "success" or "error".
            duration_ms (float): Query duration in milliseconds.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "namespace_name": namespace_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="messaging-agent",
        agent_id=agent_id,
        tool_name="list_eventhub_consumer_groups",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if EventHubManagementClient is None:
                raise ImportError("azure-mgmt-eventhub is not installed")

            credential = get_credential()
            client = EventHubManagementClient(credential, subscription_id)

            eventhubs: List[Dict[str, Any]] = []
            for eh in client.event_hubs.list_by_namespace(resource_group, namespace_name):
                consumer_groups: List[Dict[str, Any]] = []
                for cg in client.consumer_groups.list_by_event_hub(
                    resource_group, namespace_name, eh.name
                ):
                    ca = getattr(cg, "created_at", None)
                    ua = getattr(cg, "updated_at", None)
                    consumer_groups.append({
                        "consumer_group_name": getattr(cg, "name", None),
                        "created_at": (
                            ca.isoformat() if hasattr(ca, "isoformat") else str(ca)
                        ) if ca is not None else None,
                        "updated_at": (
                            ua.isoformat() if hasattr(ua, "isoformat") else str(ua)
                        ) if ua is not None else None,
                        "user_metadata": getattr(cg, "user_metadata", None),
                    })

                capture = getattr(eh, "capture_description", None)
                capture_enabled = getattr(capture, "enabled", False) if capture else False

                eventhubs.append({
                    "eventhub_name": getattr(eh, "name", None),
                    "partition_count": getattr(eh, "partition_count", None),
                    "status": getattr(eh, "status", None),
                    "message_retention_in_days": getattr(
                        eh, "message_retention_in_days", None
                    ),
                    "capture_enabled": capture_enabled,
                    "consumer_group_count": len(consumer_groups),
                    "consumer_groups": consumer_groups,
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "list_eventhub_consumer_groups: complete | ns=%s eh_count=%d duration_ms=%.0f",
                namespace_name,
                len(eventhubs),
                duration_ms,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "eventhub_count": len(eventhubs),
                "eventhubs": eventhubs,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "list_eventhub_consumer_groups: failed | ns=%s error=%s duration_ms=%.0f",
                namespace_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "eventhub_count": 0,
                "eventhubs": [],
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }


@ai_function
def get_eventhub_metrics(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
    hours: int = 4,
    eventhub_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Query Azure Monitor metrics for an Event Hubs namespace (EH-METRICS-001).

    Retrieves incoming/outgoing message and byte counts, throttled requests,
    server errors, and user errors via Azure Monitor. Derives an estimated
    consumer lag count as (incoming_messages - outgoing_messages) over the window.

    Note: estimated_lag_count is an approximation based on aggregate metrics.
    For exact per-partition lag, the data-plane SDK (EventHubConsumerClient)
    is required, which needs a connection string or SAS token — not available
    in this read-only managed-identity agent.

    Args:
        namespace_name: Event Hubs namespace name.
        resource_group: Resource group containing the namespace.
        subscription_id: Azure subscription ID.
        hours: Look-back window in hours (default: 4).
        eventhub_name: Optional filter to scope metrics to a specific Event Hub entity.

    Returns:
        Dict with keys:
            namespace_name (str): Namespace name.
            resource_group (str): Resource group.
            subscription_id (str): Subscription queried.
            timespan_hours (int): Look-back window applied.
            eventhub_name (str | None): Event Hub filter applied (None = namespace-level).
            incoming_messages (float | None): Total incoming messages in window.
            outgoing_messages (float | None): Total outgoing messages in window.
            incoming_bytes (float | None): Total incoming bytes in window.
            outgoing_bytes (float | None): Total outgoing bytes in window.
            throttled_requests (int | None): Total throttled requests.
            server_errors (int | None): Total server errors.
            user_errors (int | None): Total user errors.
            estimated_lag_count (int | None): Approximate lag = incoming - outgoing.
            data_points (list): Raw per-metric time-series data.
            query_status (str): "success" or "error".
            duration_ms (float): Query duration in milliseconds.
    """
    agent_id = get_agent_identity()
    tool_params = {
        "namespace_name": namespace_name,
        "resource_group": resource_group,
        "subscription_id": subscription_id,
        "hours": hours,
        "eventhub_name": eventhub_name,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="messaging-agent",
        agent_id=agent_id,
        tool_name="get_eventhub_metrics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            resource_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.EventHub/namespaces/{namespace_name}"
            )
            client = MonitorManagementClient(credential, subscription_id)

            timespan = f"PT{hours}H"
            metric_names = (
                "IncomingMessages,OutgoingMessages,IncomingBytes,OutgoingBytes,"
                "ThrottledRequests,ServerErrors,UserErrors"
            )

            kwargs: Dict[str, Any] = {
                "resource_uri": resource_id,
                "metricnames": metric_names,
                "timespan": timespan,
                "interval": "PT5M",
                "aggregation": "Total",
            }
            if eventhub_name is not None:
                kwargs["filter"] = f"EntityName eq '{eventhub_name}'"

            response = client.metrics.list(**kwargs)

            # Accumulators
            incoming_total: Optional[float] = None
            outgoing_total: Optional[float] = None
            incoming_bytes_total: Optional[float] = None
            outgoing_bytes_total: Optional[float] = None
            throttled_total: float = 0.0
            server_errors_total: float = 0.0
            user_errors_total: float = 0.0
            data_points: List[Dict[str, Any]] = []

            for metric in response.value:
                metric_name_val = metric.name.value if metric.name else ""
                for ts in metric.timeseries:
                    for dp in ts.data:
                        ts_str = dp.time_stamp.isoformat() if dp.time_stamp else None
                        data_points.append({
                            "metric": metric_name_val,
                            "timestamp": ts_str,
                            "total": dp.total,
                        })
                        if dp.total is None:
                            continue
                        if metric_name_val == "IncomingMessages":
                            incoming_total = (incoming_total or 0.0) + dp.total
                        elif metric_name_val == "OutgoingMessages":
                            outgoing_total = (outgoing_total or 0.0) + dp.total
                        elif metric_name_val == "IncomingBytes":
                            incoming_bytes_total = (incoming_bytes_total or 0.0) + dp.total
                        elif metric_name_val == "OutgoingBytes":
                            outgoing_bytes_total = (outgoing_bytes_total or 0.0) + dp.total
                        elif metric_name_val == "ThrottledRequests":
                            throttled_total += dp.total
                        elif metric_name_val == "ServerErrors":
                            server_errors_total += dp.total
                        elif metric_name_val == "UserErrors":
                            user_errors_total += dp.total

            estimated_lag_count: Optional[int] = (
                int(incoming_total - outgoing_total)
                if incoming_total is not None and outgoing_total is not None
                else None
            )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "get_eventhub_metrics: complete | ns=%s incoming=%.0f lag=%s "
                "throttled=%d duration_ms=%.0f",
                namespace_name,
                incoming_total or 0.0,
                estimated_lag_count,
                int(throttled_total),
                duration_ms,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "timespan_hours": hours,
                "eventhub_name": eventhub_name,
                "incoming_messages": incoming_total,
                "outgoing_messages": outgoing_total,
                "incoming_bytes": incoming_bytes_total,
                "outgoing_bytes": outgoing_bytes_total,
                "throttled_requests": int(throttled_total),
                "server_errors": int(server_errors_total),
                "user_errors": int(user_errors_total),
                "estimated_lag_count": estimated_lag_count,
                "data_points": data_points,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "get_eventhub_metrics: failed | ns=%s error=%s duration_ms=%.0f",
                namespace_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "namespace_name": namespace_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "timespan_hours": hours,
                "eventhub_name": eventhub_name,
                "incoming_messages": None,
                "outgoing_messages": None,
                "incoming_bytes": None,
                "outgoing_bytes": None,
                "throttled_requests": None,
                "server_errors": None,
                "user_errors": None,
                "estimated_lag_count": None,
                "data_points": [],
                "query_status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            }
