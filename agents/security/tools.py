"""Security Agent tool functions — real Azure SDK implementations.

7 tools covering Defender alerts, Key Vault diagnostics, IAM changes,
secure score, RBAC assignments, policy compliance, and public endpoint scanning.

Allowed MCP tools (explicit allowlist — v2 namespace names, no wildcards):
    keyvault, role, monitor, resourcehealth, advisor
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry

# ---------------------------------------------------------------------------
# Lazy imports — SDKs may not be installed in all environments
# ---------------------------------------------------------------------------

try:
    from azure.mgmt.security import SecurityCenter
except ImportError:
    SecurityCenter = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.authorization import AuthorizationManagementClient
except ImportError:
    AuthorizationManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.policyinsights import PolicyInsightsClient
except ImportError:
    PolicyInsightsClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.network import NetworkManagementClient
except ImportError:
    NetworkManagementClient = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-security-agent")
logger = logging.getLogger(__name__)

# Explicit MCP tool allowlist — v2 namespace names (no dotted names, no wildcards).
ALLOWED_MCP_TOOLS: List[str] = [
    "keyvault",
    "role",
    "monitor",
    "resourcehealth",
    "advisor",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {
        "azure-mgmt-security": "azure.mgmt.security",
        "azure-mgmt-authorization": "azure.mgmt.authorization",
        "azure-mgmt-policyinsights": "azure.mgmt.policyinsights",
        "azure-mgmt-monitor": "azure.mgmt.monitor",
        "azure-monitor-query": "azure.monitor.query",
        "azure-mgmt-network": "azure.mgmt.network",
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


# ---------------------------------------------------------------------------
# Tool 1: query_defender_alerts
# ---------------------------------------------------------------------------


@ai_function
def query_defender_alerts(
    subscription_id: str,
    severity: Optional[str] = None,
    asc_location: str = "centralus",
) -> Dict[str, Any]:
    """Query active Defender for Cloud alerts for a subscription.

    Retrieves security alerts from Microsoft Defender for Cloud.
    Results can be filtered by severity (High/Medium/Low/Informational).

    Args:
        subscription_id: Azure subscription ID to query.
        severity: Optional severity filter ("High", "Medium", "Low",
            "Informational"). If None, returns all severities.
        asc_location: ASC location (default: "centralus").

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            severity_filter (str | None): Severity filter applied.
            asc_location (str): ASC location used.
            alerts (list): Defender alert objects.
            alert_count (int): Total number of alerts returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "severity": severity,
        "asc_location": asc_location,
    }

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
            client = SecurityCenter(credential, subscription_id, asc_location=asc_location)
            raw_alerts = client.alerts.list()

            alerts: List[Dict[str, Any]] = []
            for alert in raw_alerts:
                if len(alerts) >= 200:
                    break
                if severity is not None and getattr(alert, "severity", None) != severity:
                    continue
                alerts.append({
                    "alert_display_name": getattr(alert, "alert_display_name", None),
                    "severity": getattr(alert, "severity", None),
                    "status": getattr(alert, "status", None),
                    "description": getattr(alert, "description", None),
                    "compromised_entity": getattr(alert, "compromised_entity", None),
                    "time_generated_utc": (
                        alert.time_generated_utc.isoformat()
                        if getattr(alert, "time_generated_utc", None)
                        else None
                    ),
                    "alert_type": getattr(alert, "alert_type", None),
                    "product_name": getattr(alert, "product_name", None),
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_defender_alerts: complete | sub=%s alerts=%d severity=%s duration_ms=%.0f",
                subscription_id,
                len(alerts),
                severity,
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "severity_filter": severity,
                "asc_location": asc_location,
                "alerts": alerts,
                "alert_count": len(alerts),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_defender_alerts: failed | sub=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "severity_filter": severity,
                "asc_location": asc_location,
                "alerts": [],
                "alert_count": 0,
                "query_status": "error",
                "error": str(e),
            }


# ---------------------------------------------------------------------------
# Tool 2: query_keyvault_diagnostics
# ---------------------------------------------------------------------------


@ai_function
def query_keyvault_diagnostics(
    vault_name: str,
    timespan_hours: int = 2,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Query Key Vault diagnostic logs for access anomalies.

    Retrieves Key Vault audit logs including secret/key/certificate
    access operations to detect anomalous access patterns. Used for
    immediate escalation assessment (security constraint #1).

    NOTE: This tool queries Key Vault CONTROL PLANE logs only.
    The Security Agent MUST NOT access Key Vault data plane
    (secrets, keys, certificates).

    Args:
        vault_name: Name of the Key Vault to query.
        timespan_hours: Look-back window in hours (default: 2).
        workspace_id: Log Analytics workspace ID. If None, reads from
            LOG_ANALYTICS_WORKSPACE_ID environment variable.

    Returns:
        Dict with keys:
            vault_name (str): Key Vault queried.
            timespan_hours (int): Look-back window applied.
            workspace_id (str): Workspace used.
            operations (list): Audit log entries with operation type and caller.
            operation_count (int): Number of operations returned.
            anomaly_indicators (list): Flagged access patterns.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    resolved_workspace_id = workspace_id or os.environ.get("LOG_ANALYTICS_WORKSPACE_ID")
    tool_params = {
        "vault_name": vault_name,
        "timespan_hours": timespan_hours,
        "workspace_id": resolved_workspace_id,
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
        start_time = time.monotonic()
        try:
            if LogsQueryClient is None:
                raise ImportError("azure-monitor-query is not installed")
            if not resolved_workspace_id:
                raise ValueError(
                    "workspace_id is required — pass it directly or set "
                    "LOG_ANALYTICS_WORKSPACE_ID environment variable"
                )

            credential = get_credential()
            client = LogsQueryClient(credential)

            kql_query = (
                "AzureDiagnostics"
                " | where ResourceProvider == 'MICROSOFT.KEYVAULT'"
                f" | where Resource =~ '{vault_name}'"
                f" | where TimeGenerated > ago({timespan_hours}h)"
                " | project TimeGenerated, OperationName, CallerIPAddress,"
                " ResultType, ResultSignature, ResultDescription,"
                " Identity=identity_claim_upn_s"
                " | order by TimeGenerated desc"
                " | take 100"
            )

            response = client.query_workspace(
                workspace_id=resolved_workspace_id,
                query=kql_query,
                timespan=timedelta(hours=timespan_hours),
            )

            operations: List[Dict[str, Any]] = []
            if hasattr(response, "status") and response.status == LogsQueryStatus.SUCCESS:
                for table in response.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        operations.append(
                            dict(
                                zip(
                                    col_names,
                                    [str(v) if v is not None else None for v in row],
                                )
                            )
                        )

            # Anomaly detection
            anomaly_indicators: List[str] = []
            unique_callers = {
                op.get("CallerIPAddress")
                for op in operations
                if op.get("CallerIPAddress")
            }
            if len(unique_callers) > 5:
                anomaly_indicators.append(
                    f"High caller diversity: {len(unique_callers)} unique IPs"
                )

            failed_ops = [
                op for op in operations if op.get("ResultType") != "Success"
            ]
            if failed_ops:
                anomaly_indicators.append(
                    f"Failed operations detected: {len(failed_ops)} failures"
                )

            from collections import Counter
            op_counts = Counter(op.get("OperationName") for op in operations)
            bulk_ops = {
                name: count for name, count in op_counts.items() if count > 20
            }
            if bulk_ops:
                anomaly_indicators.append(
                    f"Bulk operations detected: {bulk_ops}"
                )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_keyvault_diagnostics: complete | vault=%s ops=%d anomalies=%d duration_ms=%.0f",
                vault_name,
                len(operations),
                len(anomaly_indicators),
                duration_ms,
            )
            return {
                "vault_name": vault_name,
                "timespan_hours": timespan_hours,
                "workspace_id": resolved_workspace_id,
                "operations": operations,
                "operation_count": len(operations),
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
                "timespan_hours": timespan_hours,
                "workspace_id": resolved_workspace_id,
                "operations": [],
                "operation_count": 0,
                "anomaly_indicators": [],
                "query_status": "error",
                "error": str(e),
            }


# ---------------------------------------------------------------------------
# Tool 3: query_iam_changes
# ---------------------------------------------------------------------------


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
            total_changes (int): Total number of changes found.
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
                "and resourceProvider eq 'Microsoft.Authorization'"
            )
            events = client.activity_logs.list(filter=filter_str)

            rbac_changes: List[Dict[str, Any]] = []
            keyvault_policy_changes: List[Dict[str, Any]] = []
            identity_operations: List[Dict[str, Any]] = []

            for event in events:
                op_name = (
                    event.operation_name.value
                    if event.operation_name
                    else ""
                )
                entry = {
                    "eventTimestamp": (
                        event.event_timestamp.isoformat()
                        if event.event_timestamp
                        else None
                    ),
                    "operationName": op_name,
                    "caller": event.caller,
                    "status": (
                        event.status.value if event.status else None
                    ),
                    "resourceId": event.resource_id,
                    "level": (
                        event.level.value if event.level else None
                    ),
                    "description": event.description,
                }

                op_lower = op_name.lower()
                if "roleassignments/write" in op_lower or "roleassignments/delete" in op_lower:
                    rbac_changes.append(entry)
                elif "microsoft.keyvault/vaults/accesspolicies" in op_lower:
                    keyvault_policy_changes.append(entry)
                elif "microsoft.managedidentity" in op_lower or "microsoft.authorization/policyassignments" in op_lower:
                    identity_operations.append(entry)

            total_changes = len(rbac_changes) + len(keyvault_policy_changes) + len(identity_operations)
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_iam_changes: complete | sub=%s rbac=%d kv=%d identity=%d duration_ms=%.0f",
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
                "total_changes": total_changes,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_iam_changes: failed | sub=%s error=%s duration_ms=%.0f",
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
                "total_changes": 0,
                "query_status": "error",
                "error": str(e),
            }


# ---------------------------------------------------------------------------
# Tool 4: query_secure_score
# ---------------------------------------------------------------------------


@ai_function
def query_secure_score(
    subscription_id: str,
    asc_location: str = "centralus",
) -> Dict[str, Any]:
    """Query the Microsoft Defender for Cloud Secure Score for a subscription.

    Provides a security posture overview including current score, max possible,
    and percentage. Use this to understand overall security health.

    Args:
        subscription_id: Azure subscription ID to query.
        asc_location: ASC location (default: "centralus").

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            current_score (float): Current secure score.
            max_score (int): Maximum possible score.
            percentage (float): Score as percentage.
            weight (int): Score weight.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"subscription_id": subscription_id, "asc_location": asc_location}

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
            client = SecurityCenter(credential, subscription_id, asc_location=asc_location)
            score = client.secure_scores.get(secure_score_name="ascScore")

            current_score = (
                score.current_score if hasattr(score, "current_score") else 0.0
            )
            max_score = (
                score.max_score if hasattr(score, "max_score") else 0
            )
            percentage = (
                score.percentage if hasattr(score, "percentage") else 0.0
            )
            weight = (
                score.weight if hasattr(score, "weight") else 0
            )

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_secure_score: complete | sub=%s score=%.1f/%.0f pct=%.1f%% duration_ms=%.0f",
                subscription_id,
                current_score,
                max_score,
                percentage * 100 if percentage <= 1.0 else percentage,
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "current_score": current_score,
                "max_score": max_score,
                "percentage": percentage,
                "weight": weight,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_secure_score: failed | sub=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "current_score": 0.0,
                "max_score": 0,
                "percentage": 0.0,
                "weight": 0,
                "query_status": "error",
                "error": str(e),
            }


# ---------------------------------------------------------------------------
# Tool 5: query_rbac_assignments
# ---------------------------------------------------------------------------


@ai_function
def query_rbac_assignments(
    subscription_id: str,
    scope: Optional[str] = None,
    principal_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Query RBAC role assignments for a subscription or specific scope.

    Lists Azure role assignments to audit RBAC drift. Can filter by scope
    (e.g., resource group or resource) and/or principal ID.

    Args:
        subscription_id: Azure subscription ID to query.
        scope: Optional scope to filter assignments (e.g., resource group ID).
            If None, lists all assignments for the subscription.
        principal_id: Optional principal ID to filter assignments.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            scope_filter (str | None): Scope filter applied.
            principal_id_filter (str | None): Principal ID filter applied.
            assignments (list): RBAC assignment objects.
            assignment_count (int): Total assignments returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "scope": scope,
        "principal_id": principal_id,
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

            if scope is not None:
                raw_assignments = client.role_assignments.list_for_scope(scope=scope)
            else:
                raw_assignments = client.role_assignments.list_for_subscription()

            assignments: List[Dict[str, Any]] = []
            for ra in raw_assignments:
                if len(assignments) >= 500:
                    break
                if principal_id is not None and getattr(ra, "principal_id", None) != principal_id:
                    continue
                assignments.append({
                    "id": ra.id,
                    "principal_id": getattr(ra, "principal_id", None),
                    "principal_type": getattr(ra, "principal_type", None),
                    "role_definition_id": getattr(ra, "role_definition_id", None),
                    "scope": getattr(ra, "scope", None),
                    "created_on": (
                        ra.created_on.isoformat()
                        if getattr(ra, "created_on", None)
                        else None
                    ),
                    "updated_on": (
                        ra.updated_on.isoformat()
                        if getattr(ra, "updated_on", None)
                        else None
                    ),
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_rbac_assignments: complete | sub=%s scope=%s assignments=%d duration_ms=%.0f",
                subscription_id,
                scope,
                len(assignments),
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "scope_filter": scope,
                "principal_id_filter": principal_id,
                "assignments": assignments,
                "assignment_count": len(assignments),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_rbac_assignments: failed | sub=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "scope_filter": scope,
                "principal_id_filter": principal_id,
                "assignments": [],
                "assignment_count": 0,
                "query_status": "error",
                "error": str(e),
            }


# ---------------------------------------------------------------------------
# Tool 6: query_policy_compliance
# ---------------------------------------------------------------------------


@ai_function
def query_policy_compliance(
    subscription_id: str,
    compliance_state: str = "NonCompliant",
    max_results: int = 100,
) -> Dict[str, Any]:
    """Query Azure Policy compliance state for a subscription.

    Retrieves policy compliance results, filtered by compliance state.
    Default filters for NonCompliant resources to identify policy violations.

    Args:
        subscription_id: Azure subscription ID to query.
        compliance_state: Compliance state filter (default: "NonCompliant").
        max_results: Maximum number of results to return (default: 100).

    Returns:
        Dict with keys:
            subscription_id (str): Subscription queried.
            compliance_state_filter (str): Compliance state filter applied.
            max_results (int): Max results requested.
            policy_states (list): Policy compliance state objects.
            non_compliant_count (int): Count of non-compliant resources.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_id": subscription_id,
        "compliance_state": compliance_state,
        "max_results": max_results,
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
            raw_states = client.policy_states.list_query_results_for_subscription(
                policy_states_resource="latest",
            )

            policy_states: List[Dict[str, Any]] = []
            for state in raw_states:
                if len(policy_states) >= max_results:
                    break
                state_compliance = getattr(state, "compliance_state", None)
                if state_compliance != compliance_state:
                    continue
                policy_states.append({
                    "resource_id": getattr(state, "resource_id", None),
                    "policy_assignment_id": getattr(state, "policy_assignment_id", None),
                    "policy_definition_id": getattr(state, "policy_definition_id", None),
                    "compliance_state": state_compliance,
                    "resource_type": getattr(state, "resource_type", None),
                    "resource_group": getattr(state, "resource_group", None),
                    "is_compliant": getattr(state, "is_compliant", False),
                    "policy_definition_action": getattr(state, "policy_definition_action", None),
                })

            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "query_policy_compliance: complete | sub=%s state=%s results=%d duration_ms=%.0f",
                subscription_id,
                compliance_state,
                len(policy_states),
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "compliance_state_filter": compliance_state,
                "max_results": max_results,
                "policy_states": policy_states,
                "non_compliant_count": len(policy_states),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "query_policy_compliance: failed | sub=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "compliance_state_filter": compliance_state,
                "max_results": max_results,
                "policy_states": [],
                "non_compliant_count": 0,
                "query_status": "error",
                "error": str(e),
            }


# ---------------------------------------------------------------------------
# Tool 7: scan_public_endpoints
# ---------------------------------------------------------------------------


@ai_function
def scan_public_endpoints(
    subscription_id: str,
) -> Dict[str, Any]:
    """Scan all public IP addresses in a subscription for exposure assessment.

    Lists all public IP addresses and identifies unassociated IPs that may
    represent unnecessary exposure. Use when public-facing exposure is suspected.

    Args:
        subscription_id: Azure subscription ID to scan.

    Returns:
        Dict with keys:
            subscription_id (str): Subscription scanned.
            public_ips (list): Public IP address objects.
            public_ip_count (int): Total public IPs found.
            associated_count (int): IPs associated with a resource.
            unassociated_count (int): IPs not associated with any resource.
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
            raw_ips = client.public_ip_addresses.list_all()

            public_ips: List[Dict[str, Any]] = []
            associated_count = 0
            for pip in raw_ips:
                is_associated = getattr(pip, "ip_configuration", None) is not None
                if is_associated:
                    associated_count += 1

                # Extract resource group from ID
                rg = None
                if pip.id:
                    parts = pip.id.split("/")
                    try:
                        rg_idx = [p.lower() for p in parts].index("resourcegroups")
                        rg = parts[rg_idx + 1]
                    except (ValueError, IndexError):
                        pass

                public_ips.append({
                    "name": pip.name,
                    "resource_group": rg,
                    "ip_address": getattr(pip, "ip_address", None),
                    "public_ip_allocation_method": getattr(pip, "public_ip_allocation_method", None),
                    "ip_configuration_id": (
                        pip.ip_configuration.id
                        if getattr(pip, "ip_configuration", None)
                        else None
                    ),
                    "dns_fqdn": (
                        pip.dns_settings.fqdn
                        if getattr(pip, "dns_settings", None)
                        and getattr(pip.dns_settings, "fqdn", None)
                        else None
                    ),
                    "sku_name": (
                        pip.sku.name
                        if getattr(pip, "sku", None)
                        else None
                    ),
                    "associated": is_associated,
                })

            unassociated_count = len(public_ips) - associated_count
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "scan_public_endpoints: complete | sub=%s total=%d associated=%d unassociated=%d duration_ms=%.0f",
                subscription_id,
                len(public_ips),
                associated_count,
                unassociated_count,
                duration_ms,
            )
            return {
                "subscription_id": subscription_id,
                "public_ips": public_ips,
                "public_ip_count": len(public_ips),
                "associated_count": associated_count,
                "unassociated_count": unassociated_count,
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "scan_public_endpoints: failed | sub=%s error=%s duration_ms=%.0f",
                subscription_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "subscription_id": subscription_id,
                "public_ips": [],
                "public_ip_count": 0,
                "associated_count": 0,
                "unassociated_count": 0,
                "query_status": "error",
                "error": str(e),
            }
