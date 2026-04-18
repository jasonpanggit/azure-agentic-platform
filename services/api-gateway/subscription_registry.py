from __future__ import annotations
"""Subscription registry — discovers all accessible Azure subscriptions.

Provides SubscriptionRegistry which:
- Discovers all Enabled subscriptions via azure-mgmt-subscription SDK
- Persists to Cosmos DB `subscriptions` container
- Caches in-memory for O(1) get_all_ids() access
- Refreshes every 6 hours via run_refresh_loop()
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COSMOS_DATABASE_NAME_DEFAULT = "aap"

# Module-level singleton set by main.py during startup.
# Endpoints that cannot access request.app.state use get_managed_subscription_ids().
_registry: Optional["SubscriptionRegistry"] = None


def set_registry(registry: "SubscriptionRegistry") -> None:
    """Register the singleton instance. Called once at application startup."""
    global _registry
    _registry = registry


async def get_managed_subscription_ids() -> List[str]:
    """Return subscription IDs from the in-memory registry cache.

    Returns an empty list (non-fatal) if the registry has not been initialised yet.
    """
    if _registry is None:
        logger.warning("subscription_registry: singleton not set — returning empty list")
        return []
    return _registry.get_all_ids()


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
    # Subscription discovery via azure-mgmt-subscription
    # ------------------------------------------------------------------

    def discover(self) -> List[Dict[str, str]]:
        """Discover all enabled subscriptions the managed identity can access.

        Uses azure-mgmt-subscription SubscriptionClient which lists all subscriptions
        at the tenant level — the correct API for subscription discovery (not ARG).
        Returns [{id, name}, ...]. Returns empty list (non-fatal) on any error.
        """
        start = time.monotonic()
        try:
            from azure.mgmt.subscription import SubscriptionClient  # type: ignore[import]
        except ImportError:
            logger.warning(
                "subscription_registry: azure-mgmt-subscription not installed — returning empty list"
            )
            return []

        try:
            client = SubscriptionClient(self._credential)
            result = [
                {"id": sub.subscription_id, "name": sub.display_name or sub.subscription_id}
                for sub in client.subscriptions.list()
                if sub.state and str(sub.state).lower() == "enabled"
                and sub.subscription_id
            ]
            logger.info(
                "subscription_registry: discovered | count=%d duration_ms=%.1f",
                len(result),
                (time.monotonic() - start) * 1000,
            )
            return result
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
