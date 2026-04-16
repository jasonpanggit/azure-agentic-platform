CREATE TABLE IF NOT EXISTS cve_cache (
    cache_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vm_resource_id TEXT NOT NULL,
    cve_data JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cve_cache_vm ON cve_cache(vm_resource_id);
CREATE INDEX IF NOT EXISTS idx_cve_cache_expires ON cve_cache(expires_at);
