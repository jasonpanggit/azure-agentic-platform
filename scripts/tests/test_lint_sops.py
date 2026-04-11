"""Tests for scripts/lint_sops.py — SOP schema validation."""
from __future__ import annotations

from pathlib import Path

import pytest


VALID_SOP = """---
title: "VM High CPU"
version: "1.0"
domain: compute
scenario_tags:
  - cpu
  - high
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
This SOP covers high CPU on Azure VMs.

## Pre-conditions
- Resource type is VM

## Triage Steps

1. **[DIAGNOSTIC]** Check CPU metrics.
   - *Expected signal:* CPU below 80%.
   - *Abnormal signal:* CPU above 90% for 5 min.

2. **[NOTIFY]** Notify operator.
   - *Channels:* teams, email
   - *Severity:* warning

## Remediation Steps

3. **[REMEDIATION:MEDIUM]** Restart VM if thrashing.
   - *Reversibility:* reversible
   - *Approval message:* "Approve restart of {resource_name}?"

## Escalation
- Escalate to SRE if inconclusive.

## Rollback
- Auto-rollback via WAL.

## References
- KB: https://learn.microsoft.com/
"""


class TestLintSop:
    """Verify lint_sop validates schema correctly."""

    def test_valid_sop_passes(self, tmp_path: Path) -> None:
        sop_file = tmp_path / "vm-high-cpu.md"
        sop_file.write_text(VALID_SOP)

        from scripts.lint_sops import lint_sop

        errors = lint_sop(sop_file)
        assert errors == []

    def test_missing_front_matter_fails(self, tmp_path: Path) -> None:
        sop_file = tmp_path / "bad.md"
        sop_file.write_text("# No front matter")

        from scripts.lint_sops import lint_sop

        errors = lint_sop(sop_file)
        assert len(errors) > 0
        assert any("front matter" in e.lower() for e in errors)

    def test_missing_title_fails(self, tmp_path: Path) -> None:
        sop_file = tmp_path / "bad.md"
        sop_file.write_text(
            "---\ndomain: compute\nversion: '1.0'\n---\n## Description\ntest"
        )

        from scripts.lint_sops import lint_sop

        errors = lint_sop(sop_file)
        assert any("title" in e.lower() for e in errors)

    def test_missing_domain_fails(self, tmp_path: Path) -> None:
        sop_file = tmp_path / "bad.md"
        sop_file.write_text(
            "---\ntitle: Test\nversion: '1.0'\n---\n## Description\ntest"
        )

        from scripts.lint_sops import lint_sop

        errors = lint_sop(sop_file)
        assert any("domain" in e.lower() for e in errors)

    def test_missing_required_sections_fails(self, tmp_path: Path) -> None:
        sop_file = tmp_path / "bad.md"
        sop_file.write_text(
            "---\ntitle: Test\ndomain: compute\nversion: '1.0'\n---\n## Description\nonly description"
        )

        from scripts.lint_sops import lint_sop

        errors = lint_sop(sop_file)
        # Should flag missing Triage Steps, Remediation Steps, Escalation sections
        assert len(errors) > 0

    def test_non_generic_without_resource_types_warns(self, tmp_path: Path) -> None:
        sop_file = tmp_path / "bad.md"
        sop_file.write_text(
            "---\ntitle: Test\ndomain: compute\nversion: '1.0'\nis_generic: false\n---\n"
            "## Description\ntest\n## Triage Steps\n1. **[DIAGNOSTIC]** test\n"
            "## Remediation Steps\n2. **[REMEDIATION:LOW]** test\n"
            "## Escalation\n- escalate\n## Rollback\n- rollback\n## References\n- KB: test"
        )

        from scripts.lint_sops import lint_sop

        errors = lint_sop(sop_file)
        assert any("resource_types" in e.lower() for e in errors)
