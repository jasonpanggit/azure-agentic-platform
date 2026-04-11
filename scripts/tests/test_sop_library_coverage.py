"""Tests for SOP library completeness (Phase 31)."""
from __future__ import annotations

from pathlib import Path

import pytest

SOP_DIR = Path("sops")
REQUIRED_FILES = [
    "compute/vm-high-cpu.md",
    "compute/vm-memory-pressure.md",
    "compute/vm-disk-exhaustion.md",
    "compute/vm-unavailable.md",
    "compute/vm-boot-failure.md",
    "compute/vm-network-unreachable.md",
    "compute/compute-generic.md",
    "arc/arc-vm-disconnected.md",
    "arc/arc-vm-extension-failure.md",
    "arc/arc-vm-patch-gap.md",
    "arc/arc-generic.md",
    "vmss/vmss-scale-failure.md",
    "vmss/vmss-unhealthy-instances.md",
    "vmss/vmss-generic.md",
    "aks/aks-node-not-ready.md",
    "aks/aks-pod-crashloop.md",
    "aks/aks-upgrade-required.md",
    "aks/aks-generic.md",
    "patch/patch-compliance-violation.md",
    "patch/patch-installation-failure.md",
    "patch/patch-critical-missing.md",
    "patch/patch-generic.md",
    "eol/eol-os-detected.md",
    "eol/eol-runtime-detected.md",
    "eol/eol-generic.md",
    "network/nsg-blocking.md",
    "network/connectivity-failure.md",
    "network/network-generic.md",
    "security/security-defender-alert.md",
    "security/security-rbac-anomaly.md",
    "security/security-generic.md",
    "sre/sre-slo-breach.md",
    "sre/sre-availability-degraded.md",
    "sre/sre-generic.md",
]


@pytest.mark.parametrize("relative_path", REQUIRED_FILES)
def test_sop_file_exists(relative_path: str) -> None:
    full_path = SOP_DIR / relative_path
    assert full_path.exists(), f"Required SOP missing: sops/{relative_path}"


def test_all_sops_pass_lint() -> None:
    from scripts.lint_sops import lint_all

    results = lint_all(SOP_DIR)
    failed = {name: errs for name, errs in results.items() if errs}
    assert not failed, f"SOPs with lint errors: {failed}"


def test_at_least_34_sops_exist() -> None:
    all_sops = [
        f for f in SOP_DIR.rglob("*.md")
        if "_schema" not in str(f)
    ]
    assert len(all_sops) >= 34, f"Expected >=34 SOPs, found {len(all_sops)}"
