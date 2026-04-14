"""Unit tests for classify_domain() (DETECT-002).

These tests validate the Python mirror of the KQL classify_domain() function.
Both implementations MUST produce identical results for the same inputs.
"""
from __future__ import annotations

import pytest

from classify_domain import DOMAIN_MAPPINGS, FALLBACK_DOMAIN, VALID_DOMAINS, classify_domain


class TestClassifyDomainExactMatches:
    """Test exact ARM resource_type -> domain mappings."""

    @pytest.mark.parametrize(
        "resource_type,expected_domain",
        [
            ("Microsoft.Compute/virtualMachines", "compute"),
            ("Microsoft.Compute/virtualMachineScaleSets", "compute"),
            ("Microsoft.Compute/disks", "compute"),
            ("Microsoft.Network/networkSecurityGroups", "network"),
            ("Microsoft.Network/virtualNetworks", "network"),
            ("Microsoft.Network/loadBalancers", "network"),
            ("Microsoft.Network/applicationGateways", "network"),
            ("Microsoft.Storage/storageAccounts", "storage"),
            ("Microsoft.Storage/blobServices", "storage"),
            ("Microsoft.KeyVault/vaults", "security"),
            ("Microsoft.HybridCompute/machines", "arc"),
            ("Microsoft.Kubernetes/connectedClusters", "arc"),
        ],
    )
    def test_exact_match(self, resource_type: str, expected_domain: str) -> None:
        assert classify_domain(resource_type) == expected_domain


class TestClassifyDomainPrefixMatches:
    """Test prefix-based matching for broad categories."""

    @pytest.mark.parametrize(
        "resource_type,expected_domain",
        [
            ("Microsoft.Security/alerts", "security"),
            ("Microsoft.Security/assessments", "security"),
            ("Microsoft.AzureArcData/sqlManagedInstances", "arc"),
            ("Microsoft.AzureArcData/postgresInstances", "arc"),
        ],
    )
    def test_prefix_match(self, resource_type: str, expected_domain: str) -> None:
        assert classify_domain(resource_type) == expected_domain


class TestClassifyDomainCaseInsensitive:
    """Test that classification is case-insensitive (KQL has_any is case-insensitive)."""

    @pytest.mark.parametrize(
        "resource_type,expected_domain",
        [
            ("microsoft.compute/virtualmachines", "compute"),
            ("MICROSOFT.COMPUTE/VIRTUALMACHINES", "compute"),
            ("Microsoft.NETWORK/virtualNetworks", "network"),
            ("microsoft.hybridcompute/machines", "arc"),
        ],
    )
    def test_case_insensitive(self, resource_type: str, expected_domain: str) -> None:
        assert classify_domain(resource_type) == expected_domain


class TestClassifyDomainFallback:
    """Test SRE fallback for unrecognized resource types (D-06)."""

    @pytest.mark.parametrize(
        "resource_type",
        [
            "Microsoft.ContainerService/managedClusters",
            "Microsoft.Web/sites",
            "Microsoft.Sql/servers",
            "Microsoft.DocumentDB/databaseAccounts",
            "UnknownProvider/unknownResource",
            "",
        ],
    )
    def test_fallback_to_sre(self, resource_type: str) -> None:
        assert classify_domain(resource_type) == "sre"

    def test_none_like_empty_returns_sre(self) -> None:
        """Empty string should return sre, not raise."""
        assert classify_domain("") == "sre"


class TestClassifyDomainConstants:
    """Test that constants are correctly defined."""

    def test_fallback_domain_is_sre(self) -> None:
        assert FALLBACK_DOMAIN == "sre"

    def test_valid_domains_complete(self) -> None:
        # Phase 49 added messaging domain
        assert VALID_DOMAINS == {"compute", "network", "storage", "security", "arc", "sre", "messaging"}

    def test_all_mappings_produce_valid_domains(self) -> None:
        for resource_type, domain in DOMAIN_MAPPINGS.items():
            assert domain in VALID_DOMAINS, f"{resource_type} maps to invalid domain {domain}"

    def test_classify_domain_always_returns_valid_domain(self) -> None:
        """classify_domain() must always return a value in VALID_DOMAINS."""
        test_inputs = [
            "Microsoft.Compute/virtualMachines",
            "Microsoft.Unknown/resource",
            "",
            "totally-invalid",
        ]
        for resource_type in test_inputs:
            result = classify_domain(resource_type)
            assert result in VALID_DOMAINS, f"classify_domain({resource_type!r}) returned {result!r}"
