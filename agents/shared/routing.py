"""Shared routing helpers for conversational and incident domain classification."""
from __future__ import annotations

from typing import Optional


QUERY_DOMAIN_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "arc",
        (
            "azure arc",
            "arc-enabled",
            "arc enabled",
            "arc server",
            "arc servers",
            "arc machine",
            "arc machines",
            "arc kubernetes",
            "connected cluster",
            "connected clusters",
            "hybridcompute",
            "hybrid compute",
            "hybrid server",
            "hybrid servers",
            "arc sql",
            "arc postgres",
        ),
    ),
    (
        "patch",
        (
            "patch",
            "patches",
            "patching",
            "update manager",
            "windows update",
            "security patch",
            "patch compliance",
            "patch status",
            "missing patches",
            "pending patches",
            "kb article",
            "hotfix",
        ),
    ),
    (
        "eol",
        (
            "end of life",
            "end-of-life",
            "eol",
            "outdated software",
            "software lifecycle",
            "unsupported version",
            "lifecycle status",
            "deprecated version",
            "software expiry",
            "version support",
            "eol status",
            "lifecycle check",
        ),
    ),
    (
        "compute",
        (
            "virtual machine",
            "virtual machines",
            " vm ",
            "vmss",
            "aks",
            "app service",
            "function app",
            "compute",
            "cpu",
            "disk",
            "container app",
        ),
    ),
    (
        "network",
        (
            "network",
            "vnet",
            "nsg",
            "subnet",
            "load balancer",
            "dns",
            "expressroute",
            "vpn",
            "firewall",
            "cdn",
        ),
    ),
    (
        "storage",
        (
            "storage",
            "blob",
            "file share",
            "datalake",
            "adls",
        ),
    ),
    (
        "security",
        (
            "defender",
            "keyvault",
            "key vault",
            "rbac",
            "security",
            "identity",
            "credential",
        ),
    ),
)


def classify_query_text(query_text: str) -> dict[str, str]:
    """Classify a natural-language operator query to a domain.

    The keywords are ordered from most-specific to least-specific so Arc
    phrases such as "arc enabled servers" resolve to the Arc domain before
    generic compute words like "servers" or "machines" can influence routing.
    """
    normalized_query = f" {query_text.lower()} "

    for domain, keywords in QUERY_DOMAIN_KEYWORDS:
        matched_keyword = _first_matching_keyword(normalized_query, keywords)
        if matched_keyword is not None:
            return {
                "domain": domain,
                "confidence": "medium",
                "reason": f"Query keyword match for '{matched_keyword.strip()}'.",
            }

    return {
        "domain": "sre",
        "confidence": "low",
        "reason": "No domain keyword found in query text; defaulting to SRE.",
    }


def _first_matching_keyword(
    normalized_query: str, keywords: tuple[str, ...]
) -> Optional[str]:
    for keyword in keywords:
        if keyword in normalized_query:
            return keyword
    return None