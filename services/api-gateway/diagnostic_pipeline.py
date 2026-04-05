"""Diagnostic Pipeline — pre-fetches evidence when an incident is ingested.

Runs as a FastAPI BackgroundTask after POST /api/v1/incidents. Collects:
  - Azure Activity Log (last 2h)
  - Azure Resource Health
  - Azure Monitor Metrics (CPU, memory, disk, network — last 2h)
  - Log Analytics (if DIAGNOSTIC_LA_WORKSPACE_ID is configured)

Stores results in Cosmos DB container 'evidence' with id == incident_id.
Updates the incident document in Cosmos to set investigation_status = 'evidence_ready'.

All steps run with individual error handling — partial evidence is better than no evidence.
Pipeline never raises — all failures are logged and stored in the evidence document.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Configuration from environment
PIPELINE_ENABLED = os.environ.get("DIAGNOSTIC_PIPELINE_ENABLED", "true").lower() == "true"
PIPELINE_TIMEOUT = int(os.environ.get("DIAGNOSTIC_PIPELINE_TIMEOUT_SECONDS", "30"))
LA_WORKSPACE_ID = os.environ.get("DIAGNOSTIC_LA_WORKSPACE_ID", "")

# VM metrics to collect by default
VM_METRICS = [
    "Percentage CPU",
    "Available Memory Bytes",
    "Disk Read Bytes/sec",
    "Disk Write Bytes/sec",
    "Network In Total",
    "Network Out Total",
]


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from ARM resource ID."""
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return resource_id.split("/")[idx + 1]  # preserve original case
    except (ValueError, IndexError):
        raise ValueError(f"Cannot extract subscription_id from resource_id: {resource_id}")


async def _collect_activity_log(
    credential: Any,
    resource_id: str,
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Collect Activity Log entries for a resource."""
    start_time = time.monotonic()
    try:
        from azure.mgmt.monitor import MonitorManagementClient

        sub_id = _extract_subscription_id(resource_id)
        start = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
        filter_str = (
            f"eventTimestamp ge '{start.isoformat()}' "
            f"and resourceId eq '{resource_id}'"
        )

        client = MonitorManagementClient(credential, sub_id)
        entries = []
        events = await asyncio.get_event_loop().run_in_executor(
            None, lambda: list(client.activity_logs.list(filter=filter_str))
        )
        for event in events:
            entries.append({
                "eventTimestamp": event.event_timestamp.isoformat() if event.event_timestamp else None,
                "operationName": event.operation_name.value if event.operation_name else None,
                "caller": event.caller,
                "status": event.status.value if event.status else None,
                "level": event.level.value if event.level else None,
                "description": event.description,
            })
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "pipeline: activity_log complete | resource=%s entries=%d duration_ms=%.0f",
            resource_id, len(entries), duration_ms,
        )
        return {"status": "success", "entries": entries, "duration_ms": duration_ms}
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "pipeline: activity_log failed | resource=%s error=%s duration_ms=%.0f",
            resource_id, e, duration_ms, exc_info=True,
        )
        return {"status": "error", "entries": [], "error": str(e), "duration_ms": duration_ms}


async def _collect_resource_health(
    credential: Any,
    resource_id: str,
) -> Dict[str, Any]:
    """Collect Resource Health availability status."""
    start_time = time.monotonic()
    try:
        from azure.mgmt.resourcehealth import MicrosoftResourceHealth

        sub_id = _extract_subscription_id(resource_id)
        client = MicrosoftResourceHealth(credential, sub_id)
        status = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.availability_statuses.get_by_resource(
                resource_uri=resource_id,
                expand="recommendedActions",
            ),
        )
        availability_state = (
            status.properties.availability_state.value
            if status.properties and status.properties.availability_state
            else "Unknown"
        )
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "pipeline: resource_health complete | resource=%s state=%s duration_ms=%.0f",
            resource_id, availability_state, duration_ms,
        )
        return {
            "status": "success",
            "availability_state": availability_state,
            "summary": status.properties.summary if status.properties else None,
            "reason_type": status.properties.reason_type if status.properties else None,
            "occurred_time": (
                status.properties.occurred_time.isoformat()
                if status.properties and status.properties.occurred_time
                else None
            ),
            "duration_ms": duration_ms,
        }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "pipeline: resource_health failed | resource=%s error=%s duration_ms=%.0f",
            resource_id, e, duration_ms, exc_info=True,
        )
        return {"status": "error", "availability_state": "Unknown", "error": str(e), "duration_ms": duration_ms}


async def _collect_metrics(
    credential: Any,
    resource_id: str,
    metric_names: List[str] = VM_METRICS,
    timespan: str = "PT2H",
    interval: str = "PT5M",
) -> Dict[str, Any]:
    """Collect Azure Monitor metrics."""
    start_time = time.monotonic()
    try:
        from azure.mgmt.monitor import MonitorManagementClient

        sub_id = _extract_subscription_id(resource_id)
        client = MonitorManagementClient(credential, sub_id)
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.metrics.list(
                resource_uri=resource_id,
                metricnames=",".join(metric_names),
                timespan=timespan,
                interval=interval,
                aggregation="Average,Maximum,Minimum",
            ),
        )
        metrics_out = []
        for metric in response.value:
            timeseries = []
            for ts in metric.timeseries:
                for dp in ts.data:
                    if dp.time_stamp:
                        timeseries.append({
                            "timestamp": dp.time_stamp.isoformat(),
                            "average": dp.average,
                            "maximum": dp.maximum,
                            "minimum": dp.minimum,
                        })
            metrics_out.append({
                "name": metric.name.value if metric.name else None,
                "unit": metric.unit.value if metric.unit else None,
                "timeseries": timeseries,
            })
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "pipeline: metrics complete | resource=%s metrics_count=%d duration_ms=%.0f",
            resource_id, len(metrics_out), duration_ms,
        )
        return {"status": "success", "metrics": metrics_out, "duration_ms": duration_ms}
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "pipeline: metrics failed | resource=%s error=%s duration_ms=%.0f",
            resource_id, e, duration_ms, exc_info=True,
        )
        return {"status": "error", "metrics": [], "error": str(e), "duration_ms": duration_ms}


async def _collect_log_analytics(
    credential: Any,
    workspace_id: str,
    resource_id: str,
    domain: str,
    timespan: str = "PT2H",
) -> Dict[str, Any]:
    """Collect Log Analytics errors/warnings for the resource."""
    if not workspace_id:
        logger.info("pipeline: log_analytics skipped | reason=workspace_id_not_configured")
        return {"status": "skipped", "rows": [], "duration_ms": 0}

    start_time = time.monotonic()
    try:
        from azure.monitor.query import LogsQueryClient, LogsQueryStatus

        # Build a domain-appropriate KQL query
        kql = _build_kql_for_domain(resource_id, domain)
        client = LogsQueryClient(credential)
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.query_workspace(
                workspace_id=workspace_id,
                query=kql,
                timespan=timespan,
            ),
        )
        rows = []
        if response.status == LogsQueryStatus.SUCCESS:
            for table in response.tables:
                col_names = [col.name for col in table.columns]
                for row in table.rows:
                    rows.append(dict(zip(col_names, [str(v) if v is not None else None for v in row])))
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "pipeline: log_analytics complete | workspace=%s rows=%d duration_ms=%.0f",
            workspace_id, len(rows), duration_ms,
        )
        return {"status": "success", "rows": rows, "kql": kql, "duration_ms": duration_ms}
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "pipeline: log_analytics failed | workspace=%s error=%s duration_ms=%.0f",
            workspace_id, e, duration_ms, exc_info=True,
        )
        return {"status": "error", "rows": [], "error": str(e), "duration_ms": duration_ms}


def _build_kql_for_domain(resource_id: str, domain: str) -> str:
    """Build a KQL query appropriate for the domain and resource."""
    resource_id_lower = resource_id.lower()
    base = (
        f"union Event, Syslog\n"
        f"| where TimeGenerated > ago(2h)\n"
        f"| where _ResourceId =~ '{resource_id_lower}'\n"
        f"| where EventLevelName in ('Error', 'Warning') or SeverityLevel in ('err', 'warning', 'crit', 'alert', 'emerg')\n"
        f"| project TimeGenerated, EventLevelName, SeverityLevel, RenderedDescription, Computer\n"
        f"| order by TimeGenerated desc\n"
        f"| take 50"
    )
    return base


def _build_evidence_summary(
    activity_log: Dict[str, Any],
    resource_health: Dict[str, Any],
    metrics: Dict[str, Any],
    log_analytics: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a human-readable evidence summary from raw pipeline results."""
    # Health state
    health_state = resource_health.get("availability_state", "Unknown")

    # Recent changes from activity log
    recent_changes = [
        {
            "timestamp": e.get("eventTimestamp"),
            "operation": e.get("operationName"),
            "caller": e.get("caller"),
            "status": e.get("status"),
        }
        for e in activity_log.get("entries", [])
        if e.get("status") in ("Started", "Succeeded", "Failed")
    ][:10]  # top 10

    # Metric anomalies — simple threshold checks
    metric_anomalies = []
    THRESHOLDS = {
        "Percentage CPU": ("average", 90, "%"),
        "Available Memory Bytes": ("minimum", 524288000, "bytes", True),  # < 500MB is bad
    }
    for m in metrics.get("metrics", []):
        name = m.get("name")
        if name in THRESHOLDS:
            field, threshold, unit, *flags = THRESHOLDS[name]
            invert = bool(flags)
            for point in m.get("timeseries", []):
                val = point.get(field)
                if val is not None:
                    breached = val < threshold if invert else val > threshold
                    if breached:
                        metric_anomalies.append({
                            "metric_name": name,
                            "current_value": val,
                            "threshold": threshold,
                            "unit": unit,
                            "timestamp": point.get("timestamp"),
                        })
                        break  # one anomaly per metric is enough

    # Log errors
    rows = log_analytics.get("rows", [])
    log_errors = {
        "count": len(rows),
        "sample": [r.get("RenderedDescription") or r.get("Message", "") for r in rows[:3]],
    }

    return {
        "health_state": health_state,
        "recent_changes": recent_changes,
        "metric_anomalies": metric_anomalies,
        "log_errors": log_errors,
    }


async def run_diagnostic_pipeline(
    incident_id: str,
    resource_id: str,
    domain: str,
    credential: Any,
    cosmos_client: Any,
    cosmos_db_name: str = "aap",
) -> None:
    """
    Main pipeline entry point. Called as a BackgroundTask from incident ingestion.

    Collects all diagnostic data in parallel (activity log, resource health, metrics)
    then sequentially runs log analytics (depends on knowing the domain).
    Writes evidence to Cosmos DB. Updates incident investigation_status.

    Args:
        incident_id: Incident ID (used as Cosmos document ID).
        resource_id: Primary affected resource ARM ID.
        domain: Incident domain (compute, network, storage, etc.).
        credential: Azure DefaultAzureCredential instance.
        cosmos_client: CosmosClient instance (may be None in dev mode).
        cosmos_db_name: Cosmos DB database name.
    """
    if not PIPELINE_ENABLED:
        logger.info("pipeline: disabled | incident_id=%s", incident_id)
        return

    pipeline_start = time.monotonic()
    logger.info(
        "pipeline: starting | incident_id=%s resource_id=%s domain=%s",
        incident_id, resource_id, domain,
    )

    try:
        # Step 1: Run activity log, resource health, and metrics in parallel
        activity_task = asyncio.create_task(
            asyncio.wait_for(
                _collect_activity_log(credential, resource_id),
                timeout=PIPELINE_TIMEOUT,
            )
        )
        health_task = asyncio.create_task(
            asyncio.wait_for(
                _collect_resource_health(credential, resource_id),
                timeout=PIPELINE_TIMEOUT,
            )
        )
        metrics_task = asyncio.create_task(
            asyncio.wait_for(
                _collect_metrics(credential, resource_id),
                timeout=PIPELINE_TIMEOUT,
            )
        )

        activity_result, health_result, metrics_result = await asyncio.gather(
            activity_task, health_task, metrics_task, return_exceptions=True
        )

        # Normalize exceptions from gather
        def _safe(result: Any, default: Dict) -> Dict:
            if isinstance(result, Exception):
                logger.error("pipeline: gather_exception | error=%s", result, exc_info=True)
                return {**default, "status": "error", "error": str(result)}
            return result

        activity_result = _safe(activity_result, {"entries": []})
        health_result = _safe(health_result, {"availability_state": "Unknown"})
        metrics_result = _safe(metrics_result, {"metrics": []})

        # Step 2: Log Analytics (sequential — domain already known)
        la_result = await asyncio.wait_for(
            _collect_log_analytics(
                credential, LA_WORKSPACE_ID, resource_id, domain
            ),
            timeout=PIPELINE_TIMEOUT,
        )

        # Step 3: Build evidence summary
        evidence_summary = _build_evidence_summary(
            activity_result, health_result, metrics_result, la_result
        )

        # Step 4: Determine pipeline status
        statuses = [
            activity_result.get("status"),
            health_result.get("status"),
            metrics_result.get("status"),
            la_result.get("status"),
        ]
        if all(s == "success" for s in statuses if s != "skipped"):
            pipeline_status = "complete"
        elif any(s == "success" for s in statuses):
            pipeline_status = "partial"
        else:
            pipeline_status = "failed"

        total_duration_ms = (time.monotonic() - pipeline_start) * 1000

        # Step 5: Write evidence to Cosmos DB
        evidence_doc = {
            "id": incident_id,
            "incident_id": incident_id,
            "resource_id": resource_id,
            "domain": domain,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "collection_duration_ms": total_duration_ms,
            "pipeline_status": pipeline_status,
            "activity_log": activity_result,
            "resource_health": health_result,
            "metrics": metrics_result,
            "log_analytics": la_result,
            "evidence_summary": evidence_summary,
        }

        if cosmos_client is not None:
            try:
                db = cosmos_client.get_database_client(cosmos_db_name)
                container = db.get_container_client("evidence")
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: container.upsert_item(evidence_doc),
                )
                logger.info(
                    "pipeline: evidence written | incident_id=%s status=%s duration_ms=%.0f",
                    incident_id, pipeline_status, total_duration_ms,
                )

                # Step 6: Update incident investigation_status
                # The incidents container uses /resource_id as partition key.
                try:
                    incidents_container = db.get_container_client("incidents")
                    incident_doc = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: incidents_container.read_item(incident_id, partition_key=resource_id),
                    )
                    incident_doc["investigation_status"] = "evidence_ready"
                    incident_doc["evidence_collected_at"] = datetime.now(timezone.utc).isoformat()
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: incidents_container.replace_item(incident_id, incident_doc),
                    )
                    logger.info(
                        "pipeline: incident updated | incident_id=%s investigation_status=evidence_ready",
                        incident_id,
                    )
                except Exception as e:
                    # Incident may not exist in Cosmos yet (Foundry creates it async)
                    logger.warning(
                        "pipeline: incident_update skipped | incident_id=%s reason=%s",
                        incident_id, e,
                    )
            except Exception as e:
                logger.error(
                    "pipeline: cosmos_write failed | incident_id=%s error=%s",
                    incident_id, e, exc_info=True,
                )
        else:
            logger.warning(
                "pipeline: cosmos_client=None | evidence not persisted | incident_id=%s",
                incident_id,
            )
            # Still log summary even without Cosmos
            logger.info(
                "pipeline: evidence_summary | incident_id=%s health=%s changes=%d metric_anomalies=%d log_errors=%d",
                incident_id,
                evidence_summary["health_state"],
                len(evidence_summary["recent_changes"]),
                len(evidence_summary["metric_anomalies"]),
                evidence_summary["log_errors"]["count"],
            )

    except asyncio.TimeoutError:
        total_duration_ms = (time.monotonic() - pipeline_start) * 1000
        logger.error(
            "pipeline: timeout | incident_id=%s timeout_seconds=%d duration_ms=%.0f",
            incident_id, PIPELINE_TIMEOUT, total_duration_ms,
        )
    except Exception as e:
        total_duration_ms = (time.monotonic() - pipeline_start) * 1000
        logger.error(
            "pipeline: fatal_error | incident_id=%s error=%s duration_ms=%.0f",
            incident_id, e, total_duration_ms, exc_info=True,
        )
    # Never raise — pipeline runs in background
