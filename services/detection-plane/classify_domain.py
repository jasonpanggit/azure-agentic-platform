"""Python mirror of the KQL classify_domain() function (DETECT-002).

This module provides the same domain classification logic as the KQL
function in fabric/kql/functions/classify_domain.kql. It MUST produce
identical results for the same inputs. Used by:
1. Unit tests to validate classification logic
2. The Fabric User Data Function as a fallback/validation layer
"""
from __future__ import annotations

# Domain classification mapping: ARM resource_type prefix -> AAP domain
# Decision D-05: resource_type is the primary classification signal
# Decision D-06: unrecognized types fall back to "sre"
DOMAIN_MAPPINGS: dict[str, str] = {
    # Compute domain
    "microsoft.compute/virtualmachines": "compute",
    "microsoft.compute/virtualmachinescalesets": "compute",
    "microsoft.compute/disks": "compute",
    "microsoft.batch/batchaccounts": "compute",
    "microsoft.compute/availabilitysets": "compute",
    "microsoft.compute/images": "compute",
    # Network domain
    "microsoft.network/virtualnetworks": "network",
    "microsoft.network/networksecuritygroups": "network",
    "microsoft.network/loadbalancers": "network",
    "microsoft.network/applicationgateways": "network",
    "microsoft.network/azurefirewalls": "network",
    "microsoft.network/publicipaddresses": "network",
    "microsoft.network/trafficmanagerprofiles": "network",
    "microsoft.network/frontdoors": "network",
    "microsoft.network/dnszones": "network",
    "microsoft.network/expressroutecircuits": "network",
    "microsoft.network/vpngateways": "network",
    # Storage domain
    "microsoft.storage/storageaccounts": "storage",
    "microsoft.storage/fileservices": "storage",
    "microsoft.storage/blobservices": "storage",
    "microsoft.storagesync/storagesyncservices": "storage",
    # Security domain
    "microsoft.keyvault/vaults": "security",
    "microsoft.security": "security",
    "microsoft.sentinel": "security",
    # Arc domain (hybrid resources)
    "microsoft.hybridcompute/machines": "arc",
    "microsoft.kubernetes/connectedclusters": "arc",
    "microsoft.azurearcdata": "arc",
    # Messaging domain (Phase 49) — Service Bus and Event Hub
    "microsoft.servicebus/namespaces": "messaging",
    "microsoft.servicebus/namespaces/queues": "messaging",
    "microsoft.servicebus": "messaging",
    "microsoft.eventhub/namespaces": "messaging",
    "microsoft.eventhub/namespaces/eventhubs": "messaging",
    "microsoft.eventhub": "messaging",
    # FinOps domain (Phase 52) — Cost Management and Budget alerts
    "microsoft.costmanagement": "finops",
    "microsoft.costmanagement/budgets": "finops",
    "microsoft.costmanagement/alerts": "finops",
    "microsoft.billing": "finops",
}

# SRE fallback domain (D-06)
FALLBACK_DOMAIN = "sre"

# Valid domain values (matches IncidentPayload.domain regex: ^(compute|network|storage|security|arc|sre|patch|eol|messaging|finops)$)
VALID_DOMAINS = frozenset({"compute", "network", "storage", "security", "arc", "sre", "patch", "eol", "messaging", "finops"})


def classify_domain(resource_type: str) -> str:
    """Classify an ARM resource_type into an AAP agent domain.

    Args:
        resource_type: ARM resource type string
            (e.g., "Microsoft.Compute/virtualMachines").

    Returns:
        One of: "compute", "network", "storage", "security", "arc", "sre".
        Always returns a non-empty string (sre fallback for unrecognized types).
    """
    if not resource_type:
        return FALLBACK_DOMAIN

    normalized = resource_type.lower().strip()

    # Exact match first
    if normalized in DOMAIN_MAPPINGS:
        return DOMAIN_MAPPINGS[normalized]

    # Prefix match for broad categories (e.g., "microsoft.security/alerts")
    for prefix, domain in DOMAIN_MAPPINGS.items():
        if normalized.startswith(prefix):
            return domain

    return FALLBACK_DOMAIN
