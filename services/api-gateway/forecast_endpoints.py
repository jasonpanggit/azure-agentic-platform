from __future__ import annotations
"""Forecast API endpoints — capacity exhaustion forecasts (INTEL-005).

Routes:
  GET /api/v1/forecasts?resource_id=<id>  → ForecastResult for one resource
  GET /api/v1/forecasts/imminent          → list[ForecastResult] (breach_imminent only)

Both endpoints require Entra ID Bearer token (verify_token).
ForecasterClient is accessed via request.app.state.forecaster_client.
"""

import asyncio
import logging
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from services.api_gateway.auth import verify_token
from services.api_gateway.forecaster import FORECAST_BREACH_ALERT_MINUTES
from services.api_gateway.models import ForecastResult, MetricForecast

logger = logging.getLogger(__name__)

router = APIRouter(tags=["forecasts"])


# ---------------------------------------------------------------------------
# Dependency: get ForecasterClient from app.state
# ---------------------------------------------------------------------------


def _get_forecaster_client(request: Request) -> Any:
    """Return the ForecasterClient singleton from app.state.

    Raises HTTP 503 if ForecasterClient was not initialized at startup
    (e.g., COSMOS_ENDPOINT not set or FORECAST_ENABLED=false).
    """
    client = getattr(request.app.state, "forecaster_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Forecast service not available (COSMOS_ENDPOINT not set or FORECAST_ENABLED=false)",
        )
    return client


# ---------------------------------------------------------------------------
# Helpers: doc conversion
# ---------------------------------------------------------------------------


def _docs_to_forecast_result(docs: list[dict]) -> ForecastResult:
    """Convert Cosmos baseline docs for one resource into a ForecastResult.

    Args:
        docs: List of Cosmos baseline documents for a single resource_id.

    Returns:
        ForecastResult with all MetricForecast entries populated.

    Raises:
        ValueError: If docs is empty.
    """
    if not docs:
        raise ValueError("No docs to convert")

    resource_id = docs[0]["resource_id"]
    resource_type = docs[0].get("resource_type", "")
    forecasts: List[MetricForecast] = []

    for doc in docs:
        ttb = doc.get("time_to_breach_minutes")
        forecasts.append(
            MetricForecast(
                metric_name=doc["metric_name"],
                current_value=doc["level"],
                threshold=doc["threshold"],
                trend_per_interval=doc["trend"],
                time_to_breach_minutes=ttb,
                confidence=doc.get("confidence", "low"),
                mape=doc.get("mape", 0.0),
                last_updated=doc["last_updated"],
                breach_imminent=(
                    ttb is not None and ttb < FORECAST_BREACH_ALERT_MINUTES
                ),
            )
        )

    has_imminent = any(f.breach_imminent for f in forecasts)
    return ForecastResult(
        resource_id=resource_id,
        resource_type=resource_type,
        forecasts=forecasts,
        has_imminent_breach=has_imminent,
    )


def _group_docs_by_resource(docs: list[dict]) -> list[ForecastResult]:
    """Group Cosmos baseline docs by resource_id and convert to ForecastResult list.

    Args:
        docs: Flat list of Cosmos baseline docs across multiple resources.

    Returns:
        List of ForecastResult objects, one per unique resource_id.
        Resources that fail conversion are skipped (logged as warning).
    """
    grouped: dict[str, list[dict]] = {}
    for doc in docs:
        rid = doc.get("resource_id", "")
        if rid not in grouped:
            grouped[rid] = []
        grouped[rid].append(doc)

    results: list[ForecastResult] = []
    for resource_docs in grouped.values():
        try:
            results.append(_docs_to_forecast_result(resource_docs))
        except Exception as exc:
            logger.warning(
                "forecasts: group_docs conversion failed | error=%s", exc
            )
    return results


# ---------------------------------------------------------------------------
# Endpoints
# NOTE: /imminent MUST be registered BEFORE the resource-scoped route to
#       prevent FastAPI from interpreting "imminent" as a resource_id value.
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/forecasts/imminent",
    response_model=list[ForecastResult],
)
async def get_imminent_forecasts(
    forecaster_client: Any = Depends(_get_forecaster_client),
    _token: dict = Depends(verify_token),
) -> list[ForecastResult]:
    """Get all resources with at least one metric breach expected within 60 minutes.

    Queries the Cosmos baselines container for documents where
    time_to_breach_minutes < FORECAST_BREACH_ALERT_MINUTES (default 60).
    Results are grouped by resource_id into ForecastResult objects.

    Returns empty list if no breaches are imminent.
    Returns 503 if the forecast service is not initialized.

    Authentication: Entra ID Bearer token required.
    """
    logger.info("forecasts: imminent request")

    loop = asyncio.get_running_loop()
    try:
        docs = await loop.run_in_executor(
            None, forecaster_client.get_all_imminent
        )
    except Exception as exc:
        logger.error(
            "forecasts: get_all_imminent failed | error=%s", exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Forecast query failed: {exc}",
        ) from exc

    results = _group_docs_by_resource(docs)
    logger.info(
        "forecasts: imminent complete | resources=%d", len(results)
    )
    return results


@router.get(
    "/api/v1/forecasts",
    response_model=ForecastResult,
)
async def get_resource_forecasts(
    resource_id: str = Query(
        ...,
        description="Full ARM resource ID to fetch capacity forecasts for",
        min_length=1,
    ),
    forecaster_client: Any = Depends(_get_forecaster_client),
    _token: dict = Depends(verify_token),
) -> ForecastResult:
    """Get all capacity forecasts for a specific resource.

    Returns a ForecastResult containing all metric forecasts for the resource.
    Forecasts are computed by double exponential smoothing (Holt's method)
    over the last 2 hours of Azure Monitor data.

    Returns 404 if no baselines exist for the resource yet (sweep has not
    run for this resource, or the resource type is not in FORECAST_METRICS).
    Returns 503 if the forecast service is not initialized.

    Authentication: Entra ID Bearer token required.
    """
    logger.info(
        "forecasts: resource request | resource_id=%s", resource_id[:80]
    )

    loop = asyncio.get_running_loop()
    try:
        docs = await loop.run_in_executor(
            None, forecaster_client.get_forecasts, resource_id
        )
    except Exception as exc:
        logger.error(
            "forecasts: get_forecasts failed | resource=%s error=%s",
            resource_id[:80], exc, exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Forecast query failed: {exc}",
        ) from exc

    if not docs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No forecast baselines found for resource: {resource_id}",
        )

    try:
        result = _docs_to_forecast_result(docs)
    except Exception as exc:
        logger.error(
            "forecasts: doc conversion failed | resource=%s error=%s",
            resource_id[:80], exc, exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Forecast conversion failed: {exc}",
        ) from exc

    logger.info(
        "forecasts: resource complete | resource_id=%s metrics=%d has_imminent=%s",
        resource_id[:80], len(result.forecasts), result.has_imminent_breach,
    )
    return result
