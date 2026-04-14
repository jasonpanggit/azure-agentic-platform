"""Subscription registry — ARG-backed discovery of all accessible Azure subscriptions.

Provides SubscriptionRegistry which:
- Discovers all Enabled subscriptions via Azure Resource Graph
- Persists to Cosmos DB `subscriptions` container
- Caches in-memory for O(1) get_all_ids() access
- Refreshes every 6 hours via run_refresh_loop()
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ARG KQL: all enabled subscriptions accessible to the managed identity
_SUBSCRIPTION_KQL = """
Resources
| where type =~ 'microsoft.resources/subscriptions'
| where properties.state =~ 'Enabled'
| project subscriptionId, displayName = name
""".strip()

COSMOS_DATABASE_NAME_DEFAULT = "aap"


class SubscriptionRegistry:
    """Discovers and caches all Azure subscriptions the managed identity can Reader."""

    def __init__(
        self,
        credential: Any,
        cosmos_client: Optional[Any],
        cosmos_database_name: str = COSMOS_DATABASE_NAME_DEFAULT,
    ):
        self._credential = credential
        self._cosmos_client = cosmos_client
        self._cosmos_database_name = cosmos_database_name
        self._cache: List[Dict[str, str]] = []

    # ------------------------------------------------------------------
    # ARG discovery
    # ------------------------------------------------------------------

    def _run_arg_query(self) -> List[Dict[str, str]]:
        """Execute ARG query to list enabled subscriptions. Returns raw rows."""
        try:
            from azure.mgmt.resourcegraph import ResourceGraphClient
            from azure.mgmt.resourcegraph.models import QueryRequest
        except ImportError as exc:
            raise exc

        client = ResourceGraphClient(self._credential)
        # Query at tenant scope (no subscription filter) to find all accessible subs
        request = QueryRequest(query=_SUBSCRIPTION_KQL, subscriptions=[])
        response = client.resources(request)
        return list(response.data) if response.data else []

    def discover(self) -> List[Dict[str, str]]:
        """Discover all enabled subscriptions. Returns [{id, name}, ...].

        Returns empty list (non-fatal) if azure-mgmt-resourcegraph is unavailable.
        """
        start = time.monotonic()
        try:
            rows = self._run_arg_query()
            result = [
                {"id": row["subscriptionId"], "name": row["displayName"]}
                for row in rows
                if row.get("subscriptionId")
            ]
            logger.info(
                "subscription_registry: discovered | count=%d duration_ms=%.1f",
                len(result),
                (time.monotonic() - start) * 1000,
            )
            return result
        except ImportError:
            logger.warning(
                "subscription_registry: azure-mgmt-resourcegraph not available — returning empty list"
            )
            return []
        except Exception as exc:
            logger.error("subscription_registry: discover error | error=%s", exc)
            return []

    # ------------------------------------------------------------------
    # Cosmos persistence
    # ------------------------------------------------------------------

    def sync_to_cosmos(self) -> None:
        """Upsert cached subscriptions to Cosmos DB. No-op if cosmos_client is None."""
        if self._cosmos_client is None:
            return
        try:
            container = (
                self._cosmos_client
                .get_database_client(self._cosmos_database_name)
                .get_container_client("subscriptions")
            )
            now = datetime.now(timezone.utc).isoformat()
            for sub in self._cache:
                container.upsert_item({
                    "id": sub["id"],
                    "subscription_id": sub["id"],
                    "name": sub["name"],
                    "last_synced": now,
                })
            logger.info(
                "subscription_registry: cosmos sync complete | count=%d",
                len(self._cache),
            )
        except Exception as exc:
            logger.error("subscription_registry: cosmos sync error | error=%s", exc)

    # ------------------------------------------------------------------
    # Cache access
    # ------------------------------------------------------------------

    def get_all_ids(self) -> List[str]:
        """Return all discovered subscription IDs from in-memory cache."""
        return [s["id"] for s in self._cache]

    def get_all(self) -> List[Dict[str, str]]:
        """Return all discovered subscriptions [{id, name}] from cache."""
        return list(self._cache)

    # ------------------------------------------------------------------
    # Full sync (discover + persist)
    # ------------------------------------------------------------------

    async def full_sync(self) -> None:
        """Discover subscriptions and persist to Cosmos. Updates in-memory cache."""
        loop = asyncio.get_event_loop()
        subs = await loop.run_in_executor(None, self.discover)
        self._cache = subs
        await loop.run_in_executor(None, self.sync_to_cosmos)

    # ------------------------------------------------------------------
    # Background refresh loop
    # ------------------------------------------------------------------

    async def run_refresh_loop(self, interval_seconds: int = 6 * 3600) -> None:
        """Refresh subscriptions on startup then every interval_seconds.

        Designed to run as an asyncio background task via asyncio.create_task().
        Logs errors but never propagates them (non-fatal background task).
        """
        while True:
            try:
                await self.full_sync()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("subscription_registry: refresh error | error=%s", exc)
            await asyncio.sleep(interval_seconds)
