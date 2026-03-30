"""Detection plane pipeline flow — classify_domain() mock-based tests (CONCERNS 3.1).

Tests classify_domain() with known ARM resource types.
Import-safe: classify_domain.py has no Azure SDK at module level.
"""
from __future__ import annotations

import pytest

from classify_domain import classify_domain


class TestPipelineFlow:
    """Tests for the detect -> classify pipeline."""

    def test_classify_domain_compute_resource(self) -> None:
        """classify_domain maps compute resource types to 'compute' domain."""
        result = classify_domain("Microsoft.Compute/virtualMachines")
        assert result == "compute"

    def test_classify_domain_network_resource(self) -> None:
        """classify_domain maps network resource types to 'network' domain."""
        result = classify_domain("Microsoft.Network/virtualNetworks")
        assert result == "network"

    def test_classify_domain_storage_resource(self) -> None:
        """classify_domain maps storage resource types to 'storage' domain."""
        result = classify_domain("Microsoft.Storage/storageAccounts")
        assert result == "storage"

    def test_classify_domain_arc_resource(self) -> None:
        """classify_domain maps Arc resource types to 'arc' domain."""
        result = classify_domain("Microsoft.HybridCompute/machines")
        assert result == "arc"

    def test_classify_domain_unknown_returns_fallback(self) -> None:
        """classify_domain returns 'sre' for unknown resource types."""
        result = classify_domain("Microsoft.Unknown/resources")
        assert result == "sre"

    def test_classify_domain_empty_string_returns_fallback(self) -> None:
        """classify_domain handles empty string input gracefully."""
        result = classify_domain("")
        assert isinstance(result, str)
        assert len(result) > 0
