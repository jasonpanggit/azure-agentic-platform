"""Unit tests for os_normalizer module.

Covers all raw image SKU values from the task specification plus edge cases.
Tests both normalize_os() and get_vm_type() functions.

Task: fix/patch-tab-vm-count-and-machine-name (OS normalizer)
"""
from __future__ import annotations

import pytest

from services.api_gateway.os_normalizer import get_vm_type, normalize_os


# ---------------------------------------------------------------------------
# normalize_os: Windows Server patterns
# ---------------------------------------------------------------------------


class TestNormalizeOsWindowsServer:
    """Windows Server SKU normalization."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("WindowsServer2025-datacenter-azure-edition", "Windows Server 2025 Datacenter"),
            ("WindowsServer2025-datacenter-g2", "Windows Server 2025 Datacenter"),
            ("WindowsServer2022-datacenter-g2", "Windows Server 2022 Datacenter"),
            ("WindowsServer2022-datacenter-azure-edition", "Windows Server 2022 Datacenter"),
            ("WindowsServer2022-Datacenter", "Windows Server 2022 Datacenter"),
            ("WindowsServer2019-datacenter-gensecond", "Windows Server 2019 Datacenter"),
            ("WindowsServer2019-Datacenter", "Windows Server 2019 Datacenter"),
            ("WindowsServer2016-Datacenter", "Windows Server 2016 Datacenter"),
            ("WindowsServer2016-datacenter-gensecond", "Windows Server 2016 Datacenter"),
            ("WindowsServer2012R2-Datacenter", "Windows Server 2012 R2 Datacenter"),
        ],
        ids=[
            "2025-azure-edition",
            "2025-g2",
            "2022-g2",
            "2022-azure-edition",
            "2022-datacenter",
            "2019-gensecond",
            "2019-datacenter",
            "2016-datacenter",
            "2016-gensecond",
            "2012R2-datacenter",
        ],
    )
    def test_windows_server_skus(self, raw: str, expected: str) -> None:
        assert normalize_os(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("2019-Datacenter", "Windows Server 2019 Datacenter"),
            ("2022-datacenter", "Windows Server 2022 Datacenter"),
            ("2025-datacenter", "Windows Server 2025 Datacenter"),
        ],
        ids=["2019-bare", "2022-bare", "2025-bare"],
    )
    def test_bare_year_datacenter(self, raw: str, expected: str) -> None:
        assert normalize_os(raw) == expected


# ---------------------------------------------------------------------------
# normalize_os: Windows client patterns
# ---------------------------------------------------------------------------


class TestNormalizeOsWindowsClient:
    """Windows 10/11 client SKU normalization."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("win10-21h2-pro", "Windows 10"),
            ("win11-22h2-ent", "Windows 11"),
            ("win10-enterprise", "Windows 10"),
        ],
        ids=["win10-pro", "win11-ent", "win10-enterprise"],
    )
    def test_windows_client_skus(self, raw: str, expected: str) -> None:
        assert normalize_os(raw) == expected


# ---------------------------------------------------------------------------
# normalize_os: Bare Windows / already normalized
# ---------------------------------------------------------------------------


class TestNormalizeOsWindowsMisc:
    """Bare 'windows' and already-clean Windows strings."""

    def test_bare_windows(self) -> None:
        assert normalize_os("windows") == "Windows"

    def test_bare_windows_uppercase(self) -> None:
        assert normalize_os("Windows") == "Windows"

    def test_already_clean_windows_server(self) -> None:
        """Already-clean strings pass through unchanged."""
        assert normalize_os("Windows Server 2022 Datacenter") == "Windows Server 2022 Datacenter"

    def test_already_clean_windows_with_prefix(self) -> None:
        assert normalize_os("Windows Server 2019 Datacenter") == "Windows Server 2019 Datacenter"

    def test_arc_vm_standard_edition_preserved(self) -> None:
        """Arc VMs report 'Windows Server 2016 Standard' — must not be overwritten to Datacenter."""
        assert normalize_os("Windows Server 2016 Standard") == "Windows Server 2016 Standard"

    def test_arc_vm_standard_2019(self) -> None:
        assert normalize_os("Windows Server 2019 Standard") == "Windows Server 2019 Standard"

    def test_arc_vm_standard_2022(self) -> None:
        assert normalize_os("Windows Server 2022 Standard") == "Windows Server 2022 Standard"

    def test_arc_vm_essentials_edition(self) -> None:
        assert normalize_os("Windows Server 2019 Essentials") == "Windows Server 2019 Essentials"


# ---------------------------------------------------------------------------
# normalize_os: Linux Ubuntu patterns
# ---------------------------------------------------------------------------


class TestNormalizeOsUbuntu:
    """Ubuntu SKU normalization."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("22_04-lts", "Ubuntu 22.04 LTS"),
            ("22.04-lts", "Ubuntu 22.04 LTS"),
            ("ubuntu-22_04", "Ubuntu 22.04 LTS"),
            ("UbuntuServer 22.04", "Ubuntu 22.04 LTS"),
            ("20_04-lts", "Ubuntu 20.04 LTS"),
            ("20.04-lts", "Ubuntu 20.04 LTS"),
            ("18_04-lts", "Ubuntu 18.04 LTS"),
        ],
        ids=[
            "22_04-lts",
            "22.04-lts",
            "ubuntu-22_04",
            "ubuntuserver-22.04",
            "20_04-lts",
            "20.04-lts",
            "18_04-lts",
        ],
    )
    def test_ubuntu_skus(self, raw: str, expected: str) -> None:
        assert normalize_os(raw) == expected

    def test_already_clean_ubuntu(self) -> None:
        assert normalize_os("Ubuntu 22.04 LTS") == "Ubuntu 22.04 LTS"

    def test_ubuntu_24_04(self) -> None:
        assert normalize_os("ubuntu-24_04-lts") == "Ubuntu 24.04 LTS"


# ---------------------------------------------------------------------------
# normalize_os: Linux RHEL patterns
# ---------------------------------------------------------------------------


class TestNormalizeOsRhel:
    """RHEL SKU normalization."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("RHEL-8-gen2", "RHEL 8"),
            ("rhel-8-lvm", "RHEL 8"),
            ("RHEL-9-gen2", "RHEL 9"),
            ("rhel-9-lvm", "RHEL 9"),
            ("RHEL-7-gen2", "RHEL 7"),
        ],
        ids=["rhel8-gen2", "rhel8-lvm", "rhel9-gen2", "rhel9-lvm", "rhel7-gen2"],
    )
    def test_rhel_skus(self, raw: str, expected: str) -> None:
        assert normalize_os(raw) == expected


# ---------------------------------------------------------------------------
# normalize_os: Linux SLES patterns
# ---------------------------------------------------------------------------


class TestNormalizeOsSles:
    """SLES SKU normalization."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("sles-15-sp4", "SLES 15"),
            ("SLES 15 SP3", "SLES 15"),
            ("sles-12-sp5", "SLES 12"),
        ],
        ids=["sles15-sp4", "sles15-sp3", "sles12-sp5"],
    )
    def test_sles_skus(self, raw: str, expected: str) -> None:
        assert normalize_os(raw) == expected


# ---------------------------------------------------------------------------
# normalize_os: Linux Debian patterns
# ---------------------------------------------------------------------------


class TestNormalizeOsDebian:
    """Debian SKU normalization."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("debian-11-gen2", "Debian 11"),
            ("debian-12-gen2", "Debian 12"),
        ],
        ids=["debian11", "debian12"],
    )
    def test_debian_skus(self, raw: str, expected: str) -> None:
        assert normalize_os(raw) == expected


# ---------------------------------------------------------------------------
# normalize_os: Linux CentOS patterns
# ---------------------------------------------------------------------------


class TestNormalizeOsCentos:
    """CentOS SKU normalization."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("centos-8-gen2", "CentOS 8"),
            ("centos-7-gen2", "CentOS 7"),
        ],
        ids=["centos8", "centos7"],
    )
    def test_centos_skus(self, raw: str, expected: str) -> None:
        assert normalize_os(raw) == expected


# ---------------------------------------------------------------------------
# normalize_os: Bare Linux
# ---------------------------------------------------------------------------


class TestNormalizeOsLinuxMisc:
    """Bare 'linux' and other Linux edge cases."""

    def test_bare_linux_lower(self) -> None:
        assert normalize_os("linux") == "Linux"

    def test_bare_linux_title(self) -> None:
        assert normalize_os("Linux") == "Linux"


# ---------------------------------------------------------------------------
# normalize_os: Edge cases
# ---------------------------------------------------------------------------


class TestNormalizeOsEdgeCases:
    """None, empty, whitespace, and fallback behavior."""

    def test_none_returns_unknown(self) -> None:
        assert normalize_os(None) == "Unknown"

    def test_empty_string_returns_unknown(self) -> None:
        assert normalize_os("") == "Unknown"

    def test_whitespace_returns_unknown(self) -> None:
        assert normalize_os("   ") == "Unknown"

    def test_none_with_os_type_windows(self) -> None:
        assert normalize_os(None, os_type="Windows") == "Windows"

    def test_none_with_os_type_linux(self) -> None:
        assert normalize_os(None, os_type="Linux") == "Linux"

    def test_empty_with_os_type(self) -> None:
        assert normalize_os("", os_type="windows") == "Windows"

    def test_none_with_none_os_type(self) -> None:
        assert normalize_os(None, os_type=None) == "Unknown"

    def test_unknown_sku_fallback_cleanup(self) -> None:
        """Unrecognized SKUs get basic cleanup (hyphens to spaces, title-case)."""
        result = normalize_os("some-custom-image")
        assert result == "Some Custom Image"

    def test_unknown_sku_with_underscores(self) -> None:
        result = normalize_os("custom_image_v2")
        assert result == "Custom Image V2"

    def test_whitespace_in_raw_is_stripped(self) -> None:
        assert normalize_os("  windows  ") == "Windows"

    def test_case_insensitivity(self) -> None:
        """Case-insensitive matching for Windows Server patterns."""
        assert normalize_os("windowsserver2022-DATACENTER-G2") == "Windows Server 2022 Datacenter"

    def test_os_type_fallback_with_whitespace(self) -> None:
        assert normalize_os("  ", os_type="  linux  ") == "Linux"


# ---------------------------------------------------------------------------
# normalize_os: Screenshot-specific raw values
# ---------------------------------------------------------------------------


class TestNormalizeOsScreenshotValues:
    """Test exact raw values from the task specification screenshot."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("windows", "Windows"),
            ("WindowsServer2025-datacenter-azure-edition", "Windows Server 2025 Datacenter"),
            ("WindowsServer2022-datacenter-g2", "Windows Server 2022 Datacenter"),
            ("WindowsServer2025-datacenter-g2", "Windows Server 2025 Datacenter"),
            ("WindowsServer2019-datacenter-gensecond", "Windows Server 2019 Datacenter"),
            ("WindowsServer2019-Datacenter", "Windows Server 2019 Datacenter"),
            ("WindowsServer2022-datacenter-g2", "Windows Server 2022 Datacenter"),
        ],
        ids=[
            "screenshot-windows",
            "screenshot-2025-azure-edition",
            "screenshot-2022-g2",
            "screenshot-2025-g2",
            "screenshot-2019-gensecond",
            "screenshot-2019-datacenter",
            "screenshot-2022-g2-dup",
        ],
    )
    def test_screenshot_values(self, raw: str, expected: str) -> None:
        assert normalize_os(raw) == expected


# ---------------------------------------------------------------------------
# normalize_os: KQL strcat(offer, " ", sku) values — Azure VMs
# ---------------------------------------------------------------------------


class TestNormalizeOsStrcatValues:
    """Values produced by KQL strcat(imageReference.offer, " ", imageReference.sku).

    These strings have a space between the offer ("WindowsServer") and the
    SKU year, which triggers the _ALREADY_CLEAN_PATTERN false positive.
    This was the root cause of Azure VMs showing raw OS names in the Patch tab.
    """

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("WindowsServer 2025-datacenter-azure-edition", "Windows Server 2025 Datacenter"),
            ("WindowsServer 2022-datacenter-g2", "Windows Server 2022 Datacenter"),
            ("WindowsServer 2019-datacenter-gensecond", "Windows Server 2019 Datacenter"),
            ("WindowsServer 2019-Datacenter", "Windows Server 2019 Datacenter"),
            ("WindowsServer 2025-datacenter-g2", "Windows Server 2025 Datacenter"),
            ("WindowsServer 2016-Datacenter", "Windows Server 2016 Datacenter"),
            ("WindowsServer 2012-R2-Datacenter", "Windows Server 2012 R2 Datacenter"),
        ],
        ids=[
            "strcat-2025-azure-edition",
            "strcat-2022-g2",
            "strcat-2019-gensecond",
            "strcat-2019-datacenter",
            "strcat-2025-g2",
            "strcat-2016-datacenter",
            "strcat-2012-r2-datacenter",
        ],
    )
    def test_strcat_offer_sku_values(self, raw: str, expected: str) -> None:
        assert normalize_os(raw) == expected


# ---------------------------------------------------------------------------
# get_vm_type
# ---------------------------------------------------------------------------


class TestGetVmType:
    """VM type classification based on ARM resource type."""

    def test_azure_vm(self) -> None:
        assert get_vm_type("microsoft.compute/virtualmachines") == "Azure VM"

    def test_azure_vm_mixed_case(self) -> None:
        assert get_vm_type("Microsoft.Compute/virtualMachines") == "Azure VM"

    def test_arc_vm(self) -> None:
        assert get_vm_type("microsoft.hybridcompute/machines") == "Arc VM"

    def test_arc_vm_mixed_case(self) -> None:
        assert get_vm_type("Microsoft.HybridCompute/machines") == "Arc VM"

    def test_none_returns_unknown(self) -> None:
        assert get_vm_type(None) == "Unknown"

    def test_empty_string_returns_unknown(self) -> None:
        assert get_vm_type("") == "Unknown"

    def test_other_resource_type_returns_azure_vm(self) -> None:
        """Non-hybrid resource types default to Azure VM."""
        assert get_vm_type("microsoft.compute/disks") == "Azure VM"

    def test_arc_in_patch_assessment_type(self) -> None:
        """Arc machine patch assessment resource type also classified correctly."""
        assert get_vm_type("microsoft.hybridcompute/machines/patchassessmentresults") == "Arc VM"
