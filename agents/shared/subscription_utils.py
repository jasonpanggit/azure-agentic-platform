"""Shared subscription utilities for Azure agent tools.

Provides extract_subscription_id() — a canonical helper for extracting
the Azure subscription ID from an ARM resource ID. Previously duplicated
across compute, network, security, sre, database, appservice, arc, patch,
eol, messaging, and containerapps agents.
"""
from __future__ import annotations


def extract_subscription_id(resource_id: str) -> str:
    """Extract the Azure subscription ID from an ARM resource ID.

    Args:
        resource_id: Full ARM resource ID, e.g.:
            /subscriptions/{sub}/resourceGroups/{rg}/providers/...

    Returns:
        The subscription GUID string (lowercase).

    Raises:
        ValueError: If the resource_id does not contain a subscriptions segment.
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        sub_id = parts[idx + 1]
        if not sub_id:
            raise ValueError("Empty subscription segment")
        return sub_id
    except (ValueError, IndexError) as exc:
        raise ValueError(
            f"Cannot extract subscription_id from resource_id: {resource_id}"
        ) from exc
