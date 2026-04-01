"""Structured logging setup for all AAP agent containers."""
from __future__ import annotations

import contextlib
import logging
import os
import time
from typing import Any, Generator, Optional


def setup_logging(agent_name: str) -> logging.Logger:
    """Configure structured logging for an agent container.

    Reads LOG_LEVEL from environment (default: INFO).
    Format: timestamp level logger_name message — machine-readable for Azure Monitor.

    Logs startup config (env var presence, NOT values) so Container Apps log
    stream shows what the agent loaded.

    Args:
        agent_name: Short agent name for the root logger context (e.g., "compute").

    Returns:
        A Logger instance for the calling module.
    """
    level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,  # override any existing basicConfig
    )
    logger = logging.getLogger(f"aiops.{agent_name}")

    # Log startup configuration (env var presence, not values)
    _env_vars = [
        "AZURE_PROJECT_ENDPOINT",
        "AZURE_CLIENT_ID",
        "ORCHESTRATOR_AGENT_ID",
        "COSMOS_ENDPOINT",
        "LOG_ANALYTICS_WORKSPACE_ID",
        "DIAGNOSTIC_PIPELINE_ENABLED",
        "LOG_LEVEL",
    ]
    for var in _env_vars:
        val = os.environ.get(var)
        if val:
            # Log presence, not value (some may be sensitive)
            logger.info("startup: %s=set", var)
        else:
            logger.debug("startup: %s=not_set", var)

    logger.info("aiops.%s: logging configured | level=%s", agent_name, level_str)
    return logger


@contextlib.contextmanager
def log_azure_call(
    logger: logging.Logger,
    operation: str,
    resource: Optional[str] = None,
    **kwargs: Any,
) -> Generator[None, None, None]:
    """Context manager that logs Azure SDK call duration and outcome.

    Usage:
        with log_azure_call(logger, "activity_log.list", resource=resource_id):
            result = client.activity_logs.list(filter=...)

    Logs:
        DEBUG azure_call: starting | operation={} resource={}
        INFO  azure_call: complete | operation={} duration_ms={}
        ERROR azure_call: failed | operation={} resource={} error={} duration_ms={}

    Args:
        logger: Logger instance.
        operation: Short operation name (e.g., "metrics.list", "cosmos.upsert").
        resource: Optional resource identifier for context.
        **kwargs: Additional fields to include in log lines.
    """
    start = time.monotonic()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
    resource_str = f" resource={resource}" if resource else ""
    logger.debug(
        "azure_call: starting | operation=%s%s%s",
        operation,
        resource_str,
        f" {extra}" if extra else "",
    )
    try:
        yield
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "azure_call: complete | operation=%s%s duration_ms=%.0f%s",
            operation,
            resource_str,
            duration_ms,
            f" {extra}" if extra else "",
        )
    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "azure_call: failed | operation=%s%s error=%s duration_ms=%.0f%s",
            operation,
            resource_str,
            exc,
            duration_ms,
            f" {extra}" if extra else "",
            exc_info=True,
        )
        raise
