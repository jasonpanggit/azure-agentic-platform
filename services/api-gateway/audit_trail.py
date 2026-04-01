"""Audit trail — dual write to Cosmos DB + Fabric OneLake (AUDIT-002).

Every approval state transition is written to:
1. Cosmos DB approvals container (hot-path query) — blocking, must succeed
2. Fabric OneLake (long-term retention >= 2 years) — non-blocking, fire-and-forget

OneLake failures are logged but never block the approval flow.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

ONELAKE_ENDPOINT = os.environ.get("ONELAKE_ENDPOINT", "")
ONELAKE_CONTAINER = os.environ.get("ONELAKE_AUDIT_CONTAINER", "audit-approvals")


async def write_audit_record(approval_record: dict) -> None:
    """Write an approval audit record to OneLake (non-blocking).

    Cosmos DB write is assumed to be already done by the caller.
    This function handles the async OneLake write.
    """
    approval_id = approval_record.get("id", "unknown")
    logger.info("audit: writing record to OneLake | approval_id=%s", approval_id)
    try:
        await _write_to_onelake(approval_record)
        logger.info("audit: record written | approval_id=%s", approval_id)
    except Exception as exc:
        logger.error(
            "OneLake audit write failed for approval %s (non-blocking): %s",
            approval_record.get("id", "unknown"),
            exc,
        )


async def _write_to_onelake(record: dict) -> None:
    """Write an audit record to Fabric OneLake as a JSON file."""
    if not ONELAKE_ENDPOINT:
        logger.debug("ONELAKE_ENDPOINT not configured; skipping OneLake write")
        return

    from azure.identity import DefaultAzureCredential
    from azure.storage.filedatalake import DataLakeServiceClient

    credential = DefaultAzureCredential()
    service_client = DataLakeServiceClient(
        account_url=ONELAKE_ENDPOINT,
        credential=credential,
    )

    file_system_client = service_client.get_file_system_client(ONELAKE_CONTAINER)
    now = datetime.now(timezone.utc)
    file_path = (
        f"approvals/{now.strftime('%Y/%m/%d')}/"
        f"{record.get('id', 'unknown')}.json"
    )

    file_client = file_system_client.get_file_client(file_path)
    data = json.dumps(record, default=str).encode("utf-8")
    logger.info(
        "onelake: writing audit record | approval_id=%s path=%s",
        record.get("id"),
        file_path,
    )
    file_client.upload_data(data, overwrite=True)

    logger.info(
        "Audit record %s written to OneLake at %s",
        record.get("id"),
        file_path,
    )
