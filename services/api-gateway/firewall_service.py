from __future__ import annotations
"""Azure Firewall audit service (Phase 104).

Queries Azure Firewall resources and their policy rule collections via ARG,
then classifies rules into security findings.

Contains:
- get_firewall_rules: ARG-backed query returning firewalls + rules
- get_firewall_audit: classify rules into FirewallAuditFinding list
- FirewallRule / FirewallAuditFinding dataclasses
"""

import json
import logging
import time
from dataclasses import dataclass
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
        "azure-mgmt-resourcegraph unavailable — Firewall service will return empty: %s",
        _ARG_IMPORT_ERROR or "ImportError",
    )

# ---------------------------------------------------------------------------
# ARG KQL
# ---------------------------------------------------------------------------

_FIREWALL_KQL = """
Resources
| where type =~ 'microsoft.network/azurefirewalls'
| project
    firewall_id = tolower(id),
    firewall_name = name,
    resourceGroup,
    subscriptionId,
    location,
    sku_tier = tostring(properties.sku.tier),
    threat_intel_mode = tostring(properties.threatIntelMode),
    policy_id = tolower(tostring(properties.firewallPolicy.id))
"""

_POLICY_RULES_KQL = """
Resources
| where type =~ 'microsoft.network/firewallpolicies'
| mv-expand rc = properties.ruleCollections
| mv-expand rule = rc.rules
| project
    policy_id = tolower(id),
    policy_name = name,
    resourceGroup,
    subscriptionId,
    collection_name = tostring(rc.name),
    collection_priority = toint(rc.priority),
    action = tostring(rc.action.type),
    rule_name = tostring(rule.name),
    rule_type = tostring(rule['ruleType']),
    source_addresses = tostring(rule.sourceAddresses),
    destination_addresses = tostring(rule.destinationAddresses),
    destination_ports = tostring(rule.destinationPorts),
    protocols = tostring(rule.ipProtocols)
"""

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class FirewallRule:
    firewall_id: str
    firewall_name: str
    resource_group: str
    subscription_id: str
    location: str
    sku_tier: str
    threat_intel_mode: str
    policy_id: str
    policy_name: str
    collection_name: str
    collection_priority: int
    action: str
    rule_name: str
    rule_type: str
    source_addresses: List[str]
    destination_addresses: List[str]
    destination_ports: List[str]
    protocols: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "firewall_id": self.firewall_id,
            "firewall_name": self.firewall_name,
            "resource_group": self.resource_group,
            "subscription_id": self.subscription_id,
            "location": self.location,
            "sku_tier": self.sku_tier,
            "threat_intel_mode": self.threat_intel_mode,
            "policy_id": self.policy_id,
            "policy_name": self.policy_name,
            "collection_name": self.collection_name,
            "collection_priority": self.collection_priority,
            "action": self.action,
            "rule_name": self.rule_name,
            "rule_type": self.rule_type,
            "source_addresses": self.source_addresses,
            "destination_addresses": self.destination_addresses,
            "destination_ports": self.destination_ports,
            "protocols": self.protocols,
        }


@dataclass
class FirewallAuditFinding:
    firewall_name: str
    rule_name: str
    collection_name: str
    issue_type: str  # too_wide_source | too_wide_destination | too_wide_ports | overlap_shadowed
    severity: str    # critical | high | medium
    detail: str
    remediation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "firewall_name": self.firewall_name,
            "rule_name": self.rule_name,
            "collection_name": self.collection_name,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "detail": self.detail,
            "remediation": self.remediation,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json_list(raw: str) -> List[str]:
    """Parse a JSON array string from ARG into a Python list. Returns [] on failure."""
    if not raw or raw in ("null", "[]", ""):
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [str(parsed)]
    except (json.JSONDecodeError, TypeError):
        # Some ARG values come back as bare strings
        raw = raw.strip("[]").strip('"')
        if raw:
            return [s.strip().strip('"') for s in raw.split(",") if s.strip()]
        return []


def _is_wildcard(values: List[str]) -> bool:
    """Return True if any value in the list is a wildcard or internet-facing CIDR."""
    wildcards = {"*", "0.0.0.0/0", "internet", "any"}
    return any(v.lower().strip() in wildcards for v in values)


# ---------------------------------------------------------------------------
# Classification logic — pure, no I/O
# ---------------------------------------------------------------------------


def classify_firewall_rule(rule: FirewallRule) -> List[FirewallAuditFinding]:
    """Classify a single firewall rule into zero or more audit findings.

    Checks:
    - too_wide_source: sourceAddresses contains * or 0.0.0.0/0 → critical/high
    - too_wide_destination: destinationAddresses * AND destinationPorts * → high
    - too_wide_ports: destinationPorts 0-65535 or * on Allow → high
    Returns a list so a rule can generate multiple findings.
    """
    findings: List[FirewallAuditFinding] = []
    is_allow = rule.action.lower() in ("allow", "")

    # too_wide_source
    if _is_wildcard(rule.source_addresses):
        sev = "critical" if is_allow else "high"
        findings.append(FirewallAuditFinding(
            firewall_name=rule.firewall_name,
            rule_name=rule.rule_name,
            collection_name=rule.collection_name,
            issue_type="too_wide_source",
            severity=sev,
            detail=(
                f"Rule '{rule.rule_name}' in collection '{rule.collection_name}' "
                f"allows traffic from any source ({rule.source_addresses})."
            ),
            remediation=(
                "Restrict source addresses to known trusted IP ranges or VNet address spaces. "
                "Avoid wildcards (*) or 0.0.0.0/0 in source address fields."
            ),
        ))

    # too_wide_destination
    if _is_wildcard(rule.destination_addresses) and _is_wildcard(rule.destination_ports):
        findings.append(FirewallAuditFinding(
            firewall_name=rule.firewall_name,
            rule_name=rule.rule_name,
            collection_name=rule.collection_name,
            issue_type="too_wide_destination",
            severity="high",
            detail=(
                f"Rule '{rule.rule_name}' allows traffic to any destination address "
                f"and any port (destination: {rule.destination_addresses}, "
                f"ports: {rule.destination_ports})."
            ),
            remediation=(
                "Specify explicit destination FQDNs, IP addresses, or address groups. "
                "Replace wildcard destination ports with the minimum required port set."
            ),
        ))

    # too_wide_ports (Allow rules with * or 0-65535 ports, excluding already flagged above)
    if is_allow and _is_wildcard(rule.destination_ports) and not _is_wildcard(rule.destination_addresses):
        already = any(f.issue_type == "too_wide_destination" for f in findings)
        if not already:
            findings.append(FirewallAuditFinding(
                firewall_name=rule.firewall_name,
                rule_name=rule.rule_name,
                collection_name=rule.collection_name,
                issue_type="too_wide_ports",
                severity="high",
                detail=(
                    f"Allow rule '{rule.rule_name}' permits all destination ports "
                    f"({rule.destination_ports}), granting broader access than necessary."
                ),
                remediation=(
                    "Restrict destination ports to the exact ports required by the application. "
                    "Avoid using * or full-range port specifications on Allow rules."
                ),
            ))
    # Also flag 0-65535 explicit range
    elif is_allow:
        for port in rule.destination_ports:
            if port.strip() == "0-65535":
                findings.append(FirewallAuditFinding(
                    firewall_name=rule.firewall_name,
                    rule_name=rule.rule_name,
                    collection_name=rule.collection_name,
                    issue_type="too_wide_ports",
                    severity="high",
                    detail=(
                        f"Allow rule '{rule.rule_name}' permits the full port range 0-65535, "
                        "granting unrestricted port access."
                    ),
                    remediation=(
                        "Restrict destination ports to only those required by the workload. "
                        "Remove or replace the 0-65535 range with specific ports."
                    ),
                ))
                break

    return findings


def detect_overlapping_rules(rules: List[FirewallRule]) -> List[FirewallAuditFinding]:
    """Detect shadowed rules: same source+dest+port fingerprint at different priorities.

    Two rules overlap/shadow when they share the same collection, source addresses,
    destination addresses, and destination ports but have different priorities —
    the lower-priority rule will never be evaluated.

    Never raises — returns [] on any failure.
    """
    findings: List[FirewallAuditFinding] = []
    try:
        # Group by (firewall_id, collection_name, src, dst, ports)
        seen: Dict[tuple, FirewallRule] = {}
        for rule in rules:
            key = (
                rule.firewall_id,
                rule.collection_name,
                tuple(sorted(rule.source_addresses)),
                tuple(sorted(rule.destination_addresses)),
                tuple(sorted(rule.destination_ports)),
            )
            if key in seen:
                prev = seen[key]
                if prev.collection_priority != rule.collection_priority:
                    findings.append(FirewallAuditFinding(
                        firewall_name=rule.firewall_name,
                        rule_name=rule.rule_name,
                        collection_name=rule.collection_name,
                        issue_type="overlap_shadowed",
                        severity="medium",
                        detail=(
                            f"Rule '{rule.rule_name}' (priority {rule.collection_priority}) "
                            f"is shadowed by '{prev.rule_name}' (priority {prev.collection_priority}) "
                            f"in collection '{rule.collection_name}' — same source, destination, and ports."
                        ),
                        remediation=(
                            "Review and remove or reorder overlapping rules. "
                            "Ensure higher-priority rules capture the intended traffic subset "
                            "and lower-priority rules are not silently bypassed."
                        ),
                    ))
            else:
                seen[key] = rule
    except Exception as exc:  # noqa: BLE001
        logger.warning("Overlap detection failed: %s", exc)
    return findings


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def get_firewall_rules(
    subscription_ids: List[str],
    credential: Optional[Any] = None,
) -> Dict[str, Any]:
    """Query Azure Firewall resources and policy rules from ARG.

    Returns { firewalls: [...], rules: [...], count: int }.
    Never raises — returns empty result on failure.
    """
    start_time = time.monotonic()

    if not subscription_ids:
        logger.debug("get_firewall_rules: no subscription_ids, returning empty")
        return {"firewalls": [], "rules": [], "count": 0}

    try:
        from services.api_gateway.arg_helper import run_arg_query  # noqa: PLC0415

        fw_rows = run_arg_query(credential, subscription_ids, _FIREWALL_KQL)
        policy_rows = run_arg_query(credential, subscription_ids, _POLICY_RULES_KQL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firewall ARG query failed: %s", exc)
        return {"firewalls": [], "rules": [], "count": 0}

    # Build firewall lookup by policy_id
    fw_by_policy: Dict[str, Dict[str, Any]] = {}
    firewalls: List[Dict[str, Any]] = []
    for row in fw_rows:
        fw_dict = {
            "firewall_id": row.get("firewall_id", ""),
            "firewall_name": row.get("firewall_name", ""),
            "resource_group": row.get("resourceGroup", ""),
            "subscription_id": row.get("subscriptionId", ""),
            "location": row.get("location", ""),
            "sku_tier": row.get("sku_tier", ""),
            "threat_intel_mode": row.get("threat_intel_mode", ""),
            "policy_id": row.get("policy_id", ""),
        }
        firewalls.append(fw_dict)
        pid = (row.get("policy_id") or "").lower().strip()
        if pid:
            fw_by_policy[pid] = fw_dict

    # Join rules with firewall metadata
    rules: List[FirewallRule] = []
    for row in policy_rows:
        try:
            pid = (row.get("policy_id") or "").lower().strip()
            fw = fw_by_policy.get(pid, {})
            rule = FirewallRule(
                firewall_id=fw.get("firewall_id", ""),
                firewall_name=fw.get("firewall_name", row.get("policy_name", "")),
                resource_group=fw.get("resource_group", row.get("resourceGroup", "")),
                subscription_id=fw.get("subscription_id", row.get("subscriptionId", "")),
                location=fw.get("location", ""),
                sku_tier=fw.get("sku_tier", ""),
                threat_intel_mode=fw.get("threat_intel_mode", ""),
                policy_id=pid,
                policy_name=row.get("policy_name", ""),
                collection_name=row.get("collection_name", ""),
                collection_priority=row.get("collection_priority", 0) or 0,
                action=row.get("action", ""),
                rule_name=row.get("rule_name", ""),
                rule_type=row.get("rule_type", ""),
                source_addresses=_parse_json_list(row.get("source_addresses", "")),
                destination_addresses=_parse_json_list(row.get("destination_addresses", "")),
                destination_ports=_parse_json_list(row.get("destination_ports", "")),
                protocols=_parse_json_list(row.get("protocols", "")),
            )
            rules.append(rule)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping firewall rule row: %s | error: %s", row, exc)
            continue

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "get_firewall_rules: %d firewalls, %d rules (%.0fms)",
        len(firewalls), len(rules), duration_ms,
    )
    return {
        "firewalls": firewalls,
        "rules": [r.to_dict() for r in rules],
        "count": len(rules),
    }


def get_firewall_audit(
    subscription_ids: List[str],
    credential: Optional[Any] = None,
    severity_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify firewall rules into audit findings.

    Returns { findings: [...], summary: { critical, high, medium, total }, generated_at }.
    Never raises — returns empty result on failure.
    """
    start_time = time.monotonic()
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    if not subscription_ids:
        return {
            "findings": [],
            "summary": {"critical": 0, "high": 0, "medium": 0, "total": 0},
            "generated_at": generated_at,
        }

    try:
        from services.api_gateway.arg_helper import run_arg_query  # noqa: PLC0415

        fw_rows = run_arg_query(credential, subscription_ids, _FIREWALL_KQL)
        policy_rows = run_arg_query(credential, subscription_ids, _POLICY_RULES_KQL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firewall audit ARG query failed: %s", exc)
        return {
            "findings": [],
            "summary": {"critical": 0, "high": 0, "medium": 0, "total": 0},
            "generated_at": generated_at,
        }

    # Build firewall lookup
    fw_by_policy: Dict[str, Dict[str, Any]] = {}
    for row in fw_rows:
        pid = (row.get("policy_id") or "").lower().strip()
        if pid:
            fw_by_policy[pid] = {
                "firewall_id": row.get("firewall_id", ""),
                "firewall_name": row.get("firewall_name", ""),
                "resource_group": row.get("resourceGroup", ""),
                "subscription_id": row.get("subscriptionId", ""),
                "location": row.get("location", ""),
                "sku_tier": row.get("sku_tier", ""),
                "threat_intel_mode": row.get("threat_intel_mode", ""),
            }

    # Build rule objects
    rules: List[FirewallRule] = []
    for row in policy_rows:
        try:
            pid = (row.get("policy_id") or "").lower().strip()
            fw = fw_by_policy.get(pid, {})
            rules.append(FirewallRule(
                firewall_id=fw.get("firewall_id", ""),
                firewall_name=fw.get("firewall_name", row.get("policy_name", "")),
                resource_group=fw.get("resource_group", row.get("resourceGroup", "")),
                subscription_id=fw.get("subscription_id", row.get("subscriptionId", "")),
                location=fw.get("location", ""),
                sku_tier=fw.get("sku_tier", ""),
                threat_intel_mode=fw.get("threat_intel_mode", ""),
                policy_id=pid,
                policy_name=row.get("policy_name", ""),
                collection_name=row.get("collection_name", ""),
                collection_priority=row.get("collection_priority", 0) or 0,
                action=row.get("action", ""),
                rule_name=row.get("rule_name", ""),
                rule_type=row.get("rule_type", ""),
                source_addresses=_parse_json_list(row.get("source_addresses", "")),
                destination_addresses=_parse_json_list(row.get("destination_addresses", "")),
                destination_ports=_parse_json_list(row.get("destination_ports", "")),
                protocols=_parse_json_list(row.get("protocols", "")),
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping rule row in audit: %s | error: %s", row, exc)
            continue

    # Classify each rule
    all_findings: List[FirewallAuditFinding] = []
    for rule in rules:
        try:
            all_findings.extend(classify_firewall_rule(rule))
        except Exception as exc:  # noqa: BLE001
            logger.warning("classify_firewall_rule failed for rule %s: %s", rule.rule_name, exc)

    # Detect overlapping/shadowed rules
    try:
        all_findings.extend(detect_overlapping_rules(rules))
    except Exception as exc:  # noqa: BLE001
        logger.warning("detect_overlapping_rules failed: %s", exc)

    # Apply severity filter
    if severity_filter:
        all_findings = [f for f in all_findings if f.severity == severity_filter.lower()]

    summary = {
        "critical": sum(1 for f in all_findings if f.severity == "critical"),
        "high": sum(1 for f in all_findings if f.severity == "high"),
        "medium": sum(1 for f in all_findings if f.severity == "medium"),
        "total": len(all_findings),
    }

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "get_firewall_audit: %d findings (%.0fms) — c=%d h=%d m=%d",
        len(all_findings), duration_ms,
        summary["critical"], summary["high"], summary["medium"],
    )

    return {
        "findings": [f.to_dict() for f in all_findings],
        "summary": summary,
        "generated_at": generated_at,
    }
