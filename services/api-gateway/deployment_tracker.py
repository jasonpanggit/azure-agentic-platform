from __future__ import annotations
"""Deployment Tracker — GitOps integration for deployment event ingestion and correlation (Phase 60).

Architecture:
- DeploymentEvent: Pydantic model for deployment events (GitHub Actions / Azure DevOps)
- DeploymentTracker: Cosmos DB persistence + DeploymentCorrelator logic
- DeploymentCorrelator: find deployments correlated to an incident timestamp + resource_group
- All functions never raise — return structured error dicts

Cosmos container: `deployments` (partition key: resource_group)
"""
import os

import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment config
# ---------------------------------------------------------------------------

COSMOS_DATABASE: str = os.environ.get("COSMOS_DATABASE", "aap")
COSMOS_DEPLOYMENTS_CONTAINER: str = os.environ.get(
    "COSMOS_DEPLOYMENTS_CONTAINER", "deployments"
)

# Correlation window: -30min before incident to +5min after
CORRELATION_WINDOW_BEFORE_MIN: int = int(
    os.environ.get("DEPLOYMENT_CORRELATION_BEFORE_MIN", "30")
)
CORRELATION_WINDOW_AFTER_MIN: int = int(
    os.environ.get("DEPLOYMENT_CORRELATION_AFTER_MIN", "5")
)


def _log_availability() -> None:
    logger.debug("deployment_tracker: module loaded (no optional SDK imports required)")


_log_availability()


# ---------------------------------------------------------------------------
# DeploymentEvent model
# ---------------------------------------------------------------------------

class DeploymentEvent(BaseModel):
    """Deployment event model — ingested from GitHub Actions / Azure DevOps webhooks."""

    deployment_id: str = Field(
        default_factory=lambda: f"dep-{uuid.uuid4().hex[:12]}",
        description="Unique deployment ID",
    )
    source: str = Field(
        default="github",
        description="Source CI/CD system: 'github' or 'azdo'",
    )
    repository: str = Field(description="Repository name (e.g., 'org/repo')")
    environment: str = Field(
        default="production",
        description="Target deployment environment (e.g., 'production', 'staging')",
    )
    status: str = Field(
        description="Deployment status: 'success', 'failure', 'in_progress', 'queued', 'cancelled'"
    )
    commit_sha: str = Field(description="Git commit SHA (full or short)")
    author: str = Field(description="Deploying author / actor username")
    pipeline_url: str = Field(
        default="",
        description="URL to the CI/CD pipeline run",
    )
    resource_group: str = Field(
        default="",
        description="Azure resource group targeted by this deployment",
    )
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 deployment start timestamp",
    )
    completed_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 deployment completion timestamp (None if in-progress)",
    )


# ---------------------------------------------------------------------------
# DeploymentTracker
# ---------------------------------------------------------------------------

class DeploymentTracker:
    """Handles deployment event persistence and correlation against incidents."""

    def __init__(self, cosmos_client: Any) -> None:
        self._cosmos = cosmos_client
        self._container: Optional[Any] = None

    def _get_container(self) -> Any:
        """Return or lazily init the Cosmos `deployments` container client."""
        if self._container is None:
            db = self._cosmos.get_database_client(COSMOS_DATABASE)
            try:
                self._container = db.create_container_if_not_exists(
                    id=COSMOS_DEPLOYMENTS_CONTAINER,
                    partition_key={"paths": ["/resource_group"], "kind": "Hash"},
                )
            except Exception:
                self._container = db.get_container_client(COSMOS_DEPLOYMENTS_CONTAINER)
        return self._container

    def ingest_event(self, event: DeploymentEvent) -> Dict[str, Any]:
        """Persist a deployment event to Cosmos DB.

        Args:
            event: DeploymentEvent to store.

        Returns:
            Dict with deployment_id, status, or error on failure.
            Never raises.
        """
        start_time = time.monotonic()

        if self._cosmos is None:
            logger.warning("deployment_tracker: ingest_event — cosmos_client is None")
            return {
                "error": "Cosmos DB not configured",
                "deployment_id": event.deployment_id,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }

        try:
            container = self._get_container()
            doc: Dict[str, Any] = {
                "id": event.deployment_id,
                **event.model_dump(),
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }
            # Use resource_group as partition key — fall back to "unknown" if empty
            if not doc.get("resource_group"):
                doc["resource_group"] = "unknown"
            container.upsert_item(doc)
            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            logger.info(
                "deployment_tracker: ingest_event | deployment_id=%s repo=%s env=%s status=%s duration_ms=%s",
                event.deployment_id,
                event.repository,
                event.environment,
                event.status,
                duration_ms,
            )
            return {
                "deployment_id": event.deployment_id,
                "status": "stored",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            logger.warning(
                "deployment_tracker: ingest_event error | deployment_id=%s error=%s",
                event.deployment_id,
                exc,
            )
            return {
                "error": str(exc),
                "deployment_id": event.deployment_id,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }

    def list_recent(
        self,
        resource_group: Optional[str] = None,
        limit: int = 20,
        hours_back: int = 24,
    ) -> Dict[str, Any]:
        """List recent deployments.

        Args:
            resource_group: Filter by resource group (None = all groups).
            limit: Max number of deployments to return.
            hours_back: Look-back window in hours.

        Returns:
            Dict with deployments list and metadata.
            Never raises.
        """
        start_time = time.monotonic()

        if self._cosmos is None:
            return {
                "deployments": [],
                "total": 0,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                "error": "Cosmos DB not configured",
            }

        try:
            container = self._get_container()
            cutoff = (
                datetime.now(timezone.utc) - timedelta(hours=hours_back)
            ).isoformat()

            if resource_group:
                query = (
                    "SELECT * FROM c WHERE c.resource_group = @rg "
                    "AND c.started_at >= @cutoff "
                    "ORDER BY c.started_at DESC "
                    f"OFFSET 0 LIMIT {limit}"
                )
                params = [
                    {"name": "@rg", "value": resource_group},
                    {"name": "@cutoff", "value": cutoff},
                ]
                items = list(
                    container.query_items(
                        query=query,
                        parameters=params,
                        partition_key=resource_group,
                    )
                )
            else:
                query = (
                    "SELECT * FROM c WHERE c.started_at >= @cutoff "
                    "ORDER BY c.started_at DESC "
                    f"OFFSET 0 LIMIT {limit}"
                )
                params = [{"name": "@cutoff", "value": cutoff}]
                items = list(
                    container.query_items(
                        query=query,
                        parameters=params,
                        enable_cross_partition_query=True,
                    )
                )

            clean = [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]
            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            logger.info(
                "deployment_tracker: list_recent | rg=%s hours_back=%d count=%d duration_ms=%s",
                resource_group,
                hours_back,
                len(clean),
                duration_ms,
            )
            return {
                "deployments": clean,
                "total": len(clean),
                "hours_back": hours_back,
                "resource_group": resource_group,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration_ms,
            }

        except Exception as exc:
            logger.warning("deployment_tracker: list_recent error | error=%s", exc)
            return {
                "deployments": [],
                "total": 0,
                "error": str(exc),
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }

    def correlate(
        self,
        incident_timestamp: str,
        resource_group: Optional[str] = None,
        before_min: int = CORRELATION_WINDOW_BEFORE_MIN,
        after_min: int = CORRELATION_WINDOW_AFTER_MIN,
    ) -> Dict[str, Any]:
        """Find deployments correlated to an incident by timestamp + resource_group.

        Correlation window: [incident_time - before_min, incident_time + after_min].

        Args:
            incident_timestamp: ISO 8601 string of incident creation time.
            resource_group: Azure resource group to scope correlation.
            before_min: Minutes before incident to include (default 30).
            after_min: Minutes after incident to include (default 5).

        Returns:
            Dict with correlated_deployments list, window boundaries, and metadata.
            Never raises.
        """
        start_time = time.monotonic()

        try:
            incident_dt = datetime.fromisoformat(
                incident_timestamp.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError) as exc:
            return {
                "error": f"Invalid incident_timestamp: {exc}",
                "correlated_deployments": [],
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }

        window_start = (incident_dt - timedelta(minutes=before_min)).isoformat()
        window_end = (incident_dt + timedelta(minutes=after_min)).isoformat()

        if self._cosmos is None:
            return {
                "correlated_deployments": [],
                "window_start": window_start,
                "window_end": window_end,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                "error": "Cosmos DB not configured",
            }

        try:
            container = self._get_container()

            if resource_group:
                query = (
                    "SELECT * FROM c WHERE c.resource_group = @rg "
                    "AND c.started_at >= @ws AND c.started_at <= @we "
                    "ORDER BY c.started_at DESC"
                )
                params = [
                    {"name": "@rg", "value": resource_group},
                    {"name": "@ws", "value": window_start},
                    {"name": "@we", "value": window_end},
                ]
                items = list(
                    container.query_items(
                        query=query,
                        parameters=params,
                        partition_key=resource_group,
                    )
                )
            else:
                query = (
                    "SELECT * FROM c WHERE c.started_at >= @ws AND c.started_at <= @we "
                    "ORDER BY c.started_at DESC"
                )
                params = [
                    {"name": "@ws", "value": window_start},
                    {"name": "@we", "value": window_end},
                ]
                items = list(
                    container.query_items(
                        query=query,
                        parameters=params,
                        enable_cross_partition_query=True,
                    )
                )

            clean = [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]

            # Annotate each deployment with time_before_incident_min
            for dep in clean:
                try:
                    dep_dt = datetime.fromisoformat(
                        dep["started_at"].replace("Z", "+00:00")
                    )
                    delta_min = (incident_dt - dep_dt).total_seconds() / 60.0
                    dep["time_before_incident_min"] = round(delta_min, 1)
                except Exception:
                    dep["time_before_incident_min"] = None

            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            logger.info(
                "deployment_tracker: correlate | rg=%s incident=%s correlated=%d duration_ms=%s",
                resource_group,
                incident_timestamp,
                len(clean),
                duration_ms,
            )
            return {
                "correlated_deployments": clean,
                "window_start": window_start,
                "window_end": window_end,
                "incident_timestamp": incident_timestamp,
                "resource_group": resource_group,
                "before_min": before_min,
                "after_min": after_min,
                "duration_ms": duration_ms,
            }

        except Exception as exc:
            logger.warning("deployment_tracker: correlate error | error=%s", exc)
            return {
                "correlated_deployments": [],
                "window_start": window_start,
                "window_end": window_end,
                "error": str(exc),
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }


# ---------------------------------------------------------------------------
# GitHub webhook payload parsing
# ---------------------------------------------------------------------------

def parse_github_deployment_payload(payload: Dict[str, Any]) -> Optional[DeploymentEvent]:
    """Parse a GitHub Actions deployment webhook payload into a DeploymentEvent.

    Supports both 'deployment' event (push-triggered) and 'deployment_status' event.

    Args:
        payload: Raw GitHub webhook payload dict.

    Returns:
        DeploymentEvent if parseable, None otherwise.
        Never raises.
    """
    try:
        # Handle deployment_status event (has nested deployment + deployment_status)
        deployment = payload.get("deployment") or payload
        deployment_status = payload.get("deployment_status") or {}

        repo = payload.get("repository", {})
        repository = repo.get("full_name") or repo.get("name") or payload.get("repository", "unknown")

        status_raw = (
            deployment_status.get("state")
            or deployment.get("task")
            or payload.get("action", "in_progress")
        )
        # Normalize GitHub status values
        status_map = {
            "success": "success",
            "failure": "failure",
            "error": "failure",
            "pending": "in_progress",
            "in_progress": "in_progress",
            "queued": "queued",
            "cancelled": "cancelled",
            "deploy": "in_progress",
        }
        status = status_map.get(status_raw.lower() if status_raw else "", "in_progress")

        commit_sha = (
            deployment.get("sha")
            or payload.get("after", "")
            or payload.get("sha", "")
        )[:40]

        author = (
            (payload.get("sender") or {}).get("login")
            or (deployment.get("creator") or {}).get("login")
            or "unknown"
        )

        environment = deployment.get("environment") or "production"

        pipeline_url = (
            deployment_status.get("target_url")
            or deployment_status.get("log_url")
            or deployment.get("url")
            or ""
        )

        deployment_id = f"dep-gh-{deployment.get('id', uuid.uuid4().hex[:12])}"

        created_at = deployment.get("created_at") or datetime.now(timezone.utc).isoformat()
        updated_at = (
            deployment_status.get("updated_at")
            or deployment_status.get("created_at")
        )

        return DeploymentEvent(
            deployment_id=deployment_id,
            source="github",
            repository=repository if isinstance(repository, str) else str(repository),
            environment=environment,
            status=status,
            commit_sha=commit_sha,
            author=author,
            pipeline_url=pipeline_url,
            resource_group=payload.get("resource_group", ""),
            started_at=created_at,
            completed_at=updated_at,
        )
    except Exception as exc:
        logger.warning("deployment_tracker: parse_github_deployment_payload error | error=%s", exc)
        return None
