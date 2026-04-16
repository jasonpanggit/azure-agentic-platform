"""TenantManager — multi-tenant isolation for AAP.

Manages tenant records in PostgreSQL and provides fast in-memory caching
(5-minute TTL) for operator → tenant lookups on the hot path.
"""
from __future__ import annotations

import json as _json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------

class Tenant(BaseModel):
    """Represents a tenant in the multi-tenant AAP platform."""

    tenant_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1, description="Unique human-readable tenant name")
    subscriptions: list[str] = Field(default_factory=list, description="Azure subscription IDs")
    sla_definitions: list[dict] = Field(default_factory=list)
    compliance_frameworks: list[str] = Field(default_factory=list)
    operator_group_id: str = Field(..., description="Entra group object ID for this tenant's operators")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @field_validator("sla_definitions", mode="before")
    @classmethod
    def _parse_sla_definitions(cls, v: object) -> object:
        """Accept a JSON string in place of a list (defensive coercion)."""
        if isinstance(v, str):
            return _json.loads(v)
        return v

    @field_validator("subscriptions", "compliance_frameworks", mode="before")
    @classmethod
    def _parse_string_lists(cls, v: object) -> object:
        """Accept a JSON string in place of a list (defensive coercion)."""
        if isinstance(v, str):
            return _json.loads(v)
        return v


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------

class _CacheEntry:
    __slots__ = ("tenant", "expires_at")

    def __init__(self, tenant: Optional[Tenant], ttl_seconds: int = 300) -> None:
        self.tenant = tenant
        self.expires_at = time.monotonic() + ttl_seconds


# ---------------------------------------------------------------------------
# TenantManager
# ---------------------------------------------------------------------------

class TenantManager:
    """PostgreSQL-backed tenant manager with 5-minute in-memory cache."""

    _TTL_SECONDS = 300  # 5 minutes

    def __init__(self, postgres_dsn: Optional[str] = None) -> None:
        self._dsn = postgres_dsn
        # operator_group_id → _CacheEntry
        self._cache: dict[str, _CacheEntry] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_sdk_availability(self) -> None:
        if asyncpg is None:
            logger.warning("tenant_manager: asyncpg not installed — PostgreSQL unavailable")

    def _is_available(self) -> bool:
        return asyncpg is not None and bool(self._dsn)

    def _row_to_tenant(self, row: dict) -> Tenant:
        return Tenant(
            tenant_id=str(row["tenant_id"]),
            name=row["name"],
            subscriptions=list(row["subscriptions"] or []),
            sla_definitions=list(row["sla_definitions"] or []),
            compliance_frameworks=list(row["compliance_frameworks"] or []),
            operator_group_id=row["operator_group_id"],
            created_at=(
                row["created_at"].isoformat()
                if hasattr(row["created_at"], "isoformat")
                else str(row["created_at"])
            ),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_tenant_for_operator(self, operator_id: str) -> Optional[Tenant]:
        """Return the tenant whose operator_group_id matches operator_id.

        Checks a 5-minute in-memory cache before hitting PostgreSQL.
        Returns None when operator is not assigned to any tenant.
        Never raises — returns None on any error.
        """
        start_time = time.monotonic()
        try:
            # Cache check
            entry = self._cache.get(operator_id)
            if entry is not None and time.monotonic() < entry.expires_at:
                logger.debug("tenant_manager: cache hit | operator=%s", operator_id)
                return entry.tenant

            if not self._is_available():
                self._log_sdk_availability()
                return None

            conn = await asyncpg.connect(self._dsn)
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM tenants WHERE operator_group_id = $1 LIMIT 1",
                    operator_id,
                )
            finally:
                await conn.close()

            tenant = self._row_to_tenant(dict(row)) if row else None
            self._cache[operator_id] = _CacheEntry(tenant, self._TTL_SECONDS)
            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            logger.info(
                "tenant_manager: get_tenant_for_operator | operator=%s found=%s duration_ms=%s",
                operator_id, tenant is not None, duration_ms,
            )
            return tenant
        except Exception as exc:
            logger.warning(
                "tenant_manager: get_tenant_for_operator failed (non-fatal) | operator=%s error=%s",
                operator_id, exc,
            )
            return None

    async def list_tenants(self) -> list[Tenant]:
        """Return all tenants from PostgreSQL.

        Returns empty list when PostgreSQL is not available or on error.
        """
        start_time = time.monotonic()
        try:
            if not self._is_available():
                self._log_sdk_availability()
                return []

            conn = await asyncpg.connect(self._dsn)
            try:
                rows = await conn.fetch("SELECT * FROM tenants ORDER BY created_at DESC")
            finally:
                await conn.close()

            tenants = [self._row_to_tenant(dict(r)) for r in rows]
            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            logger.info(
                "tenant_manager: list_tenants | count=%d duration_ms=%s",
                len(tenants), duration_ms,
            )
            return tenants
        except Exception as exc:
            logger.error("tenant_manager: list_tenants failed | error=%s", exc)
            raise

    async def create_tenant(self, tenant: Tenant) -> Tenant:
        """Insert a new tenant record into PostgreSQL.

        Returns the created Tenant (with server-generated tenant_id if not provided).
        Never raises — returns the input Tenant with error logged on failure.
        """
        start_time = time.monotonic()
        try:
            if not self._is_available():
                self._log_sdk_availability()
                return tenant

            import json

            conn = await asyncpg.connect(self._dsn)
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO tenants
                        (tenant_id, name, subscriptions, sla_definitions,
                         compliance_frameworks, operator_group_id, created_at)
                    VALUES
                        ($1::uuid, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6, $7)
                    RETURNING *
                    """,
                    tenant.tenant_id,
                    tenant.name,
                    json.dumps(tenant.subscriptions),
                    json.dumps(tenant.sla_definitions),
                    json.dumps(tenant.compliance_frameworks),
                    tenant.operator_group_id,
                    datetime.fromisoformat(tenant.created_at),
                )
            finally:
                await conn.close()

            created = self._row_to_tenant(dict(row))
            # Warm the cache
            self._cache[created.operator_group_id] = _CacheEntry(created, self._TTL_SECONDS)
            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            logger.info(
                "tenant_manager: create_tenant | tenant_id=%s name=%s duration_ms=%s",
                created.tenant_id, created.name, duration_ms,
            )
            return created
        except Exception as exc:
            logger.error(
                "tenant_manager: create_tenant failed | name=%s error=%s",
                tenant.name, exc,
            )
            raise

    async def update_subscriptions(self, tenant_id: str, subscriptions: list[str]) -> Optional[Tenant]:
        """Update the subscription list for a tenant.

        Returns updated Tenant or None if not found / error.
        """
        start_time = time.monotonic()
        try:
            if not self._is_available():
                self._log_sdk_availability()
                return None

            import json

            conn = await asyncpg.connect(self._dsn)
            try:
                row = await conn.fetchrow(
                    """
                    UPDATE tenants
                    SET subscriptions = $1::jsonb
                    WHERE tenant_id = $2::uuid
                    RETURNING *
                    """,
                    json.dumps(subscriptions),
                    tenant_id,
                )
            finally:
                await conn.close()

            if row is None:
                return None

            updated = self._row_to_tenant(dict(row))
            # Invalidate cache for this operator group
            self._cache.pop(updated.operator_group_id, None)
            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            logger.info(
                "tenant_manager: update_subscriptions | tenant_id=%s subs=%d duration_ms=%s",
                tenant_id, len(subscriptions), duration_ms,
            )
            return updated
        except Exception as exc:
            logger.warning(
                "tenant_manager: update_subscriptions failed (non-fatal) | tenant_id=%s error=%s",
                tenant_id, exc,
            )
            return None

    async def get_tenant_by_id(self, tenant_id: str) -> Optional[Tenant]:
        """Look up a tenant by tenant_id UUID. Returns None on error or not found."""
        start_time = time.monotonic()
        try:
            if not self._is_available():
                self._log_sdk_availability()
                return None

            conn = await asyncpg.connect(self._dsn)
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM tenants WHERE tenant_id = $1::uuid LIMIT 1",
                    tenant_id,
                )
            finally:
                await conn.close()

            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            if row is None:
                logger.info("tenant_manager: get_tenant_by_id | tenant_id=%s not_found duration_ms=%s", tenant_id, duration_ms)
                return None

            tenant = self._row_to_tenant(dict(row))
            logger.info("tenant_manager: get_tenant_by_id | tenant_id=%s duration_ms=%s", tenant_id, duration_ms)
            return tenant
        except Exception as exc:
            logger.warning(
                "tenant_manager: get_tenant_by_id failed (non-fatal) | tenant_id=%s error=%s",
                tenant_id, exc,
            )
            return None
