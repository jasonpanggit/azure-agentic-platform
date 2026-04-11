"""Idempotent SOP upload script -- uploads/updates SOP files in Foundry vector store.

Idempotency mechanism:
1. Compute SHA-256 hash of each .md file
2. Look up existing row in PostgreSQL sops table by foundry_filename
3. If row exists AND content_hash matches -> skip (no change)
4. If row exists AND hash differs -> delete old Foundry file, re-upload, update row
5. If no row -> upload to Foundry vector store (aap-sops-v1), insert row

Run after Phase 31 (initial SOP library)::

    python scripts/upload_sops.py

Run after any SOP update::

    python scripts/upload_sops.py

Or set up a GitHub Actions trigger on push to sops/**/*.md.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Directory containing all SOP .md files (from repo root)
SOP_DIR = Path("sops")
SOP_VECTOR_STORE_NAME = "aap-sops-v1"


def compute_sop_hash(sop_path: Path) -> str:
    """Compute SHA-256 hash of a SOP file's content.

    Args:
        sop_path: Path to the SOP markdown file.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    content = sop_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def parse_sop_front_matter(sop_path: Path) -> dict:
    """Parse YAML front matter from a SOP markdown file.

    Expects the file to start with '---' delimited YAML front matter.

    Args:
        sop_path: Path to the SOP markdown file.

    Returns:
        Dict of front matter fields (title, domain, version, scenario_tags, etc.)

    Raises:
        ValueError: If the file has no YAML front matter or is missing required fields.
    """
    content = sop_path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError(
            f"SOP file '{sop_path.name}' has no YAML front matter. "
            "All SOP files must start with '---' delimited YAML."
        )

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError(
            f"SOP file '{sop_path.name}' has malformed front matter."
        )

    front_matter = yaml.safe_load(parts[1])
    if not isinstance(front_matter, dict):
        raise ValueError(
            f"SOP file '{sop_path.name}' front matter is not a YAML dict."
        )

    for required in ("title", "domain", "version"):
        if required not in front_matter:
            raise ValueError(
                f"SOP file '{sop_path.name}' missing required front matter field: '{required}'"
            )

    return front_matter


def _get_or_create_vector_store(openai_client: object) -> str:
    """Get existing 'aap-sops-v1' vector store ID or create a new one.

    Args:
        openai_client: OpenAI client from project.get_openai_client().

    Returns:
        Vector store ID string.
    """
    stores = openai_client.vector_stores.list()
    for store in stores.data:
        if store.name == SOP_VECTOR_STORE_NAME:
            logger.info("Found existing vector store: %s (%s)", store.name, store.id)
            return store.id

    vs = openai_client.vector_stores.create(name=SOP_VECTOR_STORE_NAME)
    logger.info("Created new vector store: %s (%s)", vs.name, vs.id)
    return vs.id


async def upload_sops(sop_dir: Path = SOP_DIR) -> dict[str, str]:
    """Upload all SOP files in sop_dir to the Foundry vector store.

    Returns a dict mapping filename -> action taken ("created", "updated", "skipped").
    """
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
        "FOUNDRY_ACCOUNT_ENDPOINT"
    )
    if not endpoint:
        raise SystemExit("AZURE_PROJECT_ENDPOINT env var required.")

    import asyncpg

    pg_url = os.environ.get("DATABASE_URL")
    if not pg_url:
        raise SystemExit("DATABASE_URL env var required.")

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    openai_client = project.get_openai_client()
    vs_id = _get_or_create_vector_store(openai_client)

    conn = await asyncpg.connect(pg_url)
    results: dict[str, str] = {}

    try:
        sop_files = sorted(sop_dir.glob("*.md"))
        if not sop_files:
            logger.warning("No .md files found in %s", sop_dir)
            return results

        for sop_path in sop_files:
            if sop_path.name.startswith("_"):
                logger.info("Skipping template file: %s", sop_path.name)
                continue

            filename = sop_path.name
            new_hash = compute_sop_hash(sop_path)

            existing = await conn.fetchrow(
                "SELECT foundry_file_id, content_hash FROM sops WHERE foundry_filename = $1",
                filename,
            )

            if existing and existing["content_hash"] == new_hash:
                logger.info("Skipping unchanged SOP: %s", filename)
                results[filename] = "skipped"
                continue

            # Delete old Foundry file if updating
            if existing and existing.get("foundry_file_id"):
                try:
                    openai_client.vector_stores.files.delete(
                        vector_store_id=vs_id,
                        file_id=existing["foundry_file_id"],
                    )
                    logger.info("Deleted old Foundry file for %s", filename)
                except Exception as exc:
                    logger.warning("Could not delete old file for %s: %s", filename, exc)

            # Upload new version
            front_matter = parse_sop_front_matter(sop_path)
            with open(sop_path, "rb") as f:
                uploaded = openai_client.vector_stores.files.upload_and_poll(
                    vector_store_id=vs_id,
                    file=f,
                    filename=filename,
                )
            new_file_id = uploaded.id

            # Upsert PostgreSQL row
            await conn.execute(
                """INSERT INTO sops
                       (title, domain, scenario_tags, foundry_filename, foundry_file_id,
                        content_hash, version, description, severity_threshold,
                        resource_types, is_generic, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now())
                   ON CONFLICT (foundry_filename) DO UPDATE SET
                       title = EXCLUDED.title,
                       domain = EXCLUDED.domain,
                       scenario_tags = EXCLUDED.scenario_tags,
                       foundry_file_id = EXCLUDED.foundry_file_id,
                       content_hash = EXCLUDED.content_hash,
                       version = EXCLUDED.version,
                       description = EXCLUDED.description,
                       severity_threshold = EXCLUDED.severity_threshold,
                       resource_types = EXCLUDED.resource_types,
                       is_generic = EXCLUDED.is_generic,
                       updated_at = now()
                """,
                front_matter.get("title", filename),
                front_matter.get("domain", ""),
                front_matter.get("scenario_tags", []),
                filename,
                new_file_id,
                new_hash,
                str(front_matter.get("version", "1.0")),
                front_matter.get("description", ""),
                front_matter.get("severity_threshold", "P2"),
                front_matter.get("resource_types", []),
                bool(front_matter.get("is_generic", False)),
            )

            action = "updated" if existing else "created"
            results[filename] = action
            logger.info("  %s (%s)", filename, action)

    finally:
        await conn.close()

    # Write SOP_VECTOR_STORE_ID to .env.sops for reference
    env_file = Path(".env.sops")
    env_file.write_text(f"SOP_VECTOR_STORE_ID={vs_id}\n")
    logger.info("SOP_VECTOR_STORE_ID=%s written to .env.sops", vs_id)

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = asyncio.run(upload_sops())
    print("\nSOP upload results:")
    for name, action in results.items():
        print(f"  {name}: {action}")
    print(f"\nTotal: {len(results)} SOPs processed")
