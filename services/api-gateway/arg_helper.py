"""Shared Azure Resource Graph query helper.

Extracted from vm_inventory.py and patch_endpoints.py (which contain identical
copies). New modules (topology.py) import from here. Existing modules retain
their local copies until a future cleanup phase.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def run_arg_query(
    credential: Any,
    subscription_ids: List[str],
    kql: str,
) -> List[Dict[str, Any]]:
    """Execute an Azure Resource Graph query with automatic pagination.

    Exhausts all skip_token pages and returns the complete result set.

    Args:
        credential: Azure credential (DefaultAzureCredential or compatible).
        subscription_ids: List of subscription IDs to scope the query.
        kql: KQL query string.

    Returns:
        List of result row dicts from ARG. Empty list if no results.

    Raises:
        Exception: On ARG API failure (caller decides whether to retry or degrade).
    """
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

    client = ResourceGraphClient(credential)
    all_rows: List[Dict[str, Any]] = []
    skip_token: Optional[str] = None

    while True:
        options = QueryRequestOptions(skip_token=skip_token) if skip_token else None
        request = QueryRequest(
            subscriptions=subscription_ids,
            query=kql,
            options=options,
        )
        response = client.resources(request)
        all_rows.extend(response.data)

        skip_token = response.skip_token
        if not skip_token:
            break

    logger.debug(
        "arg_helper: query complete | rows=%d subscriptions=%d",
        len(all_rows),
        len(subscription_ids),
    )
    return all_rows
