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
    url = f"{_MSRC_SUG_BASE}?$filter=kbArticles/any(k:k/articleName eq '{kb_digits}')"
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
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
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
