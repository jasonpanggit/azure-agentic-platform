"""ConcurrentOrchestrator — parallel multi-domain incident investigation.

Dispatches up to 3 domain agents concurrently using asyncio.gather with a
configurable timeout, then synthesises findings into a unified root-cause
narrative. Falls back to sequential investigation if concurrent dispatch fails.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain keyword → agent routing table
# ---------------------------------------------------------------------------

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "network": ["network", "connectivity", "vnet", "nsg", "dns", "expressroute", "latency", "packet loss", "firewall", "load balancer"],
    "compute": ["compute", "vm", "virtual machine", "cpu", "memory", "disk", "aks", "vmss", "performance", "crash", "reboot"],
    "security": ["security", "defender", "key vault", "keyvault", "rbac", "identity", "alert", "threat", "vulnerability", "breach"],
    "storage": ["storage", "blob", "file share", "datalake", "adls", "throughput", "iops"],
    "arc": ["arc", "hybrid", "arc-enabled", "connected cluster", "arc server"],
    "patch": ["patch", "update", "compliance", "missing patches", "windows update"],
}

# Default domain set when no keywords match
_DEFAULT_DOMAINS = ["compute", "network"]


def select_domains_for_incident(description: str) -> list[str]:
    """Select optimal domain agents for an incident based on keyword matching.

    Scans the incident description for known keywords and returns the set of
    domains most likely to be relevant. Falls back to compute + network when
    no keywords match.

    Args:
        description: Incident description or alert message text.

    Returns:
        List of domain names (e.g. ["compute", "network"]) — max 3 domains.
    """
    lower = description.lower()
    matched: list[str] = []

    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            matched.append(domain)

    # Cap at 3 domains to avoid excessive fan-out
    selected = matched[:3] if matched else list(_DEFAULT_DOMAINS)
    logger.info(
        "select_domains_for_incident: selected=%s from description=%r",
        selected,
        description[:120],
    )
    return selected


# ---------------------------------------------------------------------------
# Simulated domain dispatch — real platform wires these to Foundry agent calls
# ---------------------------------------------------------------------------


async def _dispatch_to_domain_agent(
    domain: str,
    incident: dict,
) -> dict:
    """Dispatch a single domain investigation and return structured findings.

    In production this would call the Foundry connected-agent tool for the
    given domain. Here we model the interface so the orchestrator layer is
    testable without live Foundry infrastructure.

    Args:
        domain: Domain name (e.g. "compute", "network").
        incident: Incident payload dict.

    Returns:
        Dict with keys: domain, findings, confidence, duration_ms, error.
        Never raises — all errors returned as structured dicts.
    """
    start = time.monotonic()
    try:
        # Real implementation: invoke Foundry agent tool here
        # e.g. await foundry_client.dispatch_agent(domain_agent_id, incident)
        findings = f"[{domain}] No live findings — stub response for incident {incident.get('incident_id', 'unknown')}"
        confidence = 0.5
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            "domain": domain,
            "findings": findings,
            "confidence": confidence,
            "duration_ms": duration_ms,
            "error": None,
        }
    except Exception as exc:  # pragma: no cover
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "_dispatch_to_domain_agent: domain=%s error=%s incident=%s",
            domain,
            exc,
            incident.get("incident_id"),
        )
        return {
            "domain": domain,
            "findings": None,
            "confidence": 0.0,
            "duration_ms": duration_ms,
            "error": str(exc),
        }


async def _dispatch_sequential(
    domains: list[str],
    incident: dict,
) -> list[dict]:
    """Fallback sequential dispatch — one domain at a time.

    Args:
        domains: Ordered list of domain names to investigate.
        incident: Incident payload dict.

    Returns:
        List of domain result dicts in domain order.
    """
    results: list[dict] = []
    for domain in domains:
        result = await _dispatch_to_domain_agent(domain, incident)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# ConcurrentOrchestrator
# ---------------------------------------------------------------------------


async def dispatch_parallel_investigation(
    incident: dict,
    domains: Optional[list[str]] = None,
    timeout_s: int = 45,
) -> dict:
    """Dispatch a parallel multi-domain incident investigation.

    Fans out to up to 3 domain agents concurrently using asyncio.gather with
    a timeout. Falls back to sequential dispatch if concurrent fails.

    Args:
        incident: Incident payload dict. Must contain at least an incident_id
            and description (or title/message) for domain selection.
        domains: Explicit domain list; auto-selected from incident description
            when None.
        timeout_s: Per-investigation timeout in seconds (default 45).

    Returns:
        Dict with keys:
            investigation_id (str): Unique ID for this investigation run.
            domains_investigated (list[str]): Domains that were queried.
            findings (list[dict]): Per-domain result dicts.
            synthesis (str): Plain-text root-cause narrative.
            total_duration_ms (int): Wall-clock time for entire fan-out.
            parallel (bool): True if concurrent dispatch succeeded.
    """
    investigation_id = str(uuid.uuid4())
    total_start = time.monotonic()

    # Auto-select domains if not explicitly provided
    if not domains:
        description = (
            incident.get("description")
            or incident.get("title")
            or incident.get("message")
            or ""
        )
        domains = select_domains_for_incident(description)

    domains = domains[:3]  # Hard cap at 3

    logger.info(
        "dispatch_parallel_investigation: starting | investigation_id=%s domains=%s incident=%s",
        investigation_id,
        domains,
        incident.get("incident_id"),
    )

    parallel = True
    findings: list[dict] = []

    try:
        tasks = [_dispatch_to_domain_agent(d, incident) for d in domains]
        findings = list(
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=False),
                timeout=float(timeout_s),
            )
        )
    except asyncio.TimeoutError:
        logger.warning(
            "dispatch_parallel_investigation: timeout after %ds — falling back to sequential | investigation_id=%s",
            timeout_s,
            investigation_id,
        )
        parallel = False
        findings = await _dispatch_sequential(domains, incident)
    except Exception as exc:
        logger.warning(
            "dispatch_parallel_investigation: concurrent failed (%s) — falling back to sequential | investigation_id=%s",
            exc,
            investigation_id,
        )
        parallel = False
        findings = await _dispatch_sequential(domains, incident)

    synthesis = _synthesise_findings(findings)
    total_duration_ms = int((time.monotonic() - total_start) * 1000)

    result = {
        "investigation_id": investigation_id,
        "domains_investigated": domains,
        "findings": findings,
        "synthesis": synthesis,
        "total_duration_ms": total_duration_ms,
        "parallel": parallel,
    }
    logger.info(
        "dispatch_parallel_investigation: complete | investigation_id=%s parallel=%s duration_ms=%d",
        investigation_id,
        parallel,
        total_duration_ms,
    )
    return result


def _synthesise_findings(findings: list[dict]) -> str:
    """Produce a plain-text root-cause summary from multi-domain findings.

    Args:
        findings: List of per-domain result dicts.

    Returns:
        Human-readable synthesis string.
    """
    successful = [f for f in findings if not f.get("error")]
    failed = [f for f in findings if f.get("error")]

    lines: list[str] = []
    if successful:
        lines.append(
            f"Investigation completed across {len(successful)} domain(s): "
            + ", ".join(f["domain"] for f in successful)
            + "."
        )
        for f in successful:
            confidence_pct = int(f.get("confidence", 0) * 100)
            lines.append(f"  [{f['domain']}] confidence={confidence_pct}% — {f['findings']}")
    if failed:
        lines.append(
            "Domains that failed: "
            + ", ".join(f"{f['domain']} ({f['error']})" for f in failed)
            + "."
        )
    if not lines:
        return "No domain findings available."
    return "\n".join(lines)
