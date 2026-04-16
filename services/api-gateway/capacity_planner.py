"""Capacity Planning Engine — linear regression, quota headroom, and IP space (Phase 57).

Architecture:
- Pure-Python linear regression engine (no numpy/statsmodels)
- _linear_regression, _days_to_exhaustion, _traffic_light: pure functions
- CapacityPlannerClient: quota headroom + IP space headroom + Cosmos snapshots
- run_capacity_sweep_loop: asyncio background task (daily sweep)

All Azure SDK calls never raise — structured error dicts returned instead.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDK availability guards (module-level lazy imports)
# ---------------------------------------------------------------------------

try:
    from azure.mgmt.compute import ComputeManagementClient
    _COMPUTE_IMPORT_ERROR: str = ""
except Exception as _e:
    ComputeManagementClient = None  # type: ignore[assignment,misc]
    _COMPUTE_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.network import NetworkManagementClient
    _NETWORK_IMPORT_ERROR: str = ""
except Exception as _e:
    NetworkManagementClient = None  # type: ignore[assignment,misc]
    _NETWORK_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest
    _ARG_IMPORT_ERROR: str = ""
except Exception as _e:
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]
    _ARG_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.storage import StorageManagementClient
    _STORAGE_IMPORT_ERROR: str = ""
except Exception as _e:
    StorageManagementClient = None  # type: ignore[assignment,misc]
    _STORAGE_IMPORT_ERROR = str(_e)

# ---------------------------------------------------------------------------
# Environment config
# ---------------------------------------------------------------------------

CAPACITY_SWEEP_ENABLED: bool = os.environ.get("CAPACITY_SWEEP_ENABLED", "true").lower() == "true"
CAPACITY_SWEEP_INTERVAL_SECONDS: int = int(os.environ.get("CAPACITY_SWEEP_INTERVAL_SECONDS", "86400"))
CAPACITY_DEFAULT_LOCATION: str = os.environ.get("CAPACITY_DEFAULT_LOCATION", "eastus")
COSMOS_CAPACITY_SNAPSHOTS_CONTAINER: str = os.environ.get(
    "COSMOS_CAPACITY_SNAPSHOTS_CONTAINER", "capacity_snapshots"
)
COSMOS_DATABASE: str = os.environ.get("COSMOS_DATABASE", "aap")


def _log_sdk_availability() -> None:
    """Log SDK availability status at module load time."""
    if _COMPUTE_IMPORT_ERROR:
        logger.warning("capacity_planner: azure-mgmt-compute unavailable: %s", _COMPUTE_IMPORT_ERROR)
    else:
        logger.debug("capacity_planner: azure-mgmt-compute available")
    if _NETWORK_IMPORT_ERROR:
        logger.warning("capacity_planner: azure-mgmt-network unavailable: %s", _NETWORK_IMPORT_ERROR)
    else:
        logger.debug("capacity_planner: azure-mgmt-network available")
    if _ARG_IMPORT_ERROR:
        logger.warning("capacity_planner: azure-mgmt-resourcegraph unavailable: %s", _ARG_IMPORT_ERROR)
    else:
        logger.debug("capacity_planner: azure-mgmt-resourcegraph available")
    if _STORAGE_IMPORT_ERROR:
        logger.warning("capacity_planner: azure-mgmt-storage unavailable: %s", _STORAGE_IMPORT_ERROR)
    else:
        logger.debug("capacity_planner: azure-mgmt-storage available")


_log_sdk_availability()

# ---------------------------------------------------------------------------
# ARG query constant
# ---------------------------------------------------------------------------

ARG_SUBNET_QUERY = """
Resources
| where type == "microsoft.network/virtualnetworks"
| mv-expand subnets = properties.subnets
| project vnetName=name, resourceGroup=resourceGroup,
    subnetName=tostring(subnets.name),
    addressPrefix=tostring(subnets.properties.addressPrefix),
    ipConfigCount=toint(array_length(subnets.properties.ipConfigurations))
| order by vnetName asc, subnetName asc
"""


# ---------------------------------------------------------------------------
# Pure-Python linear regression
# ---------------------------------------------------------------------------

def _linear_regression(x: List[float], y: List[float]) -> tuple[float, float, float]:
    """Compute linear regression slope, intercept, and R².

    Args:
        x: Independent variable values (e.g., day indices).
        y: Dependent variable values (e.g., usage percentages).

    Returns:
        Tuple of (slope, intercept, r_squared).
        Returns (0.0, y[-1] if y else 0.0, 0.0) for fewer than 2 points.
    """
    n = len(x)
    if n < 2:
        return (0.0, float(y[-1]) if y else 0.0, 0.0)

    x_mean = sum(x) / n
    y_mean = sum(y) / n

    numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    if denominator == 0.0:
        return (0.0, y_mean, 0.0)

    slope = numerator / denominator
    intercept = y_mean - slope * x_mean

    # R²: 1 - SS_res / SS_tot
    ss_res = sum((y[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
    ss_tot = sum((y[i] - y_mean) ** 2 for i in range(n))
    r_sq = 1.0 - ss_res / ss_tot if ss_tot != 0.0 else 0.0

    return (slope, intercept, max(0.0, r_sq))


def _regression_ci(
    x: List[float],
    y: List[float],
    slope: float,
    intercept: float,
) -> tuple[float, float]:
    """Compute ±90% confidence interval as percentage of intercept.

    Args:
        x: Independent variable values.
        y: Dependent variable values.
        slope: Regression slope.
        intercept: Regression intercept.

    Returns:
        Tuple of (ci_upper_pct, ci_lower_pct).
    """
    n = len(x)
    if n < 2 or intercept == 0.0:
        return (0.0, 0.0)

    residuals = [y[i] - (slope * x[i] + intercept) for i in range(n)]
    mean_residual = sum(residuals) / n
    std_residual = (sum((r - mean_residual) ** 2 for r in residuals) / n) ** 0.5

    denom = max(1, abs(intercept))
    ci_upper_pct = round((mean_residual + 1.645 * std_residual) / denom * 100, 2)
    ci_lower_pct = round((mean_residual - 1.645 * std_residual) / denom * 100, 2)
    return (ci_upper_pct, ci_lower_pct)


def _days_to_exhaustion(
    current_pct: float,
    slope_per_day: float,
    limit: float = 100.0,
) -> Optional[float]:
    """Estimate days until usage percentage reaches limit.

    Args:
        current_pct: Current usage percentage.
        slope_per_day: Growth rate per day (percentage points).
        limit: Exhaustion threshold (default 100.0%).

    Returns:
        Days to exhaustion (capped at 365), or None if not trending toward exhaustion.
    """
    if current_pct >= limit:
        return None
    if slope_per_day <= 0:
        return None
    days = (limit - current_pct) / slope_per_day
    if days > 365:
        return None
    return round(days, 1)


def _traffic_light(usage_pct: float, days_to_exhaustion: Optional[float]) -> str:
    """Compute traffic light status based on usage and days to exhaustion.

    Args:
        usage_pct: Current usage percentage.
        days_to_exhaustion: Days until exhaustion, or None.

    Returns:
        "red", "yellow", or "green".
    """
    if (days_to_exhaustion is not None and days_to_exhaustion < 30) or usage_pct >= 90:
        return "red"
    if (days_to_exhaustion is not None and days_to_exhaustion < 90) or usage_pct >= 75:
        return "yellow"
    return "green"


# ---------------------------------------------------------------------------
# CapacityPlannerClient
# ---------------------------------------------------------------------------

class CapacityPlannerClient:
    """Manages capacity planning: quota headroom, IP space headroom, and Cosmos snapshots."""

    def __init__(
        self,
        cosmos_client: Any,
        credential: Any,
        subscription_id: str,
        location: str = CAPACITY_DEFAULT_LOCATION,
    ) -> None:
        self._cosmos = cosmos_client
        self.credential = credential
        self.subscription_id = subscription_id
        self.location = location
        self._container: Optional[Any] = None

    def _get_container(self) -> Any:
        """Return Cosmos capacity_snapshots container client (lazy init)."""
        if self._container is None:
            db = self._cosmos.get_database_client(COSMOS_DATABASE)
            self._container = db.get_container_client(COSMOS_CAPACITY_SNAPSHOTS_CONTAINER)
        return self._container

    def _get_snapshots(self, quota_name: str, days: int = 90) -> List[Dict[str, Any]]:
        """Query Cosmos for historical snapshots for a given quota.

        Args:
            quota_name: Quota identifier (e.g., "cores").
            days: Number of days of history to retrieve.

        Returns:
            List of snapshot documents, empty on error or unavailability.
        """
        if self._cosmos is None:
            return []
        try:
            container = self._get_container()
            from datetime import timedelta as _timedelta
            cutoff = (datetime.now(timezone.utc) - _timedelta(days=days)).date().isoformat()
            query = (
                "SELECT * FROM c WHERE c.subscription_id = @sub "
                "AND c.quota_name = @quota AND c.snapshot_date >= @cutoff "
                "ORDER BY c.snapshot_date ASC"
            )
            params = [
                {"name": "@sub", "value": self.subscription_id},
                {"name": "@quota", "value": quota_name},
                {"name": "@cutoff", "value": cutoff},
            ]
            items = list(container.query_items(
                query=query,
                parameters=params,
                partition_key=self.subscription_id,
            ))
            return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]
        except Exception as exc:
            logger.debug("capacity_planner: _get_snapshots error | quota=%s error=%s", quota_name, exc)
            return []

    def _upsert_snapshot(self, doc: Dict[str, Any]) -> None:
        """Upsert a capacity snapshot document to Cosmos.

        Non-fatal — logs warning on failure.
        """
        if self._cosmos is None:
            return
        try:
            container = self._get_container()
            container.upsert_item(doc)
        except Exception as exc:
            logger.warning(
                "capacity_planner: _upsert_snapshot failed (non-fatal) | id=%s error=%s",
                doc.get("id", "?"), exc,
            )

    def _compute_regression_from_snapshots(self, snapshots: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute linear regression from snapshot history.

        Args:
            snapshots: List of snapshot documents with 'usage_pct' field.

        Returns:
            Dict with slope, intercept, r_squared, snapshot_count, and CI bounds.
            Returns fallback zeros if fewer than 3 snapshots.
        """
        fallback: Dict[str, Any] = {
            "slope": 0.0,
            "intercept": 0.0,
            "r_squared": 0.0,
            "snapshot_count": len(snapshots),
            "confidence_interval_upper_pct": 0.0,
            "confidence_interval_lower_pct": 0.0,
        }
        if len(snapshots) < 3:
            return fallback

        x = [float(i) for i in range(len(snapshots))]
        y = [float(s.get("usage_pct", 0.0)) for s in snapshots]
        slope, intercept, r_squared = _linear_regression(x, y)
        ci_upper, ci_lower = _regression_ci(x, y, slope, intercept)

        return {
            "slope": slope,
            "intercept": intercept,
            "r_squared": r_squared,
            "snapshot_count": len(snapshots),
            "confidence_interval_upper_pct": ci_upper,
            "confidence_interval_lower_pct": ci_lower,
        }

    def get_subscription_quota_headroom(self, location: Optional[str] = None) -> Dict[str, Any]:
        """Fetch quota headroom for compute, network, and storage in a subscription.

        Args:
            location: Azure region (defaults to self.location).

        Returns:
            Dict with quotas list, location, subscription_id, generated_at, duration_ms.
            Never raises — returns error dict on failure.
        """
        start_time = time.monotonic()
        loc = location or self.location
        quotas: List[Dict[str, Any]] = []
        warnings: List[str] = []

        try:
            # Compute quotas
            if ComputeManagementClient is not None:
                compute_client = ComputeManagementClient(self.credential, self.subscription_id)
                usages = list(compute_client.usage.list(loc))
                for item in usages:
                    if item.limit <= 0:
                        continue
                    usage_pct = round(item.current_value / item.limit * 100, 2)
                    snapshots = self._get_snapshots(item.name.value)
                    regression = self._compute_regression_from_snapshots(snapshots)
                    days_ex = _days_to_exhaustion(usage_pct, regression["slope"])
                    quotas.append({
                        "quota_name": item.name.value,
                        "display_name": item.name.localized_value,
                        "category": "compute",
                        "current_value": item.current_value,
                        "limit": item.limit,
                        "usage_pct": usage_pct,
                        "available": item.limit - item.current_value,
                        "days_to_exhaustion": days_ex,
                        "traffic_light": _traffic_light(usage_pct, days_ex),
                        "growth_rate_per_day": regression["slope"],
                        "confidence": "high" if regression["r_squared"] >= 0.8 else (
                            "medium" if regression["r_squared"] >= 0.5 else "low"
                        ),
                        "confidence_interval_upper_pct": regression["confidence_interval_upper_pct"],
                        "confidence_interval_lower_pct": regression["confidence_interval_lower_pct"],
                    })
            else:
                warnings.append(f"compute SDK unavailable: {_COMPUTE_IMPORT_ERROR}")

            # Network quotas
            if NetworkManagementClient is not None:
                net_client = NetworkManagementClient(self.credential, self.subscription_id)
                network_usages = list(net_client.usages.list(loc))
                for item in network_usages:
                    if item.limit <= 0:
                        continue
                    usage_pct = round(item.current_value / item.limit * 100, 2)
                    snapshots = self._get_snapshots(item.name.value)
                    regression = self._compute_regression_from_snapshots(snapshots)
                    days_ex = _days_to_exhaustion(usage_pct, regression["slope"])
                    quotas.append({
                        "quota_name": item.name.value,
                        "display_name": item.name.localized_value,
                        "category": "network",
                        "current_value": item.current_value,
                        "limit": item.limit,
                        "usage_pct": usage_pct,
                        "available": item.limit - item.current_value,
                        "days_to_exhaustion": days_ex,
                        "traffic_light": _traffic_light(usage_pct, days_ex),
                        "growth_rate_per_day": regression["slope"],
                        "confidence": "high" if regression["r_squared"] >= 0.8 else (
                            "medium" if regression["r_squared"] >= 0.5 else "low"
                        ),
                        "confidence_interval_upper_pct": regression["confidence_interval_upper_pct"],
                        "confidence_interval_lower_pct": regression["confidence_interval_lower_pct"],
                    })
            else:
                warnings.append(f"network SDK unavailable: {_NETWORK_IMPORT_ERROR}")

            # Storage quotas
            if StorageManagementClient is not None:
                storage_client = StorageManagementClient(self.credential, self.subscription_id)
                storage_usages = list(storage_client.usages.list_by_location(loc))
                for item in storage_usages:
                    if item.limit <= 0:
                        continue
                    usage_pct = round(item.current_value / item.limit * 100, 2)
                    snapshots = self._get_snapshots(item.name.value)
                    regression = self._compute_regression_from_snapshots(snapshots)
                    days_ex = _days_to_exhaustion(usage_pct, regression["slope"])
                    quotas.append({
                        "quota_name": item.name.value,
                        "display_name": item.name.localized_value,
                        "category": "storage",
                        "current_value": item.current_value,
                        "limit": item.limit,
                        "usage_pct": usage_pct,
                        "available": item.limit - item.current_value,
                        "days_to_exhaustion": days_ex,
                        "traffic_light": _traffic_light(usage_pct, days_ex),
                        "growth_rate_per_day": regression["slope"],
                        "confidence": "high" if regression["r_squared"] >= 0.8 else (
                            "medium" if regression["r_squared"] >= 0.5 else "low"
                        ),
                        "confidence_interval_upper_pct": regression["confidence_interval_upper_pct"],
                        "confidence_interval_lower_pct": regression["confidence_interval_lower_pct"],
                    })
            else:
                warnings.append(f"storage SDK unavailable: {_STORAGE_IMPORT_ERROR}")

            result: Dict[str, Any] = {
                "quotas": quotas,
                "location": loc,
                "subscription_id": self.subscription_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }
            if warnings:
                result["warnings"] = warnings
            return result

        except Exception as exc:
            logger.warning("capacity_planner: get_subscription_quota_headroom error | error=%s", exc)
            return {
                "error": str(exc),
                "quotas": [],
                "location": loc,
                "subscription_id": self.subscription_id,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }

    def get_ip_address_space_headroom(self) -> Dict[str, Any]:
        """Fetch IP address space headroom via ARG bulk query.

        Returns:
            Dict with subnets list, subscription_id, generated_at, duration_ms, note.
            Never raises — returns error dict on failure.
        """
        start_time = time.monotonic()

        try:
            if ResourceGraphClient is None or QueryRequest is None:
                return {
                    "error": f"resourcegraph SDK unavailable: {_ARG_IMPORT_ERROR}",
                    "subnets": [],
                    "subscription_id": self.subscription_id,
                    "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                }

            arg_client = ResourceGraphClient(self.credential)
            request = QueryRequest(subscriptions=[self.subscription_id], query=ARG_SUBNET_QUERY)
            result = arg_client.resources(request)
            rows = result.data if result.data else []

            subnets: List[Dict[str, Any]] = []
            for row in rows:
                address_prefix = row.get("addressPrefix", "")
                if not address_prefix:
                    continue
                try:
                    network = ipaddress.ip_network(address_prefix, strict=False)
                    total_ips = network.num_addresses
                except ValueError:
                    continue

                reserved = 5
                ip_config_count = row.get("ipConfigCount") or 0
                available = max(0, total_ips - reserved - ip_config_count)
                usable = max(1, total_ips - reserved)
                usage_pct = round((usable - available) / usable * 100, 2)

                subnets.append({
                    "vnet_name": row.get("vnetName", ""),
                    "resource_group": row.get("resourceGroup", ""),
                    "subnet_name": row.get("subnetName", ""),
                    "address_prefix": address_prefix,
                    "total_ips": total_ips,
                    "reserved_ips": reserved,
                    "ip_config_count": ip_config_count,
                    "available": available,
                    "usage_pct": usage_pct,
                    "traffic_light": _traffic_light(usage_pct, None),
                })

            return {
                "subnets": subnets,
                "subscription_id": self.subscription_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                "note": (
                    "Available IPs = total - 5 (Azure reserved) - attached IP configurations. "
                    "Estimate only."
                ),
            }

        except Exception as exc:
            logger.warning("capacity_planner: get_ip_address_space_headroom error | error=%s", exc)
            return {
                "error": str(exc),
                "subnets": [],
                "subscription_id": self.subscription_id,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }


# ---------------------------------------------------------------------------
# Standalone functions (for agent tool wiring)
# ---------------------------------------------------------------------------

def get_subscription_quota_headroom(
    subscription_id: str,
    location: str,
    credential: Any,
    cosmos_client: Any,
) -> Dict[str, Any]:
    """Standalone wrapper for CapacityPlannerClient.get_subscription_quota_headroom.

    Used by SRE agent tools.
    """
    client = CapacityPlannerClient(
        cosmos_client=cosmos_client,
        credential=credential,
        subscription_id=subscription_id,
        location=location,
    )
    return client.get_subscription_quota_headroom(location)


def get_ip_address_space_headroom(
    subscription_id: str,
    credential: Any,
) -> Dict[str, Any]:
    """Standalone wrapper for CapacityPlannerClient.get_ip_address_space_headroom.

    Used by network agent tools.
    """
    client = CapacityPlannerClient(
        cosmos_client=None,
        credential=credential,
        subscription_id=subscription_id,
    )
    return client.get_ip_address_space_headroom()


# ---------------------------------------------------------------------------
# Daily sweep: sync helper + async loop
# ---------------------------------------------------------------------------

def _run_single_subscription_sweep_sync(
    cosmos_client: Any,
    credential: Any,
    subscription_id: str,
) -> None:
    """Sync sweep for one subscription — fetches quotas and upserts snapshots.

    Designed to be called via run_in_executor from the async sweep loop.
    Non-fatal: logs warnings and returns on any error.
    """
    try:
        client = CapacityPlannerClient(
            cosmos_client=cosmos_client,
            credential=credential,
            subscription_id=subscription_id,
        )
        result = client.get_subscription_quota_headroom()
        quotas = result.get("quotas", [])
        location = result.get("location", CAPACITY_DEFAULT_LOCATION)
        snapshot_date = datetime.now(timezone.utc).date().isoformat()
        created_at = datetime.now(timezone.utc).isoformat()

        for quota in quotas:
            quota_name = quota.get("quota_name", "unknown")
            doc_id = f"{subscription_id}:{location}:{quota_name}:{snapshot_date}"
            doc: Dict[str, Any] = {
                "id": doc_id,
                "subscription_id": subscription_id,
                "location": location,
                "quota_name": quota_name,
                "quota_display_name": quota.get("display_name", quota_name),
                "category": quota.get("category", "unknown"),
                "current_value": quota.get("current_value", 0),
                "limit": quota.get("limit", 0),
                "usage_pct": quota.get("usage_pct", 0.0),
                "snapshot_date": snapshot_date,
                "created_at": created_at,
            }
            client._upsert_snapshot(doc)

        logger.info(
            "capacity_sweep: subscription=%s snapshots_upserted=%d",
            subscription_id, len(quotas),
        )
    except Exception as exc:
        logger.warning(
            "capacity_sweep: _run_single_subscription_sweep_sync failed | "
            "subscription=%s error=%s",
            subscription_id, exc,
        )


async def run_capacity_sweep_loop(
    cosmos_client: Any,
    credential: Any,
    subscription_ids: List[str],
    interval_seconds: int = CAPACITY_SWEEP_INTERVAL_SECONDS,
) -> None:
    """Daily asyncio loop — for each subscription, fetch quota snapshot and upsert to Cosmos.

    If CAPACITY_SWEEP_ENABLED=false, logs and exits immediately.

    Args:
        cosmos_client: CosmosClient instance.
        credential: DefaultAzureCredential.
        subscription_ids: List of subscription IDs to sweep.
        interval_seconds: Sweep interval (default 86400 — daily).
    """
    if not CAPACITY_SWEEP_ENABLED:
        logger.info("capacity_sweep: disabled (CAPACITY_SWEEP_ENABLED=false)")
        return

    logger.info("capacity_sweep: starting loop interval_seconds=%d", interval_seconds)

    while True:
        await asyncio.sleep(interval_seconds)
        for subscription_id in subscription_ids:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    _run_single_subscription_sweep_sync,
                    cosmos_client, credential, subscription_id,
                )
            except asyncio.CancelledError:
                logger.info("capacity_sweep: loop cancelled — shutting down")
                raise
            except Exception as exc:
                logger.warning(
                    "capacity_sweep: subscription=%s error=%s", subscription_id, exc
                )
