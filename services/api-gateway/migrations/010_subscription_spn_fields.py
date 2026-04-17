# services/api-gateway/migrations/010_subscription_spn_fields.py
from __future__ import annotations
"""Migration 010: Add SPN credential fields to Cosmos subscriptions container.

This migration is a no-op for SQL — the subscriptions container is in Cosmos DB
(schema-free). The new fields are added lazily on first write. This file serves
as a documentation anchor and adds safe defaults to any existing records that
lack the new fields when read by the application.

New fields added to subscription records:
  - credential_type: "mi" | "spn"  (default: "mi" for existing records)
  - client_id: str | None           (default: None)
  - tenant_id: str | None           (default: None)
  - kv_secret_name: str | None      (default: None)
  - permission_status: dict         (default: {})
  - last_validated_at: str | None   (default: None)
  - secret_expires_at: str | None   (default: None)
  - deleted_at: str | None          (default: None)
"""
import logging

logger = logging.getLogger(__name__)

DESCRIPTION = "Add SPN credential fields to Cosmos subscriptions container"


async def up(conn) -> None:  # noqa: ANN001
    """No SQL DDL required — Cosmos is schema-free.

    Documents the intent. The API layer applies defaults when reading
    existing records (see subscription_endpoints.py _enrich_record()).
    """
    logger.info("migration 010: SPN fields are schema-free in Cosmos — no DDL required")


async def down(conn) -> None:  # noqa: ANN001
    """No rollback required — field removal is backwards-compatible."""
    logger.info("migration 010 down: no-op")
