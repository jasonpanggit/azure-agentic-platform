-- Phase 64: Enterprise Multi-Tenant Gateway
-- Creates the tenants table for multi-tenant isolation in AAP.

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL UNIQUE,
    subscriptions       JSONB NOT NULL DEFAULT '[]',
    sla_definitions     JSONB NOT NULL DEFAULT '[]',
    compliance_frameworks JSONB NOT NULL DEFAULT '[]',
    operator_group_id   TEXT NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenants_operator_group ON tenants(operator_group_id);
