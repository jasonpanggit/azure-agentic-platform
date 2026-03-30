-- Migration 004: Create eol_cache table for EOL lifecycle caching (Phase 12)
-- 24h TTL, synchronous refresh on cache miss.

CREATE TABLE IF NOT EXISTS eol_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product         TEXT NOT NULL,
    version         TEXT NOT NULL,
    eol_date        DATE,
    is_eol          BOOLEAN NOT NULL,
    lts             BOOLEAN,
    latest_version  TEXT,
    support_end     DATE,
    source          TEXT NOT NULL,
    raw_response    JSONB,
    cached_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    UNIQUE (product, version, source)
);

CREATE INDEX IF NOT EXISTS idx_eol_cache_lookup
    ON eol_cache (product, version, expires_at);

COMMENT ON TABLE eol_cache IS 'EOL lifecycle cache — Phase 12. 24h TTL, synchronous refresh on miss.';
