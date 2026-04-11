"""Foundry vector store provisioning for SOP files (Phase 30).

Provides provision_sop_vector_store() which creates the Foundry-managed
vector store 'aap-sops-v1' and uploads SOP markdown files.

IMPORTANT: This module is called exclusively by scripts/upload_sops.py.
Do NOT import provision_sop_vector_store from agent runtime code.
The vector store ID is stored as SOP_VECTOR_STORE_ID env var after first run.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SOP_VECTOR_STORE_NAME = "aap-sops-v1"


def provision_sop_vector_store(project: object, sop_files: list[Path]) -> str:
    """Upload SOP markdown files to a Foundry-managed vector store.

    Creates the vector store 'aap-sops-v1', then uploads each SOP file
    using the Foundry vector_stores API. The vector store lives in
    Microsoft-managed storage — no Azure Storage Account needed.

    Called exclusively by scripts/upload_sops.py.

    Args:
        project: Authenticated AIProjectClient (azure-ai-projects 2.0.x).
        sop_files: List of Path objects pointing to .md SOP files.

    Returns:
        Vector store ID string (e.g. "vs_abc123"). Store as SOP_VECTOR_STORE_ID.
    """
    openai = project.get_openai_client()

    logger.info("Creating Foundry vector store '%s'", SOP_VECTOR_STORE_NAME)
    vs = openai.vector_stores.create(name=SOP_VECTOR_STORE_NAME)
    logger.info("Vector store created: %s", vs.id)

    for sop_path in sop_files:
        logger.info("Uploading SOP file: %s", sop_path.name)
        with open(sop_path, "rb") as f:
            openai.vector_stores.files.upload_and_poll(
                vector_store_id=vs.id,
                file=f,
                filename=sop_path.name,
            )
        logger.info("  uploaded %s", sop_path.name)

    logger.info(
        "SOP vector store ready: %s (%d files)", vs.id, len(sop_files)
    )
    return vs.id
