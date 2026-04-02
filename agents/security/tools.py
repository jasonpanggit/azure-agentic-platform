"""Security Agent tool functions — Defender, Key Vault, and IAM audit wrappers.

Allowed MCP tools (explicit allowlist — no wildcards):
    keyvault.list_vaults, keyvault.get_vault, role.list_assignments,
    monitor.query_logs, monitor.query_metrics,
    resourcehealth.get_availability_status,
    query_defender_alerts, query_keyvault_diagnostics,
    query_iam_changes, query_secure_score,
    query_rbac_assignments, query_policy_compliance,
    scan_public_endpoints
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry

# Lazy import — azure-mgmt-security may not be installed in all envs
try:
    from azure.mgmt.security import SecurityCenter
except ImportError:
    SecurityCenter = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-authorization may not be installed in all envs
try:
    from azure.mgmt.authorization import AuthorizationManagementClient
except ImportError:
    AuthorizationManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-policyinsights may not be installed in all envs
try:
    from azure.mgmt.policyinsights import PolicyInsightsClient
    from azure.mgmt.policyinsights.models import QueryOptions
except ImportError:
    PolicyInsightsClient = None  # type: ignore[assignment,misc]
    QueryOptions = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-network may not be installed in all envs
try:
    from azure.mgmt.network import NetworkManagementClient
except ImportError:
    NetworkManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-monitor may not be installed in all envs (for IAM changes)
try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-monitor-query may not be installed in all envs (for KV diagnostics)
try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-security-agent")
logger = logging.getLogger(__name__)

# Explicit MCP tool allowlist — no wildcards permitted.
ALLOWED_MCP_TOOLS: List[str] = [
    "keyvault.list_vaults",
    "keyvault.get_vault",
    "role.list_assignments",
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
]


def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {
        "azure-mgmt-security": "azure.mgmt.security",
        "azure-mgmt-authorization": "azure.mgmt.authorization",
        "azure-mgmt-policyinsights": "azure.mgmt.policyinsights",
        "azure-mgmt-network": "azure.mgmt.network",
        "azure-monitor-query": "azure.monitor.query",
    }
    for pkg, module in packages.items():
        try:
            __import__(module)
            logger.info("security_tools: sdk_available | package=%s", pkg)
        except ImportError:
            logger.warning(
                "security_tools: sdk_missing | package=%s — tool will return error", pkg
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


@ai_function
def query_defender_alerts(
    subscription_id: str,
    severity: Optional[str] = None,
) -> Dict[str, Any]:
    """Query active Defender for Cloud alerts for a subscription.

    Retrieves security alerts from Microsoft Defender for Cloud.
    Results can be filtered by severity (High/Medium/Low/Informational).

    Args:
        subscription_id: Azure subscription ID to query.
        severity: Optional severity filter ("High", "Medium", "Low",
            "Informational"). If None, returns all severities.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            severity_filter (str | None): Severity filter applied.
            alerts (list): Defender alert objects.
            alert_count (int): Total number of alerts returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"subscription_id": subscription_id, "severity": severity}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="security-agent",
        agent_id=agent_id,
        tool_name="query_defender_alerts",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if SecurityCenter is None:
                raise ImportError("azure-mgmt-security is not installed")

            credential = get_credential()
            client = SecurityCenter(credential, subscription_id)
            alerts_iter = client.alerts.list()

            alerts: List[Dict[str, Any]] = []
            for a in alerts_iter:
                if severity and a.properties and a.properties.severity != severity:
                    continue
                resource_identifiers: List[Optional[str]] = []
                if a.properties and a.properties.resource_identifiers:
                    for ri in a.properties.resource_identifiers:
                        resource_identifiers.append(
                            ri.resource_id if hasattr(ri, "resource_id") else str(ri)
                        )
                alerts.append(
                    {
                        "id": a.id,
                        "name": a.name,
                        "severity": a.properties.severity if a.properties else None,
                        "status": a.properties.status if a.properties else None,
                        "start_time_utc": (
                            a.properties.start_time_utc.isoformat()
                            if a.properties and a.properties.start_time_utc
                            else None
                        ),
                        "description": a.properties.description if a.properties else None,
                        "resource_identifiers": resource_identifiers,
                    }
                )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_defender_alerts: complete | subscription=%s alerts=%d duration_ms=%.0f",
                subscription_id,
                len(alerts),
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "severity_filter": severity,
                "alerts": alerts,
                "alert_count": len(alerts),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_defender_alerts: failed | subscription=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "severity_filter": severity,
                "alerts": [],
                "alert_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_keyvault_diagnostics(
    vault_name: str,
    workspace_id: Optional[str] = None,
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Query Key Vault diagnostic logs for access anomalies via Log Analytics.

    Retrieves Key Vault audit logs including secret/key/certificate
    access operations to detect anomalous access patterns. Used for
    immediate escalation assessment (security constraint #1).

    NOTE: This tool queries Key Vault CONTROL PLANE logs only.
    The Security Agent MUST NOT access Key Vault data plane
    (secrets, keys, certificates).

    KV audit logs live in Log Analytics (AzureDiagnostics table). When
    workspace_id is not provided, the tool returns query_status="skipped"
    gracefully — no Log Analytics workspace is configured.

    Args:
        vault_name: Name of the Key Vault to query.
        workspace_id: Log Analytics workspace resource ID. If None or empty,
            the tool returns query_status="skipped".
        timespan_hours: Look-back window in hours (default: 2).

    Returns:
        Dict with keys:
            vault_name (str): Key Vault queried.
            workspace_id (str | None): Log Analytics workspace used.
            timespan_hours (int): Look-back window applied.
            operations (list): Audit log entries with operation type and caller.
            anomaly_indicators (list): Flagged access patterns (Unauthorized/Forbidden).
            query_status (str): "success", "skipped", or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "vault_name": vault_name,
        "workspace_id": workspace_id,
        "timespan_hours": timespan_hours,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="security-agent",
        agent_id=agent_id,
        tool_name="query_keyvault_diagnostics",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        # Guard: no workspace configured — skip gracefully
        if not workspace_id:
            logger.warning(
                "query_keyvault_diagnostics: skipped | workspace_id is empty — "
                "no Log Analytics workspace configured"
            )
            return {
                "vault_name": vault_name,
                "workspace_id": workspace_id,
                "timespan_hours": timespan_hours,
                "operations": [],
                "anomaly_indicators": [],
                "query_status": "skipped",
            }

        start_time = time.monotonic()
        try:
            if LogsQueryClient is None:
                raise ImportError("azure-monitor-query is not installed")

            credential = get_credential()
            client = LogsQueryClient(credential)

            kql_query = (
                "AzureDiagnostics\n"
                '| where ResourceType == "VAULTS"\n'
                f'| where ResourceId contains "{vault_name}"\n'
                f"| where TimeGenerated > ago({timespan_hours}h)\n"
                '| where OperationName != "Authentication"\n'
                "| project TimeGenerated, OperationName, CallerIPAddress, "
                "ResultType, identity_claim_oid_g\n"
                "| order by TimeGenerated desc\n"
                "| take 200"
            )

            response = client.query_workspace(
                workspace_id=workspace_id,
                query=kql_query,
                timespan=f"PT{timespan_hours}H",
            )

            operations: List[Dict[str, Any]] = []
            if response.status == LogsQueryStatus.SUCCESS:
                for table in response.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        row_dict = dict(zip(col_names, row))
                        operations.append(
                            {
                                "timestamp": str(row_dict.get("TimeGenerated", "")),
                                "operation_name": str(row_dict.get("OperationName", "")),
                                "caller_ip": str(row_dict.get("CallerIPAddress", "")),
                                "result_type": str(row_dict.get("ResultType", "")),
                                "principal_oid": str(
                                    row_dict.get("identity_claim_oid_g", "")
                                ),
                            }
                        )

            anomaly_indicators = [
                op
                for op in operations
                if "Unauthorized" in op.get("result_type", "")
                or "Forbidden" in op.get("result_type", "")
            ]

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_keyvault_diagnostics: complete | vault=%s operations=%d "
                "anomalies=%d duration_ms=%.0f",
                vault_name,
                len(operations),
                len(anomaly_indicators),
                duration_ms,
            )
            return {
                "vault_name": vault_name,
                "workspace_id": workspace_id,
                "timespan_hours": timespan_hours,
                "operations": operations,
                "anomaly_indicators": anomaly_indicators,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_keyvault_diagnostics: failed | vault=%s error=%s duration_ms=%.0f",
                vault_name,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "vault_name": vault_name,
                "workspace_id": workspace_id,
                "timespan_hours": timespan_hours,
                "operations": [],
                "anomaly_indicators": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_iam_changes(
    subscription_id: str,
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Query Activity Log for IAM and RBAC changes in the prior N hours.

    This is the mandatory first-pass RCA step (TRIAGE-003) for security
    incidents. Retrieves RBAC role assignments, Key Vault policy changes,
    and identity operations from the Activity Log.

    Args:
        subscription_id: Azure subscription ID to query.
        timespan_hours: Look-back window in hours (default: 2, per TRIAGE-003).

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            timespan_hours (int): Look-back window applied.
            rbac_changes (list): Role assignment add/remove operations.
            keyvault_policy_changes (list): Key Vault access policy changes.
            identity_operations (list): Service principal and app registration events.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"subscription_id": subscription_id, "timespan_hours": timespan_hours}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="security-agent",
        agent_id=agent_id,
        tool_name="query_iam_changes",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
            client = MonitorManagementClient(credential, subscription_id)

            start = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
            filter_str = (
                f"eventTimestamp ge '{start.isoformat()}' "
                "and ("
                "operationName/value eq 'Microsoft.Authorization/roleAssignments/write' "
                "or operationName/value eq 'Microsoft.Authorization/roleAssignments/delete' "
                "or operationName/value eq 'Microsoft.KeyVault/vaults/accessPolicies/write'"
                ")"
            )

            events = client.activity_logs.list(filter=filter_str)

            rbac_changes: List[Dict[str, Any]] = []
            keyvault_policy_changes: List[Dict[str, Any]] = []
            identity_operations: List[Dict[str, Any]] = []

            for event in events:
                op_name = (
                    event.operation_name.value if event.operation_name else ""
                )
                entry = {
                    "eventTimestamp": (
                        event.event_timestamp.isoformat()
                        if event.event_timestamp
                        else None
                    ),
                    "operationName": op_name,
                    "caller": event.caller,
                    "status": event.status.value if event.status else None,
                    "resourceId": event.resource_id,
                }
                if op_name.startswith("Microsoft.Authorization/roleAssignments"):
                    rbac_changes.append(entry)
                elif op_name.startswith("Microsoft.KeyVault/vaults/accessPolicies"):
                    keyvault_policy_changes.append(entry)
                else:
                    identity_operations.append(entry)

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_iam_changes: complete | subscription=%s rbac=%d kv=%d "
                "identity=%d duration_ms=%.0f",
                subscription_id,
                len(rbac_changes),
                len(keyvault_policy_changes),
                len(identity_operations),
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "timespan_hours": timespan_hours,
                "rbac_changes": rbac_changes,
                "keyvault_policy_changes": keyvault_policy_changes,
                "identity_operations": identity_operations,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_iam_changes: failed | subscription=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "timespan_hours": timespan_hours,
                "rbac_changes": [],
                "keyvault_policy_changes": [],
                "identity_operations": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_secure_score(
    subscription_id: str,
) -> Dict[str, Any]:
    """Query the Microsoft Defender for Cloud Secure Score for a subscription.

    Returns the subscription-level composite security posture score using
    the fixed identifier "ascScore". This hard-coded identifier is the
    standard name for the overall subscription secure score in Defender for
    Cloud — it is not the subscription ID.

    Args:
        subscription_id: Azure subscription ID to query.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            score_percentage (float | None): Secure score as a percentage (0–100).
            current_score (float | None): Current raw score value.
            max_score (float | None): Maximum possible score.
            unhealthy_resource_count (int | None): Number of unhealthy resources.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"subscription_id": subscription_id}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="security-agent",
        agent_id=agent_id,
        tool_name="query_secure_score",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if SecurityCenter is None:
                raise ImportError("azure-mgmt-security is not installed")

            credential = get_credential()
            client = SecurityCenter(credential, subscription_id)
            # "ascScore" is the fixed identifier for the subscription-level
            # composite Defender for Cloud secure score.
            score = client.secure_scores.get(subscription_id, "ascScore")

            score_percentage = None
            current_score = None
            max_score = None
            unhealthy_resource_count = None

            if score.properties and score.properties.score:
                score_percentage = score.properties.score.percentage
                current_score = score.properties.score.current
                max_score = score.properties.score.max
            if score.properties:
                unhealthy_resource_count = score.properties.unhealthy_resource_count

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_secure_score: complete | subscription=%s score_pct=%s duration_ms=%.0f",
                subscription_id,
                score_percentage,
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "score_percentage": score_percentage,
                "current_score": current_score,
                "max_score": max_score,
                "unhealthy_resource_count": unhealthy_resource_count,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_secure_score: failed | subscription=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "score_percentage": None,
                "current_score": None,
                "max_score": None,
                "unhealthy_resource_count": None,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_rbac_assignments(
    subscription_id: str,
    scope: Optional[str] = None,
    max_results: int = 100,
) -> Dict[str, Any]:
    """Query RBAC role assignments for a subscription or specific scope.

    Lists role assignments to identify over-privileged identities or
    unexpected access grants. A large subscription can return thousands of
    assignments — use max_results to cap the result set. Check the
    `truncated` flag to know if results were cut off.

    Args:
        subscription_id: Azure subscription ID to query.
        scope: Optional scope to filter by (e.g. resource group ID or
            resource ID). If None, lists all assignments in the subscription.
        max_results: Maximum number of assignments to return (default: 100).
            If the actual count exceeds this, `truncated` will be True.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            scope (str | None): Scope filter applied.
            assignments (list): Role assignment objects.
            total_count (int): Number of assignments returned.
            truncated (bool): True if results were capped at max_results.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "scope": scope,
        "max_results": max_results,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="security-agent",
        agent_id=agent_id,
        tool_name="query_rbac_assignments",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if AuthorizationManagementClient is None:
                raise ImportError("azure-mgmt-authorization is not installed")

            credential = get_credential()
            client = AuthorizationManagementClient(credential, subscription_id)

            if scope:
                assignments_iter = client.role_assignments.list_for_scope(scope)
            else:
                assignments_iter = client.role_assignments.list_for_subscription()

            assignments: List[Dict[str, Any]] = []
            truncated = False
            count = 0
            for assignment in assignments_iter:
                if count >= max_results:
                    truncated = True
                    break
                assignments.append(
                    {
                        "id": assignment.id,
                        "principal_id": assignment.principal_id,
                        "principal_type": (
                            assignment.principal_type
                            if hasattr(assignment, "principal_type")
                            else None
                        ),
                        "role_definition_id": assignment.role_definition_id,
                        "scope": assignment.scope,
                    }
                )
                count += 1

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_rbac_assignments: complete | subscription=%s count=%d "
                "truncated=%s duration_ms=%.0f",
                subscription_id,
                len(assignments),
                truncated,
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "scope": scope,
                "assignments": assignments,
                "total_count": len(assignments),
                "truncated": truncated,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_rbac_assignments: failed | subscription=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "scope": scope,
                "assignments": [],
                "total_count": 0,
                "truncated": False,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_policy_compliance(
    subscription_id: str,
    policy_definition_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Query Azure Policy compliance state for non-compliant resources.

    Returns only non-compliant policy states. The full compliant count
    requires a separate query — this tool surfaces violations only.
    Use policy_definition_id to narrow results to a specific policy.

    Args:
        subscription_id: Azure subscription ID to query.
        policy_definition_id: Optional policy definition resource ID to
            filter results. If None, returns non-compliant states across
            all policies.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            policy_definition_id (str | None): Policy filter applied.
            non_compliant_count (int): Number of non-compliant resources found.
            policy_states (list): Non-compliant policy state objects.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "policy_definition_id": policy_definition_id,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="security-agent",
        agent_id=agent_id,
        tool_name="query_policy_compliance",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if PolicyInsightsClient is None:
                raise ImportError("azure-mgmt-policyinsights is not installed")

            credential = get_credential()
            client = PolicyInsightsClient(credential, subscription_id)

            filter_str = "complianceState eq 'NonCompliant'"
            if policy_definition_id:
                filter_str += f" and policyDefinitionId eq '{policy_definition_id}'"

            query_options = QueryOptions(filter=filter_str) if QueryOptions else None
            results = client.policy_states.list_query_results_for_subscription(
                "latest",
                subscription_id,
                query_options=query_options,
            )

            policy_states: List[Dict[str, Any]] = []
            for state in results:
                policy_states.append(
                    {
                        "resource_id": state.resource_id,
                        "policy_assignment_name": state.policy_assignment_name,
                        "policy_definition_id": state.policy_definition_id,
                        "compliance_state": state.compliance_state,
                        "timestamp": (
                            state.timestamp.isoformat() if state.timestamp else None
                        ),
                    }
                )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_policy_compliance: complete | subscription=%s non_compliant=%d "
                "duration_ms=%.0f",
                subscription_id,
                len(policy_states),
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "policy_definition_id": policy_definition_id,
                "non_compliant_count": len(policy_states),
                "policy_states": policy_states,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_policy_compliance: failed | subscription=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "policy_definition_id": policy_definition_id,
                "non_compliant_count": 0,
                "policy_states": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def scan_public_endpoints(
    subscription_id: str,
) -> Dict[str, Any]:
    """Scan all public IP addresses in a subscription to identify internet-facing resources.

    Enumerates every public IP across all resource groups to help identify
    unintended internet-facing resources. Any public IP with no
    resource_association may be an orphaned resource wasting cost and
    increasing attack surface.

    Args:
        subscription_id: Azure subscription ID to scan.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription scanned.
            public_ips (list): Public IP address objects.
            total_count (int): Number of public IPs found.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"subscription_id": subscription_id}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="security-agent",
        agent_id=agent_id,
        tool_name="scan_public_endpoints",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if NetworkManagementClient is None:
                raise ImportError("azure-mgmt-network is not installed")

            credential = get_credential()
            client = NetworkManagementClient(credential, subscription_id)

            public_ips: List[Dict[str, Any]] = []
            for ip in client.public_ip_addresses.list_all():
                # Extract resource group from the resource ID
                resource_group: Optional[str] = None
                if ip.id:
                    parts = ip.id.split("/")
                    try:
                        rg_idx = [p.lower() for p in parts].index("resourcegroups")
                        resource_group = parts[rg_idx + 1]
                    except (ValueError, IndexError):
                        pass

                public_ips.append(
                    {
                        "id": ip.id,
                        "name": ip.name,
                        "resource_group": resource_group,
                        "ip_address": ip.ip_address,
                        "allocation_method": (
                            ip.public_ip_allocation_method
                            if hasattr(ip, "public_ip_allocation_method")
                            else None
                        ),
                        "sku": ip.sku.name if ip.sku else None,
                        "resource_association": (
                            ip.ip_configuration.id
                            if ip.ip_configuration
                            else None
                        ),
                    }
                )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "scan_public_endpoints: complete | subscription=%s public_ips=%d "
                "duration_ms=%.0f",
                subscription_id,
                len(public_ips),
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "public_ips": public_ips,
                "total_count": len(public_ips),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "scan_public_endpoints: failed | subscription=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "public_ips": [],
                "total_count": 0,
                "query_status": "error",
                "error": str(e),
            }
