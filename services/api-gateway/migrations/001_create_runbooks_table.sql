-- Migration 001: Create runbooks table for Runbook RAG (TRIAGE-005)
-- pgvector extension must already be enabled (Phase 1 INFRA-003)

-- Ensure pgvector extension is available
CREATE EXTENSION IF NOT EXISTS vector;

-- Runbooks table (D-16)
CREATE TABLE IF NOT EXISTS runbooks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    domain      TEXT NOT NULL CHECK (domain IN ('compute','network','storage','security','arc','sre')),
    version     TEXT NOT NULL DEFAULT '1.0',
    content     TEXT NOT NULL,
    embedding   vector(1536) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW index for cosine similarity search (preferred over IVFFlat for better recall)
CREATE INDEX IF NOT EXISTS idx_runbooks_embedding ON runbooks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Domain filter index for filtered vector search
CREATE INDEX IF NOT EXISTS idx_runbooks_domain ON runbooks (domain);

-- Comment for documentation
COMMENT ON TABLE runbooks IS 'Runbook library for RAG — TRIAGE-005. Agents retrieve top-3 semantically relevant runbooks via pgvector cosine similarity.';
