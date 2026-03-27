"""Runbook retrieval tool for domain agents (TRIAGE-005).

Provides a callable tool that queries the api-gateway's runbook search
endpoint and returns the top-3 semantically relevant runbooks for
citation in triage responses.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

API_GATEWAY_URL = os.environ.get("API_GATEWAY_URL", "http://localhost:8000")


async def retrieve_runbooks(
    query: str,
    domain: Optional[str] = None,
    limit: int = 3,
) -> list[dict]:
    """Retrieve top-3 runbooks by semantic similarity for a given query.

    Called by domain agents during triage to find relevant operational
    runbooks for citation in the diagnosis response.

    Args:
        query: Natural-language description of the incident or symptom.
        domain: Optional domain filter (compute, network, storage, security, arc, sre).
        limit: Max number of runbooks to return (default 3).

    Returns:
        List of dicts with keys: title, domain, version, similarity, content_excerpt.
        Returns empty list if the runbook service is unavailable.
    """
    params = {"query": query, "limit": str(limit)}
    if domain:
        params["domain"] = domain

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{API_GATEWAY_URL}/api/v1/runbooks/search",
                params=params,
            )
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        logger.warning("Runbook retrieval failed (non-blocking): %s", exc)
        return []


def format_runbook_citations(runbooks: list[dict]) -> str:
    """Format runbook results as a citation string for triage responses.

    Args:
        runbooks: List of runbook search results.

    Returns:
        Formatted string like:
        "Referenced runbooks: VM High CPU Troubleshooting (v1.0), VMSS Scaling Failure (v1.0)"
    """
    if not runbooks:
        return ""
    citations = [f"{r['title']} (v{r['version']})" for r in runbooks]
    return f"Referenced runbooks: {', '.join(citations)}"
