# Phase 30 — SOP Engine + Teams Notifications Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the SOP engine: provision a Foundry-managed vector store for SOP markdown files, add a PostgreSQL metadata table, implement a per-incident SOP selector, inject grounding instructions into each agent run, add the `sop_notify` tool to all agents, and add 3 new Teams card types for SOP notifications.

**Architecture:** `agents/shared/sop_store.py` handles vector store provisioning (called only by `scripts/upload_sops.py`). `agents/shared/sop_loader.py` does a fast PostgreSQL lookup to select the right SOP filename, then returns a grounding instruction that tells the agent to use `file_search` to retrieve the content. Each domain agent's request handler calls `select_sop_for_incident()` before invoking the Responses API. `sop_notify` is a shared `@ai_function` added to all agents. ACS Email is provisioned for email notifications. Three new Teams card types are added to the bot.

**Tech Stack:** `azure-ai-projects>=2.0.1` (vector stores API via `get_openai_client()`), `asyncpg` (PostgreSQL), `azure-communication-email` (ACS), TypeScript/Teams bot, Python pytest, `pyyaml` (front matter parsing), `hashlib` (SHA-256 content hash)

**Spec:** `docs/superpowers/specs/2026-04-11-world-class-aiops-phases-29-34-design.md` §4

---

## Chunk 1: PostgreSQL Migration — `sops` Table

### Task 1: Write failing migration test

**Files:**
- Create: `services/api-gateway/tests/test_sops_migration.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for the `sops` PostgreSQL migration (Phase 30)."""
from __future__ import annotations

import pytest


class TestSopsMigration:
    """Validate the sops table DDL and indexes."""

    def test_migration_file_exists(self):
        import os

        path = "services/api-gateway/migrations/003_create_sops_table.py"
        assert os.path.exists(path), f"Migration file not found: {path}"

    def test_migration_creates_sops_table(self):
        """Migration SQL must include CREATE TABLE sops."""
        with open("services/api-gateway/migrations/003_create_sops_table.py") as f:
            content = f.read()
        assert "CREATE TABLE sops" in content or "CREATE TABLE IF NOT EXISTS sops" in content

    def test_migration_includes_content_hash_column(self):
        with open("services/api-gateway/migrations/003_create_sops_table.py") as f:
            content = f.read()
        assert "content_hash" in content

    def test_migration_includes_scenario_tags_array(self):
        with open("services/api-gateway/migrations/003_create_sops_table.py") as f:
            content = f.read()
        assert "scenario_tags" in content
        assert "TEXT[]" in content or "text[]" in content

    def test_migration_includes_domain_index(self):
        with open("services/api-gateway/migrations/003_create_sops_table.py") as f:
            content = f.read()
        assert "CREATE INDEX" in content
        assert "domain" in content
```

- [ ] **Step 2: Run test — expect FileNotFoundError**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_sops_migration.py -v 2>&1 | head -15
```

### Task 2: Create `003_create_sops_table.py` migration

**Files:**
- Create: `services/api-gateway/migrations/003_create_sops_table.py`

- [ ] **Step 1: Create the migration file**

```python
"""Migration 003 — Create sops metadata table (Phase 30).

The sops table is a lightweight metadata registry. SOP content lives
entirely in the Foundry vector store (aap-sops-v1). PostgreSQL only
stores the filename, domain, tags, and content hash for fast selection
and idempotent upload.

Run:
    python services/api-gateway/migrations/003_create_sops_table.py
"""
from __future__ import annotations

UP_SQL = """
CREATE TABLE IF NOT EXISTS sops (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title              TEXT NOT NULL,
    domain             TEXT NOT NULL,
    scenario_tags      TEXT[],
    foundry_filename   TEXT NOT NULL UNIQUE,
    foundry_file_id    TEXT,
    content_hash       TEXT,
    version            TEXT NOT NULL DEFAULT '1.0',
    description        TEXT,
    severity_threshold TEXT DEFAULT 'P2',
    resource_types     TEXT[],
    is_generic         BOOLEAN DEFAULT FALSE,
    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sops_domain_generic ON sops (domain, is_generic);
CREATE INDEX IF NOT EXISTS idx_sops_foundry_filename ON sops (foundry_filename);
"""

DOWN_SQL = """
DROP TABLE IF EXISTS sops;
"""


async def up(conn) -> None:
    """Apply migration 003 — create sops table."""
    await conn.execute(UP_SQL)


async def down(conn) -> None:
    """Roll back migration 003 — drop sops table."""
    await conn.execute(DOWN_SQL)


if __name__ == "__main__":
    import asyncio
    import os

    import asyncpg

    async def main() -> None:
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            await up(conn)
            print("Migration 003 applied successfully.")
        finally:
            await conn.close()

    asyncio.run(main())
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_sops_migration.py -v
```

- [ ] **Step 3: Commit**

```bash
git add services/api-gateway/migrations/003_create_sops_table.py \
        services/api-gateway/tests/test_sops_migration.py
git commit -m "feat(phase-30): add sops PostgreSQL migration (003_create_sops_table)"
```

---

## Chunk 2: SOP Store — Foundry Vector Store Provisioning

### Task 3: Write failing tests for `sop_store.py`

**Files:**
- Create: `agents/tests/shared/test_sop_store.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for agents/shared/sop_store.py — Foundry vector store provisioning."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


class TestProvisionSopVectorStore:
    """Verify provision_sop_vector_store creates vector store and uploads files."""

    def _make_project_mock(self):
        mock_project = MagicMock()
        mock_openai = MagicMock()
        mock_vs = MagicMock()
        mock_vs.id = "vs_test_123"
        mock_openai.vector_stores.create.return_value = mock_vs
        mock_openai.vector_stores.files.upload_and_poll.return_value = MagicMock()
        mock_project.get_openai_client.return_value = mock_openai
        return mock_project, mock_openai, mock_vs

    def test_creates_vector_store_with_name(self, tmp_path):
        sop_file = tmp_path / "vm-high-cpu.md"
        sop_file.write_text("# test SOP")

        mock_project, mock_openai, mock_vs = self._make_project_mock()

        from agents.shared.sop_store import provision_sop_vector_store

        result = provision_sop_vector_store(mock_project, [sop_file])

        mock_openai.vector_stores.create.assert_called_once_with(name="aap-sops-v1")

    def test_returns_vector_store_id(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text("# test")

        mock_project, mock_openai, mock_vs = self._make_project_mock()

        from agents.shared.sop_store import provision_sop_vector_store

        result = provision_sop_vector_store(mock_project, [sop_file])
        assert result == "vs_test_123"

    def test_uploads_each_sop_file(self, tmp_path):
        sop1 = tmp_path / "vm-high-cpu.md"
        sop2 = tmp_path / "vm-memory.md"
        sop1.write_text("# SOP 1")
        sop2.write_text("# SOP 2")

        mock_project, mock_openai, mock_vs = self._make_project_mock()

        from agents.shared.sop_store import provision_sop_vector_store

        provision_sop_vector_store(mock_project, [sop1, sop2])

        assert mock_openai.vector_stores.files.upload_and_poll.call_count == 2

    def test_upload_uses_filename_from_path(self, tmp_path):
        sop_file = tmp_path / "vm-high-cpu.md"
        sop_file.write_text("# test")

        mock_project, mock_openai, mock_vs = self._make_project_mock()

        from agents.shared.sop_store import provision_sop_vector_store

        provision_sop_vector_store(mock_project, [sop_file])

        call_kwargs = mock_openai.vector_stores.files.upload_and_poll.call_args
        assert call_kwargs.kwargs.get("filename") == "vm-high-cpu.md" or \
               "vm-high-cpu.md" in str(call_kwargs)

    def test_empty_file_list_creates_empty_store(self, tmp_path):
        mock_project, mock_openai, mock_vs = self._make_project_mock()

        from agents.shared.sop_store import provision_sop_vector_store

        result = provision_sop_vector_store(mock_project, [])
        mock_openai.vector_stores.create.assert_called_once()
        mock_openai.vector_stores.files.upload_and_poll.assert_not_called()
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_sop_store.py -v 2>&1 | head -10
```

### Task 4: Implement `agents/shared/sop_store.py`

**Files:**
- Create: `agents/shared/sop_store.py`

- [ ] **Step 1: Create `agents/shared/sop_store.py`**

```python
"""Foundry vector store provisioning for SOP files (Phase 30).

Provides provision_sop_vector_store() which creates (or reuses) the
Foundry-managed vector store 'aap-sops-v1' and uploads SOP markdown files.

IMPORTANT: This module is called exclusively by scripts/upload_sops.py.
Do NOT import provision_sop_vector_store from agent runtime code.
The vector store ID is stored as SOP_VECTOR_STORE_ID env var after first run.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SOP_VECTOR_STORE_NAME = "aap-sops-v1"


def provision_sop_vector_store(project: object, sop_files: list[Path]) -> str:
    """Upload SOP markdown files to a Foundry-managed vector store.

    Creates the vector store 'aap-sops-v1' if it does not exist, then
    uploads each SOP file using the Foundry vector_stores API. The vector
    store lives in Microsoft-managed storage — no Azure Storage Account needed.

    Called exclusively by scripts/upload_sops.py.

    Args:
        project: Authenticated AIProjectClient (azure-ai-projects 2.0.x).
        sop_files: List of Path objects pointing to .md SOP files.

    Returns:
        Vector store ID string (e.g. "vs_abc123"). Store as SOP_VECTOR_STORE_ID.
    """
    openai = project.get_openai_client()

    logger.info("Creating Foundry vector store '%s'", SOP_VECTOR_STORE_NAME)
    vs = openai.vector_stores.create(name=SOP_VECTOR_STORE_NAME)
    logger.info("Vector store created: %s", vs.id)

    for sop_path in sop_files:
        logger.info("Uploading SOP file: %s", sop_path.name)
        with open(sop_path, "rb") as f:
            openai.vector_stores.files.upload_and_poll(
                vector_store_id=vs.id,
                file=f,
                filename=sop_path.name,   # e.g. "vm-high-cpu.md"
            )
        logger.info("  ✓ uploaded %s", sop_path.name)

    logger.info(
        "SOP vector store ready: %s (%d files)", vs.id, len(sop_files)
    )
    return vs.id
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_sop_store.py -v
```

- [ ] **Step 3: Commit**

```bash
git add agents/shared/sop_store.py agents/tests/shared/test_sop_store.py
git commit -m "feat(phase-30): add sop_store.py for Foundry vector store provisioning"
```

---

## Chunk 3: SOP Loader — Per-Incident Selection

### Task 5: Write failing tests for `sop_loader.py`

**Files:**
- Create: `agents/tests/shared/test_sop_loader.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for agents/shared/sop_loader.py — per-incident SOP selection."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_sop_row(
    filename: str = "vm-high-cpu.md",
    title: str = "VM High CPU",
    version: str = "1.0",
    is_generic: bool = False,
):
    """Build a mock asyncpg row."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "foundry_filename": filename,
        "title": title,
        "version": version,
        "is_generic": is_generic,
    }[key]
    return row


class TestSelectSopForIncident:
    """Verify select_sop_for_incident returns correct SOP and grounding instruction."""

    @pytest.mark.asyncio
    async def test_returns_sop_load_result(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_sop_row()

        incident = {
            "incident_id": "inc-001",
            "alert_title": "CPU high on vm1",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "domain": "compute",
        }

        from agents.shared.sop_loader import SopLoadResult, select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert isinstance(result, SopLoadResult)

    @pytest.mark.asyncio
    async def test_returns_correct_filename(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_sop_row(filename="vm-high-cpu.md")

        incident = {
            "incident_id": "inc-002",
            "alert_title": "CPU high",
            "resource_type": "Microsoft.Compute/virtualMachines",
        }

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert result.foundry_filename == "vm-high-cpu.md"

    @pytest.mark.asyncio
    async def test_falls_back_to_generic_when_no_specific_match(self):
        mock_conn = AsyncMock()
        # First call (specific) returns None, second (generic) returns row
        mock_conn.fetchrow.side_effect = [
            None,
            _make_sop_row(filename="compute-generic.md", is_generic=True),
        ]

        incident = {
            "incident_id": "inc-003",
            "alert_title": "unknown issue",
            "resource_type": "Microsoft.Compute/virtualMachines",
        }

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert result.foundry_filename == "compute-generic.md"
        assert result.is_generic is True

    @pytest.mark.asyncio
    async def test_grounding_instruction_contains_filename(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_sop_row(filename="vm-disk-exhaustion.md")

        incident = {"incident_id": "inc-004", "alert_title": "disk full", "resource_type": ""}

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert "vm-disk-exhaustion.md" in result.grounding_instruction

    @pytest.mark.asyncio
    async def test_grounding_instruction_contains_hitl_warning(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_sop_row()

        incident = {"incident_id": "inc-005", "alert_title": "test", "resource_type": ""}

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert "REMEDIATION" in result.grounding_instruction
        assert "ApprovalRecord" in result.grounding_instruction

    @pytest.mark.asyncio
    async def test_grounding_instruction_marks_generic_fallback(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.side_effect = [
            None,
            _make_sop_row(filename="compute-generic.md", is_generic=True),
        ]

        incident = {"incident_id": "inc-006", "alert_title": "unknown", "resource_type": ""}

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert "GENERIC FALLBACK" in result.grounding_instruction
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_sop_loader.py -v 2>&1 | head -10
```

### Task 6: Implement `agents/shared/sop_loader.py`

**Files:**
- Create: `agents/shared/sop_loader.py`

- [ ] **Step 1: Create `agents/shared/sop_loader.py`**

```python
"""SOP loader — per-incident SOP selection from PostgreSQL metadata table.

Selects the most relevant SOP for an incident using a two-layer lookup:
1. Fast PostgreSQL metadata query (domain + resource_type + tag overlap)
2. If no specific match, falls back to the generic SOP for the domain

The agent then uses its FileSearchTool to retrieve the full SOP content
from the Foundry vector store. No blob storage or direct file reads here.

Usage (in each agent's incident handler):
    from shared.sop_loader import select_sop_for_incident
    sop = await select_sop_for_incident(incident, domain="compute", pg_conn=conn)
    # inject sop.grounding_instruction into the Responses API call
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class SopLoadResult:
    """Result of a SOP selection for an incident."""

    title: str
    version: str
    foundry_filename: str        # e.g. "vm-high-cpu.md"
    is_generic: bool
    grounding_instruction: str   # injected into agent additional_instructions


def _extract_incident_tags(incident: dict[str, Any]) -> list[str]:
    """Extract keyword tags from the incident for SOP tag overlap matching.

    Splits alert_title into lowercase words, filters stop words and
    short tokens. Returns a list of candidate tags.

    Args:
        incident: Incident dict with at least 'alert_title' key.

    Returns:
        List of lowercase keyword strings.
    """
    stop_words = {"the", "a", "an", "is", "on", "in", "at", "of", "and", "or", "for"}
    title = incident.get("alert_title", "")
    resource_type = incident.get("resource_type", "")

    # Extract words from title
    words = re.findall(r"[a-zA-Z]+", title.lower())
    tags = [w for w in words if w not in stop_words and len(w) > 2]

    # Add resource type fragments (e.g. "virtualMachines" → "virtualmachines")
    if resource_type:
        type_fragment = resource_type.split("/")[-1].lower()
        tags.append(type_fragment)

    return list(set(tags))


async def select_sop_for_incident(
    incident: dict[str, Any],
    domain: str,
    pg_conn: Any,   # asyncpg.Connection — typed as Any to avoid hard dependency
) -> SopLoadResult:
    """Select the best SOP for an incident from the PostgreSQL metadata table.

    Selection priority:
    1. Scenario-specific SOP: domain match + resource_type match + highest tag overlap
    2. Generic domain SOP: domain match + is_generic=TRUE

    The selected SOP's grounding_instruction tells the agent to retrieve
    the full content via its FileSearchTool (file_search tool call).

    Args:
        incident: Incident dict with keys: incident_id, alert_title, resource_type.
        domain: Agent domain name (e.g. "compute", "patch", "arc").
        pg_conn: Active asyncpg connection to the platform PostgreSQL database.

    Returns:
        SopLoadResult with grounding_instruction ready for injection.

    Raises:
        ValueError: If no SOP (specific or generic) is found for the domain.
    """
    incident_tags = _extract_incident_tags(incident)
    resource_type = incident.get("resource_type", "")

    # 1. Try to find scenario-specific SOP by domain + resource_type + tag overlap
    row = await pg_conn.fetchrow(
        """SELECT foundry_filename, title, version, is_generic,
                  array_length(
                    ARRAY(SELECT unnest(scenario_tags) INTERSECT SELECT unnest($3::text[])),
                    1
                  ) AS tag_overlap
           FROM sops
           WHERE domain = $1
             AND is_generic = FALSE
             AND ($2 = ANY(resource_types) OR resource_types IS NULL)
           ORDER BY tag_overlap DESC NULLS LAST,
                    array_length(scenario_tags, 1) DESC NULLS LAST
           LIMIT 1""",
        domain,
        resource_type,
        incident_tags,
    )

    if row is None:
        logger.info(
            "No scenario-specific SOP for domain=%s resource_type=%s; falling back to generic",
            domain,
            resource_type,
        )
        row = await pg_conn.fetchrow(
            "SELECT foundry_filename, title, version, is_generic "
            "FROM sops WHERE domain = $1 AND is_generic = TRUE LIMIT 1",
            domain,
        )

    if row is None:
        raise ValueError(
            f"No SOP found for domain '{domain}'. "
            "Run scripts/upload_sops.py to populate the SOP library."
        )

    filename: str = row["foundry_filename"]
    is_generic: bool = row["is_generic"]
    title: str = row["title"]
    version: str = row["version"]

    logger.info(
        "Selected SOP '%s' (v%s, generic=%s) for incident %s",
        filename,
        version,
        is_generic,
        incident.get("incident_id", "?"),
    )

    grounding = _build_grounding_instruction(
        filename=filename,
        title=title,
        version=version,
        is_generic=is_generic,
    )

    return SopLoadResult(
        title=title,
        version=version,
        foundry_filename=filename,
        is_generic=is_generic,
        grounding_instruction=grounding,
    )


def _build_grounding_instruction(
    filename: str,
    title: str,
    version: str,
    is_generic: bool,
) -> str:
    """Build the grounding instruction string injected into the agent run.

    The instruction tells the agent:
    1. Which SOP file to retrieve via file_search
    2. To follow the SOP steps strictly
    3. That every [REMEDIATION] step requires an ApprovalRecord
    4. That every [NOTIFY] step requires calling sop_notify
    """
    generic_note = (
        "\n[GENERIC FALLBACK — no scenario-specific SOP matched for this incident]"
        if is_generic
        else ""
    )

    return f"""
## Active SOP: {title} (v{version}){generic_note}

Use the `file_search` tool to retrieve the full SOP content for file: **{filename}**
Follow every step in that SOP as your primary guide for this incident.

Rules you MUST follow:
- Every [REMEDIATION] step REQUIRES human approval — call `propose_*` tool, never execute directly.
  The propose_* tool creates an ApprovalRecord. Do NOT make any ARM API calls without one.
- Every [NOTIFY] step REQUIRES calling the `sop_notify` tool with channels=["teams","email"].
- Log any step you skip with explicit justification in your response.
- Complete all [DIAGNOSTIC] steps before forming a diagnosis.
"""
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_sop_loader.py -v
```

- [ ] **Step 3: Commit**

```bash
git add agents/shared/sop_loader.py agents/tests/shared/test_sop_loader.py
git commit -m "feat(phase-30): add sop_loader.py for per-incident SOP selection"
```

---

## Chunk 4: `sop_notify` Tool

### Task 7: Write failing tests for `sop_notify`

**Files:**
- Create: `agents/tests/shared/test_sop_notify.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for agents/shared/sop_notify.py — SOP notification tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestSopNotify:
    """Verify sop_notify dispatches to Teams and/or email correctly."""

    @pytest.mark.asyncio
    @patch("agents.shared.sop_notify._send_teams_notification")
    @patch("agents.shared.sop_notify._send_email_notification")
    async def test_sends_teams_when_teams_in_channels(
        self, mock_email, mock_teams
    ):
        mock_teams.return_value = {"ok": True}
        mock_email.return_value = {"ok": True}

        from agents.shared.sop_notify import sop_notify

        result = await sop_notify(
            message="VM cpu is high",
            severity="warning",
            channels=["teams"],
            incident_id="inc-001",
            resource_name="vm1",
            sop_step="Step 2: Notify operator",
        )
        mock_teams.assert_called_once()
        mock_email.assert_not_called()
        assert result["status"] == "sent"

    @pytest.mark.asyncio
    @patch("agents.shared.sop_notify._send_teams_notification")
    @patch("agents.shared.sop_notify._send_email_notification")
    async def test_sends_email_when_email_in_channels(
        self, mock_email, mock_teams
    ):
        mock_email.return_value = {"ok": True}

        from agents.shared.sop_notify import sop_notify

        result = await sop_notify(
            message="test",
            severity="info",
            channels=["email"],
            incident_id="inc-002",
            resource_name="vm2",
            sop_step="Step 3",
        )
        mock_email.assert_called_once()
        mock_teams.assert_not_called()

    @pytest.mark.asyncio
    @patch("agents.shared.sop_notify._send_teams_notification")
    @patch("agents.shared.sop_notify._send_email_notification")
    async def test_sends_both_when_both_channels_specified(
        self, mock_email, mock_teams
    ):
        mock_teams.return_value = {"ok": True}
        mock_email.return_value = {"ok": True}

        from agents.shared.sop_notify import sop_notify

        result = await sop_notify(
            message="critical issue",
            severity="critical",
            channels=["teams", "email"],
            incident_id="inc-003",
            resource_name="vm3",
            sop_step="Step 2",
        )
        mock_teams.assert_called_once()
        mock_email.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.shared.sop_notify._send_teams_notification")
    @patch("agents.shared.sop_notify._send_email_notification")
    async def test_result_contains_sop_step(self, mock_email, mock_teams):
        mock_teams.return_value = {"ok": True}

        from agents.shared.sop_notify import sop_notify

        result = await sop_notify(
            message="test",
            severity="info",
            channels=["teams"],
            incident_id="inc-004",
            resource_name="vm4",
            sop_step="Step 5: escalate",
        )
        assert result["sop_step"] == "Step 5: escalate"

    @pytest.mark.asyncio
    @patch("agents.shared.sop_notify._send_teams_notification")
    @patch("agents.shared.sop_notify._send_email_notification")
    async def test_teams_failure_does_not_raise(self, mock_email, mock_teams):
        """Notification failures are logged but never raised — never fail the agent run."""
        mock_teams.side_effect = Exception("Teams unavailable")

        from agents.shared.sop_notify import sop_notify

        result = await sop_notify(
            message="test",
            severity="warning",
            channels=["teams"],
            incident_id="inc-005",
            resource_name="vm5",
            sop_step="Step 1",
        )
        # Should return error status, not raise
        assert result["status"] in ("partial", "error", "sent")
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_sop_notify.py -v 2>&1 | head -10
```

### Task 8: Implement `agents/shared/sop_notify.py`

**Files:**
- Create: `agents/shared/sop_notify.py`

- [ ] **Step 1: Create `agents/shared/sop_notify.py`**

```python
"""SOP notification tool — dispatches Teams + email notifications (Phase 30).

Provides the `sop_notify` @ai_function that agents call whenever a SOP
step is marked [NOTIFY]. Supports Teams and email channels independently.
Notification failures are logged but never raised — they must not interrupt
the agent's triage workflow.

Add to each agent's tools list:
    from shared.sop_notify import sop_notify
    tools=[..., sop_notify]
"""
from __future__ import annotations

import logging
import os
from typing import Literal

from agent_framework import ai_function

logger = logging.getLogger(__name__)


@ai_function
async def sop_notify(
    message: str,
    severity: Literal["info", "warning", "critical"],
    channels: list[Literal["teams", "email"]],
    incident_id: str,
    resource_name: str,
    sop_step: str,
) -> dict:
    """Send a notification as required by the active SOP.

    Call this whenever the SOP specifies a [NOTIFY] step.
    Always use this tool — never skip notification steps.

    Args:
        message: Human-readable notification message.
        severity: Notification severity level.
        channels: List of channels to notify. Pass ["teams", "email"] for both.
            Valid values: "teams", "email". Do NOT pass "both".
        incident_id: Incident identifier (e.g. "inc-001").
        resource_name: Affected resource name (e.g. "vm-prod-01").
        sop_step: Current SOP step description (e.g. "Step 2: Notify operator").

    Returns:
        Dict with status, channels (results per channel), and sop_step.
    """
    results: dict[str, object] = {}
    any_success = False

    if "teams" in channels:
        try:
            results["teams"] = await _send_teams_notification(
                message=message,
                severity=severity,
                incident_id=incident_id,
                resource_name=resource_name,
                sop_step=sop_step,
            )
            any_success = True
        except Exception as exc:
            logger.warning("sop_notify: Teams notification failed: %s", exc)
            results["teams"] = {"ok": False, "error": str(exc)}

    if "email" in channels:
        try:
            results["email"] = await _send_email_notification(
                message=message,
                severity=severity,
                incident_id=incident_id,
                resource_name=resource_name,
                sop_step=sop_step,
            )
            any_success = True
        except Exception as exc:
            logger.warning("sop_notify: Email notification failed: %s", exc)
            results["email"] = {"ok": False, "error": str(exc)}

    all_failed = all(
        isinstance(v, dict) and v.get("ok") is False for v in results.values()
    )
    status = "error" if all_failed else ("partial" if not any_success else "sent")

    return {"status": status, "channels": results, "sop_step": sop_step}


async def _send_teams_notification(
    message: str,
    severity: str,
    incident_id: str,
    resource_name: str,
    sop_step: str,
) -> dict:
    """Send a SOP notification card to the Teams bot internal endpoint."""
    import httpx

    teams_bot_url = os.environ.get("TEAMS_BOT_INTERNAL_URL", "")
    channel_id = os.environ.get("TEAMS_CHANNEL_ID", "")

    if not teams_bot_url or not channel_id:
        logger.warning("sop_notify: TEAMS_BOT_INTERNAL_URL or TEAMS_CHANNEL_ID not set")
        return {"ok": False, "error": "Teams not configured"}

    payload = {
        "card_type": "sop_notification",
        "channel_id": channel_id,
        "payload": {
            "incident_id": incident_id,
            "resource_name": resource_name,
            "message": message,
            "severity": severity,
            "sop_step": sop_step,
        },
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{teams_bot_url}/teams/internal/notify",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def _send_email_notification(
    message: str,
    severity: str,
    incident_id: str,
    resource_name: str,
    sop_step: str,
) -> dict:
    """Send a notification email via Azure Communication Services (ACS)."""
    acs_connection_string = os.environ.get("ACS_CONNECTION_STRING", "")
    from_address = os.environ.get("NOTIFICATION_EMAIL_FROM", "")
    to_address = os.environ.get("NOTIFICATION_EMAIL_TO", "")

    if not all([acs_connection_string, from_address, to_address]):
        logger.warning("sop_notify: ACS email not configured (missing env vars)")
        return {"ok": False, "error": "ACS email not configured"}

    try:
        from azure.communication.email import EmailClient
    except ImportError:
        return {"ok": False, "error": "azure-communication-email not installed"}

    subject = f"[{severity.upper()}] AIOps SOP Notification — {incident_id}"
    body_text = (
        f"Incident: {incident_id}\n"
        f"Resource: {resource_name}\n"
        f"SOP Step: {sop_step}\n\n"
        f"{message}"
    )
    body_html = (
        f"<p><strong>Incident:</strong> {incident_id}</p>"
        f"<p><strong>Resource:</strong> {resource_name}</p>"
        f"<p><strong>SOP Step:</strong> {sop_step}</p>"
        f"<p>{message}</p>"
    )

    email_client = EmailClient.from_connection_string(acs_connection_string)
    message_obj = {
        "senderAddress": from_address,
        "recipients": {"to": [{"address": to_address}]},
        "content": {"subject": subject, "plainText": body_text, "html": body_html},
    }

    poller = email_client.begin_send(message_obj)
    result = poller.result()
    return {"ok": True, "message_id": result.get("id")}
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_sop_notify.py -v
```

- [ ] **Step 3: Commit**

```bash
git add agents/shared/sop_notify.py agents/tests/shared/test_sop_notify.py
git commit -m "feat(phase-30): add sop_notify @ai_function for SOP NOTIFY steps"
```

---

## Chunk 5: Teams Bot — New SOP Card Types

### Task 9: Write failing tests for new Teams card types

**Files:**
- Create: `services/teams-bot/src/cards/__tests__/sop-notification-card.test.ts`

- [ ] **Step 1: Create the test file**

```typescript
import { buildSopNotificationCard } from "../sop-notification-card";
import { buildSopEscalationCard } from "../sop-escalation-card";
import { buildSopSummaryCard } from "../sop-summary-card";

describe("SOP notification cards", () => {
  describe("buildSopNotificationCard", () => {
    it("returns an AdaptiveCard object", () => {
      const card = buildSopNotificationCard({
        incident_id: "inc-001",
        resource_name: "vm-prod-01",
        message: "CPU threshold breached",
        severity: "warning",
        sop_step: "Step 2: Notify operator",
      });
      expect(card.type).toBe("AdaptiveCard");
    });

    it("includes incident_id in the card body", () => {
      const card = buildSopNotificationCard({
        incident_id: "inc-test-001",
        resource_name: "vm1",
        message: "test",
        severity: "info",
        sop_step: "Step 1",
      });
      const json = JSON.stringify(card);
      expect(json).toContain("inc-test-001");
    });

    it("includes resource_name in the card body", () => {
      const card = buildSopNotificationCard({
        incident_id: "inc-001",
        resource_name: "my-vm-prod",
        message: "test",
        severity: "critical",
        sop_step: "Step 2",
      });
      const json = JSON.stringify(card);
      expect(json).toContain("my-vm-prod");
    });
  });

  describe("buildSopEscalationCard", () => {
    it("returns an AdaptiveCard with acknowledge action", () => {
      const card = buildSopEscalationCard({
        incident_id: "inc-002",
        resource_name: "vm2",
        message: "escalating to SRE",
        sop_step: "Step 5: Escalate",
        context: "Triage inconclusive after 3 steps",
      });
      expect(card.type).toBe("AdaptiveCard");
      const json = JSON.stringify(card);
      expect(json.toLowerCase()).toContain("acknowledge");
    });
  });

  describe("buildSopSummaryCard", () => {
    it("returns an AdaptiveCard with steps_run count", () => {
      const card = buildSopSummaryCard({
        incident_id: "inc-003",
        resource_name: "vm3",
        sop_title: "VM High CPU",
        steps_run: 4,
        steps_skipped: 1,
        outcome: "resolved",
      });
      expect(card.type).toBe("AdaptiveCard");
      const json = JSON.stringify(card);
      expect(json).toContain("4");
    });
  });
});
```

- [ ] **Step 2: Run test — expect compilation/import error**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/teams-bot
npx jest src/cards/__tests__/sop-notification-card.test.ts 2>&1 | head -15
```

### Task 10: Create the 3 new SOP card files

**Files:**
- Create: `services/teams-bot/src/cards/sop-notification-card.ts`
- Create: `services/teams-bot/src/cards/sop-escalation-card.ts`
- Create: `services/teams-bot/src/cards/sop-summary-card.ts`
- Modify: `services/teams-bot/src/types.ts`

- [ ] **Step 1: Create `sop-notification-card.ts`**

```typescript
export interface SopNotificationPayload {
  incident_id: string;
  resource_name: string;
  message: string;
  severity: "info" | "warning" | "critical";
  sop_step: string;
}

export function buildSopNotificationCard(payload: SopNotificationPayload): object {
  const severityColor =
    payload.severity === "critical"
      ? "Attention"
      : payload.severity === "warning"
      ? "Warning"
      : "Good";

  return {
    type: "AdaptiveCard",
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    version: "1.5",
    body: [
      {
        type: "TextBlock",
        text: `🔔 AIOps SOP Notification`,
        weight: "Bolder",
        size: "Medium",
        color: severityColor,
      },
      {
        type: "FactSet",
        facts: [
          { title: "Incident", value: payload.incident_id },
          { title: "Resource", value: payload.resource_name },
          { title: "Severity", value: payload.severity.toUpperCase() },
          { title: "SOP Step", value: payload.sop_step },
        ],
      },
      {
        type: "TextBlock",
        text: payload.message,
        wrap: true,
      },
    ],
  };
}
```

- [ ] **Step 2: Create `sop-escalation-card.ts`**

```typescript
export interface SopEscalationPayload {
  incident_id: string;
  resource_name: string;
  message: string;
  sop_step: string;
  context: string;
}

export function buildSopEscalationCard(payload: SopEscalationPayload): object {
  return {
    type: "AdaptiveCard",
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    version: "1.5",
    body: [
      {
        type: "TextBlock",
        text: `⚠️ SOP Escalation — ${payload.incident_id}`,
        weight: "Bolder",
        size: "Medium",
        color: "Attention",
      },
      {
        type: "FactSet",
        facts: [
          { title: "Resource", value: payload.resource_name },
          { title: "SOP Step", value: payload.sop_step },
          { title: "Context", value: payload.context },
        ],
      },
      { type: "TextBlock", text: payload.message, wrap: true },
    ],
    actions: [
      {
        type: "Action.Submit",
        title: "Acknowledge",
        data: { action: "acknowledge_escalation", incident_id: payload.incident_id },
      },
    ],
  };
}
```

- [ ] **Step 3: Create `sop-summary-card.ts`**

```typescript
export interface SopSummaryPayload {
  incident_id: string;
  resource_name: string;
  sop_title: string;
  steps_run: number;
  steps_skipped: number;
  outcome: "resolved" | "escalated" | "pending_approval" | "failed";
}

export function buildSopSummaryCard(payload: SopSummaryPayload): object {
  const outcomeEmoji =
    payload.outcome === "resolved"
      ? "✅"
      : payload.outcome === "escalated"
      ? "⚠️"
      : payload.outcome === "pending_approval"
      ? "⏳"
      : "❌";

  return {
    type: "AdaptiveCard",
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    version: "1.5",
    body: [
      {
        type: "TextBlock",
        text: `${outcomeEmoji} SOP Execution Summary`,
        weight: "Bolder",
        size: "Medium",
      },
      {
        type: "FactSet",
        facts: [
          { title: "Incident", value: payload.incident_id },
          { title: "Resource", value: payload.resource_name },
          { title: "SOP", value: payload.sop_title },
          { title: "Steps Run", value: String(payload.steps_run) },
          { title: "Steps Skipped", value: String(payload.steps_skipped) },
          { title: "Outcome", value: payload.outcome },
        ],
      },
    ],
  };
}
```

- [ ] **Step 4: Update `types.ts` to add new card types**

In `services/teams-bot/src/types.ts`, update `CardType`:

```typescript
export type CardType =
  | "alert"
  | "approval"
  | "outcome"
  | "reminder"
  | "sop_notification"
  | "sop_escalation"
  | "sop_summary";
```

Add new payload interfaces:

```typescript
export interface SopNotificationPayload {
  incident_id: string;
  resource_name: string;
  message: string;
  severity: "info" | "warning" | "critical";
  sop_step: string;
}

export interface SopEscalationPayload {
  incident_id: string;
  resource_name: string;
  message: string;
  sop_step: string;
  context: string;
}

export interface SopSummaryPayload {
  incident_id: string;
  resource_name: string;
  sop_title: string;
  steps_run: number;
  steps_skipped: number;
  outcome: "resolved" | "escalated" | "pending_approval" | "failed";
}
```

- [ ] **Step 5: Update `routes/notify.ts` to handle new card types**

In `services/teams-bot/src/routes/notify.ts`, add cases for the 3 new types in the card switch/if logic:

```typescript
import { buildSopNotificationCard } from "../cards/sop-notification-card";
import { buildSopEscalationCard } from "../cards/sop-escalation-card";
import { buildSopSummaryCard } from "../cards/sop-summary-card";

// In the card builder switch:
case "sop_notification":
  card = buildSopNotificationCard(req.payload as SopNotificationPayload);
  break;
case "sop_escalation":
  card = buildSopEscalationCard(req.payload as SopEscalationPayload);
  break;
case "sop_summary":
  card = buildSopSummaryCard(req.payload as SopSummaryPayload);
  break;
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/teams-bot
npx jest src/cards/__tests__/sop-notification-card.test.ts -v
```

- [ ] **Step 7: Run full teams-bot test suite**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/teams-bot
npx jest --passWithNoTests
```

- [ ] **Step 8: Commit**

```bash
git add services/teams-bot/src/cards/sop-notification-card.ts \
        services/teams-bot/src/cards/sop-escalation-card.ts \
        services/teams-bot/src/cards/sop-summary-card.ts \
        services/teams-bot/src/cards/__tests__/sop-notification-card.test.ts \
        services/teams-bot/src/types.ts \
        services/teams-bot/src/routes/notify.ts
git commit -m "feat(phase-30): add SOP Teams card types (notification, escalation, summary)"
```

---

## Chunk 6: SOP Upload Script

### Task 11: Write failing tests for `scripts/upload_sops.py`

**Files:**
- Create: `scripts/tests/test_upload_sops.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for scripts/upload_sops.py — idempotent SOP upload."""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestComputeSopHash:
    """Verify SHA-256 content hash computation."""

    def test_returns_sha256_hex_string(self, tmp_path):
        sop_file = tmp_path / "test.md"
        content = b"# Test SOP\nThis is a test."
        sop_file.write_bytes(content)

        from scripts.upload_sops import compute_sop_hash

        result = compute_sop_hash(sop_file)
        expected = hashlib.sha256(content).hexdigest()
        assert result == expected

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "sop1.md"
        f2 = tmp_path / "sop2.md"
        f1.write_text("version 1")
        f2.write_text("version 2")

        from scripts.upload_sops import compute_sop_hash

        assert compute_sop_hash(f1) != compute_sop_hash(f2)

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "sop1.md"
        f2 = tmp_path / "sop2_copy.md"
        f1.write_text("same content")
        f2.write_text("same content")

        from scripts.upload_sops import compute_sop_hash

        assert compute_sop_hash(f1) == compute_sop_hash(f2)


class TestParseSopFrontMatter:
    """Verify YAML front matter parsing."""

    def test_extracts_title(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text(
            "---\ntitle: VM High CPU\ndomain: compute\nversion: '1.0'\n---\n# Body"
        )

        from scripts.upload_sops import parse_sop_front_matter

        result = parse_sop_front_matter(sop_file)
        assert result["title"] == "VM High CPU"

    def test_extracts_domain(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text("---\ntitle: Test\ndomain: patch\nversion: '1.0'\n---\n")

        from scripts.upload_sops import parse_sop_front_matter

        result = parse_sop_front_matter(sop_file)
        assert result["domain"] == "patch"

    def test_missing_front_matter_raises(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text("# No front matter here")

        from scripts.upload_sops import parse_sop_front_matter

        with pytest.raises(ValueError, match="front matter"):
            parse_sop_front_matter(sop_file)
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest scripts/tests/test_upload_sops.py -v 2>&1 | head -10
```

### Task 12: Create `scripts/upload_sops.py`

**Files:**
- Create: `scripts/upload_sops.py`

- [ ] **Step 1: Create `scripts/upload_sops.py`**

```python
"""Idempotent SOP upload script — uploads/updates SOP files in Foundry vector store.

Idempotency mechanism:
1. Compute SHA-256 hash of each .md file
2. Look up existing row in PostgreSQL sops table by foundry_filename
3. If row exists AND content_hash matches → skip (no change)
4. If row exists AND hash differs → delete old Foundry file, re-upload, update row
5. If no row → upload to Foundry vector store (aap-sops-v1), insert row

Run after Phase 31 (initial SOP library):
    python scripts/upload_sops.py

Run after any SOP update:
    python scripts/upload_sops.py

Or set up a GitHub Actions trigger on push to sops/**/*.md.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Directory containing all SOP .md files (from repo root)
SOP_DIR = Path("sops")
SOP_VECTOR_STORE_NAME = "aap-sops-v1"


def compute_sop_hash(sop_path: Path) -> str:
    """Compute SHA-256 hash of a SOP file's content.

    Args:
        sop_path: Path to the SOP markdown file.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    content = sop_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def parse_sop_front_matter(sop_path: Path) -> dict:
    """Parse YAML front matter from a SOP markdown file.

    Expects the file to start with '---' delimited YAML front matter.

    Args:
        sop_path: Path to the SOP markdown file.

    Returns:
        Dict of front matter fields (title, domain, version, scenario_tags, etc.)

    Raises:
        ValueError: If the file has no YAML front matter.
    """
    content = sop_path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError(
            f"SOP file '{sop_path.name}' has no YAML front matter. "
            "All SOP files must start with '---' delimited YAML."
        )

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError(
            f"SOP file '{sop_path.name}' has malformed front matter."
        )

    front_matter = yaml.safe_load(parts[1])
    if not isinstance(front_matter, dict):
        raise ValueError(
            f"SOP file '{sop_path.name}' front matter is not a YAML dict."
        )

    for required in ("title", "domain", "version"):
        if required not in front_matter:
            raise ValueError(
                f"SOP file '{sop_path.name}' missing required front matter field: '{required}'"
            )

    return front_matter


def _get_or_create_vector_store(openai_client: object) -> str:
    """Get existing 'aap-sops-v1' vector store ID or create a new one.

    Args:
        openai_client: OpenAI client from project.get_openai_client().

    Returns:
        Vector store ID string.
    """
    # List existing stores and find by name
    stores = openai_client.vector_stores.list()
    for store in stores.data:
        if store.name == SOP_VECTOR_STORE_NAME:
            logger.info("Found existing vector store: %s (%s)", store.name, store.id)
            return store.id

    # Create new
    vs = openai_client.vector_stores.create(name=SOP_VECTOR_STORE_NAME)
    logger.info("Created new vector store: %s (%s)", vs.name, vs.id)
    return vs.id


async def upload_sops(sop_dir: Path = SOP_DIR) -> dict[str, str]:
    """Upload all SOP files in sop_dir to the Foundry vector store.

    Returns a dict mapping filename → action taken ("created", "updated", "skipped").
    """
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
        "FOUNDRY_ACCOUNT_ENDPOINT"
    )
    if not endpoint:
        raise SystemExit("AZURE_PROJECT_ENDPOINT env var required.")

    import asyncpg

    pg_url = os.environ.get("DATABASE_URL")
    if not pg_url:
        raise SystemExit("DATABASE_URL env var required.")

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    openai_client = project.get_openai_client()
    vs_id = _get_or_create_vector_store(openai_client)

    conn = await asyncpg.connect(pg_url)
    results: dict[str, str] = {}

    try:
        sop_files = sorted(sop_dir.glob("*.md"))
        if not sop_files:
            logger.warning("No .md files found in %s", sop_dir)
            return results

        for sop_path in sop_files:
            if sop_path.name.startswith("_"):
                logger.info("Skipping template file: %s", sop_path.name)
                continue

            filename = sop_path.name
            new_hash = compute_sop_hash(sop_path)

            existing = await conn.fetchrow(
                "SELECT foundry_file_id, content_hash FROM sops WHERE foundry_filename = $1",
                filename,
            )

            if existing and existing["content_hash"] == new_hash:
                logger.info("Skipping unchanged SOP: %s", filename)
                results[filename] = "skipped"
                continue

            # Delete old Foundry file if updating
            if existing and existing.get("foundry_file_id"):
                try:
                    openai_client.vector_stores.files.delete(
                        vector_store_id=vs_id,
                        file_id=existing["foundry_file_id"],
                    )
                    logger.info("Deleted old Foundry file for %s", filename)
                except Exception as exc:
                    logger.warning("Could not delete old file for %s: %s", filename, exc)

            # Upload new version
            front_matter = parse_sop_front_matter(sop_path)
            with open(sop_path, "rb") as f:
                uploaded = openai_client.vector_stores.files.upload_and_poll(
                    vector_store_id=vs_id,
                    file=f,
                    filename=filename,
                )
            new_file_id = uploaded.id

            # Upsert PostgreSQL row
            await conn.execute(
                """INSERT INTO sops
                       (title, domain, scenario_tags, foundry_filename, foundry_file_id,
                        content_hash, version, description, severity_threshold,
                        resource_types, is_generic, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now())
                   ON CONFLICT (foundry_filename) DO UPDATE SET
                       title = EXCLUDED.title,
                       domain = EXCLUDED.domain,
                       scenario_tags = EXCLUDED.scenario_tags,
                       foundry_file_id = EXCLUDED.foundry_file_id,
                       content_hash = EXCLUDED.content_hash,
                       version = EXCLUDED.version,
                       description = EXCLUDED.description,
                       severity_threshold = EXCLUDED.severity_threshold,
                       resource_types = EXCLUDED.resource_types,
                       is_generic = EXCLUDED.is_generic,
                       updated_at = now()
                """,
                front_matter.get("title", filename),
                front_matter.get("domain", ""),
                front_matter.get("scenario_tags", []),
                filename,
                new_file_id,
                new_hash,
                str(front_matter.get("version", "1.0")),
                front_matter.get("description", ""),
                front_matter.get("severity_threshold", "P2"),
                front_matter.get("resource_types", []),
                bool(front_matter.get("is_generic", False)),
            )

            action = "updated" if existing else "created"
            results[filename] = action
            logger.info("  ✓ %s (%s)", filename, action)

    finally:
        await conn.close()

    # Write SOP_VECTOR_STORE_ID to .env.sops for reference
    env_file = Path(".env.sops")
    env_file.write_text(f"SOP_VECTOR_STORE_ID={vs_id}\n")
    logger.info("SOP_VECTOR_STORE_ID=%s written to .env.sops", vs_id)

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = asyncio.run(upload_sops())
    print("\nSOP upload results:")
    for name, action in results.items():
        print(f"  {name}: {action}")
    print(f"\nTotal: {len(results)} SOPs processed")
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest scripts/tests/test_upload_sops.py -v
```

- [ ] **Step 3: Commit**

```bash
git add scripts/upload_sops.py scripts/tests/test_upload_sops.py
git commit -m "feat(phase-30): add scripts/upload_sops.py with SHA-256 idempotency"
```

---

## Chunk 7: Terraform — ACS Email + SOP Vector Store Env Var

### Task 13: Terraform ACS + env var changes

**Files:**
- Modify: `terraform/modules/databases/postgres.tf` or a new `terraform/modules/notifications/main.tf`
- Modify: `terraform/modules/agent-apps/main.tf`

- [ ] **Step 1: Add ACS Email Communication Service resource**

Add to Terraform (use the `databases` module or a new `notifications` module):

```hcl
resource "azurerm_email_communication_service" "acs_email" {
  name                = "aap-acs-email-prod"
  resource_group_name = var.resource_group_name
  data_location       = "United States"
}

resource "azurerm_communication_service" "acs" {
  name                = "aap-acs-prod"
  resource_group_name = var.resource_group_name
  data_location       = "United States"
}
```

- [ ] **Step 2: Add `SOP_VECTOR_STORE_ID` env var placeholder to all Container Apps**

In `terraform/modules/agent-apps/main.tf`, add to every agent Container App:

```hcl
env {
  name  = "SOP_VECTOR_STORE_ID"
  value = var.sop_vector_store_id
}
env {
  name  = "ACS_CONNECTION_STRING"
  secret_name = "acs-connection-string"
}
env {
  name  = "NOTIFICATION_EMAIL_FROM"
  value = var.notification_email_from
}
env {
  name  = "NOTIFICATION_EMAIL_TO"
  value = var.notification_email_to
}
```

Add to `variables.tf`:
```hcl
variable "sop_vector_store_id" {
  description = "Foundry vector store ID for SOP files (set after running upload_sops.py)"
  type        = string
  default     = ""
}
variable "notification_email_from" {
  type    = string
  default = ""
}
variable "notification_email_to" {
  type    = string
  default = ""
}
```

- [ ] **Step 3: Run terraform plan**

```bash
cd terraform/envs/prod
terraform plan -var-file=credentials.tfvars -var-file=terraform.tfvars 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```bash
git add terraform/
git commit -m "feat(phase-30): add ACS Email resource and SOP_VECTOR_STORE_ID env var to Terraform"
```

---

## Chunk 8: Phase 30 Integration Smoke Test

### Task 14: Integration smoke test

**Files:**
- Create: `agents/tests/integration/test_phase30_smoke.py`

- [ ] **Step 1: Create smoke test**

```python
"""Phase 30 smoke tests — SOP engine wiring."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestPhase30Smoke:
    """Verify the Phase 30 SOP engine components are importable and wired."""

    def test_sop_store_importable(self):
        from agents.shared.sop_store import provision_sop_vector_store
        assert provision_sop_vector_store

    def test_sop_loader_importable(self):
        from agents.shared.sop_loader import SopLoadResult, select_sop_for_incident
        assert select_sop_for_incident
        assert SopLoadResult

    def test_sop_notify_importable(self):
        from agents.shared.sop_notify import sop_notify
        assert sop_notify

    def test_migration_file_exists(self):
        import os
        assert os.path.exists("services/api-gateway/migrations/003_create_sops_table.py")

    def test_upload_sops_script_importable(self):
        from scripts.upload_sops import compute_sop_hash, parse_sop_front_matter, upload_sops
        assert all([compute_sop_hash, parse_sop_front_matter, upload_sops])

    @pytest.mark.asyncio
    async def test_sop_loader_returns_grounding_for_mock_incident(self):
        mock_conn = AsyncMock()
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "foundry_filename": "vm-high-cpu.md",
            "title": "VM High CPU",
            "version": "1.0",
            "is_generic": False,
        }[k]
        mock_conn.fetchrow.return_value = row

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(
            {"incident_id": "inc-smoke", "alert_title": "cpu high", "resource_type": ""},
            "compute",
            mock_conn,
        )
        assert result.foundry_filename == "vm-high-cpu.md"
        assert "file_search" in result.grounding_instruction
```

- [ ] **Step 2: Run full smoke test**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/integration/test_phase30_smoke.py -v
```

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest agents/ services/api-gateway/tests/ -v --tb=short 2>&1 | tail -30
```

- [ ] **Step 4: Final commit**

```bash
git add agents/tests/integration/test_phase30_smoke.py
git commit -m "test(phase-30): add Phase 30 SOP engine integration smoke tests"
```

---

## Phase 30 Done Checklist

- [ ] `003_create_sops_table.py` migration created (sops table with content_hash)
- [ ] `agents/shared/sop_store.py` provision_sop_vector_store() created
- [ ] `agents/shared/sop_loader.py` select_sop_for_incident() with tag overlap SQL
- [ ] `agents/shared/sop_notify.py` @ai_function with teams + email, no "both" shorthand
- [ ] 3 new Teams card types (sop_notification, sop_escalation, sop_summary)
- [ ] `types.ts` CardType union extended
- [ ] `scripts/upload_sops.py` with SHA-256 idempotency + asyncpg upsert
- [ ] Terraform: ACS Email resource + SOP_VECTOR_STORE_ID env var
- [ ] All tests pass
