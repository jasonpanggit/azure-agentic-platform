"""OS name normalizer for Azure VM and Arc machine image SKU strings.

Converts raw Azure image SKU strings (e.g. "WindowsServer2022-datacenter-g2")
into human-readable OS names (e.g. "Windows Server 2022 Datacenter").

Also provides a VM type classifier based on ARM resource type.

This module is pure Python (stdlib only) with no Azure SDK dependencies.
All functions are deterministic with no side effects.
"""
from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Pre-compiled regex patterns
# ---------------------------------------------------------------------------

# Matches "WindowsServer2022-datacenter*" or "windows server 2022*"
_WIN_SERVER_PATTERN = re.compile(
    r"(?:windows[\s._-]?server[\s._-]?)(\d{4})\s*(R2)?",
    re.IGNORECASE,
)

# Matches bare year-datacenter patterns like "2022-datacenter", "2019-Datacenter"
_WIN_YEAR_DATACENTER_PATTERN = re.compile(
    r"^(\d{4})\s*-?\s*(?:datacenter|dc)",
    re.IGNORECASE,
)

# Matches "win10-*" or "win11-*"
_WIN_CLIENT_PATTERN = re.compile(
    r"^win(\d+)",
    re.IGNORECASE,
)

# Ubuntu patterns: "22_04-lts", "22.04-lts", "ubuntu-22_04", "UbuntuServer 22.04"
_UBUNTU_PATTERN = re.compile(
    r"(?:ubuntu(?:server)?[\s._-]*)?(1[468]|20|22|24)[\s._-]?(0[0-9])[\s._-]?(?:lts)?",
    re.IGNORECASE,
)

# RHEL patterns: "RHEL-*8*", "rhel-8*", etc.
_RHEL_PATTERN = re.compile(
    r"rhel[\s._-]*(\d+)",
    re.IGNORECASE,
)

# SLES patterns: "sles-15*", "SLES 15*"
_SLES_PATTERN = re.compile(
    r"sles[\s._-]*(\d+)",
    re.IGNORECASE,
)

# Debian patterns: "debian-11*", "debian-12*"
_DEBIAN_PATTERN = re.compile(
    r"debian[\s._-]*(\d+)",
    re.IGNORECASE,
)

# CentOS patterns: "centos-7*", "centos-8*"
_CENTOS_PATTERN = re.compile(
    r"centos[\s._-]*(\d+)",
    re.IGNORECASE,
)

# Already-clean string: contains a space and starts uppercase
_ALREADY_CLEAN_PATTERN = re.compile(
    r"^[A-Z][a-zA-Z]+ .+$",
)


def normalize_os(raw: str | None, os_type: str | None = None) -> str:
    """Normalize a raw Azure image SKU string into a human-readable OS name.

    Args:
        raw: Raw OS version string from ARG (e.g. image SKU, osName, osSku).
        os_type: Fallback OS type ("Windows" or "Linux") when raw is empty.

    Returns:
        Human-readable OS name string. Never returns empty string.
    """
    # 1. Handle None/empty
    if not raw or not raw.strip():
        if os_type:
            return os_type.strip().title()
        return "Unknown"

    raw = raw.strip()

    # 2. Check if already clean (e.g. "Ubuntu 22.04 LTS", "Windows Server 2022 Datacenter")
    #    But exclude known raw patterns that happen to start uppercase with a space
    #    (e.g. "UbuntuServer 22.04", "SLES 15 SP3")
    if _ALREADY_CLEAN_PATTERN.match(raw) and " " in raw:
        # Try Linux patterns first — some "clean-looking" strings are actually raw
        normalized = _try_normalize_linux(raw)
        if normalized:
            return normalized
        return raw

    # 3. Windows patterns
    normalized = _try_normalize_windows(raw)
    if normalized:
        return normalized

    # 4. Linux patterns
    normalized = _try_normalize_linux(raw)
    if normalized:
        return normalized

    # 5. Bare "windows" or "linux"
    if raw.lower() == "windows":
        return "Windows"
    if raw.lower() == "linux":
        return "Linux"

    # 6. Fallback: basic cleanup
    return _basic_cleanup(raw)


def _try_normalize_windows(raw: str) -> Optional[str]:
    """Attempt to normalize a Windows SKU string.

    Returns normalized string or None if not a recognized Windows pattern.
    """
    # "WindowsServer2022-datacenter-g2" -> "Windows Server 2022 Datacenter"
    match = _WIN_SERVER_PATTERN.search(raw)
    if match:
        year = match.group(1)
        r2_suffix = " R2" if match.group(2) else ""
        return f"Windows Server {year}{r2_suffix} Datacenter"

    # "2022-datacenter" -> "Windows Server 2022 Datacenter"
    match = _WIN_YEAR_DATACENTER_PATTERN.match(raw)
    if match:
        year = match.group(1)
        return f"Windows Server {year} Datacenter"

    # "win10-*" -> "Windows 10", "win11-*" -> "Windows 11"
    match = _WIN_CLIENT_PATTERN.match(raw)
    if match:
        version = match.group(1)
        return f"Windows {version}"

    return None


def _try_normalize_linux(raw: str) -> Optional[str]:
    """Attempt to normalize a Linux SKU string.

    Returns normalized string or None if not a recognized Linux pattern.
    """
    # Ubuntu patterns
    match = _UBUNTU_PATTERN.search(raw)
    if match:
        major = match.group(1)
        minor = match.group(2)
        return f"Ubuntu {major}.{minor} LTS"

    # RHEL patterns
    match = _RHEL_PATTERN.search(raw)
    if match:
        major = match.group(1)
        return f"RHEL {major}"

    # SLES patterns
    match = _SLES_PATTERN.search(raw)
    if match:
        major = match.group(1)
        return f"SLES {major}"

    # Debian patterns
    match = _DEBIAN_PATTERN.search(raw)
    if match:
        major = match.group(1)
        return f"Debian {major}"

    # CentOS patterns
    match = _CENTOS_PATTERN.search(raw)
    if match:
        major = match.group(1)
        return f"CentOS {major}"

    return None


def _basic_cleanup(raw: str) -> str:
    """Fallback: replace hyphens/underscores with spaces and title-case."""
    cleaned = raw.replace("-", " ").replace("_", " ")
    # Collapse multiple spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.title() if cleaned else "Unknown"


def get_vm_type(resource_type: str | None) -> str:
    """Classify a VM as 'Azure VM' or 'Arc VM' based on its ARM resource type.

    Args:
        resource_type: The ARM resource type string
            (e.g. "microsoft.compute/virtualmachines" or
            "microsoft.hybridcompute/machines").

    Returns:
        "Azure VM", "Arc VM", or "Unknown".
    """
    if not resource_type:
        return "Unknown"
    rt = resource_type.lower()
    if "hybridcompute" in rt:
        return "Arc VM"
    return "Azure VM"
