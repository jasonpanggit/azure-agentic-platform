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
        Dict mapping filename -> list of errors (empty = valid).
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
