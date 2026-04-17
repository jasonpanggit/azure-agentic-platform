from __future__ import annotations
"""NSG security audit service (Phase 77).

Scans all Network Security Groups across subscriptions for risky rules
and surfaces them as security findings stored in Cosmos DB.

Contains:
- classify_rule: pure function mapping NSG rule → severity + description
- scan_nsg_compliance: ARG-based scan returning NSGFinding list
- persist_findings: upsert findings to nsg_findings Cosmos container
- get_findings: query findings with optional filters
- get_summary: aggregate counts by severity + top risky NSGs
"""

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy SDK imports
# ---------------------------------------------------------------------------

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
    _ARG_IMPORT_ERROR: str = ""
except Exception as _e:  # noqa: BLE001
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    _ARG_IMPORT_ERROR = str(_e)

if ResourceGraphClient is None:
    logger.warning(
        "azure-mgmt-resourcegraph unavailable — NSG scan will return empty: %s",
        _ARG_IMPORT_ERROR or "ImportError",
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SENSITIVE_PORTS_CRITICAL: frozenset[str] = frozenset({"22", "3389", "445", "23"})
SENSITIVE_PORTS_HIGH: frozenset[str] = frozenset({"1433", "3306", "5432"})
SENSITIVE_PORTS_ALL: frozenset[str] = SENSITIVE_PORTS_CRITICAL | SENSITIVE_PORTS_HIGH

INTERNET_SOURCES: frozenset[str] = frozenset({"*", "internet", "0.0.0.0/0"})

NSG_FINDINGS_CONTAINER: str = "nsg_findings"
FINDINGS_TTL_SECONDS: int = 604800  # 7 days

# ---------------------------------------------------------------------------
# ARG KQL
# ---------------------------------------------------------------------------

NSG_RULES_KQL: str = """
Resources
| where type =~ 'microsoft.network/networksecuritygroups'
| mv-expand rule = properties.securityRules
| where rule.properties.access =~ 'Allow'
| where rule.properties.direction =~ 'Inbound'
| project
    nsg_id = tolower(id),
    nsg_name = name,
    resourceGroup,
    subscriptionId,
    location,
    rule_name = tostring(rule.name),
    priority = toint(rule.properties.priority),
    source_address = tostring(rule.properties.sourceAddressPrefix),
    destination_port = tostring(rule.properties.destinationPortRange),
    destination_ports = tostring(rule.properties.destinationPortRanges)
| order by priority asc
"""

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class NSGFinding:
    finding_id: str
    nsg_id: str
    nsg_name: str
    resource_group: str
    subscription_id: str
    location: str
    rule_name: str
    priority: int
    direction: str
    access: str
    source_address: str
    destination_port: str
    severity: str
    description: str
    remediation: str
    scanned_at: str
    ttl: int = field(default=FINDINGS_TTL_SECONDS)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.finding_id,
            "finding_id": self.finding_id,
            "nsg_id": self.nsg_id,
            "nsg_name": self.nsg_name,
            "resource_group": self.resource_group,
            "subscription_id": self.subscription_id,
            "location": self.location,
            "rule_name": self.rule_name,
            "priority": self.priority,
            "direction": self.direction,
            "access": self.access,
            "source_address": self.source_address,
            "destination_port": self.destination_port,
            "severity": self.severity,
            "description": self.description,
            "remediation": self.remediation,
            "scanned_at": self.scanned_at,
            "ttl": self.ttl,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "NSGFinding":
        return cls(
            finding_id=d.get("finding_id", d.get("id", "")),
            nsg_id=d.get("nsg_id", ""),
            nsg_name=d.get("nsg_name", ""),
            resource_group=d.get("resource_group", ""),
            subscription_id=d.get("subscription_id", ""),
            location=d.get("location", ""),
            rule_name=d.get("rule_name", ""),
            priority=d.get("priority", 0),
            direction=d.get("direction", "Inbound"),
            access=d.get("access", "Allow"),
            source_address=d.get("source_address", ""),
            destination_port=d.get("destination_port", ""),
            severity=d.get("severity", "info"),
            description=d.get("description", ""),
            remediation=d.get("remediation", ""),
            scanned_at=d.get("scanned_at", ""),
            ttl=d.get("ttl", FINDINGS_TTL_SECONDS),
        )


# ---------------------------------------------------------------------------
# Classification logic — pure function, no I/O
# ---------------------------------------------------------------------------


def _is_internet_source(source: str) -> bool:
    """Return True if the source address prefix represents the internet."""
    return source.lower().strip() in INTERNET_SOURCES


def _is_broad_cidr(source: str) -> bool:
    """Return True for overly broad CIDR ranges (/8 or /16)."""
    src = source.strip()
    if "/" not in src:
        return False
    try:
        prefix_len = int(src.split("/")[-1])
        return prefix_len <= 16
    except ValueError:
        return False


def _port_in_set(port: str, port_set: frozenset[str]) -> bool:
    """Check whether a port string (single value or range) matches the sensitive set."""
    port = port.strip()
    if port == "*":
        return True
    # Single port
    if port in port_set:
        return True
    # Range like "1-1024" or "80-443"
    if "-" in port:
        try:
            lo, hi = (int(p) for p in port.split("-", 1))
            return any(int(p) in range(lo, hi + 1) for p in port_set)
        except ValueError:
            pass
    return False


def classify_rule(
    source_address: str,
    destination_port: str,
    destination_ports: str,
) -> Optional[Dict[str, str]]:
    """Classify an NSG Allow-Inbound rule and return severity + description + remediation.

    Returns None if the rule is not considered risky.

    Args:
        source_address: sourceAddressPrefix value from the NSG rule.
        destination_port: destinationPortRange (single port, range, or *).
        destination_ports: destinationPortRanges (comma-separated multi-port list).

    Returns:
        Dict with keys: severity, description, remediation — or None.
    """
    # Resolve effective port list: prefer destination_ports if populated
    ports: List[str] = []
    if destination_ports and destination_ports not in ("", "[]", "null"):
        cleaned = destination_ports.strip("[]").replace('"', "")
        ports = [p.strip() for p in cleaned.split(",") if p.strip()]
    if not ports and destination_port:
        ports = [destination_port.strip()]

    is_internet = _is_internet_source(source_address)
    is_broad = _is_broad_cidr(source_address)

    for port in ports:
        # CRITICAL: internet access to most dangerous ports
        if is_internet and _port_in_set(port, SENSITIVE_PORTS_CRITICAL):
            port_name = _port_label(port, SENSITIVE_PORTS_CRITICAL)
            return {
                "severity": "critical",
                "description": (
                    f"NSG rule allows unrestricted internet access to {port_name}. "
                    f"Source: {source_address}, Port: {port}."
                ),
                "remediation": (
                    f"Restrict the source address prefix to trusted IP ranges or VNet. "
                    f"Remove or deny inbound {port_name} access from internet."
                ),
            }

        # HIGH: internet access to database ports
        if is_internet and _port_in_set(port, SENSITIVE_PORTS_HIGH):
            port_name = _port_label(port, SENSITIVE_PORTS_HIGH)
            return {
                "severity": "high",
                "description": (
                    f"NSG rule allows internet access to database port {port_name}. "
                    f"Source: {source_address}, Port: {port}."
                ),
                "remediation": (
                    f"Database ports should never be exposed to the internet. "
                    f"Restrict source to private VNet address space only."
                ),
            }

        # MEDIUM: broad CIDR (/8 or /16) to any sensitive port
        if is_broad and _port_in_set(port, SENSITIVE_PORTS_ALL):
            port_name = _port_label(port, SENSITIVE_PORTS_ALL)
            return {
                "severity": "medium",
                "description": (
                    f"NSG rule allows overly broad source CIDR ({source_address}) "
                    f"to sensitive port {port_name}."
                ),
                "remediation": (
                    f"Tighten the source CIDR to the minimum required IP range. "
                    f"Avoid /8 or /16 CIDR blocks for access to sensitive ports."
                ),
            }

        # INFO: wildcard destination port from any non-internet source
        if port == "*":
            return {
                "severity": "info",
                "description": (
                    f"NSG rule allows all inbound ports from {source_address}. "
                    "Wildcard destination port rules grant broader access than necessary."
                ),
                "remediation": (
                    "Replace the wildcard (*) destination port with an explicit list "
                    "of required ports to enforce least-privilege access."
                ),
            }

    return None


def _port_label(port: str, reference_set: frozenset[str]) -> str:
    """Return a human-readable label for a port, e.g. '22 (SSH)'."""
    port_names: Dict[str, str] = {
        "22": "22 (SSH)",
        "3389": "3389 (RDP)",
        "1433": "1433 (SQL Server)",
        "3306": "3306 (MySQL)",
        "5432": "5432 (PostgreSQL)",
        "445": "445 (SMB)",
        "23": "23 (Telnet)",
    }
    if port in port_names:
        return port_names[port]
    # Check if range covers a known sensitive port
    if "-" in port:
        try:
            lo, hi = (int(p) for p in port.split("-", 1))
            for p in reference_set:
                if lo <= int(p) <= hi and p in port_names:
                    return f"{port} (includes {port_names[p]})"
        except ValueError:
            pass
    if port == "*":
        return "* (all ports)"
    return port


# ---------------------------------------------------------------------------
# Scan function
# ---------------------------------------------------------------------------


def scan_nsg_compliance(
    credential: Any,
    subscription_ids: List[str],
) -> List[NSGFinding]:
    """Scan all NSGs across subscriptions using ARG and return security findings.

    Never raises — returns empty list on any failure.

    Args:
        credential: Azure credential object.
        subscription_ids: List of subscription IDs to scan.

    Returns:
        List of NSGFinding objects for risky rules found.
    """
    if not subscription_ids:
        logger.warning("scan_nsg_compliance called with empty subscription_ids")
        return []

    try:
        from services.api_gateway.arg_helper import run_arg_query  # noqa: PLC0415
        rows = run_arg_query(credential, subscription_ids, NSG_RULES_KQL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NSG ARG query failed: %s", exc)
        return []

    scanned_at = datetime.now(tz=timezone.utc).isoformat()
    findings: List[NSGFinding] = []

    for row in rows:
        try:
            source_address = row.get("source_address", "") or ""
            destination_port = row.get("destination_port", "") or ""
            destination_ports = row.get("destination_ports", "") or ""

            classification = classify_rule(source_address, destination_port, destination_ports)
            if classification is None:
                continue

            # Build a stable finding_id from nsg_id + rule_name so repeated scans upsert
            nsg_id = row.get("nsg_id", "") or ""
            rule_name = row.get("rule_name", "") or ""
            finding_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{nsg_id}#{rule_name}"))

            finding = NSGFinding(
                finding_id=finding_id,
                nsg_id=nsg_id,
                nsg_name=row.get("nsg_name", "") or "",
                resource_group=row.get("resourceGroup", "") or "",
                subscription_id=row.get("subscriptionId", "") or "",
                location=row.get("location", "") or "",
                rule_name=rule_name,
                priority=row.get("priority", 0) or 0,
                direction="Inbound",
                access="Allow",
                source_address=source_address,
                destination_port=destination_port if destination_port else destination_ports,
                severity=classification["severity"],
                description=classification["description"],
                remediation=classification["remediation"],
                scanned_at=scanned_at,
            )
            findings.append(finding)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to process NSG rule row: %s | error: %s", row, exc)
            continue

    logger.info(
        "NSG scan complete: %d findings from %d rows across %d subscriptions",
        len(findings),
        len(rows),
        len(subscription_ids),
    )
    return findings


# ---------------------------------------------------------------------------
# Cosmos DB helpers
# ---------------------------------------------------------------------------


def _get_nsg_container(cosmos_client: Any, db_name: str) -> Any:
    """Get or create the nsg_findings container with TTL enabled."""
    try:
        database = cosmos_client.get_database_client(db_name)
        try:
            container = database.get_container_client(NSG_FINDINGS_CONTAINER)
            container.read()
            return container
        except Exception:  # noqa: BLE001
            container = database.create_container_if_not_exists(
                id=NSG_FINDINGS_CONTAINER,
                partition_key={"paths": ["/subscription_id"], "kind": "Hash"},
                default_ttl=FINDINGS_TTL_SECONDS,
            )
            logger.info("Created Cosmos container: %s", NSG_FINDINGS_CONTAINER)
            return container
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to access nsg_findings container: %s", exc)
        raise


def persist_findings(
    cosmos_client: Any,
    db_name: str,
    findings: List[NSGFinding],
) -> None:
    """Upsert NSG findings to Cosmos DB nsg_findings container.

    Never raises — logs warning on failure.

    Args:
        cosmos_client: Initialized CosmosClient.
        db_name: Cosmos database name.
        findings: List of NSGFinding objects to persist.
    """
    if not findings:
        return

    try:
        container = _get_nsg_container(cosmos_client, db_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot persist NSG findings — container unavailable: %s", exc)
        return

    success = 0
    errors = 0
    for finding in findings:
        try:
            container.upsert_item(finding.to_dict())
            success += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to upsert NSG finding %s: %s", finding.finding_id, exc)
            errors += 1

    logger.info(
        "NSG findings persisted: success=%d errors=%d", success, errors
    )


def get_findings(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    severity: Optional[str] = None,
) -> List[NSGFinding]:
    """Query NSG findings from Cosmos DB with optional filters.

    Never raises — returns empty list on failure.

    Args:
        cosmos_client: Initialized CosmosClient.
        db_name: Cosmos database name.
        subscription_ids: Optional list to filter by subscription.
        severity: Optional severity filter (critical/high/medium/info).

    Returns:
        List of NSGFinding objects.
    """
    try:
        container = _get_nsg_container(cosmos_client, db_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot query NSG findings: %s", exc)
        return []

    try:
        conditions: List[str] = []
        parameters: List[Dict[str, Any]] = []

        if severity:
            conditions.append("c.severity = @severity")
            parameters.append({"name": "@severity", "value": severity.lower()})

        if subscription_ids:
            placeholders = [f"@sub{i}" for i in range(len(subscription_ids))]
            conditions.append(f"c.subscription_id IN ({', '.join(placeholders)})")
            for i, sid in enumerate(subscription_ids):
                parameters.append({"name": f"@sub{i}", "value": sid})

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM c {where_clause} ORDER BY c.scanned_at DESC"

        items = list(container.query_items(
            query=query,
            parameters=parameters if parameters else None,
            enable_cross_partition_query=True,
        ))

        return [NSGFinding.from_dict(item) for item in items]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to query NSG findings: %s", exc)
        return []


def get_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return aggregated NSG finding counts by severity and top risky NSGs.

    Never raises — returns empty summary on failure.

    Returns:
        {
            "counts": {"critical": int, "high": int, "medium": int, "info": int, "total": int},
            "top_risky_nsgs": [{"nsg_name": str, "nsg_id": str, "finding_count": int}],
            "generated_at": iso_timestamp
        }
    """
    empty: Dict[str, Any] = {
        "counts": {"critical": 0, "high": 0, "medium": 0, "info": 0, "total": 0},
        "top_risky_nsgs": [],
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    try:
        container = _get_nsg_container(cosmos_client, db_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot compute NSG summary: %s", exc)
        return empty

    try:
        all_findings = list(container.query_items(
            query="SELECT c.severity, c.nsg_id, c.nsg_name FROM c",
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch NSG findings for summary: %s", exc)
        return empty

    counts: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "info": 0}
    nsg_counts: Dict[str, Dict[str, Any]] = {}

    for item in all_findings:
        sev = (item.get("severity") or "info").lower()
        if sev in counts:
            counts[sev] += 1

        nsg_id = item.get("nsg_id", "")
        nsg_name = item.get("nsg_name", "")
        if nsg_id:
            if nsg_id not in nsg_counts:
                nsg_counts[nsg_id] = {"nsg_name": nsg_name, "nsg_id": nsg_id, "finding_count": 0}
            nsg_counts[nsg_id]["finding_count"] += 1

    top_nsgs = sorted(nsg_counts.values(), key=lambda x: x["finding_count"], reverse=True)[:5]

    return {
        "counts": {**counts, "total": sum(counts.values())},
        "top_risky_nsgs": top_nsgs,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
