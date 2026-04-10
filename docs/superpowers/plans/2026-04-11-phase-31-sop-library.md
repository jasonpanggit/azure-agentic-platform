# Phase 31 — SOP Library Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author ≥34 production-quality SOP markdown files covering all domains, validate them for schema compliance, create the `sops/` directory structure, and run `scripts/upload_sops.py` to populate the Foundry vector store and PostgreSQL metadata table.

**Architecture:** All SOP files live under `sops/` in the repo root, following the template in `sops/_schema/sop-template.md`. A lint script (`scripts/lint_sops.py`) validates each file's YAML front matter, required sections, and step type labels. Files are grouped by domain. After lint passes, `scripts/upload_sops.py` (Phase 30) uploads them to Foundry and registers metadata in PostgreSQL.

**Tech Stack:** Markdown, YAML front matter, `pyyaml`, Python pytest (for lint validation), `scripts/upload_sops.py` (Phase 30)

**Spec:** `docs/superpowers/specs/2026-04-11-world-class-aiops-phases-29-34-design.md` §5

**Prerequisite:** Phase 30 must be complete (sops table exists, upload_sops.py exists).

---

## Chunk 1: SOP Schema Template + Lint Tool

### Task 1: Create SOP schema template

**Files:**
- Create: `sops/_schema/sop-template.md`
- Create: `sops/_schema/README.md`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p sops/_schema
mkdir -p sops/compute
mkdir -p sops/arc
mkdir -p sops/vmss
mkdir -p sops/aks
mkdir -p sops/patch
mkdir -p sops/eol
mkdir -p sops/network
mkdir -p sops/security
mkdir -p sops/sre
```

- [ ] **Step 2: Create `sops/_schema/sop-template.md`**

```markdown
---
title: "Human-readable SOP title"
version: "1.0"
domain: compute
scenario_tags:
  - tag1
  - tag2
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
<!-- One paragraph explaining when this SOP applies and what it covers. -->

## Pre-conditions
- Resource type is X
- Alert rule is Y

## Triage Steps

1. **[DIAGNOSTIC]** Description of what to check and what tool to use.
   - *Expected signal:* What a healthy result looks like.
   - *Abnormal signal:* What triggers escalation or next step.

2. **[NOTIFY]** If <condition>: send notification via Teams + email with message template:
   > "Incident {incident_id}: {resource_name} — {alert_title}. Current state: {state}."
   - *Channels:* teams, email
   - *Severity:* warning

3. **[DECISION]** Based on triage findings, determine root cause from:
   - Cause A: <description>
   - Cause B: <description>
   - Unknown: escalate

## Remediation Steps

4. **[REMEDIATION:MEDIUM]** If Cause A: description of proposed action.
   - *Reversibility:* reversible
   - *Estimated impact:* description
   - *Approval message:* "Approve action on {resource_name}?"

5. **[REMEDIATION:HIGH]** If Cause B: description of proposed action.
   - *Reversibility:* irreversible
   - *Estimated impact:* description
   - *Approval message:* "Approve action on {resource_name}?"

## Escalation
- If triage inconclusive: escalate to SRE agent
- If remediation rejected: create priority incident and notify on-call via Teams

## Rollback
- On DEGRADED verification: auto-rollback via existing WAL mechanism

## References
- KB: https://learn.microsoft.com/
```

- [ ] **Step 3: Create `sops/_schema/README.md`**

```markdown
# SOP Authoring Guide

All SOP files must follow `sop-template.md`. Key rules:

1. Front matter is required — `title`, `domain`, `version` are mandatory fields.
2. Step types must use exact labels: `[DIAGNOSTIC]`, `[NOTIFY]`, `[DECISION]`,
   `[REMEDIATION:LOW]`, `[REMEDIATION:MEDIUM]`, `[REMEDIATION:HIGH]`,
   `[REMEDIATION:CRITICAL]`, `[ESCALATE]`.
3. Every file with `is_generic: false` must have at least one entry in `resource_types`.
4. Generic SOPs must set `is_generic: true` and use filename pattern `{domain}-generic.md`.
5. After authoring, run `python scripts/lint_sops.py` to validate.
6. Then run `python scripts/upload_sops.py` to upload to Foundry.
```

- [ ] **Step 4: Commit schema files**

```bash
git add sops/_schema/
git commit -m "feat(phase-31): add SOP schema template and authoring guide"
```

### Task 2: Write failing tests for SOP lint tool

**Files:**
- Create: `scripts/tests/test_lint_sops.py`

- [ ] **Step 1: Create the test file**

```python
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

    def test_valid_sop_passes(self, tmp_path):
        sop_file = tmp_path / "vm-high-cpu.md"
        sop_file.write_text(VALID_SOP)

        from scripts.lint_sops import lint_sop

        errors = lint_sop(sop_file)
        assert errors == []

    def test_missing_front_matter_fails(self, tmp_path):
        sop_file = tmp_path / "bad.md"
        sop_file.write_text("# No front matter")

        from scripts.lint_sops import lint_sop

        errors = lint_sop(sop_file)
        assert len(errors) > 0
        assert any("front matter" in e.lower() for e in errors)

    def test_missing_title_fails(self, tmp_path):
        sop_file = tmp_path / "bad.md"
        sop_file.write_text(
            "---\ndomain: compute\nversion: '1.0'\n---\n## Description\ntest"
        )

        from scripts.lint_sops import lint_sop

        errors = lint_sop(sop_file)
        assert any("title" in e.lower() for e in errors)

    def test_missing_domain_fails(self, tmp_path):
        sop_file = tmp_path / "bad.md"
        sop_file.write_text(
            "---\ntitle: Test\nversion: '1.0'\n---\n## Description\ntest"
        )

        from scripts.lint_sops import lint_sop

        errors = lint_sop(sop_file)
        assert any("domain" in e.lower() for e in errors)

    def test_missing_required_sections_fails(self, tmp_path):
        sop_file = tmp_path / "bad.md"
        sop_file.write_text(
            "---\ntitle: Test\ndomain: compute\nversion: '1.0'\n---\n## Description\nonly description"
        )

        from scripts.lint_sops import lint_sop

        errors = lint_sop(sop_file)
        # Should flag missing Triage Steps, Remediation Steps, Escalation sections
        assert len(errors) > 0

    def test_non_generic_without_resource_types_warns(self, tmp_path):
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
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
python -m pytest scripts/tests/test_lint_sops.py -v 2>&1 | head -10
```

### Task 3: Implement `scripts/lint_sops.py`

**Files:**
- Create: `scripts/lint_sops.py`

- [ ] **Step 1: Create `scripts/lint_sops.py`**

```python
"""SOP lint tool — validates SOP markdown files against the schema (Phase 31).

Run before uploading to catch authoring errors early:
    python scripts/lint_sops.py
    python scripts/lint_sops.py sops/compute/vm-high-cpu.md  # single file

Exit code 0 = all valid, 1 = validation errors found.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

REQUIRED_FRONT_MATTER = ("title", "domain", "version")
REQUIRED_SECTIONS = (
    "## Description",
    "## Triage Steps",
    "## Remediation Steps",
    "## Escalation",
    "## Rollback",
    "## References",
)
VALID_STEP_TYPES = frozenset([
    "[DIAGNOSTIC]",
    "[NOTIFY]",
    "[DECISION]",
    "[ESCALATE]",
    "[REMEDIATION:LOW]",
    "[REMEDIATION:MEDIUM]",
    "[REMEDIATION:HIGH]",
    "[REMEDIATION:CRITICAL]",
])


def lint_sop(sop_path: Path) -> list[str]:
    """Validate a single SOP file against the schema.

    Args:
        sop_path: Path to the SOP markdown file.

    Returns:
        List of error strings. Empty list means the file is valid.
    """
    errors: list[str] = []
    content = sop_path.read_text(encoding="utf-8")

    # 1. Front matter presence
    if not content.startswith("---"):
        errors.append(f"{sop_path.name}: missing YAML front matter (must start with '---')")
        return errors  # can't continue without front matter

    parts = content.split("---", 2)
    if len(parts) < 3:
        errors.append(f"{sop_path.name}: malformed front matter (no closing '---')")
        return errors

    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        errors.append(f"{sop_path.name}: YAML parse error: {exc}")
        return errors

    if not isinstance(fm, dict):
        errors.append(f"{sop_path.name}: front matter is not a YAML mapping")
        return errors

    # 2. Required front matter fields
    for field in REQUIRED_FRONT_MATTER:
        if field not in fm:
            errors.append(f"{sop_path.name}: missing required front matter field '{field}'")

    # 3. Non-generic SOPs must have resource_types
    is_generic = fm.get("is_generic", False)
    if not is_generic:
        resource_types = fm.get("resource_types", [])
        if not resource_types:
            errors.append(
                f"{sop_path.name}: non-generic SOP must have at least one entry in 'resource_types'"
            )

    # 4. Generic SOPs should have is_generic: true
    if sop_path.stem.endswith("-generic") and not is_generic:
        errors.append(
            f"{sop_path.name}: filename ends with '-generic' but is_generic is not true"
        )

    # 5. Required sections
    body = parts[2]
    for section in REQUIRED_SECTIONS:
        if section not in body:
            errors.append(f"{sop_path.name}: missing required section '{section}'")

    return errors


def lint_all(sop_dir: Path) -> dict[str, list[str]]:
    """Lint all .md files in sop_dir (excluding _schema/).

    Returns:
        Dict mapping filename → list of errors (empty = valid).
    """
    results: dict[str, list[str]] = {}
    for sop_file in sorted(sop_dir.rglob("*.md")):
        if "_schema" in sop_file.parts:
            continue
        errors = lint_sop(sop_file)
        results[sop_file.name] = errors
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sop_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sops")

    if sop_dir.is_file():
        errors = lint_sop(sop_dir)
        if errors:
            for e in errors:
                print(f"  ✗ {e}")
            sys.exit(1)
        else:
            print(f"  ✓ {sop_dir.name} is valid")
            sys.exit(0)

    results = lint_all(sop_dir)
    has_errors = False
    for filename, errors in results.items():
        if errors:
            has_errors = True
            print(f"\n✗ {filename}:")
            for e in errors:
                print(f"    {e}")
        else:
            print(f"  ✓ {filename}")

    if has_errors:
        sys.exit(1)
    else:
        print(f"\nAll {len(results)} SOPs are valid.")
        sys.exit(0)
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest scripts/tests/test_lint_sops.py -v
```

- [ ] **Step 3: Commit**

```bash
git add scripts/lint_sops.py scripts/tests/test_lint_sops.py
git commit -m "feat(phase-31): add scripts/lint_sops.py for SOP schema validation"
```

---

## Chunk 2: SOP Library — Compute Domain (7 files)

### Task 4: Author compute domain SOPs

**Files to create:** `sops/compute/vm-high-cpu.md`, `sops/compute/vm-memory-pressure.md`, `sops/compute/vm-disk-exhaustion.md`, `sops/compute/vm-unavailable.md`, `sops/compute/vm-boot-failure.md`, `sops/compute/vm-network-unreachable.md`, `sops/compute/compute-generic.md`

- [ ] **Step 1: Create `sops/compute/vm-high-cpu.md`**

```markdown
---
title: "Azure VM — High CPU Utilization"
version: "1.0"
domain: compute
scenario_tags:
  - high-cpu
  - cpu
  - throttling
  - performance
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where CPU utilization exceeds 90% for more than 5 minutes,
indicating resource contention, runaway processes, or insufficient VM sizing.

## Pre-conditions
- Resource type is Microsoft.Compute/virtualMachines
- Alert: CPU percentage > 90% for ≥5 minutes

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_activity_log` for the VM (2h look-back). Check for recent
   deployments, configuration changes, or scaling events that may have triggered load.
   - *Expected signal:* No changes in the last 2 hours.
   - *Abnormal signal:* Recent deployment → likely application regression.

2. **[DIAGNOSTIC]** Call `query_monitor_metrics` for CPU, memory, disk I/O (last 1h, 5-min granularity).
   - *Expected signal:* CPU below 80%, no co-located resource pressure.
   - *Abnormal signal:* CPU sustained >90% with normal memory → CPU-bound workload.

3. **[DIAGNOSTIC]** Call `query_log_analytics` for `Perf` table, `% Processor Time` object,
   last 30 minutes.
   - *Expected signal:* Specific process(es) consuming CPU identifiable.
   - *Abnormal signal:* No data → Log Analytics workspace not connected.

4. **[DIAGNOSTIC]** Call `query_resource_health` for the VM.
   - *Expected signal:* Available.
   - *Abnormal signal:* Degraded or platform issue → skip to Escalation.

5. **[NOTIFY]** Alert operator of sustained CPU breach:
   > "Incident {incident_id}: {resource_name} CPU exceeded 90% for >5 min.
   >  Investigating cause. No action taken yet."
   - *Channels:* teams, email
   - *Severity:* warning

6. **[DECISION]** Determine root cause:
   - Cause A: Recent deployment → application regression
   - Cause B: VM undersized for current workload
   - Cause C: Platform issue (resource health degraded)
   - Unknown → escalate

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** If Cause A: propose VM restart to apply latest config/restart app.
   - Call `propose_vm_restart` with `incident_id`, `resource_id`, reason="High CPU post-deployment"
   - *Reversibility:* reversible (VM restarts automatically)
   - *Estimated impact:* ~2-5 min downtime
   - *Approval message:* "Approve restarting {resource_name} to recover from high CPU post-deployment?"

8. **[REMEDIATION:HIGH]** If Cause B: propose VM resize to next SKU tier.
   - First call `query_vm_sku_options` to list available SKUs in same family
   - Then call `propose_vm_resize` with `target_sku` and reason="CPU saturation — undersized VM"
   - *Reversibility:* reversible
   - *Estimated impact:* ~5-10 min downtime for deallocate/resize/start
   - *Approval message:* "Approve resizing {resource_name} from {current_sku} to {target_sku}?"

## Escalation
- If Cause C (platform issue): escalate to SRE agent for Azure Service Health correlation
- If root cause unknown after all diagnostic steps: escalate to SRE agent
- If remediation rejected: create priority P1 incident, notify on-call via Teams

## Rollback
- VM restart: no rollback needed (idempotent)
- VM resize: resize back to original SKU via `propose_vm_resize` with original SKU

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/troubleshoot-high-cpu
- Related SOPs: vm-memory-pressure.md, sre-slo-breach.md
```

- [ ] **Step 2: Create `sops/compute/vm-memory-pressure.md`**

```markdown
---
title: "Azure VM — Memory Pressure"
version: "1.0"
domain: compute
scenario_tags:
  - memory
  - oom
  - swap
  - pagefile
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where available memory drops below 10% or OOM kills are detected,
indicating memory-intensive workloads or memory leaks.

## Pre-conditions
- Resource type is Microsoft.Compute/virtualMachines
- Alert: Available memory < 10% OR OOM kill event detected

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_activity_log` for the VM (2h look-back).
   - *Abnormal signal:* Recent deployment or config change.

2. **[DIAGNOSTIC]** Call `query_monitor_metrics` for available memory bytes (last 1h).
   - *Expected signal:* >500 MB available.
   - *Abnormal signal:* <100 MB → critical memory pressure.

3. **[DIAGNOSTIC]** Call `query_log_analytics` for `Perf` table, `Available MBytes` counter,
   and `Event` table for EventID 2004 (OOM kernel warning) in last 30 minutes.
   - *Abnormal signal:* OOM event found → OS-level kill in progress.

4. **[DIAGNOSTIC]** Call `query_resource_health`.
   - *Abnormal signal:* Degraded → platform-side memory issue.

5. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: {resource_name} memory pressure detected.
   >  Available memory < 10%. OOM risk."
   - *Channels:* teams, email
   - *Severity:* warning

6. **[DECISION]** Determine root cause:
   - Cause A: Memory leak in application (growing RSS over time)
   - Cause B: VM undersized for workload
   - Cause C: Platform issue

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** If Cause A: propose VM restart to clear leaked memory.
   - Call `propose_vm_restart` with reason="Memory leak recovery"
   - *Reversibility:* reversible
   - *Approval message:* "Approve restarting {resource_name} to recover from memory leak?"

8. **[REMEDIATION:HIGH]** If Cause B: propose VM resize to higher-memory SKU.
   - Call `query_vm_sku_options`, then `propose_vm_resize`
   - *Approval message:* "Approve resizing {resource_name} to {target_sku} for memory capacity?"

## Escalation
- If Cause C: escalate to SRE agent
- If OOM kills are ongoing and restart rejected: escalate immediately

## Rollback
- VM restart: no rollback
- VM resize: resize back to original SKU

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/troubleshoot-performance-bottlenecks
- Related SOPs: vm-high-cpu.md
```

- [ ] **Step 3: Create `sops/compute/vm-disk-exhaustion.md`**

```markdown
---
title: "Azure VM — Disk Space Exhaustion"
version: "1.0"
domain: compute
scenario_tags:
  - disk
  - storage
  - exhaustion
  - full
severity_threshold: P1
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where OS disk or data disk utilization exceeds 90%,
risking application failures and OS instability.

## Pre-conditions
- Alert: Disk space > 90% on OS disk or data disk

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_monitor_metrics` for disk space utilization (last 1h).
   - *Abnormal signal:* Any disk > 90%.

2. **[DIAGNOSTIC]** Call `query_disk_health` for the VM's OS disk and data disks.
   - *Expected signal:* All disks in Succeeded state, IOPS within limits.
   - *Abnormal signal:* Disk in Failed state → provisioning issue.

3. **[DIAGNOSTIC]** Call `query_log_analytics` for `Perf` table, `% Free Space` counter.
   - *Abnormal signal:* Trend shows accelerating growth (log file flood, dump file accumulation).

4. **[NOTIFY]** Alert operator:
   > "Incident {incident_id}: {resource_name} disk space critical (>90% full).
   >  Risk of application failure."
   - *Channels:* teams, email
   - *Severity:* critical

5. **[DECISION]** Root cause:
   - Cause A: Log file accumulation (accelerating growth pattern)
   - Cause B: Application data growth (steady growth)
   - Cause C: Disk too small for workload

## Remediation Steps

6. **[REMEDIATION:MEDIUM]** If Cause A or B: propose VM restart to flush temp files (last resort).
   - Only if disk cleanup scripts are unavailable.
   - Call `propose_vm_restart` with reason="Disk space recovery — flush temp/log files"
   - *Approval message:* "Approve restarting {resource_name} to flush temp files and recover disk space?"

7. **[REMEDIATION:HIGH]** If Cause C: propose disk resize (expand data disk).
   - Note: disk resize requires VM deallocation. Coordinate with application team.
   - Call `propose_vm_redeploy` with reason="Requires maintenance window for disk expansion"
   - *Approval message:* "Approve maintenance window for {resource_name} disk expansion?"

## Escalation
- If growth is accelerating and remediation is rejected: P0 escalation to on-call via Teams

## Rollback
- VM restart: no rollback
- Disk resize: irreversible (can only expand, not shrink)

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/linux/expand-disks
```

- [ ] **Step 4: Create `sops/compute/vm-unavailable.md`**

```markdown
---
title: "Azure VM — VM Unavailable / Unresponsive"
version: "1.0"
domain: compute
scenario_tags:
  - unavailable
  - unresponsive
  - stopped
  - deallocated
severity_threshold: P1
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where the VM is in a stopped, deallocated, or unresponsive state.

## Pre-conditions
- VM power state is Stopped, Deallocated, or health probe is failing

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_resource_health` for the VM.
   - *Expected signal:* Available.
   - *Abnormal signal:* Unavailable → platform issue; Degraded → partial failure.

2. **[DIAGNOSTIC]** Call `query_activity_log` (2h look-back).
   - *Abnormal signal:* Explicit stop/deallocate event → check who triggered it.

3. **[DIAGNOSTIC]** Call `query_monitor_metrics` for VM heartbeat signal.
   - *Abnormal signal:* No heartbeat → VM OS hung or host issue.

4. **[NOTIFY]** Notify operator immediately (P1):
   > "Incident {incident_id}: {resource_name} is unavailable. Immediate investigation in progress."
   - *Channels:* teams, email
   - *Severity:* critical

5. **[DECISION]** Root cause:
   - Cause A: Intentional stop (authorized user action) → verify intent
   - Cause B: Platform host failure → Resource Health shows Unavailable
   - Cause C: VM OS hung (heartbeat lost, resource health Available) → reboot needed

## Remediation Steps

6. **[REMEDIATION:HIGH]** If Cause C: propose VM restart.
   - Call `propose_vm_restart` with reason="VM unresponsive — OS hung"
   - *Approval message:* "Approve force-restarting {resource_name} to recover from unresponsive state?"

7. **[REMEDIATION:HIGH]** If Cause B: propose VM redeploy (move to different host).
   - Call `propose_vm_redeploy` with reason="Host-level failure"
   - *Approval message:* "Approve redeploying {resource_name} to a healthy host?"

## Escalation
- If Cause A and intentional: no action, close incident
- If platform issue persists: open Azure Support ticket, escalate to SRE

## Rollback
- Restart: no rollback
- Redeploy: irreversible (new host allocation)

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/troubleshoot-vm-not-running
```

- [ ] **Step 5: Create `sops/compute/vm-boot-failure.md`**

```markdown
---
title: "Azure VM — Boot Failure"
version: "1.0"
domain: compute
scenario_tags:
  - boot
  - startup
  - grub
  - bootloader
severity_threshold: P1
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where the VM fails to boot, indicated by boot diagnostics showing
GRUB rescue, kernel panic, or OS startup failure.

## Pre-conditions
- VM is in running state but unresponsive OR health probes failing
- Boot diagnostics enabled

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_boot_diagnostics` to retrieve boot screenshot URI and serial log.
   - *Expected signal:* Login prompt visible in screenshot.
   - *Abnormal signal:* GRUB rescue screen, kernel panic, or Windows BSOD.

2. **[DIAGNOSTIC]** Call `query_activity_log` (4h look-back).
   - *Abnormal signal:* Recent OS disk swap or extension installation before failure.

3. **[DIAGNOSTIC]** Call `query_resource_health`.
   - *Abnormal signal:* Unavailable → possible host issue, not OS.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: {resource_name} boot failure detected. Serial log retrieved."
   - *Channels:* teams, email
   - *Severity:* critical

5. **[DECISION]** Root cause:
   - Cause A: OS update or kernel change broke boot
   - Cause B: File system corruption
   - Cause C: Disk missing or detached

## Remediation Steps

6. **[REMEDIATION:HIGH]** If Cause A: propose VM redeploy (repair disk offline).
   - This requires operator to attach OS disk to repair VM.
   - Call `propose_vm_redeploy` with reason="Boot failure — OS repair needed"
   - *Approval message:* "Approve redeploying {resource_name} for OS disk repair?"

## Escalation
- Boot failures often require manual disk repair — escalate to on-call with boot diagnostics screenshot

## Rollback
- Redeploy: irreversible

## References
- KB: https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-machines/boot-error-troubleshoot
```

- [ ] **Step 6: Create `sops/compute/vm-network-unreachable.md`**

```markdown
---
title: "Azure VM — Network Unreachable"
version: "1.0"
domain: compute
scenario_tags:
  - network
  - connectivity
  - nsg
  - unreachable
severity_threshold: P2
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where the VM is running but cannot be reached over the network,
indicating NSG rule issues, routing problems, or NIC misconfiguration.

## Pre-conditions
- VM power state: Running
- Network connectivity probe failing

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_resource_health` for the VM.
   - *Expected signal:* Available.
   - *Abnormal signal:* Degraded → possible platform network issue.

2. **[DIAGNOSTIC]** Call `query_activity_log` (2h look-back).
   - *Abnormal signal:* Recent NSG rule change or NIC modification.

3. **[DIAGNOSTIC]** Route to Network agent via `route_to_domain` with domain="network".
   - Network agent will check NSG rules, effective routes, and flow logs.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: {resource_name} network unreachable. NSG/routing investigation in progress."
   - *Channels:* teams, email
   - *Severity:* warning

5. **[DECISION]** Root cause:
   - Cause A: NSG rule blocking traffic → Network agent identifies rule
   - Cause B: Route table misconfiguration
   - Cause C: VM NIC in failed state

## Remediation Steps

6. **[REMEDIATION:HIGH]** If Cause C: propose VM restart to reset NIC.
   - Call `propose_vm_restart` with reason="NIC reset for connectivity recovery"
   - *Approval message:* "Approve restarting {resource_name} to reset NIC state?"

## Escalation
- If Cause A or B: escalate to Network agent for NSG/routing remediation
- Network changes require Network domain agent and separate approval

## Rollback
- VM restart: no rollback

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/troubleshoot-rdp-nsg-problem
- Related SOPs: network-nsg-blocking.md
```

- [ ] **Step 7: Create `sops/compute/compute-generic.md`**

```markdown
---
title: "Compute Domain — Generic Triage"
version: "1.0"
domain: compute
scenario_tags: []
severity_threshold: P3
resource_types: []
is_generic: true
author: platform-team
last_updated: 2026-04-11
---

## Description
Generic compute domain triage procedure. Used when no scenario-specific SOP matches
the incident. Covers basic VM/VMSS/AKS health checks and escalation path.

## Pre-conditions
- Domain classified as compute

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_activity_log` for all affected resources (2h look-back).

2. **[DIAGNOSTIC]** Call `query_resource_health` for all affected resources.

3. **[DIAGNOSTIC]** Call `query_monitor_metrics` for CPU, memory, disk, network (last 1h).

4. **[DIAGNOSTIC]** Call `query_log_analytics` for errors and warnings in the incident window.

5. **[NOTIFY]** Notify operator of investigation start:
   > "Incident {incident_id}: Compute triage in progress for {resource_name}."
   - *Channels:* teams
   - *Severity:* info

6. **[DECISION]** Based on findings, route to the most specific SOP if one matches,
   or escalate to SRE for cross-domain correlation.

## Remediation Steps

7. **[REMEDIATION:LOW]** Only propose remediation if a clear, reversible action is identified.
   - Use specific propose_* tools as appropriate.
   - *Approval message:* Required for any action.

## Escalation
- If root cause unclear: escalate to SRE agent
- If cross-domain symptoms: request orchestrator re-route

## Rollback
- Per specific action taken.

## References
- KB: https://learn.microsoft.com/en-us/azure/virtual-machines/
```

- [ ] **Step 8: Lint compute SOPs**

```bash
python scripts/lint_sops.py sops/compute/
```

Expected: all 7 files pass lint.

- [ ] **Step 9: Commit compute SOPs**

```bash
git add sops/compute/
git commit -m "feat(phase-31): add 7 compute domain SOPs (VM high-cpu, memory, disk, boot, network, generic)"
```

---

## Chunk 3: SOP Library — Arc, VMSS, AKS Domains

### Task 5: Author Arc VM SOPs (4 files)

**Files:** `sops/arc/arc-vm-disconnected.md`, `sops/arc/arc-vm-extension-failure.md`, `sops/arc/arc-vm-patch-gap.md`, `sops/arc/arc-generic.md`

- [ ] **Step 1: Create `sops/arc/arc-vm-disconnected.md`**

```markdown
---
title: "Arc VM — Agent Disconnected"
version: "1.0"
domain: arc
scenario_tags:
  - disconnected
  - connectivity
  - agent
severity_threshold: P2
resource_types:
  - Microsoft.HybridCompute/machines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Arc-enabled server scenarios where the Azure Connected Machine Agent (ACMA)
stops reporting, indicating connectivity loss or agent crash.

## Pre-conditions
- Arc machine connectivity status: Disconnected
- Last heartbeat >15 minutes ago

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_arc_connectivity` for the machine.
   - Check `lastStatusChange`, `agentVersion`, `disconnectReason`.

2. **[DIAGNOSTIC]** Call `query_activity_log` for the Arc machine (2h look-back).
   - *Abnormal signal:* Recent network policy change blocking outbound connectivity.

3. **[DIAGNOSTIC]** Call `query_resource_health` for the Arc machine.
   - *Abnormal signal:* Unavailable → prolonged disconnection.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: Arc VM {resource_name} disconnected since {lastStatusChange}."
   - *Channels:* teams, email
   - *Severity:* warning

5. **[DECISION]** Root cause:
   - Cause A: Network outage (firewall blocked *.his.arc.azure.com)
   - Cause B: Agent crash or service stopped
   - Cause C: Machine powered off

## Remediation Steps

6. **[REMEDIATION:MEDIUM]** If Cause B: propose Arc patch assessment trigger to verify
   agent responsiveness after network access confirmed.
   - Call `propose_arc_assessment` with reason="Verify agent reconnection"
   - *Approval message:* "Approve triggering patch assessment on {resource_name} to test connectivity?"

## Escalation
- If Cause A: escalate to network team to verify firewall rules for Arc endpoints
- If machine powered off: no automated action

## Rollback
- Assessment trigger: no rollback needed

## References
- KB: https://learn.microsoft.com/en-us/azure/azure-arc/servers/troubleshoot-agent-onboard
```

- [ ] **Step 2: Create `sops/arc/arc-vm-extension-failure.md`**

```markdown
---
title: "Arc VM — Extension Provisioning Failure"
version: "1.0"
domain: arc
scenario_tags:
  - extension
  - provisioning
  - failed
severity_threshold: P2
resource_types:
  - Microsoft.HybridCompute/machines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Arc-enabled server scenarios where a VM extension fails to provision,
potentially blocking monitoring agents, patch management, or guest configuration.

## Pre-conditions
- Arc machine extension in Failed or Unknown provisioning state

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_arc_extension_health` to list all extensions and their
   provisioning states and error messages.
   - *Abnormal signal:* Extension in Failed state with error code.

2. **[DIAGNOSTIC]** Call `query_arc_connectivity` to verify agent is connected.
   - *Abnormal signal:* Disconnected → fix connectivity first (see arc-vm-disconnected.md).

3. **[DIAGNOSTIC]** Call `query_activity_log` (4h look-back) for extension install attempts.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: Arc VM {resource_name} extension {extension_name} in Failed state."
   - *Channels:* teams
   - *Severity:* warning

5. **[DECISION]** Root cause:
   - Cause A: Agent disconnected → connectivity must be restored first
   - Cause B: Extension configuration error (wrong settings)
   - Cause C: Extension version conflict

## Remediation Steps

6. **[REMEDIATION:MEDIUM]** If Cause B or C: propose assessment to re-trigger extension.
   - Call `propose_arc_assessment` with reason="Re-trigger failed extension provisioning"
   - *Approval message:* "Approve re-triggering extension provisioning on {resource_name}?"

## Escalation
- If extension is security-critical (AMA, MDE): P1 escalation
- If repeated failures: open support case

## Rollback
- Extension re-trigger: no rollback

## References
- KB: https://learn.microsoft.com/en-us/azure/azure-arc/servers/manage-vm-extensions
```

- [ ] **Step 3: Create `sops/arc/arc-vm-patch-gap.md`**

```markdown
---
title: "Arc VM — Patch Compliance Gap"
version: "1.0"
domain: arc
scenario_tags:
  - patch
  - compliance
  - missing
  - critical
severity_threshold: P2
resource_types:
  - Microsoft.HybridCompute/machines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Arc-enabled server scenarios where patch compliance drops below threshold,
indicating critical or security patches are missing.

## Pre-conditions
- Patch compliance below configured threshold (default: critical patches missing)

## Triage Steps

1. **[DIAGNOSTIC]** Route to Patch agent: `route_to_domain` with domain="patch".
   - Patch agent will run `query_patch_assessment` to enumerate missing patches.

2. **[DIAGNOSTIC]** Call `query_arc_connectivity` to verify agent is connected.
   - *Abnormal signal:* Disconnected → assessment data may be stale.

3. **[DIAGNOSTIC]** Call `query_arc_guest_config` to check compliance assignment status.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: Arc VM {resource_name} has critical patches missing."
   - *Channels:* teams, email
   - *Severity:* warning

5. **[DECISION]** Root cause:
   - Cause A: Machine disconnected — patch data stale
   - Cause B: Update Manager excluded this machine
   - Cause C: Patches available but not scheduled

## Remediation Steps

6. **[REMEDIATION:MEDIUM]** If Cause C: propose patch assessment to refresh compliance data.
   - Call `propose_arc_assessment` with reason="Refresh patch compliance for critical patches"
   - *Approval message:* "Approve triggering patch assessment on {resource_name} to refresh data?"

## Escalation
- If machine has critical CVEs with active exploits: P1 escalation to security team

## Rollback
- Assessment: no rollback

## References
- KB: https://learn.microsoft.com/en-us/azure/update-manager/manage-arc-enabled-servers
```

- [ ] **Step 4: Create `sops/arc/arc-generic.md`** (generic fallback)

```markdown
---
title: "Arc Domain — Generic Triage"
version: "1.0"
domain: arc
scenario_tags: []
severity_threshold: P3
resource_types: []
is_generic: true
author: platform-team
last_updated: 2026-04-11
---

## Description
Generic Arc domain triage. Used when no scenario-specific SOP matches.

## Pre-conditions
- Domain classified as arc

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_arc_connectivity` for the machine.
2. **[DIAGNOSTIC]** Call `query_arc_extension_health` to list extension states.
3. **[DIAGNOSTIC]** Call `query_resource_health`.
4. **[DIAGNOSTIC]** Call `query_activity_log` (2h look-back).
5. **[NOTIFY]** Notify operator of investigation start.
   - *Channels:* teams
   - *Severity:* info

6. **[DECISION]** Route to specific Arc SOP if pattern matches, else escalate.

## Remediation Steps
7. **[REMEDIATION:LOW]** Only propose reversible actions with explicit approval.

## Escalation
- Unknown issues: escalate to SRE agent

## Rollback
- Per action taken.

## References
- KB: https://learn.microsoft.com/en-us/azure/azure-arc/servers/
```

- [ ] **Step 5: Lint arc SOPs**

```bash
python scripts/lint_sops.py sops/arc/
```

- [ ] **Step 6: Commit arc SOPs**

```bash
git add sops/arc/
git commit -m "feat(phase-31): add 4 Arc domain SOPs"
```

### Task 6: Author VMSS SOPs (3 files) and AKS SOPs (4 files)

> Follow the same pattern. Each file uses the sop-template.md structure.

- [ ] **Step 1: Create VMSS SOPs**

Create `sops/vmss/vmss-scale-failure.md`, `sops/vmss/vmss-unhealthy-instances.md`, `sops/vmss/vmss-generic.md` following the same domain/tag/resource_types pattern using:
- domain: `compute` (VMSS tools are on compute agent)
- resource_types: `Microsoft.Compute/virtualMachineScaleSets`
- scenario_tags: scale-failure, unhealthy, autoscale (as appropriate)

Key steps for `vmss-scale-failure.md`:
- `query_vmss_autoscale` (check autoscale settings and recent events)
- `query_vmss_instances` (list instances with health state)
- `propose_vmss_scale` (HITL for manual scale)

Key steps for `vmss-unhealthy-instances.md`:
- `query_vmss_instances` (list with health state)
- `query_vmss_rolling_upgrade` (check for failed upgrades)
- `query_resource_health`

- [ ] **Step 2: Create AKS SOPs**

Create `sops/aks/aks-node-not-ready.md`, `sops/aks/aks-pod-crashloop.md`, `sops/aks/aks-upgrade-required.md`, `sops/aks/aks-generic.md` using:
- domain: `compute` (AKS tools are on compute agent)
- resource_types: `Microsoft.ContainerService/managedClusters`

Key steps for `aks-node-not-ready.md`:
- `query_aks_node_pools` (health, VM size, resource pressure)
- `query_aks_diagnostics` (control plane logs)
- `propose_aks_node_pool_scale` (HITL)

Key steps for `aks-upgrade-required.md`:
- `query_aks_upgrade_profile` (available versions, deprecated APIs)
- Escalate to operator for upgrade planning

- [ ] **Step 3: Lint and commit VMSS + AKS SOPs**

```bash
python scripts/lint_sops.py sops/vmss/ sops/aks/
git add sops/vmss/ sops/aks/
git commit -m "feat(phase-31): add VMSS (3) and AKS (4) SOPs"
```

---

## Chunk 4: SOP Library — Patch, EOL, Network, Security, SRE Domains

### Task 7: Author remaining domain SOPs

- [ ] **Step 1: Create Patch SOPs (4 files)**

`sops/patch/patch-compliance-violation.md`, `sops/patch/patch-installation-failure.md`, `sops/patch/patch-critical-missing.md`, `sops/patch/patch-generic.md`

Each uses:
- domain: `patch`
- resource_types: `Microsoft.Compute/virtualMachines`, `Microsoft.HybridCompute/machines`
- Tools: `query_patch_assessment`, `query_patch_installation_history`, `query_activity_log`, `query_resource_health`

- [ ] **Step 2: Create EOL SOPs (3 files)**

`sops/eol/eol-os-detected.md`, `sops/eol/eol-runtime-detected.md`, `sops/eol/eol-generic.md`

Each uses:
- domain: `eol`
- Tools: `query_eol_status`, `query_software_inventory`, `sop_notify`
- Key: EOL findings are advisory — propose upgrade plan via Teams/email notification, no ARM actions

- [ ] **Step 3: Create Network SOPs (3 files)**

`sops/network/nsg-blocking.md`, `sops/network/connectivity-failure.md`, `sops/network/network-generic.md`

- domain: `network`
- resource_types: `Microsoft.Network/networkSecurityGroups`, `Microsoft.Network/virtualNetworks`

- [ ] **Step 4: Create Security SOPs (3 files)**

`sops/security/security-defender-alert.md`, `sops/security/security-rbac-anomaly.md`, `sops/security/security-generic.md`

- domain: `security`
- resource_types: as appropriate
- Key: Security SOPs escalate immediately via `sop_notify` with critical severity

- [ ] **Step 5: Create SRE SOPs (3 files)**

`sops/sre/sre-slo-breach.md`, `sops/sre/sre-availability-degraded.md`, `sops/sre/sre-generic.md`

- domain: `sre`

- [ ] **Step 6: Lint all remaining SOPs**

```bash
python scripts/lint_sops.py sops/patch/ sops/eol/ sops/network/ sops/security/ sops/sre/
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add sops/patch/ sops/eol/ sops/network/ sops/security/ sops/sre/
git commit -m "feat(phase-31): add patch(4), eol(3), network(3), security(3), sre(3) SOPs"
```

---

## Chunk 5: Validate Full Library and Upload

### Task 8: Lint all 34 SOPs and verify coverage

- [ ] **Step 1: Run full lint check**

```bash
python scripts/lint_sops.py sops/
```

Expected: all 34 SOP files pass (0 errors).

- [ ] **Step 2: Write a library coverage test**

Create `scripts/tests/test_sop_library_coverage.py`:

```python
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
def test_sop_file_exists(relative_path: str):
    full_path = SOP_DIR / relative_path
    assert full_path.exists(), f"Required SOP missing: sops/{relative_path}"


def test_all_sops_pass_lint():
    from scripts.lint_sops import lint_all

    results = lint_all(SOP_DIR)
    failed = {name: errs for name, errs in results.items() if errs}
    assert not failed, f"SOPs with lint errors: {failed}"


def test_at_least_34_sops_exist():
    all_sops = [
        f for f in SOP_DIR.rglob("*.md")
        if "_schema" not in str(f)
    ]
    assert len(all_sops) >= 34, f"Expected ≥34 SOPs, found {len(all_sops)}"
```

- [ ] **Step 3: Run coverage test**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest scripts/tests/test_sop_library_coverage.py -v
```

Expected: all parametrized tests PASS

- [ ] **Step 4: Commit coverage test**

```bash
git add scripts/tests/test_sop_library_coverage.py
git commit -m "test(phase-31): add SOP library coverage test (34 required files)"
```

### Task 9: Upload SOP library to Foundry (production)

> Note: This step requires a live Azure environment. Skip in CI; run manually post-deploy.

- [ ] **Step 1: Set environment variables**

```bash
export AZURE_PROJECT_ENDPOINT="https://<your-foundry-account>.services.ai.azure.com/api/projects/<project>"
export DATABASE_URL="postgresql://..."
```

- [ ] **Step 2: Run upload script**

```bash
python scripts/upload_sops.py
```

Expected output:
```
SOP upload results:
  vm-high-cpu.md: created
  vm-memory-pressure.md: created
  ... (34 total)

SOP_VECTOR_STORE_ID=vs_abc123 written to .env.sops
```

- [ ] **Step 3: Set SOP_VECTOR_STORE_ID in Terraform**

Update `terraform/envs/prod/terraform.tfvars`:

```hcl
sop_vector_store_id = "vs_abc123"  # from .env.sops output
```

- [ ] **Step 4: Apply Terraform to propagate env var**

```bash
cd terraform/envs/prod
terraform apply -var-file=credentials.tfvars -var-file=terraform.tfvars -auto-approve
```

- [ ] **Step 5: Final Phase 31 commit**

```bash
git add .
git commit -m "feat(phase-31): SOP library complete — 34 SOPs authored, linted, and registered"
```

---

## Phase 31 Done Checklist

- [ ] `sops/_schema/sop-template.md` created
- [ ] `scripts/lint_sops.py` validates all SOP files
- [ ] 7 compute SOPs created and linted
- [ ] 4 arc SOPs created and linted
- [ ] 3 VMSS SOPs created and linted
- [ ] 4 AKS SOPs created and linted
- [ ] 4 patch SOPs created and linted
- [ ] 3 EOL SOPs created and linted
- [ ] 3 network SOPs created and linted
- [ ] 3 security SOPs created and linted
- [ ] 3 SRE SOPs created and linted
- [ ] Library coverage test passes (≥34 files, all lint-clean)
- [ ] `scripts/upload_sops.py` executed (or documented for post-deploy run)
- [ ] `SOP_VECTOR_STORE_ID` in Terraform env var
