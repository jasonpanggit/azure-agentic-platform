#!/usr/bin/env python3
"""Runbook seed script — idempotent embedding + insertion into PostgreSQL pgvector.

Usage:
    python scripts/seed-runbooks/seed.py

Environment variables:
    POSTGRES_DSN         — PostgreSQL connection string
    POSTGRES_HOST        — PostgreSQL host (if DSN not set)
    POSTGRES_PORT        — PostgreSQL port (default: 5432)
    POSTGRES_DB          — Database name (default: aap)
    POSTGRES_USER        — Username (default: aap_admin)
    POSTGRES_PASSWORD    — Password
    AZURE_OPENAI_ENDPOINT — Azure OpenAI endpoint
    AZURE_OPENAI_API_KEY  — Azure OpenAI API key

Behavior:
    - Reads all .md files from scripts/seed-runbooks/runbooks/
    - Parses YAML frontmatter (title, domain, version, tags)
    - Generates 1536-dim embeddings via Azure OpenAI text-embedding-3-small
    - INSERT ... ON CONFLICT (title) DO UPDATE (idempotent)
    - Creates the runbooks table + indexes if not present

Never auto-runs against prod — prod seed is a documented manual step.
"""
import json
import os
import sys
from pathlib import Path

import psycopg
import yaml
from openai import AzureOpenAI
from pgvector.psycopg import register_vector

RUNBOOKS_DIR = Path(__file__).parent / "runbooks"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


def build_dsn() -> str:
    """Build PostgreSQL DSN from environment variables."""
    dsn = os.environ.get("POSTGRES_DSN", "")
    if dsn:
        return dsn
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "aap")
    user = os.environ.get("POSTGRES_USER", "aap_admin")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def ensure_table(conn: psycopg.Connection) -> None:
    """Create runbooks table and indexes if not present."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runbooks (
            id SERIAL PRIMARY KEY,
            title TEXT UNIQUE NOT NULL,
            domain TEXT NOT NULL,
            version TEXT NOT NULL,
            tags TEXT[] DEFAULT '{}',
            content TEXT NOT NULL,
            embedding vector(1536) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    # Idempotent migrations: harmonise schema between api-gateway startup migration
    # (older schema: UUID id, INTEGER version, no tags, no UNIQUE title) and seed schema.
    conn.execute("""
        ALTER TABLE runbooks ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}'
    """)
    conn.execute("""
        ALTER TABLE runbooks ALTER COLUMN version TYPE TEXT USING version::TEXT
    """)
    # Add UNIQUE constraint on title if not present (needed for ON CONFLICT upsert).
    conn.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'runbooks'::regclass AND conname = 'runbooks_title_key'
            ) THEN
                ALTER TABLE runbooks ADD CONSTRAINT runbooks_title_key UNIQUE (title);
            END IF;
        END
        $$
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_runbooks_embedding
        ON runbooks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_runbooks_domain ON runbooks (domain)
    """)
    conn.commit()


def parse_runbook(filepath: Path) -> dict:
    """Parse a runbook markdown file with YAML frontmatter."""
    text = filepath.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1])
            body = parts[2].strip()
            return {
                "title": frontmatter.get("title", filepath.stem),
                "domain": frontmatter.get("domain", "unknown"),
                "version": frontmatter.get("version", "1.0"),
                "tags": frontmatter.get("tags", []),
                "content": body,
            }
    return {
        "title": filepath.stem,
        "domain": "unknown",
        "version": "1.0",
        "tags": [],
        "content": text.strip(),
    }


def generate_embedding(client: AzureOpenAI, text: str) -> list[float]:
    """Generate a 1536-dim embedding for the given text."""
    response = client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
    return response.data[0].embedding


def upsert_runbook(conn: psycopg.Connection, runbook: dict, embedding: list[float]) -> str:
    """Insert or update a runbook record. Returns 'inserted' or 'updated'."""
    result = conn.execute(
        """
        INSERT INTO runbooks (title, domain, version, tags, content, embedding, updated_at)
        VALUES (%(title)s, %(domain)s, %(version)s, %(tags)s, %(content)s, %(embedding)s, now())
        ON CONFLICT (title) DO UPDATE SET
            domain = EXCLUDED.domain,
            version = EXCLUDED.version,
            tags = EXCLUDED.tags,
            content = EXCLUDED.content,
            embedding = EXCLUDED.embedding,
            updated_at = now()
        RETURNING (xmax = 0) AS is_insert
        """,
        {
            "title": runbook["title"],
            "domain": runbook["domain"],
            "version": runbook["version"],
            "tags": runbook["tags"],
            "content": runbook["content"],
            "embedding": str(embedding),
        },
    )
    row = result.fetchone()
    conn.commit()
    return "inserted" if row and row[0] else "updated"


def main() -> None:
    """Main entry point."""
    # Collect runbook files
    md_files = sorted(RUNBOOKS_DIR.glob("*.md"))
    if not md_files:
        print(f"ERROR: No .md files found in {RUNBOOKS_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(md_files)} runbook files")

    # Initialize OpenAI client — support Entra auth when API key is absent or sentinel.
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    azure_ad_token_provider = None
    if not api_key or api_key == "DISABLED_LOCAL_AUTH_USE_MI":
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        credential = DefaultAzureCredential()
        azure_ad_token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        api_key = None

    openai_client = AzureOpenAI(
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        api_key=api_key,
        azure_ad_token_provider=azure_ad_token_provider,
        api_version="2024-06-01",
    )

    # Connect to PostgreSQL
    dsn = build_dsn()
    print(f"Connecting to PostgreSQL...")
    with psycopg.connect(dsn) as conn:
        register_vector(conn)
        ensure_table(conn)

        inserted = 0
        updated = 0
        for filepath in md_files:
            runbook = parse_runbook(filepath)
            print(f"  Processing: {runbook['title']} ({runbook['domain']})")

            # Generate embedding for the full content
            embedding = generate_embedding(openai_client, runbook["content"])

            # Upsert
            action = upsert_runbook(conn, runbook, embedding)
            if action == "inserted":
                inserted += 1
            else:
                updated += 1

        print(f"\nDone: {inserted} inserted, {updated} updated, {len(md_files)} total")


if __name__ == "__main__":
    main()
