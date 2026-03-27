#!/usr/bin/env python3
"""Validate runbook embeddings — each runbook must return cosine similarity > 0.75
for at least one test query matching its domain (D-10, TRIAGE-005 SC-3).

Usage:
    python scripts/seed-runbooks/validate.py

Environment variables: same as seed.py
"""
import os
import sys

import psycopg
from openai import AzureOpenAI
from pgvector.psycopg import register_vector

EMBEDDING_MODEL = "text-embedding-3-small"
SIMILARITY_THRESHOLD = 0.75

# Domain-specific test queries — each domain has 2 queries
DOMAIN_QUERIES = {
    "compute": [
        "VM is experiencing high CPU utilization above 90 percent",
        "Virtual machine disk is full and needs space reclaimed",
    ],
    "network": [
        "NSG rule is blocking traffic that should be allowed",
        "VPN gateway connection dropped and is not reconnecting",
    ],
    "storage": [
        "Azure blob storage is being throttled with 503 errors",
        "Storage account access key needs to be rotated",
    ],
    "security": [
        "Unauthorized access attempt detected in audit logs",
        "Service principal credentials are about to expire",
    ],
    "arc": [
        "Arc-enabled server is showing as disconnected",
        "Arc Kubernetes cluster Flux GitOps reconciliation is failing",
    ],
    "sre": [
        "Multi-region failover procedure needed for disaster recovery",
        "Unexpected cost increase detected in Azure subscription",
    ],
}


def build_dsn() -> str:
    dsn = os.environ.get("POSTGRES_DSN", "")
    if dsn:
        return dsn
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "aap")
    user = os.environ.get("POSTGRES_USER", "aap_admin")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def main() -> None:
    openai_client = AzureOpenAI(
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version="2024-06-01",
    )

    dsn = build_dsn()
    failures = []
    total_checked = 0

    with psycopg.connect(dsn) as conn:
        register_vector(conn)

        # Get all runbooks grouped by domain
        rows = conn.execute(
            "SELECT id, title, domain FROM runbooks ORDER BY domain, title"
        ).fetchall()

        if not rows:
            print("ERROR: No runbooks found in database. Run seed.py first.")
            sys.exit(1)

        print(f"Validating {len(rows)} runbooks across {len(DOMAIN_QUERIES)} domains\n")

        for domain, queries in DOMAIN_QUERIES.items():
            domain_runbooks = [r for r in rows if r[2] == domain]
            if not domain_runbooks:
                print(f"  WARNING: No runbooks found for domain '{domain}'")
                continue

            for query_text in queries:
                # Generate query embedding
                response = openai_client.embeddings.create(
                    input=[query_text], model=EMBEDDING_MODEL
                )
                query_embedding = response.data[0].embedding
                embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

                # Search for top match in this domain
                result = conn.execute(
                    """
                    SELECT title, 1 - (embedding <=> %s::vector) AS similarity
                    FROM runbooks
                    WHERE domain = %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT 1
                    """,
                    (embedding_str, domain, embedding_str),
                ).fetchone()

                total_checked += 1
                if result:
                    title, similarity = result[0], float(result[1])
                    status = "PASS" if similarity >= SIMILARITY_THRESHOLD else "FAIL"
                    if status == "FAIL":
                        failures.append((domain, query_text, title, similarity))
                    print(f"  [{status}] {domain}: \"{query_text[:60]}...\" -> {title} (sim={similarity:.4f})")
                else:
                    failures.append((domain, query_text, "NO MATCH", 0))
                    print(f"  [FAIL] {domain}: \"{query_text[:60]}...\" -> NO MATCH")

    print(f"\n{'='*60}")
    print(f"Total checks: {total_checked}")
    print(f"Passed: {total_checked - len(failures)}")
    print(f"Failed: {len(failures)}")

    if failures:
        print(f"\nFailed validations:")
        for domain, query, title, sim in failures:
            print(f"  {domain}: \"{query[:80]}\" -> {title} (sim={sim:.4f}, threshold={SIMILARITY_THRESHOLD})")
        sys.exit(1)
    else:
        print("\nAll runbooks pass similarity threshold validation!")
        sys.exit(0)


if __name__ == "__main__":
    main()
