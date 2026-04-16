"""IaC Drift Detector — compares Terraform state against live ARM API (Phase 58).

Architecture:
- DriftDetector: reads tfstate from Azure Blob Storage, compares to live ARM resources
- DriftFinding: dataclass for a single drift observation
- classify_drift_severity: pure function, no side effects
- All Azure SDK calls never raise — structured error dicts returned instead
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDK availability guards (module-level lazy imports)
# ---------------------------------------------------------------------------

try:
    from azure.storage.blob import BlobServiceClient
    _BLOB_IMPORT_ERROR: str = ""
except Exception as _e:
    BlobServiceClient = None  # type: ignore[assignment,misc]
    _BLOB_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.resource import ResourceManagementClient
    _RESOURCE_IMPORT_ERROR: str = ""
except Exception as _e:
    ResourceManagementClient = None  # type: ignore[assignment,misc]
    _RESOURCE_IMPORT_ERROR = str(_e)

# ---------------------------------------------------------------------------
# Environment config
# ---------------------------------------------------------------------------

DRIFT_STATE_STORAGE_ACCOUNT: str = os.environ.get(
    "DRIFT_STATE_STORAGE_ACCOUNT", ""
)
DRIFT_STATE_CONTAINER: str = os.environ.get(
    "DRIFT_STATE_CONTAINER", "terraform-state"
)
DRIFT_STATE_BLOB: str = os.environ.get(
    "DRIFT_STATE_BLOB", "prod.tfstate"
)
COSMOS_DRIFT_CONTAINER: str = os.environ.get(
    "COSMOS_DRIFT_CONTAINER", "drift_findings"
)
COSMOS_DATABASE: str = os.environ.get("COSMOS_DATABASE", "aap")

# Attributes considered critical — drift in these triggers HIGH severity
_CRITICAL_ATTRIBUTE_PATTERNS: List[str] = [
    "sku",
    "location",
    "network_profile",
    "os_profile",
    "admin_password",
    "secret_permissions",
    "access_policies",
    "ip_configurations",
    "subnet_id",
    "address_space",
]


def _log_sdk_availability() -> None:
    """Log SDK availability status at module load time."""
    if _BLOB_IMPORT_ERROR:
        logger.warning("drift_detector: azure-storage-blob unavailable: %s", _BLOB_IMPORT_ERROR)
    else:
        logger.debug("drift_detector: azure-storage-blob available")
    if _RESOURCE_IMPORT_ERROR:
        logger.warning("drift_detector: azure-mgmt-resource unavailable: %s", _RESOURCE_IMPORT_ERROR)
    else:
        logger.debug("drift_detector: azure-mgmt-resource available")


_log_sdk_availability()

# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass
class TerraformResource:
    """A resource extracted from Terraform state."""

    resource_id: str
    resource_type: str
    terraform_type: str
    name: str
    attributes: Dict[str, Any]


@dataclass
class DriftFinding:
    """A single drift observation between Terraform state and live ARM."""

    finding_id: str
    resource_id: str
    resource_type: str
    resource_name: str
    attribute_path: str
    terraform_value: Any
    live_value: Any
    drift_severity: str  # LOW | MEDIUM | HIGH | CRITICAL
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.finding_id,
            "finding_id": self.finding_id,
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "resource_name": self.resource_name,
            "attribute_path": self.attribute_path,
            "terraform_value": self.terraform_value,
            "live_value": self.live_value,
            "drift_severity": self.drift_severity,
            "detected_at": self.detected_at,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def classify_drift_severity(
    attribute_path: str,
    terraform_value: Any,
    live_value: Any,
    resource_deleted: bool = False,
) -> str:
    """Classify drift severity for a given attribute change.

    Args:
        attribute_path: Dot-separated path to the changed attribute.
        terraform_value: Value in Terraform state.
        live_value: Value observed in live ARM API.
        resource_deleted: True if the resource no longer exists.

    Returns:
        Severity string: "CRITICAL", "HIGH", "MEDIUM", or "LOW".
    """
    if resource_deleted:
        return "CRITICAL"

    # Tags and metadata drift → LOW
    path_lower = attribute_path.lower()
    if path_lower.startswith("tags") or path_lower in ("kind", "etag"):
        return "LOW"

    # Critical attribute patterns → HIGH
    for pattern in _CRITICAL_ATTRIBUTE_PATTERNS:
        if pattern in path_lower:
            return "HIGH"

    # Numeric / boolean attribute changes → MEDIUM
    if isinstance(terraform_value, (int, float, bool)) or isinstance(live_value, (int, float, bool)):
        return "MEDIUM"

    return "MEDIUM"


def _flatten_dict(obj: Any, prefix: str = "") -> Dict[str, Any]:
    """Recursively flatten a nested dict to dot-separated keys.

    Args:
        obj: Object to flatten.
        prefix: Current key prefix.

    Returns:
        Flat dict with dot-separated keys.
    """
    result: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                result.update(_flatten_dict(v, new_key))
            else:
                result[new_key] = v
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            new_key = f"{prefix}[{i}]"
            if isinstance(item, (dict, list)):
                result.update(_flatten_dict(item, new_key))
            else:
                result[new_key] = item
    else:
        result[prefix] = obj
    return result


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from an ARM resource ID.

    Args:
        resource_id: Full ARM resource ID.

    Returns:
        Subscription ID string, or empty string if not parseable.
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return resource_id.split("/")[idx + 1]
    except (ValueError, IndexError):
        return ""


def parse_tfstate_resources(tfstate: Dict[str, Any]) -> List[TerraformResource]:
    """Parse Terraform state JSON into TerraformResource objects.

    Args:
        tfstate: Parsed JSON of a .tfstate file.

    Returns:
        List of TerraformResource extracted from all non-data resources.
    """
    resources: List[TerraformResource] = []
    for resource in tfstate.get("resources", []):
        if resource.get("mode") == "data":
            continue  # Skip data sources
        tf_type = resource.get("type", "")
        r_name = resource.get("name", "")
        for instance in resource.get("instances", []):
            attrs = instance.get("attributes", {})
            resource_id = attrs.get("id", "")
            if not resource_id:
                continue
            resources.append(
                TerraformResource(
                    resource_id=resource_id,
                    resource_type=tf_type,
                    terraform_type=tf_type,
                    name=r_name,
                    attributes=attrs,
                )
            )
    return resources


def compare_attributes(
    resource_id: str,
    resource_type: str,
    resource_name: str,
    terraform_attrs: Dict[str, Any],
    live_attrs: Dict[str, Any],
) -> List[DriftFinding]:
    """Compare flattened attribute dicts and produce DriftFindings for differences.

    Args:
        resource_id: ARM resource ID.
        resource_type: Terraform resource type.
        resource_name: Terraform resource name.
        terraform_attrs: Flattened attributes from tfstate.
        live_attrs: Flattened attributes from live ARM.

    Returns:
        List of DriftFinding for each attribute that differs.
    """
    findings: List[DriftFinding] = []
    # Only compare keys that exist in tfstate (authoritative source of intent)
    for attr_path, tf_val in terraform_attrs.items():
        if attr_path in ("id", "timeouts"):
            continue  # Skip non-meaningful meta fields
        live_val = live_attrs.get(attr_path)
        if live_val is None and tf_val is None:
            continue
        # Normalise for comparison: stringify both to handle int/str mismatches
        if str(tf_val) != str(live_val):
            severity = classify_drift_severity(attr_path, tf_val, live_val)
            finding_id = f"drift-{abs(hash(resource_id + attr_path))}"
            findings.append(
                DriftFinding(
                    finding_id=finding_id,
                    resource_id=resource_id,
                    resource_type=resource_type,
                    resource_name=resource_name,
                    attribute_path=attr_path,
                    terraform_value=tf_val,
                    live_value=live_val,
                    drift_severity=severity,
                    description=f"Attribute '{attr_path}' differs: terraform={tf_val!r} live={live_val!r}",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# DriftDetector
# ---------------------------------------------------------------------------


class DriftDetector:
    """Reads Terraform state from Blob Storage and compares to live ARM resources."""

    def __init__(
        self,
        credential: Any,
        cosmos_client: Any,
        storage_account_url: str = "",
        state_container: str = DRIFT_STATE_CONTAINER,
        state_blob: str = DRIFT_STATE_BLOB,
    ) -> None:
        self.credential = credential
        self._cosmos = cosmos_client
        self.storage_account_url = storage_account_url or (
            f"https://{DRIFT_STATE_STORAGE_ACCOUNT}.blob.core.windows.net"
            if DRIFT_STATE_STORAGE_ACCOUNT else ""
        )
        self.state_container = state_container
        self.state_blob = state_blob
        self._drift_container: Optional[Any] = None

    # ------------------------------------------------------------------
    # Cosmos helpers
    # ------------------------------------------------------------------

    def _get_drift_container(self) -> Any:
        """Return Cosmos drift_findings container (lazy init)."""
        if self._drift_container is None:
            db = self._cosmos.get_database_client(COSMOS_DATABASE)
            self._drift_container = db.get_container_client(COSMOS_DRIFT_CONTAINER)
        return self._drift_container

    def _save_findings(self, findings: List[DriftFinding]) -> None:
        """Upsert all DriftFindings to Cosmos. Non-fatal."""
        if self._cosmos is None:
            return
        try:
            container = self._get_drift_container()
            for f in findings:
                container.upsert_item(f.to_dict())
        except Exception as exc:
            logger.warning("drift_detector: _save_findings error | error=%s", exc)

    def _list_findings_from_cosmos(
        self,
        severity: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query Cosmos for stored drift findings."""
        if self._cosmos is None:
            return []
        try:
            container = self._get_drift_container()
            query = "SELECT TOP @limit * FROM c WHERE 1=1"
            params: List[Dict[str, Any]] = [{"name": "@limit", "value": limit}]
            if severity:
                query += " AND c.drift_severity = @severity"
                params.append({"name": "@severity", "value": severity})
            if resource_type:
                query += " AND c.resource_type = @resource_type"
                params.append({"name": "@resource_type", "value": resource_type})
            query += " ORDER BY c.detected_at DESC"
            items = list(container.query_items(query=query, parameters=params))
            return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]
        except Exception as exc:
            logger.warning("drift_detector: _list_findings_from_cosmos error | error=%s", exc)
            return []

    # ------------------------------------------------------------------
    # Tfstate loading
    # ------------------------------------------------------------------

    def _load_tfstate(self) -> Dict[str, Any]:
        """Download and parse Terraform state from Blob Storage.

        Returns:
            Parsed tfstate dict, or empty dict on failure.
        """
        start_time = time.monotonic()
        if BlobServiceClient is None:
            logger.warning("drift_detector: _load_tfstate blob SDK unavailable")
            return {}
        if not self.storage_account_url:
            logger.warning("drift_detector: _load_tfstate no storage account URL configured")
            return {}
        try:
            blob_client = BlobServiceClient(
                self.storage_account_url, credential=self.credential
            )
            container_client = blob_client.get_container_client(self.state_container)
            blob = container_client.get_blob_client(self.state_blob)
            data = blob.download_blob().readall()
            tfstate = json.loads(data)
            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            logger.info(
                "drift_detector: tfstate loaded | resources=%d duration_ms=%s",
                len(tfstate.get("resources", [])), duration_ms,
            )
            return tfstate
        except Exception as exc:
            logger.warning("drift_detector: _load_tfstate error | error=%s", exc)
            return {}

    # ------------------------------------------------------------------
    # Live ARM lookup
    # ------------------------------------------------------------------

    def _get_live_resource(
        self,
        resource_id: str,
        subscription_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a live resource from ARM by resource ID.

        Returns:
            Flattened attribute dict, or None if resource not found.
        """
        if ResourceManagementClient is None:
            return None
        try:
            rm_client = ResourceManagementClient(self.credential, subscription_id)
            # Parse resource type and name from ID
            # /subscriptions/{sub}/resourceGroups/{rg}/providers/{type}/{name}
            parts = resource_id.split("/")
            # Find "providers" segment
            try:
                prov_idx = [p.lower() for p in parts].index("providers")
            except ValueError:
                return None
            api_version = "2021-04-01"
            resource = rm_client.resources.get_by_id(resource_id, api_version=api_version)
            if resource is None:
                return None
            raw: Dict[str, Any] = resource.as_dict() if hasattr(resource, "as_dict") else {}
            props = raw.get("properties", {})
            flat = _flatten_dict(props)
            # Include top-level fields
            for key in ("location", "sku", "kind"):
                val = raw.get(key)
                if val is not None:
                    flat[key] = val
            tags = raw.get("tags") or {}
            for k, v in tags.items():
                flat[f"tags.{k}"] = v
            return flat
        except Exception as exc:
            msg = str(exc).lower()
            if "resourcenotfound" in msg or "not found" in msg or "404" in msg:
                return None  # Resource deleted
            logger.debug("drift_detector: _get_live_resource error | id=%s error=%s", resource_id, exc)
            return None

    # ------------------------------------------------------------------
    # Main scan
    # ------------------------------------------------------------------

    def run_scan(
        self,
        subscription_ids: Optional[List[str]] = None,
        save_to_cosmos: bool = True,
    ) -> Dict[str, Any]:
        """Run a full drift scan: load tfstate, compare to live ARM.

        Args:
            subscription_ids: Explicit list of subscription IDs to scope scan.
            save_to_cosmos: Whether to persist findings to Cosmos DB.

        Returns:
            Dict with findings list, scan metadata, duration_ms.
            Never raises.
        """
        start_time = time.monotonic()
        findings: List[DriftFinding] = []
        warnings: List[str] = []

        try:
            tfstate = self._load_tfstate()
            if not tfstate:
                warnings.append("Terraform state could not be loaded — scan aborted")
                return {
                    "findings": [],
                    "total_findings": 0,
                    "scanned_resources": 0,
                    "warnings": warnings,
                    "scanned_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                }

            tf_resources = parse_tfstate_resources(tfstate)
            scanned = 0

            for tf_resource in tf_resources:
                resource_id = tf_resource.resource_id
                sub_id = _extract_subscription_id(resource_id)
                if not sub_id:
                    continue
                if subscription_ids and sub_id not in subscription_ids:
                    continue

                scanned += 1
                live_attrs = self._get_live_resource(resource_id, sub_id)

                if live_attrs is None:
                    # Resource was deleted — CRITICAL finding
                    finding_id = f"drift-deleted-{abs(hash(resource_id))}"
                    findings.append(
                        DriftFinding(
                            finding_id=finding_id,
                            resource_id=resource_id,
                            resource_type=tf_resource.resource_type,
                            resource_name=tf_resource.name,
                            attribute_path="*",
                            terraform_value="<exists>",
                            live_value="<deleted>",
                            drift_severity="CRITICAL",
                            description=f"Resource {resource_id!r} exists in Terraform state but not in Azure",
                        )
                    )
                else:
                    tf_flat = _flatten_dict(tf_resource.attributes)
                    attr_findings = compare_attributes(
                        resource_id=resource_id,
                        resource_type=tf_resource.resource_type,
                        resource_name=tf_resource.name,
                        terraform_attrs=tf_flat,
                        live_attrs=live_attrs,
                    )
                    findings.extend(attr_findings)

            if save_to_cosmos and findings:
                self._save_findings(findings)

            duration_ms = round((time.monotonic() - start_time) * 1000, 1)
            logger.info(
                "drift_detector: scan complete | resources=%d findings=%d duration_ms=%s",
                scanned, len(findings), duration_ms,
            )
            result: Dict[str, Any] = {
                "findings": [f.to_dict() for f in findings],
                "total_findings": len(findings),
                "scanned_resources": scanned,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration_ms,
            }
            if warnings:
                result["warnings"] = warnings
            return result

        except Exception as exc:
            logger.warning("drift_detector: run_scan error | error=%s", exc)
            return {
                "error": str(exc),
                "findings": [],
                "total_findings": 0,
                "scanned_resources": 0,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }

    def list_findings(
        self,
        severity: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Return stored drift findings from Cosmos DB.

        Args:
            severity: Filter by severity (LOW/MEDIUM/HIGH/CRITICAL).
            resource_type: Filter by Terraform resource type.
            limit: Maximum number of findings to return.

        Returns:
            Dict with findings list and metadata. Never raises.
        """
        start_time = time.monotonic()
        try:
            items = self._list_findings_from_cosmos(severity, resource_type, limit)
            return {
                "findings": items,
                "total": len(items),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }
        except Exception as exc:
            logger.warning("drift_detector: list_findings error | error=%s", exc)
            return {
                "error": str(exc),
                "findings": [],
                "total": 0,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }

    def propose_terraform_fix(self, finding: Dict[str, Any]) -> str:
        """Generate a suggested Terraform HCL diff for a drift finding.

        Args:
            finding: A DriftFinding dict.

        Returns:
            HCL diff string suggesting how to reconcile the drift.
        """
        resource_id = finding.get("resource_id", "unknown")
        attr_path = finding.get("attribute_path", "unknown")
        tf_val = finding.get("terraform_value")
        live_val = finding.get("live_value")
        resource_type = finding.get("resource_type", "azurerm_resource")
        resource_name = finding.get("resource_name", "this")
        severity = finding.get("drift_severity", "MEDIUM")

        if attr_path == "*" and live_val == "<deleted>":
            return (
                f"# CRITICAL: Resource was deleted from Azure\n"
                f"# Resource: {resource_id}\n"
                f"# Option A — re-import the resource:\n"
                f"#   terraform import {resource_type}.{resource_name} {resource_id!r}\n"
                f"# Option B — remove from state if deletion was intentional:\n"
                f"#   terraform state rm {resource_type}.{resource_name}\n"
            )

        return (
            f"# Drift: {severity} severity\n"
            f"# Resource: {resource_id}\n"
            f"# Attribute: {attr_path}\n"
            f"\n"
            f"# In your Terraform configuration for {resource_type}.{resource_name}:\n"
            f"# Change:\n"
            f"#   {attr_path} = {tf_val!r}\n"
            f"# To match live state:\n"
            f"#   {attr_path} = {live_val!r}\n"
            f"#\n"
            f"# Or run 'terraform apply' to push Terraform state back to Azure.\n"
        )
