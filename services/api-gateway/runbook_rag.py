"""Runbook RAG retrieval — pgvector cosine similarity search (TRIAGE-005).

Searches the PostgreSQL `runbooks` table using pgvector cosine similarity.
Returns top-N results above a configurable similarity threshold.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = float(os.environ.get("RUNBOOK_SIMILARITY_THRESHOLD", "0.75"))
POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small")

# Content excerpt length
MAX_EXCERPT_LENGTH = 300


async def generate_query_embedding(query: str) -> list[float]:
    """Generate an embedding vector for the search query using Azure OpenAI.

    Uses DefaultAzureCredential when AZURE_OPENAI_API_KEY is absent (local auth
    disabled on the Foundry account — Entra-only mode).

    Args:
        query: Natural-language search query.

    Returns:
        1536-dimensional float vector.
    """
    from openai import AzureOpenAI

    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    azure_ad_token_provider = None
    if not api_key or api_key == "DISABLED_LOCAL_AUTH_USE_MI":
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        credential = DefaultAzureCredential()
        azure_ad_token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        api_key = None

    client = AzureOpenAI(
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        api_key=api_key,
        azure_ad_token_provider=azure_ad_token_provider,
        api_version="2024-06-01",
    )
    response = client.embeddings.create(
        input=[query],
        model=EMBEDDING_MODEL,
    )
    return response.data[0].embedding


async def search_runbooks(
    query_embedding: list[float],
    domain: Optional[str] = None,
    limit: int = 3,
) -> list[dict]:
    """Search runbooks by cosine similarity using pgvector.

    Args:
        query_embedding: 1536-dim embedding vector for the query.
        domain: Optional domain filter (compute, network, etc.).
        limit: Maximum number of results to return.

    Returns:
        List of dicts with id, title, domain, version, similarity, content_excerpt.
    """
    import asyncpg
    from pgvector.asyncpg import register_vector

    dsn = POSTGRES_DSN or _build_dsn()
    conn = await asyncpg.connect(dsn)
    await register_vector(conn)

    try:
        # After register_vector, asyncpg handles vector encoding natively.
        # Pass query_embedding as a list directly — do NOT stringify or cast with ::vector.
        if domain:
            rows = await conn.fetch(
                """
                SELECT id, title, domain, version, content,
                       1 - (embedding <=> $1) AS similarity
                FROM runbooks
                WHERE domain = $2
                ORDER BY embedding <=> $1
                LIMIT $3
                """,
                query_embedding,
                domain,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, title, domain, version, content,
                       1 - (embedding <=> $1) AS similarity
                FROM runbooks
                ORDER BY embedding <=> $1
                LIMIT $2
                """,
                query_embedding,
                limit,
            )

        results = []
        for row in rows:
            sim = float(row["similarity"])
            if sim >= SIMILARITY_THRESHOLD:
                results.append({
                    "id": str(row["id"]),
                    "title": row["title"],
                    "domain": row["domain"],
                    "version": row["version"],
                    "similarity": round(sim, 4),
                    "content_excerpt": row["content"][:MAX_EXCERPT_LENGTH],
                })
        return results
    finally:
        await conn.close()


def _build_dsn() -> str:
    """Build PostgreSQL DSN from environment variables."""
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "aap")
    user = os.environ.get("POSTGRES_USER", "aap")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"
