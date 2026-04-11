"""Remediation executor — closed-loop ARM execution with WAL, verification, and auto-rollback.

Flow per execution:
  1. Pre-flight: blast-radius check + new active incident scan (REMEDI-010)
  2. Write WAL record status=pending BEFORE ARM call (REMEDI-011)
  3. Execute ARM action via ComputeManagementClient
  4. Update WAL record status=complete|failed
  5. Schedule verification BackgroundTask (fires after VERIFICATION_DELAY_MINUTES, REMEDI-009)
  6. Verification: classify RESOLVED/IMPROVED/DEGRADED/TIMEOUT via Azure Resource Health
  7. Auto-rollback on DEGRADED (REMEDI-012)

Background task:
  run_wal_stale_monitor — every 5 min, alerts on pending WAL records > WAL_STALE_ALERT_MINUTES old
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

COSMOS_REMEDIATION_AUDIT_CONTAINER = os.environ.get(
    "COSMOS_REMEDIATION_AUDIT_CONTAINER", "remediation_audit"
)
COSMOS_DATABASE_NAME = os.environ.get("COSMOS_DATABASE_NAME", "aap")

SAFE_ARM_ACTIONS: dict[str, dict[str, Optional[str]]] = {
    "restart_vm":    {"arm_op": "restart",           "rollback_op": None},
    "deallocate_vm": {"arm_op": "deallocate",         "rollback_op": "start"},
    "start_vm":      {"arm_op": "start",              "rollback_op": "deallocate"},
    "resize_vm":     {"arm_op": "resize",             "rollback_op": "resize_to_original"},
}


def _get_remediation_audit_container(cosmos_client: Optional[Any]) -> Any:
    """Return the remediation_audit container proxy.

    Falls back to creating a CosmosClient from COSMOS_ENDPOINT env var if cosmos_client is None.
    """
    if cosmos_client is None:
        from azure.cosmos import CosmosClient as _CosmosClient
        endpoint = os.environ.get("COSMOS_ENDPOINT", "")
        if not endpoint:
            raise RuntimeError("COSMOS_ENDPOINT not set and no cosmos_client provided")
        from azure.identity import DefaultAzureCredential
        cosmos_client = _CosmosClient(endpoint, credential=DefaultAzureCredential())

    container_name = os.environ.get(
        "COSMOS_REMEDIATION_AUDIT_CONTAINER", "remediation_audit"
    )
    db_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
    return cosmos_client.get_database_client(db_name).get_container_client(container_name)


async def _write_wal(
    execution_id: str,
    cosmos_client: Optional[Any],
    *,
    status: str = "pending",
    update_fields: Optional[dict] = None,
    base_record: Optional[dict] = None,
) -> None:
    """Write or update a WAL record in the remediation_audit container.

    - Initial write: pass base_record (full RemediationAuditRecord dict), status="pending"
    - Update: pass execution_id + update_fields dict, omit base_record
    Always uses replace_item for updates (preserves immutability — no delete).
    Never raises — logs errors and returns silently.
    """
    try:
        container = _get_remediation_audit_container(cosmos_client)
        if base_record is not None:
            record = dict(base_record)
            record["id"] = execution_id
            record["status"] = status
            record["wal_written_at"] = datetime.now(timezone.utc).isoformat()
            container.create_item(body=record)
            logger.debug("_write_wal: created pending record | execution_id=%s", execution_id)
        elif update_fields is not None:
            # Read existing record and merge updates
            existing_items = list(container.query_items(
                query="SELECT * FROM c WHERE c.id = @execution_id",
                parameters=[{"name": "@execution_id", "value": execution_id}],
                enable_cross_partition_query=True,
            ))
            if not existing_items:
                logger.warning("_write_wal: no record found for update | execution_id=%s", execution_id)
                return
            existing = existing_items[0]
            updated = {**existing, **update_fields}
            container.replace_item(item=execution_id, body=updated)
            logger.debug("_write_wal: updated record | execution_id=%s fields=%s", execution_id, list(update_fields))
    except Exception as exc:
        logger.error("_write_wal: error (non-fatal) | execution_id=%s error=%s", execution_id, exc)


async def _run_preflight(
    resource_id: str,
    approval_issued_at: str,
    topology_client: Optional[Any],
    cosmos_client: Optional[Any],
) -> tuple[bool, int, str]:
    """Run pre-flight checks before executing a remediation action (REMEDI-010).

    Returns (passed, blast_radius_size, reason).
    - passed=True if all checks pass
    - blast_radius_size is the number of affected resources
    - reason is "ok" on pass, or a description of the failure
    """
    blast_radius_size = 0

    # Check blast radius
    if topology_client is not None:
        try:
            blast_radius = topology_client.get_blast_radius(resource_id, 3)
            blast_radius_size = blast_radius.get("total_affected", 0)
        except Exception as exc:
            logger.warning("_run_preflight: blast_radius check failed (non-fatal) | %s", exc)
            blast_radius_size = 0

    if blast_radius_size > 50:
        logger.warning(
            "_run_preflight: blast radius too large | resource_id=%s blast_radius_size=%d",
            resource_id, blast_radius_size,
        )
        return False, blast_radius_size, "blast_radius_exceeds_limit"

    # Check for new active incidents created after approval was issued
    if cosmos_client is not None:
        try:
            db_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
            incidents_container = cosmos_client.get_database_client(db_name).get_container_client("incidents")
            query = (
                "SELECT c.incident_id, c.status FROM c "
                "WHERE c.resource_id = @resource_id "
                "AND c.status NOT IN ('closed', 'suppressed_cascade', 'resolved') "
                "AND c.created_at > @approval_issued_at"
            )
            new_incidents = list(incidents_container.query_items(
                query=query,
                parameters=[
                    {"name": "@resource_id", "value": resource_id},
                    {"name": "@approval_issued_at", "value": approval_issued_at},
                ],
                enable_cross_partition_query=True,
            ))
            if new_incidents:
                logger.warning(
                    "_run_preflight: new active incidents detected post-approval | "
                    "resource_id=%s count=%d",
                    resource_id, len(new_incidents),
                )
                return False, blast_radius_size, "new_active_incidents_detected"
        except Exception as exc:
            logger.warning("_run_preflight: incident scan failed (non-fatal) | %s", exc)

    return True, blast_radius_size, "ok"


def _parse_arm_resource_id(resource_id: str) -> tuple[str, str, str]:
    """Parse ARM resource ID into (subscription_id, resource_group, resource_name).

    Expected format: /subscriptions/{sub}/resourceGroups/{rg}/providers/.../name
    """
    parts = resource_id.split("/")
    subscription_id = parts[2] if len(parts) > 2 else ""
    resource_group = parts[4] if len(parts) > 4 else ""
    resource_name = parts[-1] if parts else ""
    return subscription_id, resource_group, resource_name


async def _execute_arm_action(
    proposed_action: str,
    resource_id: str,
    credential: Any,
    params: Optional[dict] = None,
) -> dict:
    """Execute an ARM action against a VM resource.

    Runs sync Azure SDK calls in a thread executor to avoid blocking the event loop.
    Returns {"success": bool, "arm_op": str, "resource_id": str, "error": Optional[str]}.
    """
    if params is None:
        params = {}

    action_config = SAFE_ARM_ACTIONS.get(proposed_action)
    if action_config is None:
        return {
            "success": False,
            "arm_op": proposed_action,
            "resource_id": resource_id,
            "error": f"Unknown action: {proposed_action}",
        }

    arm_op = action_config["arm_op"]
    subscription_id, resource_group, vm_name = _parse_arm_resource_id(resource_id)

    def _sync_arm_call() -> dict:
        """Synchronous ARM call — runs in thread executor."""
        try:
            from azure.mgmt.compute import ComputeManagementClient
            compute_client = ComputeManagementClient(credential, subscription_id)

            if arm_op == "restart":
                poller = compute_client.virtual_machines.begin_restart(resource_group, vm_name)
                poller.result(timeout=120)
            elif arm_op == "deallocate":
                poller = compute_client.virtual_machines.begin_deallocate(resource_group, vm_name)
                poller.result(timeout=180)
            elif arm_op == "start":
                poller = compute_client.virtual_machines.begin_start(resource_group, vm_name)
                poller.result(timeout=180)
            elif arm_op == "resize":
                new_size = params.get("vm_size", "")
                if not new_size:
                    return {
                        "success": False,
                        "arm_op": arm_op,
                        "resource_id": resource_id,
                        "error": "resize requires vm_size parameter",
                    }
                vm = compute_client.virtual_machines.get(resource_group, vm_name)
                vm.hardware_profile.vm_size = new_size
                poller = compute_client.virtual_machines.begin_create_or_update(
                    resource_group, vm_name, vm
                )
                poller.result(timeout=300)
            elif arm_op == "resize_to_original":
                original_size = params.get("original_vm_size", "")
                if not original_size:
                    return {
                        "success": False,
                        "arm_op": arm_op,
                        "resource_id": resource_id,
                        "error": "resize_to_original requires original_vm_size parameter",
                    }
                vm = compute_client.virtual_machines.get(resource_group, vm_name)
                vm.hardware_profile.vm_size = original_size
                poller = compute_client.virtual_machines.begin_create_or_update(
                    resource_group, vm_name, vm
                )
                poller.result(timeout=300)
            else:
                return {
                    "success": False,
                    "arm_op": arm_op,
                    "resource_id": resource_id,
                    "error": f"Unhandled arm_op: {arm_op}",
                }

            logger.info("_execute_arm_action: succeeded | arm_op=%s resource_id=%s", arm_op, resource_id)
            return {"success": True, "arm_op": arm_op, "resource_id": resource_id, "error": None}

        except Exception as exc:
            logger.error(
                "_execute_arm_action: failed | arm_op=%s resource_id=%s error=%s",
                arm_op, resource_id, exc,
            )
            return {"success": False, "arm_op": arm_op, "resource_id": resource_id, "error": str(exc)}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_arm_call)


def _classify_verification(
    current_status: str,
    pre_execution_status: str,
) -> str:
    """Classify the verification result based on resource health status change.

    Returns one of: RESOLVED, IMPROVED, DEGRADED, TIMEOUT
    """
    if current_status == "Unknown":
        return "TIMEOUT"
    if current_status in ("Unavailable", "Degraded"):
        return "DEGRADED"
    if current_status == "Available":
        if pre_execution_status in ("Unavailable", "Degraded"):
            return "RESOLVED"
        return "IMPROVED"
    return "TIMEOUT"


async def _cancel_active_runs(client: Any, thread_id: str) -> None:
    """Cancel all active runs on a Foundry thread before injecting a new message.

    Follows the same pattern as chat.py create_chat_thread:
    - Lists runs on the thread
    - Cancels any with status in {"queued", "in_progress", "requires_action", "cancelling"}
    - Sleeps 1s if any were cancelled to allow propagation

    Uses client.runs.* namespace (not client.agents.*).
    """
    try:
        runs = list(client.runs.list(thread_id=thread_id))
        active_statuses = {"queued", "in_progress", "requires_action", "cancelling"}
        cancelled_any = False
        for run in runs:
            if run.status in active_statuses:
                logger.info(
                    "_cancel_active_runs: cancelling run %s (status=%s) on thread %s",
                    run.id, run.status, thread_id,
                )
                try:
                    client.runs.cancel(thread_id=thread_id, run_id=run.id)
                    cancelled_any = True
                except Exception as cancel_exc:
                    logger.warning("_cancel_active_runs: failed to cancel run %s: %s", run.id, cancel_exc)
        if cancelled_any:
            await asyncio.sleep(1)
    except Exception as exc:
        logger.warning("_cancel_active_runs: failed to list/cancel runs on thread %s: %s", thread_id, exc)


_VERIFICATION_INSTRUCTIONS: dict[str, str] = {
    "RESOLVED": (
        "The remediation action has RESOLVED the issue. "
        "Confirm the resource is healthy, summarize the root cause and fix, "
        "and recommend this incident be closed."
    ),
    "IMPROVED": (
        "The remediation action has IMPROVED the resource health but the issue "
        "is not fully resolved. Re-diagnose the current state and determine if "
        "a follow-up action is needed."
    ),
    "DEGRADED": (
        "The remediation action has DEGRADED the resource. Auto-rollback has been triggered. "
        "Re-diagnose the issue with fresh signals and propose an alternative approach. "
        "Do NOT re-propose the same action that caused degradation."
    ),
    "TIMEOUT": (
        "Verification timed out — resource health status is unknown. "
        "Re-check the resource health manually and report the current state. "
        "If the resource is healthy, recommend closure. If not, propose next steps."
    ),
}


def _build_verification_instruction(verification_result: str) -> str:
    """Build the re-diagnosis instruction based on verification outcome."""
    return _VERIFICATION_INSTRUCTIONS.get(verification_result, _VERIFICATION_INSTRUCTIONS["TIMEOUT"])


MAX_RE_DIAGNOSIS_COUNT: int = int(os.environ.get("MAX_RE_DIAGNOSIS_COUNT", "3"))


async def _inject_verification_result(
    thread_id: str,
    execution_id: str,
    verification_result: str,
    resource_id: str,
    proposed_action: str,
    rolled_back: bool,
    incident_id: str,
    cosmos_client: Optional[Any],
) -> None:
    """Inject verification result into the originating Foundry thread and create a new run (LOOP-001).

    1. Check re_diagnosis_count on the incident — if >= MAX_RE_DIAGNOSIS_COUNT, log escalation and return
    2. Cancel active runs on the thread (client.runs.cancel)
    3. Post a verification_result message following AGENT-002 envelope format (client.agents.create_message)
    4. Create a new orchestrator run for re-diagnosis (client.agents.create_run)
    5. Increment re_diagnosis_count on the incident
    """
    import json

    # --- Guard: check re_diagnosis_count ---
    current_count = 0
    if cosmos_client is not None:
        try:
            db_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
            incidents_container = cosmos_client.get_database_client(db_name).get_container_client("incidents")
            inc_docs = list(incidents_container.query_items(
                query="SELECT c.re_diagnosis_count FROM c WHERE c.incident_id = @iid",
                parameters=[{"name": "@iid", "value": incident_id}],
                enable_cross_partition_query=True,
            ))
            if inc_docs:
                current_count = inc_docs[0].get("re_diagnosis_count", 0) or 0
        except Exception as exc:
            logger.warning("_inject_verification_result: failed to read re_diagnosis_count | %s", exc)

    if current_count >= MAX_RE_DIAGNOSIS_COUNT:
        logger.warning(
            "_inject_verification_result: max re-diagnosis reached | "
            "incident_id=%s count=%d max=%d — escalating to operator",
            incident_id, current_count, MAX_RE_DIAGNOSIS_COUNT,
        )
        return

    # --- Inject message and create run ---
    try:
        from services.api_gateway.foundry import _get_foundry_client
        from services.api_gateway.instrumentation import foundry_span, agent_span

        client = _get_foundry_client()
        orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID", "")
        if not orchestrator_agent_id:
            logger.error("_inject_verification_result: ORCHESTRATOR_AGENT_ID not set")
            return

        # Cancel active runs first (uses client.runs.cancel)
        await _cancel_active_runs(client, thread_id)

        # Build AGENT-002 typed JSON envelope
        message = {
            "correlation_id": incident_id,
            "source_agent": "api-gateway",
            "target_agent": "orchestrator",
            "message_type": "verification_result",
            "payload": {
                "execution_id": execution_id,
                "verification_result": verification_result,
                "resource_id": resource_id,
                "proposed_action": proposed_action,
                "rolled_back": rolled_back,
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "instruction": _build_verification_instruction(verification_result),
            },
        }

        # Post message to thread (uses client.agents.create_message)
        with foundry_span("post_message", thread_id=thread_id) as span:
            span.set_attribute("foundry.message_type", "verification_result")
            client.agents.create_message(
                thread_id=thread_id,
                role="user",
                content=json.dumps(message),
            )

        # Create new orchestrator run (uses client.agents.create_run)
        with agent_span("orchestrator", correlation_id=execution_id) as span:
            with foundry_span("create_run", thread_id=thread_id):
                client.agents.create_run(
                    thread_id=thread_id,
                    assistant_id=orchestrator_agent_id,
                )

        # Increment re_diagnosis_count
        if cosmos_client is not None:
            try:
                db_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
                incidents_container = cosmos_client.get_database_client(db_name).get_container_client("incidents")
                incidents_container.patch_item(
                    item=incident_id,
                    partition_key=incident_id,
                    patch_operations=[
                        {"op": "incr", "path": "/re_diagnosis_count", "value": 1},
                    ],
                )
            except Exception as exc:
                logger.warning("_inject_verification_result: failed to increment re_diagnosis_count | %s", exc)

        logger.info(
            "_inject_verification_result: injected | thread_id=%s execution_id=%s result=%s count=%d",
            thread_id, execution_id, verification_result, current_count + 1,
        )

    except Exception as exc:
        logger.error(
            "_inject_verification_result: failed | thread_id=%s execution_id=%s error=%s",
            thread_id, execution_id, exc,
        )


async def _verify_remediation(
    execution_id: str,
    resource_id: str,
    incident_id: str,
    thread_id: str,
    proposed_action: str,
    credential: Any,
    cosmos_client: Optional[Any],
) -> str:
    """Verify the result of a remediation action via Azure Resource Health (REMEDI-009).

    Queries resource health, classifies result, updates WAL record,
    triggers rollback if DEGRADED (REMEDI-012), and injects verification
    result into Foundry thread for re-diagnosis (LOOP-001).
    """
    subscription_id, _, _ = _parse_arm_resource_id(resource_id)

    def _sync_health_check() -> str:
        try:
            from azure.mgmt.resourcehealth import MicrosoftResourceHealth
            health_client = MicrosoftResourceHealth(credential, subscription_id)
            status_result = health_client.availability_statuses.get_by_resource(
                resource_uri=resource_id,
                api_version="2023-07-01",
            )
            availability = getattr(
                getattr(status_result, "properties", None),
                "availability_state",
                "Unknown",
            )
            return str(availability) if availability else "Unknown"
        except Exception as exc:
            logger.warning("_verify_remediation: health check failed | %s", exc)
            return "Unknown"

    loop = asyncio.get_running_loop()
    current_health = await loop.run_in_executor(None, _sync_health_check)
    logger.info(
        "_verify_remediation: resource health | execution_id=%s resource_id=%s health=%s",
        execution_id, resource_id, current_health,
    )

    classification = _classify_verification(current_health, "Unknown")
    verified_at = datetime.now(timezone.utc).isoformat()

    await _write_wal(
        execution_id,
        cosmos_client,
        update_fields={
            "verification_result": classification,
            "verified_at": verified_at,
        },
    )
    logger.info(
        "_verify_remediation: classified | execution_id=%s result=%s",
        execution_id, classification,
    )

    rollback_id = None
    if classification == "DEGRADED":
        logger.warning(
            "_verify_remediation: DEGRADED — triggering rollback | execution_id=%s",
            execution_id,
        )
        # Read approval info from WAL record to get fields needed for rollback
        rollback_id = await _rollback(
            execution_id=execution_id,
            resource_id=resource_id,
            incident_id=incident_id,
            approval_id="",
            thread_id="",
            executed_by="system-auto-rollback",
            proposed_action=proposed_action,
            credential=credential,
            cosmos_client=cosmos_client,
        )
        if rollback_id:
            await _write_wal(
                execution_id,
                cosmos_client,
                update_fields={
                    "rolled_back": True,
                    "rollback_execution_id": rollback_id,
                },
            )

    # --- Inject verification result into originating Foundry thread (LOOP-001) ---
    if thread_id:
        rolled_back = classification == "DEGRADED" and rollback_id is not None
        await _inject_verification_result(
            thread_id=thread_id,
            execution_id=execution_id,
            verification_result=classification,
            resource_id=resource_id,
            proposed_action=proposed_action,
            rolled_back=rolled_back if classification == "DEGRADED" else False,
            incident_id=incident_id,
            cosmos_client=cosmos_client,
        )

    return classification


async def _rollback(
    execution_id: str,
    resource_id: str,
    incident_id: str,
    approval_id: str,
    thread_id: str,
    executed_by: str,
    proposed_action: str,
    credential: Any,
    cosmos_client: Optional[Any],
) -> Optional[str]:
    """Execute auto-rollback for a DEGRADED verification result (REMEDI-012).

    Returns rollback_execution_id if rollback was executed, None if not applicable.
    """
    action_config = SAFE_ARM_ACTIONS.get(proposed_action)
    if action_config is None:
        logger.warning("_rollback: unknown action, cannot rollback | proposed_action=%s", proposed_action)
        return None

    rollback_op = action_config.get("rollback_op")
    if rollback_op is None:
        logger.info(
            "_rollback: action is idempotent, no rollback needed | proposed_action=%s",
            proposed_action,
        )
        return None

    rollback_execution_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    rollback_base = {
        "incident_id": incident_id,
        "approval_id": approval_id,
        "thread_id": thread_id,
        "action_type": "rollback",
        "proposed_action": rollback_op,
        "resource_id": resource_id,
        "executed_by": executed_by,
        "executed_at": now_iso,
        "preflight_blast_radius_size": 0,
        "rolled_back": False,
        "rollback_execution_id": None,
        "verification_result": None,
        "verified_at": None,
    }

    await _write_wal(
        rollback_execution_id,
        cosmos_client,
        status="pending",
        base_record=rollback_base,
    )

    arm_result = await _execute_arm_action(rollback_op, resource_id, credential, params={})
    rollback_status = "complete" if arm_result["success"] else "failed"

    await _write_wal(
        rollback_execution_id,
        cosmos_client,
        update_fields={"status": rollback_status},
    )

    logger.info(
        "_rollback: completed | rollback_execution_id=%s status=%s",
        rollback_execution_id, rollback_status,
    )
    return rollback_execution_id


async def _delayed_verify(
    execution_id: str,
    resource_id: str,
    incident_id: str,
    thread_id: str,
    proposed_action: str,
    credential: Any,
    cosmos_client: Optional[Any],
) -> None:
    """Sleep for VERIFICATION_DELAY_MINUTES then run verification (REMEDI-009)."""
    delay = int(os.environ.get("VERIFICATION_DELAY_MINUTES", "10")) * 60
    await asyncio.sleep(delay)
    try:
        await _verify_remediation(
            execution_id=execution_id,
            resource_id=resource_id,
            incident_id=incident_id,
            thread_id=thread_id,
            proposed_action=proposed_action,
            credential=credential,
            cosmos_client=cosmos_client,
        )
    except Exception as exc:
        logger.error(
            "_delayed_verify: verification failed | execution_id=%s error=%s",
            execution_id, exc,
        )


async def _emit_wal_alert(
    stale_record: dict,
    cosmos_client: Optional[Any],
) -> None:
    """Emit a REMEDI_WAL_ALERT incident to the incidents container."""
    if cosmos_client is None:
        return
    try:
        db_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
        incidents_container = cosmos_client.get_database_client(db_name).get_container_client("incidents")
        execution_id = stale_record.get("id", "unknown")
        now_iso = datetime.now(timezone.utc).isoformat()
        alert_incident = {
            "id": f"REMEDI_WAL_ALERT_{execution_id[:8]}_{int(datetime.now(timezone.utc).timestamp())}",
            "incident_id": f"REMEDI_WAL_ALERT_{execution_id[:8]}",
            "severity": "Sev1",
            "domain": "sre",
            "status": "new",
            "title": f"Stale remediation WAL record detected: {execution_id}",
            "description": (
                f"Remediation WAL record {execution_id} has been in 'pending' status "
                f"since {stale_record.get('wal_written_at', 'unknown')}. "
                "This may indicate an ARM call that is hung or failed silently."
            ),
            "detection_rule": "REMEDI_WAL_ALERT",
            "resource_id": stale_record.get("resource_id", ""),
            "created_at": now_iso,
        }
        incidents_container.create_item(body=alert_incident)
        logger.info("_emit_wal_alert: alert created | execution_id=%s", execution_id)
    except Exception as exc:
        logger.error("_emit_wal_alert: failed to create alert | %s", exc)


async def execute_remediation(
    approval_id: str,
    credential: Any,
    cosmos_client: Optional[Any],
    topology_client: Optional[Any],
    approval_record: dict,
) -> Any:
    """Orchestrate the full remediation execution loop (REMEDI-009-012).

    Returns a RemediationResult Pydantic model.
    """
    from services.api_gateway.models import RemediationResult

    # Safety switch
    if os.environ.get("REMEDIATION_EXECUTION_ENABLED", "true").lower() == "false":
        logger.info("execute_remediation: REMEDIATION_EXECUTION_ENABLED=false — aborted")
        return RemediationResult(
            execution_id="",
            status="aborted",
            verification_scheduled=False,
            preflight_passed=False,
            blast_radius_size=0,
            abort_reason="REMEDIATION_EXECUTION_ENABLED is false",
        )

    # Extract fields from approval record
    incident_id = approval_record.get("incident_id", "")
    thread_id = approval_record.get("thread_id", "")

    # proposed_action may be at top level or nested in proposal dict
    proposed_action = approval_record.get("proposed_action") or (
        approval_record.get("proposal", {}) or {}
    ).get("action", "")
    executed_by = approval_record.get("decided_by", "unknown")
    approval_issued_at = approval_record.get("decided_at", "")

    # Get resource_id from proposal
    proposal = approval_record.get("proposal", {}) or {}
    target_resources = proposal.get("target_resources", [])
    resource_id = target_resources[0] if target_resources else approval_record.get("resource_id", "")

    # Validate action
    if proposed_action not in SAFE_ARM_ACTIONS:
        logger.warning(
            "execute_remediation: unsupported action | proposed_action=%s", proposed_action
        )
        return RemediationResult(
            execution_id="",
            status="aborted",
            verification_scheduled=False,
            preflight_passed=False,
            blast_radius_size=0,
            abort_reason=f"Unsupported action: {proposed_action}",
        )

    # Pre-flight check (REMEDI-010)
    preflight_passed, blast_radius_size, preflight_reason = await _run_preflight(
        resource_id=resource_id,
        approval_issued_at=approval_issued_at,
        topology_client=topology_client,
        cosmos_client=cosmos_client,
    )
    if not preflight_passed:
        logger.warning(
            "execute_remediation: pre-flight failed | reason=%s blast_radius=%d",
            preflight_reason, blast_radius_size,
        )
        return RemediationResult(
            execution_id="",
            status="aborted",
            verification_scheduled=False,
            preflight_passed=False,
            blast_radius_size=blast_radius_size,
            abort_reason=preflight_reason,
        )

    execution_id = str(uuid.uuid4())
    executed_at = datetime.now(timezone.utc).isoformat()

    # Write WAL record BEFORE ARM call (REMEDI-011)
    wal_base = {
        "incident_id": incident_id,
        "approval_id": approval_id,
        "thread_id": thread_id,
        "action_type": "execute",
        "proposed_action": proposed_action,
        "resource_id": resource_id,
        "executed_by": executed_by,
        "executed_at": executed_at,
        "preflight_blast_radius_size": blast_radius_size,
        "verification_result": None,
        "verified_at": None,
        "rolled_back": False,
        "rollback_execution_id": None,
    }
    await _write_wal(execution_id, cosmos_client, status="pending", base_record=wal_base)

    # Execute ARM action
    arm_params = (proposal.get("tool_parameters") or {})
    arm_result = await _execute_arm_action(proposed_action, resource_id, credential, params=arm_params)

    # Update WAL record with final status
    wal_status = "complete" if arm_result["success"] else "failed"
    await _write_wal(
        execution_id, cosmos_client, update_fields={"status": wal_status}
    )

    # Fire-and-forget OneLake logging (REMEDI-007)
    try:
        from services.api_gateway.remediation_logger import (
            log_remediation_event,
            build_remediation_event,
        )
        duration_ms = 0
        outcome = wal_status
        correlation_id = execution_id
        event = build_remediation_event(approval_record, outcome, duration_ms, correlation_id)
        asyncio.create_task(log_remediation_event(event))
    except Exception as exc:
        logger.warning("execute_remediation: OneLake log failed (non-fatal) | %s", exc)

    # Schedule verification in background (REMEDI-009)
    asyncio.create_task(
        _delayed_verify(
            execution_id=execution_id,
            resource_id=resource_id,
            incident_id=incident_id,
            thread_id=thread_id,
            proposed_action=proposed_action,
            credential=credential,
            cosmos_client=cosmos_client,
        )
    )

    return RemediationResult(
        execution_id=execution_id,
        status=wal_status,
        verification_scheduled=True,
        preflight_passed=True,
        blast_radius_size=blast_radius_size,
    )


async def run_wal_stale_monitor(
    cosmos_client: Optional[Any],
    interval_seconds: int = 300,
) -> None:
    """Background loop: every 5 min, find pending WAL records older than WAL_STALE_ALERT_MINUTES.

    For each stale record found, emit a REMEDI_WAL_ALERT incident (REMEDI-011).
    """
    while True:
        await asyncio.sleep(interval_seconds)
        if cosmos_client is None:
            continue
        try:
            stale_minutes = int(os.environ.get("WAL_STALE_ALERT_MINUTES", "10"))
            cutoff = (
                datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
            ).isoformat()
            container = _get_remediation_audit_container(cosmos_client)
            query = (
                "SELECT c.id, c.incident_id, c.approval_id, c.wal_written_at, c.resource_id "
                "FROM c WHERE c.status = 'pending' AND c.wal_written_at < @cutoff"
            )
            stale_records = list(container.query_items(
                query=query,
                parameters=[{"name": "@cutoff", "value": cutoff}],
                enable_cross_partition_query=True,
            ))
            if stale_records:
                logger.warning(
                    "run_wal_stale_monitor: found %d stale WAL records", len(stale_records)
                )
            for record in stale_records:
                logger.error(
                    "REMEDI_WAL_ALERT: stale pending WAL record | "
                    "execution_id=%s incident_id=%s wal_written_at=%s",
                    record.get("id"), record.get("incident_id"), record.get("wal_written_at"),
                )
                await _emit_wal_alert(record, cosmos_client)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("run_wal_stale_monitor: error | %s", exc)
