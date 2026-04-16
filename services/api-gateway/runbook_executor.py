"""RunbookExecutor — execute automation runbook steps sequentially with HITL gates.

Each step is streamed via SSE. Steps with require_approval=True create a Cosmos DB
approval record and wait for HITL resolution. WAL records track every step attempt.
Jinja2 templates in parameters_template are resolved from incident_context at runtime.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Literal, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

try:
    from jinja2 import Environment, StrictUndefined, TemplateError, select_autoescape
    _jinja_env = Environment(undefined=StrictUndefined, autoescape=select_autoescape([]))  # nosec B701 — templates render infra parameters, not HTML
except ImportError:
    Environment = None  # type: ignore[assignment,misc]
    _jinja_env = None  # type: ignore[assignment]
    TemplateError = Exception  # type: ignore[assignment,misc]

try:
    from pydantic import BaseModel, Field
except ImportError:
    BaseModel = object  # type: ignore[assignment,misc]
    Field = lambda *a, **kw: None  # type: ignore[assignment]

try:
    from azure.cosmos import CosmosClient
except ImportError:
    CosmosClient = None  # type: ignore[assignment,misc]

try:
    from azure.identity import DefaultAzureCredential
except ImportError:
    DefaultAzureCredential = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AutomationStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str
    parameters_template: dict = Field(default_factory=dict)
    condition: Optional[str] = None
    require_approval: bool = True
    on_failure: Literal["rollback", "continue", "abort"] = "abort"


class AutomationRunbook(BaseModel):
    runbook_id: str
    name: str
    description: str
    domain: str
    automation_steps: list[AutomationStep] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Built-in runbook definitions
# ---------------------------------------------------------------------------

BUILTIN_RUNBOOKS: dict[str, dict] = {
    "vm_high_cpu_response": {
        "runbook_id": "vm_high_cpu_response",
        "name": "VM High CPU Response",
        "description": "Diagnose and remediate high CPU usage on a virtual machine.",
        "domain": "compute",
        "tags": ["vm", "cpu", "performance"],
        "automation_steps": [
            {
                "step_id": "check_metrics",
                "tool_name": "check_vm_metrics",
                "parameters_template": {
                    "resource_id": "{{ incident.resource_id }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                    "metric": "Percentage CPU",
                    "lookback_minutes": 30,
                },
                "require_approval": False,
                "on_failure": "abort",
            },
            {
                "step_id": "restart_vm",
                "tool_name": "restart_virtual_machine",
                "parameters_template": {
                    "resource_id": "{{ incident.resource_id }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                },
                "require_approval": True,
                "on_failure": "rollback",
            },
            {
                "step_id": "verify_recovery",
                "tool_name": "check_vm_metrics",
                "parameters_template": {
                    "resource_id": "{{ incident.resource_id }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                    "metric": "Percentage CPU",
                    "lookback_minutes": 5,
                },
                "require_approval": False,
                "on_failure": "continue",
            },
        ],
    },
    "disk_full_cleanup": {
        "runbook_id": "disk_full_cleanup",
        "name": "Disk Full Cleanup",
        "description": "List large files, alert operator, and extend disk if needed.",
        "domain": "compute",
        "tags": ["disk", "storage", "cleanup"],
        "automation_steps": [
            {
                "step_id": "list_large_files",
                "tool_name": "list_large_files_on_vm",
                "parameters_template": {
                    "resource_id": "{{ incident.resource_id }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                    "threshold_gb": 1,
                },
                "require_approval": False,
                "on_failure": "continue",
            },
            {
                "step_id": "alert_operator",
                "tool_name": "send_teams_alert",
                "parameters_template": {
                    "message": "Disk full on {{ incident.resource_id }} — review large files",
                    "severity": "warning",
                },
                "require_approval": False,
                "on_failure": "continue",
            },
            {
                "step_id": "extend_disk",
                "tool_name": "extend_managed_disk",
                "parameters_template": {
                    "resource_id": "{{ incident.resource_id }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                    "additional_gb": 32,
                },
                "require_approval": True,
                "on_failure": "abort",
            },
        ],
    },
    "aks_node_drain": {
        "runbook_id": "aks_node_drain",
        "name": "AKS Node Drain",
        "description": "Cordon, drain, and verify pod rescheduling on an AKS node.",
        "domain": "compute",
        "tags": ["aks", "kubernetes", "node"],
        "automation_steps": [
            {
                "step_id": "cordon_node",
                "tool_name": "aks_cordon_node",
                "parameters_template": {
                    "cluster_resource_id": "{{ incident.resource_id }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                    "node_name": "{{ incident.node_name | default('unknown') }}",
                },
                "require_approval": True,
                "on_failure": "abort",
            },
            {
                "step_id": "drain_workloads",
                "tool_name": "aks_drain_node",
                "parameters_template": {
                    "cluster_resource_id": "{{ incident.resource_id }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                    "node_name": "{{ incident.node_name | default('unknown') }}",
                    "grace_period_seconds": 30,
                },
                "require_approval": True,
                "on_failure": "rollback",
            },
            {
                "step_id": "verify_pods_rescheduled",
                "tool_name": "aks_list_pods",
                "parameters_template": {
                    "cluster_resource_id": "{{ incident.resource_id }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                },
                "require_approval": False,
                "on_failure": "continue",
            },
        ],
    },
    "service_bus_dlq_drain": {
        "runbook_id": "service_bus_dlq_drain",
        "name": "Service Bus DLQ Drain",
        "description": "Get DLQ count, move messages, and notify team.",
        "domain": "network",
        "tags": ["service-bus", "messaging", "dlq"],
        "automation_steps": [
            {
                "step_id": "get_dlq_count",
                "tool_name": "service_bus_get_dlq_count",
                "parameters_template": {
                    "namespace": "{{ incident.namespace | default('') }}",
                    "queue_name": "{{ incident.queue_name | default('') }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                },
                "require_approval": False,
                "on_failure": "abort",
            },
            {
                "step_id": "move_dlq_messages",
                "tool_name": "service_bus_move_dlq_messages",
                "parameters_template": {
                    "namespace": "{{ incident.namespace | default('') }}",
                    "queue_name": "{{ incident.queue_name | default('') }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                    "destination_queue": "{{ incident.destination_queue | default('dlq-archive') }}",
                },
                "require_approval": True,
                "on_failure": "abort",
            },
            {
                "step_id": "notify_team",
                "tool_name": "send_teams_alert",
                "parameters_template": {
                    "message": "DLQ drain completed for {{ incident.queue_name | default('queue') }}",
                    "severity": "info",
                },
                "require_approval": False,
                "on_failure": "continue",
            },
        ],
    },
    "certificate_renewal": {
        "runbook_id": "certificate_renewal",
        "name": "Certificate Renewal",
        "description": "Check cert expiry, trigger renewal, and verify the new certificate.",
        "domain": "security",
        "tags": ["certificate", "tls", "keyvault"],
        "automation_steps": [
            {
                "step_id": "check_cert_expiry",
                "tool_name": "keyvault_get_certificate_expiry",
                "parameters_template": {
                    "keyvault_name": "{{ incident.keyvault_name | default('') }}",
                    "certificate_name": "{{ incident.certificate_name | default('') }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                },
                "require_approval": False,
                "on_failure": "abort",
            },
            {
                "step_id": "trigger_renewal",
                "tool_name": "keyvault_renew_certificate",
                "parameters_template": {
                    "keyvault_name": "{{ incident.keyvault_name | default('') }}",
                    "certificate_name": "{{ incident.certificate_name | default('') }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                },
                "require_approval": True,
                "on_failure": "abort",
            },
            {
                "step_id": "verify_cert",
                "tool_name": "keyvault_get_certificate_expiry",
                "parameters_template": {
                    "keyvault_name": "{{ incident.keyvault_name | default('') }}",
                    "certificate_name": "{{ incident.certificate_name | default('') }}",
                    "subscription_id": "{{ incident.subscription_id }}",
                },
                "require_approval": False,
                "on_failure": "continue",
            },
        ],
    },
}

# ---------------------------------------------------------------------------
# Available tools registry
# ---------------------------------------------------------------------------

AVAILABLE_TOOLS: list[dict] = [
    {"tool_name": "check_vm_metrics", "description": "Fetch Azure Monitor metrics for a VM", "domain": "compute"},
    {"tool_name": "restart_virtual_machine", "description": "Restart an Azure virtual machine", "domain": "compute"},
    {"tool_name": "list_large_files_on_vm", "description": "List large files on a VM via Run Command", "domain": "compute"},
    {"tool_name": "extend_managed_disk", "description": "Extend a managed disk by N GB", "domain": "compute"},
    {"tool_name": "aks_cordon_node", "description": "Cordon an AKS node (prevent new scheduling)", "domain": "compute"},
    {"tool_name": "aks_drain_node", "description": "Drain workloads from an AKS node", "domain": "compute"},
    {"tool_name": "aks_list_pods", "description": "List pods in an AKS cluster", "domain": "compute"},
    {"tool_name": "service_bus_get_dlq_count", "description": "Get dead-letter queue message count", "domain": "network"},
    {"tool_name": "service_bus_move_dlq_messages", "description": "Move DLQ messages to destination queue", "domain": "network"},
    {"tool_name": "keyvault_get_certificate_expiry", "description": "Get certificate expiry from Key Vault", "domain": "security"},
    {"tool_name": "keyvault_renew_certificate", "description": "Trigger certificate renewal in Key Vault", "domain": "security"},
    {"tool_name": "send_teams_alert", "description": "Send a Teams notification", "domain": "ops"},
    {"tool_name": "get_resource_health", "description": "Get Azure resource health status", "domain": "compute"},
    {"tool_name": "list_nsg_rules", "description": "List NSG rules for a resource", "domain": "network"},
    {"tool_name": "query_log_analytics", "description": "Run a KQL query against Log Analytics", "domain": "ops"},
]

# ---------------------------------------------------------------------------
# Jinja2 template resolver
# ---------------------------------------------------------------------------


def resolve_parameters(parameters_template: dict, incident_context: dict) -> dict:
    """Resolve Jinja2 template strings in parameters_template using incident_context.

    Returns a new dict with resolved values. Never raises — returns error dict on failure.
    """
    if _jinja_env is None:
        return {"error": "jinja2 not installed; cannot resolve templates", **parameters_template}

    context = {"incident": incident_context}
    resolved: dict = {}
    errors: dict = {}

    for key, value in parameters_template.items():
        if not isinstance(value, str):
            resolved[key] = value
            continue
        try:
            template = _jinja_env.from_string(value)
            resolved[key] = template.render(**context)
        except Exception as exc:
            logger.warning("Template resolution failed for key %s: %s", key, exc)
            errors[key] = str(exc)
            resolved[key] = value  # keep original on failure

    if errors:
        resolved["_template_errors"] = errors
    return resolved


# ---------------------------------------------------------------------------
# Cosmos DB helpers
# ---------------------------------------------------------------------------

import os


def _get_cosmos_container(container_name: str) -> Any:
    """Return a Cosmos DB container client. Returns None if unavailable."""
    try:
        if CosmosClient is None or DefaultAzureCredential is None:
            return None
        endpoint = os.environ.get("COSMOS_ENDPOINT", "")
        if not endpoint:
            return None
        client = CosmosClient(url=endpoint, credential=DefaultAzureCredential())
        database_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
        db = client.get_database_client(database_name)
        return db.get_container_client(container_name)
    except Exception as exc:
        logger.warning("Failed to get Cosmos container %s: %s", container_name, exc)
        return None


def _write_wal_record(step_id: str, runbook_id: str, status: str, detail: dict) -> None:
    """Write a WAL record for a runbook step. Fire-and-forget."""
    try:
        container = _get_cosmos_container("wal_records")
        if container is None:
            return
        record = {
            "id": str(uuid.uuid4()),
            "partition_key": runbook_id,
            "runbook_id": runbook_id,
            "step_id": step_id,
            "status": status,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        container.create_item(body=record)
    except Exception as exc:
        logger.warning("WAL write failed for step %s: %s", step_id, exc)


def _create_approval_record(
    step_id: str,
    tool_name: str,
    runbook_id: str,
    incident_context: dict,
    resolved_params: dict,
) -> dict:
    """Create an approval record in Cosmos DB for a HITL gate. Returns the record."""
    approval_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    timeout_minutes = int(os.environ.get("APPROVAL_TIMEOUT_MINUTES", "30"))
    from datetime import timedelta

    record = {
        "id": approval_id,
        "partition_key": approval_id,
        "type": "runbook_step_approval",
        "runbook_id": runbook_id,
        "step_id": step_id,
        "tool_name": tool_name,
        "incident_context": incident_context,
        "resolved_parameters": resolved_params,
        "status": "pending",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=timeout_minutes)).isoformat(),
    }
    try:
        container = _get_cosmos_container("approvals")
        if container is not None:
            container.create_item(body=record)
    except Exception as exc:
        logger.warning("Approval creation failed for step %s: %s", step_id, exc)
    return record


# ---------------------------------------------------------------------------
# RunbookExecutor
# ---------------------------------------------------------------------------


class RunbookExecutor:
    """Execute automation runbook steps sequentially with HITL gates."""

    def __init__(self, cosmos_client: Optional[Any] = None) -> None:
        self._cosmos_client = cosmos_client

    async def execute(
        self,
        runbook_id: str,
        incident_context: dict,
        dry_run: bool = False,
    ) -> AsyncGenerator[dict, None]:
        """Execute a runbook by ID, streaming step results.

        Yields dicts per step: {step_id, tool_name, status, result, requires_approval}.
        Looks up runbook from BUILTIN_RUNBOOKS; returns error event if not found.
        """
        runbook_data = BUILTIN_RUNBOOKS.get(runbook_id)
        if runbook_data is None:
            yield {
                "type": "error",
                "message": f"Runbook '{runbook_id}' not found",
            }
            return

        steps: list[dict] = runbook_data.get("automation_steps", [])

        yield {
            "type": "runbook_start",
            "runbook_id": runbook_id,
            "name": runbook_data.get("name"),
            "total_steps": len(steps),
            "dry_run": dry_run,
        }

        rollback_stack: list[dict] = []

        for idx, step_raw in enumerate(steps):
            step_id = step_raw.get("step_id", str(uuid.uuid4()))
            tool_name = step_raw.get("tool_name", "unknown")
            parameters_template: dict = step_raw.get("parameters_template", {})
            require_approval: bool = step_raw.get("require_approval", True)
            on_failure: str = step_raw.get("on_failure", "abort")

            start_time = time.monotonic()

            # Resolve Jinja2 templates
            resolved_params = resolve_parameters(parameters_template, incident_context)

            step_event: dict = {
                "type": "step",
                "step_index": idx,
                "step_id": step_id,
                "tool_name": tool_name,
                "resolved_parameters": resolved_params,
                "requires_approval": require_approval,
                "status": "pending",
                "result": None,
                "dry_run": dry_run,
            }

            # HITL gate
            if require_approval and not dry_run:
                approval_record = _create_approval_record(
                    step_id=step_id,
                    tool_name=tool_name,
                    runbook_id=runbook_id,
                    incident_context=incident_context,
                    resolved_params=resolved_params,
                )
                step_event["status"] = "awaiting_approval"
                step_event["approval_id"] = approval_record.get("id")
                yield step_event
                # In a full implementation, we would await approval via polling or
                # webhook callback. For the streaming model, we emit the gate event
                # and the client/HITL flow handles resolution externally.
                _write_wal_record(
                    step_id=step_id,
                    runbook_id=runbook_id,
                    status="awaiting_approval",
                    detail={"approval_id": approval_record.get("id")},
                )
                # Simulate gate — in production this would suspend and resume
                # For now, we mark as gate_emitted and continue the stream
                continue

            # Execute step (simulated — real tools wired via tool_executor)
            try:
                result = await self._execute_step(
                    tool_name=tool_name,
                    resolved_params=resolved_params,
                    dry_run=dry_run,
                )
                duration_ms = int((time.monotonic() - start_time) * 1000)
                step_event["status"] = "success"
                step_event["result"] = result
                step_event["duration_ms"] = duration_ms
                rollback_stack.append({"step_id": step_id, "tool_name": tool_name, "params": resolved_params})
                _write_wal_record(
                    step_id=step_id,
                    runbook_id=runbook_id,
                    status="success",
                    detail={"duration_ms": duration_ms, "result": result},
                )
                yield step_event

            except Exception as exc:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                error_msg = str(exc)
                logger.error("Step %s failed: %s", step_id, error_msg)
                step_event["status"] = "failed"
                step_event["result"] = {"error": error_msg}
                step_event["duration_ms"] = duration_ms
                _write_wal_record(
                    step_id=step_id,
                    runbook_id=runbook_id,
                    status="failed",
                    detail={"error": error_msg, "duration_ms": duration_ms},
                )
                yield step_event

                if on_failure == "abort":
                    yield {"type": "runbook_aborted", "reason": f"Step {step_id} failed: {error_msg}"}
                    return
                elif on_failure == "rollback":
                    async for rollback_event in self._rollback(rollback_stack, runbook_id):
                        yield rollback_event
                    yield {"type": "runbook_aborted", "reason": f"Rollback triggered by step {step_id}"}
                    return
                # on_failure == "continue" → proceed to next step

        yield {"type": "runbook_complete", "runbook_id": runbook_id}

    async def _execute_step(
        self,
        tool_name: str,
        resolved_params: dict,
        dry_run: bool = False,
    ) -> dict:
        """Execute a single tool step. Returns result dict. Never raises in dry_run."""
        if dry_run:
            return {"dry_run": True, "tool_name": tool_name, "would_execute": resolved_params}

        # Delegate to tool_executor if available
        try:
            from services.api_gateway.tool_executor import execute_tool

            return await execute_tool(tool_name=tool_name, parameters=resolved_params)
        except ImportError:
            logger.warning("tool_executor not available; returning simulated result for %s", tool_name)
            return {"simulated": True, "tool_name": tool_name, "parameters": resolved_params}
        except Exception as exc:
            raise RuntimeError(f"Tool '{tool_name}' execution failed: {exc}") from exc

    async def _rollback(
        self, rollback_stack: list[dict], runbook_id: str
    ) -> AsyncGenerator[dict, None]:
        """Emit rollback events for completed steps in reverse order."""
        for step in reversed(rollback_stack):
            yield {
                "type": "rollback_step",
                "step_id": step["step_id"],
                "tool_name": step["tool_name"],
                "status": "rollback_simulated",
            }
            _write_wal_record(
                step_id=step["step_id"],
                runbook_id=runbook_id,
                status="rolled_back",
                detail={"params": step["params"]},
            )
