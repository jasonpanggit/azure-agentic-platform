"""MSRC (Microsoft Security Response Center) API client.

Maps KB article IDs to CVE identifiers using the Security Update Guide API.
API docs: https://api.msrc.microsoft.com/sug/v2.0

No authentication required.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Any

logger = logging.getLogger(__name__)

# In-process cache: kb_digits -> (cve_list, timestamp)
_kb_cve_cache: dict[str, tuple[list[str], float]] = {}
_CACHE_TTL_SECONDS = 86400  # 24 hours

_KB_DIGITS_PATTERN = re.compile(r"\d+")
_MSRC_SUG_BASE = "https://api.msrc.microsoft.com/sug/v2.0/en-US/affectedProduct"
_REQUEST_TIMEOUT_SECONDS = 5

# Product name normalisation: ARG osVersion strings → MSRC product family strings
# MSRC uses display names like "Windows Server 2016" not "Windows Server 2016 Standard"
_OS_PRODUCT_MAP = [
    ("Windows Server 2025", "Windows Server 2025"),
    ("Windows Server 2022", "Windows Server 2022"),
    ("Windows Server 2019", "Windows Server 2019"),
    ("Windows Server 2016", "Windows Server 2016"),
    ("Windows Server 2012 R2", "Windows Server 2012 R2"),
    ("Windows Server 2012", "Windows Server 2012"),
    ("Windows 11", "Windows 11"),
    ("Windows 10", "Windows 10"),
    ("Ubuntu 24", "Ubuntu Linux"),
    ("Ubuntu 22", "Ubuntu Linux"),
    ("Ubuntu 20", "Ubuntu Linux"),
    ("Ubuntu 18", "Ubuntu Linux"),
    ("RHEL", "Red Hat Enterprise Linux"),
    ("Red Hat", "Red Hat Enterprise Linux"),
    ("CentOS", "CBL-Mariner"),
    ("Debian", "Debian Linux"),
    ("SUSE", "SUSE Linux"),
]


def _os_to_msrc_product(os_version: str) -> str:
    """Map an ARG osVersion string to the closest MSRC product family name."""
    for prefix, product in _OS_PRODUCT_MAP:
        if prefix.lower() in os_version.lower():
            return product
    return ""


def _parse_msrc_items(items: list[dict], product: str, seen: set[str]) -> list[dict]:
    """Parse MSRC SUG API items into CVE records, skipping duplicates."""
    records: list[dict] = []
    for item in items:
        cve_id = item.get("cveNumber", "")
        if not cve_id or cve_id in seen:
            continue
        seen.add(cve_id)
        kb_ids = [
            str(kb.get("articleName", ""))
            for kb in (item.get("kbArticles") or [])
            if kb.get("articleName")
        ]
        cvss = item.get("baseScore")
        try:
            cvss_f = float(cvss) if cvss is not None else None
        except (TypeError, ValueError):
            cvss_f = None
        impact = item.get("impact", "")
        cwe = (item.get("cweList") or [""])[0].split(":")[0] if item.get("cweList") else ""
        description = f"{impact} — {cwe}".strip(" —") if impact else f"Affects {product}"
        records.append({
            "cve_id": cve_id,
            "cvss_score": cvss_f,
            "severity": item.get("severity", ""),
            "description": description,
            "kb_ids": kb_ids,
            "published_date": (item.get("initialReleaseDate") or "")[:10] or None,
            "affected_product": product,
            "affected_versions": item.get("product", product),
            "vector_string": item.get("vectorString", ""),
            "impact": impact,
        })
    return records


def _fetch_cves_for_product_sync(product: str) -> list[dict]:
    """Fetch ALL CVEs for a specific product from MSRC SUG API using OData pagination.

    No date filter — fetches the complete all-time CVE history for the product.
    MSRC caps each response at 500 rows and returns @odata.nextLink when more pages
    exist. This function follows nextLink until exhausted.

    Uses `product eq '<product>'` filter — MSRC exact product names like
    "Windows Server 2016", "Windows Server 2019", etc.
    """
    odata_filter = f"product eq '{product}'"
    next_url: str | None = f"{_MSRC_SUG_BASE}?{urllib.parse.urlencode({'$filter': odata_filter, '$top': 500})}"

    records: list[dict] = []
    seen: set[str] = set()
    page = 0

    try:
        while next_url:
            page += 1
            req = urllib.request.Request(
                next_url,
                headers={"Accept": "application/json", "User-Agent": "AAP-CVELookup/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))

            records.extend(_parse_msrc_items(data.get("value", []), product, seen))
            next_url = data.get("@odata.nextLink")
            logger.debug("MSRC %s page %d: %d records (total so far: %d)", product, page, len(data.get("value", [])), len(records))

        logger.info("MSRC %s: %d CVEs fetched across %d page(s)", product, len(records), page)
        return records
    except Exception as exc:
        logger.warning("MSRC product lookup failed for %s (page %d): %s", product, page, exc)
        return records  # Return whatever we collected before the error


_product_cve_cache: dict[str, tuple[list[dict], float]] = {}


async def get_cves_for_product(os_version: str, months_back: int = 12) -> list[dict]:
    """Fetch all CVEs for an OS version's product family from MSRC.

    Fetches the complete all-time CVE history (no date filter). Results are
    cached in-process for 24 hours so the multi-page fetch only happens once.

    Args:
        os_version: ARG osVersion string (e.g. "Windows Server 2016 Standard").
        months_back: Unused — kept for API compatibility. All CVEs are returned.

    Returns:
        List of CVE dicts with cve_id, cvss_score, severity, description, kb_ids,
        published_date, affected_product, affected_versions.
        Empty list if product not mapped or on error.
    """
    product = _os_to_msrc_product(os_version)
    if not product:
        logger.debug("No MSRC product mapping for os_version=%r", os_version)
        return []

    now = time.monotonic()
    cached = _product_cve_cache.get(product)
    if cached is not None:
        cve_list, cached_at = cached
        if now - cached_at < _CACHE_TTL_SECONDS:
            return list(cve_list)

    loop = asyncio.get_running_loop()
    records = await loop.run_in_executor(None, _fetch_cves_for_product_sync, product)
    _product_cve_cache[product] = (records, now)
    return records


def _normalise_kb_id(kb_id: str) -> str:
    """Extract digits from a KB identifier.

    Accepts formats like "KB5034441" or "5034441" and returns digits only.
    """
    match = _KB_DIGITS_PATTERN.search(kb_id)
    if not match:
        return kb_id.strip()
    return match.group()


def _fetch_cves_sync(kb_digits: str) -> list[str]:
    """Synchronous HTTP call to MSRC SUG API for a single KB.

    Returns list of CVE numbers, or empty list on error.
    """
    odata_filter = f"kbArticles/any(k:k/articleName eq '{kb_digits}')"
    url = f"{_MSRC_SUG_BASE}?{urllib.parse.urlencode({'$filter': odata_filter})}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AAP-PatchEnrichment/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
            cve_numbers: list[str] = []
            for item in data.get("value", []):
                cve = item.get("cveNumber", "")
                if cve and cve not in cve_numbers:
                    cve_numbers.append(cve)
            return cve_numbers
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("MSRC lookup failed for KB %s: %s", kb_digits, exc)
        return []
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("MSRC response parse error for KB %s: %s", kb_digits, exc)
        return []


async def get_cves_for_kb(kb_id: str) -> list[str]:
    """Look up CVE identifiers for a single KB article ID.

    Args:
        kb_id: KB identifier (e.g. "KB5034441" or "5034441").

    Returns:
        List of CVE numbers (e.g. ["CVE-2024-21302", "CVE-2024-21303"]).
        Empty list on error or timeout.
    """
    kb_digits = _normalise_kb_id(kb_id)
    if not kb_digits:
        return []

    # Check cache
    now = time.monotonic()
    cached = _kb_cve_cache.get(kb_digits)
    if cached is not None:
        cve_list, cached_at = cached
        if now - cached_at < _CACHE_TTL_SECONDS:
            return list(cve_list)  # Return a copy

    # Fetch in thread executor (urllib is blocking)
    loop = asyncio.get_running_loop()
    cve_list = await loop.run_in_executor(None, _fetch_cves_sync, kb_digits)

    # Cache result
    _kb_cve_cache[kb_digits] = (cve_list, now)
    return cve_list


async def get_cves_for_kbs(kb_ids: list[str]) -> dict[str, list[str]]:
    """Look up CVE identifiers for multiple KB article IDs in parallel.

    Args:
        kb_ids: List of KB identifiers.

    Returns:
        Dict mapping each KB ID to its list of CVE numbers.
    """
    if not kb_ids:
        return {}

    tasks = [get_cves_for_kb(kb_id) for kb_id in kb_ids]
    results = await asyncio.gather(*tasks)
    return dict(zip(kb_ids, results))
