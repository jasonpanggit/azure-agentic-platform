#!/usr/bin/env python3
"""Shared utilities for Phase 8 incident simulation scripts.

Provides:
- SimulationClient: HTTP client with Entra auth for API gateway calls
- cleanup_incident: Surgical deletion of simulation records from Cosmos DB
- SimulationResult: Typed result container
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)

# Environment defaults (overridable)
API_GATEWAY_URL = os.environ.get(
    "API_GATEWAY_URL",
    "https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io",
)
COSMOS_ENDPOINT = os.environ.get(
    "COSMOS_ENDPOINT",
    "https://aap-cosmos-prod.documents.azure.com:443/",
)
COSMOS_DATABASE = os.environ.get("COSMOS_DATABASE_NAME", "aap")


@dataclass(frozen=True)
class SimulationResult:
    """Immutable result of a simulation scenario."""

    scenario: str
    incident_id: str
    thread_id: str
    run_status: str
    reply: Optional[str]
    duration_seconds: float
    success: bool
    error: Optional[str] = None


class SimulationClient:
    """HTTP client for simulation scripts with Entra ID auth."""

    def __init__(self, base_url: str = API_GATEWAY_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._credential = DefaultAzureCredential()
        self._token: Optional[str] = None

    def _acquire_token(self) -> str:
        """Acquire bearer token via DefaultAzureCredential.

        Scoped to Azure management API — the api-gateway validates
        Entra tokens in prod mode.
        """
        token = self._credential.get_token("https://management.azure.com/.default")
        return token.token

    @property
    def token(self) -> str:
        if self._token is None:
            self._token = self._acquire_token()
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def inject_incident(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /api/v1/incidents and return response body.

        Raises requests.HTTPError on non-2xx status.
        """
        resp = requests.post(
            f"{self.base_url}/api/v1/incidents",
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def poll_thread_completion(
        self, thread_id: str, timeout_seconds: int = 120
    ) -> dict[str, Any]:
        """Poll GET /api/v1/chat/{thread_id}/result until terminal status.

        Terminal statuses: completed, failed, cancelled, expired, not_found.
        Returns the final result dict.
        """
        deadline = time.time() + timeout_seconds
        poll_interval = 3.0

        while time.time() < deadline:
            resp = requests.get(
                f"{self.base_url}/api/v1/chat/{thread_id}/result",
                headers=self._headers(),
                timeout=15,
            )

            if resp.status_code == 200:
                data = resp.json()
                status = data.get("run_status", "unknown")
                if status in ("completed", "failed", "cancelled", "expired", "not_found"):
                    return data
            elif resp.status_code == 404:
                return {"thread_id": thread_id, "run_status": "not_found", "reply": None}

            time.sleep(poll_interval)
            # Exponential backoff (cap at 10s)
            poll_interval = min(poll_interval * 1.5, 10.0)

        return {"thread_id": thread_id, "run_status": "timeout", "reply": None}

    def send_chat(self, message: str, thread_id: Optional[str] = None) -> dict[str, Any]:
        """POST /api/v1/chat and return response body."""
        payload: dict[str, Any] = {"message": message}
        if thread_id:
            payload["thread_id"] = thread_id
        resp = requests.post(
            f"{self.base_url}/api/v1/chat",
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


def cleanup_incident(incident_id: str, thread_id: Optional[str] = None) -> None:
    """Delete simulation records from Cosmos DB (surgical cleanup).

    Deletes from both `incidents` and `approvals` containers.
    Idempotent — silently succeeds if records don't exist.
    """
    try:
        credential = DefaultAzureCredential()
        cosmos = CosmosClient(url=COSMOS_ENDPOINT, credential=credential)
        db = cosmos.get_database_client(COSMOS_DATABASE)

        # Delete from incidents container (cross-partition query)
        incidents_container = db.get_container_client("incidents")
        query = "SELECT * FROM c WHERE c.incident_id = @id"
        params = [{"name": "@id", "value": incident_id}]
        for item in incidents_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        ):
            incidents_container.delete_item(
                item=item["id"], partition_key=item["resource_id"]
            )
            logger.info("Deleted incident record: %s", item["id"])

        # Delete from approvals container (by thread_id if available)
        if thread_id:
            approvals_container = db.get_container_client("approvals")
            query = "SELECT * FROM c WHERE c.thread_id = @tid"
            params = [{"name": "@tid", "value": thread_id}]
            for item in approvals_container.query_items(
                query=query,
                parameters=params,
                partition_key=thread_id,
            ):
                approvals_container.delete_item(
                    item=item["id"], partition_key=thread_id
                )
                logger.info("Deleted approval record: %s", item["id"])

    except Exception as exc:
        logger.warning("Cleanup for incident %s failed (non-fatal): %s", incident_id, exc)


def run_scenario(
    scenario_name: str,
    payload: dict[str, Any],
    client: Optional[SimulationClient] = None,
    timeout_seconds: int = 120,
) -> SimulationResult:
    """Generic scenario runner: inject, poll, assert, cleanup.

    Returns an immutable SimulationResult. Does NOT raise on failure —
    the caller decides how to handle the result.
    """
    if client is None:
        client = SimulationClient()

    incident_id = payload["incident_id"]
    start = time.time()
    thread_id = ""
    run_status = "not_started"
    reply = None
    error = None

    try:
        # INJECT
        result = client.inject_incident(payload)
        thread_id = result.get("thread_id", "")
        dispatch_status = result.get("status", "unknown")
        logger.info(
            "[%s] Injected: incident_id=%s thread_id=%s status=%s",
            scenario_name, incident_id, thread_id, dispatch_status,
        )

        if dispatch_status not in ("dispatched", "deduplicated"):
            error = f"Unexpected dispatch status: {dispatch_status}"
            run_status = "dispatch_error"
        elif thread_id and dispatch_status == "dispatched":
            # POLL
            final = client.poll_thread_completion(thread_id, timeout_seconds)
            run_status = final.get("run_status", "unknown")
            reply = final.get("reply")

            if run_status != "completed":
                error = f"Run did not complete: status={run_status}"
        else:
            run_status = dispatch_status  # deduplicated

    except requests.HTTPError as exc:
        error = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        run_status = "http_error"
    except Exception as exc:
        error = str(exc)[:200]
        run_status = "exception"

    duration = time.time() - start
    success = run_status in ("completed", "deduplicated") and error is None

    # CLEANUP (always, even on failure)
    cleanup_incident(incident_id, thread_id)

    sim_result = SimulationResult(
        scenario=scenario_name,
        incident_id=incident_id,
        thread_id=thread_id,
        run_status=run_status,
        reply=reply,
        duration_seconds=round(duration, 2),
        success=success,
        error=error,
    )

    status_emoji = "PASS" if success else "FAIL"
    logger.info(
        "[%s] %s — status=%s duration=%.1fs thread=%s",
        scenario_name, status_emoji, run_status, duration, thread_id,
    )
    if error:
        logger.error("[%s] Error: %s", scenario_name, error)
    if reply:
        logger.info("[%s] Reply preview: %s", scenario_name, reply[:200])

    return sim_result


def setup_logging() -> None:
    """Configure logging for simulation scripts."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
