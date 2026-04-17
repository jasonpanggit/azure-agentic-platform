from __future__ import annotations
"""VM Extension Health Audit service (Phase 89).

Scans Azure VMs for missing critical extensions (monitoring agent,
antivirus, Defender for Servers) and persists findings to Cosmos DB.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.api_gateway.arg_helper import run_arg_query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required extension definitions
# ---------------------------------------------------------------------------

REQUIRED_WINDOWS_EXTENSIONS: Dict[str, Dict[str, str]] = {
    "MicrosoftMonitoringAgent": {
        "publisher": "Microsoft.EnterpriseCloud.Monitoring",
        "description": "Log Analytics Agent (MMA)",
        "category": "monitoring",
    },
    "AzureMonitorWindowsAgent": {
        "publisher": "Microsoft.Azure.Monitor",
        "description": "Azure Monitor Agent (AMA)",
        "category": "monitoring",
    },
    "MDE.Windows": {
        "publisher": "Microsoft.Azure.AzureDefenderForServers",
        "description": "Defender for Servers",
        "category": "security",
    },
    "IaaSAntimalware": {
        "publisher": "Microsoft.Azure.Security",
        "description": "Antimalware",
        "category": "security",
    },
}

REQUIRED_LINUX_EXTENSIONS: Dict[str, Dict[str, str]] = {
    "OmsAgentForLinux": {
        "publisher": "Microsoft.EnterpriseCloud.Monitoring",
        "description": "Log Analytics Agent (OMS)",
        "category": "monitoring",
    },
    "AzureMonitorLinuxAgent": {
        "publisher": "Microsoft.Azure.Monitor",
        "description": "Azure Monitor Agent (AMA)",
        "category": "monitoring",
    },
    "MDE.Linux": {
        "publisher": "Microsoft.Azure.AzureDefenderForServers",
        "description": "Defender for Servers",
        "category": "security",
    },
}

# ---------------------------------------------------------------------------
# ARG KQL templates
# ---------------------------------------------------------------------------

_KQL_EXTENSIONS = """
Resources
| where type =~ 'microsoft.compute/virtualmachines/extensions'
| project
    ext_id = tolower(id),
    ext_name = name,
    vm_id = tolower(tostring(split(id, '/extensions/')[0])),
    subscription_id = subscriptionId,
    resource_group = resourceGroup,
    publisher = tostring(properties.publisher),
    ext_type = tostring(properties.type),
    provisioning_state = tostring(properties.provisioningState),
    auto_upgrade = tobool(properties.enableAutomaticUpgrade)
"""

_KQL_VMS = """
Resources
| where type =~ 'microsoft.compute/virtualmachines'
| project
    vm_id = tolower(id),
    vm_name = name,
    subscription_id = subscriptionId,
    resource_group = resourceGroup,
    location,
    os_type = tostring(properties.storageProfile.osDisk.osType)
"""

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class VMExtensionFinding:
    finding_id: str
    vm_id: str
    vm_name: str
    resource_group: str
    subscription_id: str
    location: str
    os_type: str
    installed_extensions: List[Dict[str, Any]]
    missing_extensions: List[Dict[str, str]]
    failed_extensions: List[Dict[str, str]]
    severity: str
    compliance_score: float
    scanned_at: str
    ttl: int = 86400

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.finding_id,
            "finding_id": self.finding_id,
            "vm_id": self.vm_id,
            "vm_name": self.vm_name,
            "resource_group": self.resource_group,
            "subscription_id": self.subscription_id,
            "location": self.location,
            "os_type": self.os_type,
            "installed_extensions": self.installed_extensions,
            "missing_extensions": self.missing_extensions,
            "failed_extensions": self.failed_extensions,
            "severity": self.severity,
            "compliance_score": self.compliance_score,
            "scanned_at": self.scanned_at,
            "ttl": self.ttl,
        }


# ---------------------------------------------------------------------------
# Helper: determine severity and score
# ---------------------------------------------------------------------------

def _assess_coverage(
    os_type: str,
    installed_names: set,
) -> tuple:
    """Return (severity, compliance_score, missing_extensions, failed_extensions).

    installed_names: set of extension type names that succeeded.
    """
    required = REQUIRED_WINDOWS_EXTENSIONS if os_type.lower() == "windows" else REQUIRED_LINUX_EXTENSIONS

    monitoring_ext_names = {k for k, v in required.items() if v["category"] == "monitoring"}
    security_ext_names = {k for k, v in required.items() if v["category"] == "security"}

    has_monitoring = bool(monitoring_ext_names & installed_names)
    has_security = bool(security_ext_names & installed_names)

    missing: List[Dict[str, str]] = []
    if not has_monitoring:
        for name, meta in required.items():
            if meta["category"] == "monitoring" and name not in installed_names:
                missing.append({
                    "name": name,
                    "description": meta["description"],
                    "severity_contribution": "high",
                })
                break  # suggest first option
    if not has_security:
        for name, meta in required.items():
            if meta["category"] == "security" and name not in installed_names:
                missing.append({
                    "name": name,
                    "description": meta["description"],
                    "severity_contribution": "high" if has_monitoring else "critical",
                })
                break

    if not has_monitoring and not has_security:
        severity = "critical"
        score = 0.0
    elif not has_monitoring:
        severity = "high"
        score = 0.5
    elif not has_security:
        severity = "medium"
        score = 0.7
    else:
        severity = "compliant"
        score = 1.0

    return severity, score, missing


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_vm_extensions(
    credential: Any,
    subscription_ids: List[str],
) -> List[VMExtensionFinding]:
    """Query ARG for VM extensions and produce findings.

    Never raises — returns empty list on error.
    """
    start = time.monotonic()
    try:
        vm_rows = run_arg_query(credential, subscription_ids, _KQL_VMS)
        ext_rows = run_arg_query(credential, subscription_ids, _KQL_EXTENSIONS)
    except Exception as exc:  # noqa: BLE001
        logger.error("vm_extension_service: ARG query failed | error=%s", exc)
        return []

    # Build map: vm_id -> {name, publisher, state}[]
    ext_by_vm: Dict[str, List[Dict[str, Any]]] = {}
    for row in ext_rows:
        vm_id = str(row.get("vm_id", "")).lower()
        if not vm_id:
            continue
        ext_by_vm.setdefault(vm_id, []).append({
            "name": row.get("ext_type") or row.get("ext_name", ""),
            "publisher": row.get("publisher", ""),
            "state": row.get("provisioning_state", "Unknown"),
        })

    scanned_at = datetime.now(timezone.utc).isoformat()
    findings: List[VMExtensionFinding] = []

    for vm in vm_rows:
        vm_id = str(vm.get("vm_id", "")).lower()
        if not vm_id:
            continue

        os_type = vm.get("os_type") or "Unknown"
        extensions = ext_by_vm.get(vm_id, [])

        succeeded_names: set = {
            e["name"] for e in extensions if e["state"] == "Succeeded"
        }
        failed_extensions = [
            {"name": e["name"], "state": e["state"]}
            for e in extensions if e["state"] != "Succeeded"
        ]

        severity, score, missing = _assess_coverage(os_type, succeeded_names)

        # Bump to "info" if compliant but has failed extensions
        if severity == "compliant" and failed_extensions:
            severity = "info"
            score = 0.9

        finding_id = str(uuid.uuid5(uuid.NAMESPACE_URL, vm_id))
        findings.append(VMExtensionFinding(
            finding_id=finding_id,
            vm_id=vm_id,
            vm_name=str(vm.get("vm_name", "")),
            resource_group=str(vm.get("resource_group", "")),
            subscription_id=str(vm.get("subscription_id", "")),
            location=str(vm.get("location", "")),
            os_type=os_type,
            installed_extensions=extensions,
            missing_extensions=missing,
            failed_extensions=failed_extensions,
            severity=severity,
            compliance_score=round(score, 3),
            scanned_at=scanned_at,
        ))

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "vm_extension_service: scan complete | vms=%d findings=%d duration_ms=%d",
        len(vm_rows), len(findings), duration_ms,
    )
    return findings


def persist_findings(
    cosmos_client: Any,
    db_name: str,
    findings: List[VMExtensionFinding],
) -> None:
    """Upsert findings into Cosmos DB container 'vm_extension_audit'.

    Never raises.
    """
    if not findings:
        return
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client(
            "vm_extension_audit"
        )
        for f in findings:
            container.upsert_item(f.to_dict())
        logger.info("vm_extension_service: persisted %d findings", len(findings))
    except Exception as exc:  # noqa: BLE001
        logger.error("vm_extension_service: persist failed | error=%s", exc)


def get_findings(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    severity: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query findings from Cosmos DB.

    Never raises — returns empty list on error.
    """
    try:
        container = cosmos_client.get_database_client(db_name).get_container_client(
            "vm_extension_audit"
        )
        conditions = []
        params: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = ", ".join(f"@sub{i}" for i in range(len(subscription_ids)))
            conditions.append(f"c.subscription_id IN ({placeholders})")
            for i, sid in enumerate(subscription_ids):
                params.append({"name": f"@sub{i}", "value": sid})

        if severity:
            conditions.append("c.severity = @severity")
            params.append({"name": "@severity", "value": severity})

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM c {where}"

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))
        return items
    except Exception as exc:  # noqa: BLE001
        logger.error("vm_extension_service: get_findings failed | error=%s", exc)
        return []


def get_extension_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return aggregate summary of VM extension compliance.

    Never raises.
    """
    try:
        findings = get_findings(cosmos_client, db_name)
        total = len(findings)
        if total == 0:
            return {
                "total_vms": 0,
                "compliant": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "info": 0,
                "coverage_pct": 0.0,
                "top_missing": [],
            }

        sev_counts: Dict[str, int] = {"compliant": 0, "critical": 0, "high": 0, "medium": 0, "info": 0}
        missing_counter: Dict[str, int] = {}

        for f in findings:
            sev = f.get("severity", "unknown")
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
            for m in f.get("missing_extensions", []):
                name = m.get("name", "")
                missing_counter[name] = missing_counter.get(name, 0) + 1

        compliant = sev_counts.get("compliant", 0) + sev_counts.get("info", 0)
        coverage_pct = round(compliant / total * 100, 1) if total else 0.0

        top_missing = sorted(
            [{"name": k, "count": v} for k, v in missing_counter.items()],
            key=lambda x: -x["count"],
        )[:5]

        return {
            "total_vms": total,
            "compliant": compliant,
            "critical": sev_counts.get("critical", 0),
            "high": sev_counts.get("high", 0),
            "medium": sev_counts.get("medium", 0),
            "info": sev_counts.get("info", 0),
            "coverage_pct": coverage_pct,
            "top_missing": top_missing,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("vm_extension_service: summary failed | error=%s", exc)
        return {
            "total_vms": 0,
            "compliant": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "info": 0,
            "coverage_pct": 0.0,
            "top_missing": [],
        }
