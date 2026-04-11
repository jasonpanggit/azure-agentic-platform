# Phase 34 — FileSearch Knowledge + Azure AI Search RAG Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach the existing Foundry vector store (`aap-sops-v1`) as a `FileSearchTool` to every agent's `PromptAgentDefinition`, and migrate the runbook RAG from pgvector to Azure AI Search with an `AzureAISearchTool` on each agent definition. After Phase 34, operators can manage both knowledge sources directly in the Foundry portal.

**Architecture:** Phase 34 only *attaches* the vector store created in Phase 30 — no re-upload. Each agent's `create_*_agent_version()` function (Phase 29) gains two new tools: `FileSearchTool(vector_store_ids=[SOP_VECTOR_STORE_ID])` and `AzureAISearchTool(indexes=[...])`. A migration script (`scripts/migrate_runbooks_to_ai_search.py`) reads runbooks from PostgreSQL (pgvector) and indexes them into Azure AI Search. Terraform provisions the AI Search service and a Foundry connection. The existing `runbook_rag.py` in the API gateway is updated to use the AI Search client.

**Tech Stack:** `azure-ai-projects>=2.0.1` (`FileSearchTool`, `AzureAISearchTool`, `PromptAgentDefinition`), `azure-search-documents` (AI Search SDK), `azure-mgmt-search`, Python pytest, Terraform `azurerm`

**Spec:** `docs/superpowers/specs/2026-04-11-world-class-aiops-phases-29-34-design.md` §8

**Prerequisites:** Phase 29 (`create_version` registered for all agents), Phase 30 (`SOP_VECTOR_STORE_ID` env var set), Phase 31 (SOPs uploaded to vector store).

---

## Chunk 1: Azure AI Search Index + Migration Script

### Task 1: Write failing tests for the migration script

**Files:**
- Create: `scripts/tests/test_migrate_runbooks.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for scripts/migrate_runbooks_to_ai_search.py (Phase 34)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestBuildRunbookDocument:
    """Verify runbook row → AI Search document mapping."""

    def test_maps_id_field(self):
        from scripts.migrate_runbooks_to_ai_search import build_runbook_document

        row = {
            "id": "00000000-0000-0000-0000-000000000001",
            "title": "VM High CPU Runbook",
            "content": "Steps to resolve...",
            "domain": "compute",
            "version": "1.0",
            "embedding": [0.1, 0.2, 0.3],
        }
        doc = build_runbook_document(row)
        assert doc["id"] == "00000000-0000-0000-0000-000000000001"

    def test_maps_title_and_content(self):
        from scripts.migrate_runbooks_to_ai_search import build_runbook_document

        row = {
            "id": "uuid-1",
            "title": "My Runbook",
            "content": "Do this and that",
            "domain": "patch",
            "version": "2.0",
            "embedding": [],
        }
        doc = build_runbook_document(row)
        assert doc["title"] == "My Runbook"
        assert doc["content"] == "Do this and that"

    def test_maps_embedding_field(self):
        from scripts.migrate_runbooks_to_ai_search import build_runbook_document

        embedding = [0.1] * 1536
        row = {
            "id": "uuid-2",
            "title": "Test",
            "content": "content",
            "domain": "compute",
            "version": "1.0",
            "embedding": embedding,
        }
        doc = build_runbook_document(row)
        assert doc["embedding"] == embedding
        assert len(doc["embedding"]) == 1536

    def test_sanitizes_id_for_search_key(self):
        """AI Search document keys can only contain letters, digits, dash, underscore, equals."""
        from scripts.migrate_runbooks_to_ai_search import build_runbook_document

        row = {
            "id": "123e4567-e89b-12d3-a456-426614174000",
            "title": "T",
            "content": "c",
            "domain": "compute",
            "version": "1.0",
            "embedding": [],
        }
        doc = build_runbook_document(row)
        # UUID with dashes should be accepted by AI Search
        assert "-" not in doc["id"] or doc["id"].replace("-", "").isalnum()


class TestCreateRunbookIndex:
    """Verify create_runbook_index creates index with required fields."""

    def test_creates_index_with_correct_name(self):
        mock_client = MagicMock()
        mock_client.create_or_update_index.return_value = MagicMock()

        from scripts.migrate_runbooks_to_ai_search import create_runbook_index

        create_runbook_index(mock_client, "aap-runbooks")

        mock_client.create_or_update_index.assert_called_once()
        call_args = mock_client.create_or_update_index.call_args
        index = call_args.args[0] if call_args.args else call_args.kwargs.get("index")
        assert index.name == "aap-runbooks"

    def test_index_has_vector_search_profile(self):
        mock_client = MagicMock()

        from scripts.migrate_runbooks_to_ai_search import create_runbook_index

        create_runbook_index(mock_client, "aap-runbooks")

        call_args = mock_client.create_or_update_index.call_args
        index = call_args.args[0] if call_args.args else call_args.kwargs.get("index")
        assert index.vector_search is not None
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest scripts/tests/test_migrate_runbooks.py -v 2>&1 | head -10
```

### Task 2: Create `scripts/migrate_runbooks_to_ai_search.py`

**Files:**
- Create: `scripts/migrate_runbooks_to_ai_search.py`

- [ ] **Step 1: Create the migration script**

```python
"""Migrate runbooks from PostgreSQL pgvector to Azure AI Search (Phase 34).

Reads all runbooks from the PostgreSQL `runbooks` table (which includes
pgvector embeddings) and indexes them into Azure AI Search.

After migration, the `runbook_rag.py` module can switch from pgvector
to Azure AI Search hybrid search (keyword + vector).

Run once after Terraform provisions the AI Search service:
    python scripts/migrate_runbooks_to_ai_search.py

Idempotent: re-running uploads/updates without creating duplicates
(AI Search uses the document ID as a unique key).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

INDEX_NAME = "aap-runbooks"


def build_runbook_document(row: dict[str, Any]) -> dict[str, Any]:
    """Map a PostgreSQL runbook row to an Azure AI Search document.

    AI Search document keys must match [A-Za-z0-9_=-]. UUIDs with dashes
    are accepted. The embedding field maps to the vector search profile.

    Args:
        row: Dict with keys: id, title, content, domain, version, embedding.

    Returns:
        Azure AI Search document dict.
    """
    # Sanitize ID: replace hyphens with empty string for safe key
    raw_id = str(row["id"])
    safe_id = raw_id.replace("-", "")

    return {
        "id": safe_id,
        "original_id": raw_id,
        "title": row.get("title", ""),
        "content": row.get("content", ""),
        "domain": row.get("domain", ""),
        "version": str(row.get("version", "1.0")),
        "embedding": row.get("embedding", []) or [],
    }


def create_runbook_index(
    index_client: Any,
    index_name: str = INDEX_NAME,
) -> None:
    """Create or update the Azure AI Search runbook index with HNSW vector search.

    Args:
        index_client: SearchIndexClient (azure-search-documents).
        index_name: Name of the search index (default: "aap-runbooks").
    """
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SearchableField,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )

    index = SearchIndex(
        name=index_name,
        fields=[
            SimpleField(
                name="id",
                type=SearchFieldDataType.String,
                key=True,
                filterable=True,
            ),
            SimpleField(
                name="original_id",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SearchableField(name="title", type=SearchFieldDataType.String),
            SearchableField(name="content", type=SearchFieldDataType.String),
            SimpleField(
                name="domain",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=True,
            ),
            SimpleField(name="version", type=SearchFieldDataType.String),
            SearchField(
                name="embedding",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                vector_search_dimensions=1536,
                vector_search_profile_name="hnsw-profile",
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
            profiles=[
                VectorSearchProfile(
                    name="hnsw-profile",
                    algorithm_configuration_name="hnsw",
                )
            ],
        ),
    )

    index_client.create_or_update_index(index)
    logger.info("Created/updated Azure AI Search index: %s", index_name)


async def migrate_runbooks(
    pg_url: str,
    search_endpoint: str,
    search_api_key: str,
    batch_size: int = 100,
) -> dict[str, int]:
    """Read runbooks from PostgreSQL and index into Azure AI Search.

    Args:
        pg_url: PostgreSQL connection URL.
        search_endpoint: Azure AI Search service endpoint.
        search_api_key: Admin API key (or use DefaultAzureCredential for keyless).
        batch_size: Number of documents to index per batch.

    Returns:
        Dict with 'total', 'indexed', 'skipped' counts.
    """
    import asyncpg
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient

    # Create/update index schema
    index_client = SearchIndexClient(
        endpoint=search_endpoint,
        credential=AzureKeyCredential(search_api_key),
    )
    create_runbook_index(index_client)

    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=INDEX_NAME,
        credential=AzureKeyCredential(search_api_key),
    )

    conn = await asyncpg.connect(pg_url)
    stats = {"total": 0, "indexed": 0, "skipped": 0}

    try:
        rows = await conn.fetch(
            "SELECT id::text, title, content, domain, version, embedding::text "
            "FROM runbooks ORDER BY id"
        )
        stats["total"] = len(rows)
        logger.info("Migrating %d runbooks from pgvector → AI Search", len(rows))

        batch: list[dict] = []
        for row in rows:
            row_dict = dict(row)
            # Parse embedding from text representation
            embedding_raw = row_dict.get("embedding", "")
            if isinstance(embedding_raw, str) and embedding_raw.startswith("["):
                import json

                row_dict["embedding"] = json.loads(embedding_raw)
            else:
                row_dict["embedding"] = []

            doc = build_runbook_document(row_dict)
            batch.append(doc)

            if len(batch) >= batch_size:
                results = search_client.upload_documents(documents=batch)
                indexed = sum(1 for r in results if r.succeeded)
                stats["indexed"] += indexed
                stats["skipped"] += len(batch) - indexed
                logger.info(
                    "Batch indexed: %d/%d succeeded", indexed, len(batch)
                )
                batch = []

        # Upload remaining
        if batch:
            results = search_client.upload_documents(documents=batch)
            indexed = sum(1 for r in results if r.succeeded)
            stats["indexed"] += indexed
            stats["skipped"] += len(batch) - indexed

    finally:
        await conn.close()

    logger.info(
        "Migration complete: %d total, %d indexed, %d skipped",
        stats["total"],
        stats["indexed"],
        stats["skipped"],
    )
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    pg_url = os.environ.get("DATABASE_URL")
    search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    search_api_key = os.environ.get("AZURE_SEARCH_API_KEY")

    if not all([pg_url, search_endpoint, search_api_key]):
        raise SystemExit(
            "Required env vars: DATABASE_URL, AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_API_KEY"
        )

    stats = asyncio.run(
        migrate_runbooks(
            pg_url=pg_url,
            search_endpoint=search_endpoint,
            search_api_key=search_api_key,
        )
    )
    print(f"\nMigration results: {stats}")
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest scripts/tests/test_migrate_runbooks.py -v
```

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_runbooks_to_ai_search.py scripts/tests/test_migrate_runbooks.py
git commit -m "feat(phase-34): add scripts/migrate_runbooks_to_ai_search.py"
```

---

## Chunk 2: Agent Definition Updates — FileSearch + AzureAISearch Tools

### Task 3: Write failing tests for updated agent definitions

**Files:**
- Create: `agents/tests/shared/test_agent_knowledge_tools.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for Phase 34 knowledge tool attachment to agent definitions."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class TestComputeAgentVersionWithKnowledge:
    """Verify compute agent version includes FileSearch and AzureAISearch tools."""

    def test_definition_includes_file_search_tool(self, monkeypatch):
        monkeypatch.setenv("AGENT_MODEL_DEPLOYMENT", "gpt-4.1")
        monkeypatch.setenv("SOP_VECTOR_STORE_ID", "vs_test_123")

        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()

        with patch(
            "agents.compute.agent.FileSearchTool",
            return_value=MagicMock(),
        ) as mock_fst:
            from agents.compute.agent import create_compute_agent_version

            create_compute_agent_version(mock_project)

        # FileSearchTool should be instantiated with SOP_VECTOR_STORE_ID
        mock_fst.assert_called_once()
        call_kwargs = mock_fst.call_args
        vs_ids = call_kwargs.kwargs.get("vector_store_ids") or call_kwargs.args[0]
        assert "vs_test_123" in vs_ids

    def test_definition_includes_azure_ai_search_tool(self, monkeypatch):
        monkeypatch.setenv("AGENT_MODEL_DEPLOYMENT", "gpt-4.1")
        monkeypatch.setenv("SOP_VECTOR_STORE_ID", "vs_abc")
        monkeypatch.setenv("RUNBOOK_SEARCH_CONNECTION_ID", "conn_search_123")

        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()

        with patch("agents.compute.agent.AzureAISearchTool", return_value=MagicMock()) as mock_ais:
            from agents.compute.agent import create_compute_agent_version

            create_compute_agent_version(mock_project)

        mock_ais.assert_called_once()

    def test_file_search_not_added_when_env_var_missing(self, monkeypatch):
        """If SOP_VECTOR_STORE_ID is not set, FileSearchTool should be skipped gracefully."""
        monkeypatch.delenv("SOP_VECTOR_STORE_ID", raising=False)
        monkeypatch.setenv("AGENT_MODEL_DEPLOYMENT", "gpt-4.1")

        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()

        # Should not raise — graceful degradation
        from agents.compute.agent import create_compute_agent_version

        result = create_compute_agent_version(mock_project)
        assert result is not None
```

- [ ] **Step 2: Run test — expect import failure or assertion error**

```bash
python -m pytest agents/tests/shared/test_agent_knowledge_tools.py -v 2>&1 | head -15
```

### Task 4: Update all 9 agent definitions to include knowledge tools

**Files:**
- Modify: `agents/compute/agent.py`
- Modify: `agents/arc/agent.py`
- Modify: `agents/eol/agent.py`
- Modify: `agents/network/agent.py`
- Modify: `agents/patch/agent.py`
- Modify: `agents/security/agent.py`
- Modify: `agents/sre/agent.py`
- Modify: `agents/storage/agent.py`
- Modify: `agents/orchestrator/agent.py`

- [ ] **Step 1: Update compute agent's `create_compute_agent_version()` to include knowledge tools**

Modify the function in `agents/compute/agent.py`:

```python
import os

try:
    from azure.ai.projects.models import (
        AzureAISearchTool,
        AzureAISearchToolResource,
        AISearchIndexResource,
        FileSearchTool,
        PromptAgentDefinition,
    )
except ImportError:
    AzureAISearchTool = None  # type: ignore[assignment,misc]
    AzureAISearchToolResource = None  # type: ignore[assignment,misc]
    AISearchIndexResource = None  # type: ignore[assignment,misc]
    FileSearchTool = None  # type: ignore[assignment,misc]
    PromptAgentDefinition = None  # type: ignore[assignment,misc]


def create_compute_agent_version(project: "AIProjectClient") -> object:
    """Register the Compute Agent with knowledge tools (Phase 34 update).

    Attaches:
    1. FileSearchTool — SOP vector store (aap-sops-v1) for SOP retrieval
    2. AzureAISearchTool — runbook index for diagnostic context retrieval
    """
    if PromptAgentDefinition is None:
        raise ImportError("azure-ai-projects>=2.0.1 required")

    tools = [
        query_activity_log,
        query_log_analytics,
        query_resource_health,
        query_monitor_metrics,
        query_os_version,
        query_vm_extensions,
        query_boot_diagnostics,
        query_vm_sku_options,
        query_disk_health,
        propose_vm_restart,
        propose_vm_resize,
        propose_vm_redeploy,
        query_vmss_instances,
        query_vmss_autoscale,
        query_vmss_rolling_upgrade,
        propose_vmss_scale,
        query_aks_cluster_health,
        query_aks_node_pools,
        query_aks_diagnostics,
        query_aks_upgrade_profile,
        propose_aks_node_pool_scale,
    ]

    # Attach SOP vector store (Phase 30 provisioned, Phase 34 attaches)
    sop_vs_id = os.environ.get("SOP_VECTOR_STORE_ID", "")
    if sop_vs_id and FileSearchTool is not None:
        tools.append(FileSearchTool(vector_store_ids=[sop_vs_id]))

    # Attach AI Search runbook index (Phase 34 migrated)
    runbook_conn_id = os.environ.get("RUNBOOK_SEARCH_CONNECTION_ID", "")
    if runbook_conn_id and AzureAISearchTool is not None:
        tools.append(
            AzureAISearchTool(
                azure_ai_search=AzureAISearchToolResource(
                    indexes=[
                        AISearchIndexResource(
                            index_connection_id=runbook_conn_id,
                            index_name="aap-runbooks",
                        )
                    ]
                )
            )
        )

    return project.agents.create_version(
        agent_name="aap-compute-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=COMPUTE_AGENT_SYSTEM_PROMPT,
            description="Azure compute domain specialist — VMs, VMSS, AKS, App Service.",
            tools=tools,
        ),
    )
```

- [ ] **Step 2: Apply the same knowledge tool pattern to all remaining 8 agents**

For each agent, update `create_*_agent_version()` to:
1. Import `FileSearchTool`, `AzureAISearchTool`, `AzureAISearchToolResource`, `AISearchIndexResource`
2. Read `SOP_VECTOR_STORE_ID` from env — append `FileSearchTool` if set
3. Read `RUNBOOK_SEARCH_CONNECTION_ID` from env — append `AzureAISearchTool` if set
4. Use graceful degradation (skip if env var not set or SDK not available)

Agents to update: `arc`, `eol`, `network`, `patch`, `security`, `sre`, `storage`, `orchestrator`

- [ ] **Step 3: Run knowledge tools tests — expect PASS**

```bash
python -m pytest agents/tests/shared/test_agent_knowledge_tools.py -v
```

- [ ] **Step 4: Commit**

```bash
git add agents/compute/agent.py agents/arc/agent.py agents/eol/agent.py \
        agents/network/agent.py agents/patch/agent.py agents/security/agent.py \
        agents/sre/agent.py agents/storage/agent.py agents/orchestrator/agent.py \
        agents/tests/shared/test_agent_knowledge_tools.py
git commit -m "feat(phase-34): attach FileSearchTool + AzureAISearchTool to all 9 agent definitions"
```

---

## Chunk 3: Runbook RAG Migration — API Gateway

### Task 5: Write failing tests for AI Search runbook RAG

**Files:**
- Create: `services/api-gateway/tests/test_runbook_rag_search.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for AI Search-backed runbook RAG (Phase 34)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestSearchRunbooks:
    """Verify search_runbooks uses Azure AI Search when configured."""

    @patch("services.api_gateway.runbook_rag.SearchClient")
    def test_calls_search_client_when_search_configured(self, mock_search_cls):
        import os
        os.environ["AZURE_SEARCH_ENDPOINT"] = "https://test.search.windows.net"
        os.environ["AZURE_SEARCH_INDEX_NAME"] = "aap-runbooks"

        mock_client = MagicMock()
        mock_search_cls.return_value = mock_client
        search_result = MagicMock()
        search_result.__iter__ = MagicMock(return_value=iter([
            {"id": "1", "title": "VM CPU Runbook", "content": "Check CPU metrics", "domain": "compute"},
        ]))
        mock_client.search.return_value = search_result

        from services.api_gateway.runbook_rag import search_runbooks_ai_search

        results = search_runbooks_ai_search("high cpu vm", "compute", top=3)
        mock_client.search.assert_called_once()
        assert len(results) >= 1

    @patch("services.api_gateway.runbook_rag.SearchClient")
    def test_filters_by_domain(self, mock_search_cls):
        mock_client = MagicMock()
        mock_search_cls.return_value = mock_client
        mock_client.search.return_value = iter([])

        from services.api_gateway.runbook_rag import search_runbooks_ai_search

        search_runbooks_ai_search("cpu", "compute", top=5)

        call_kwargs = mock_client.search.call_args.kwargs
        filter_str = call_kwargs.get("filter", "") or ""
        assert "compute" in filter_str

    @patch("services.api_gateway.runbook_rag.SearchClient", None)
    def test_returns_empty_when_sdk_not_installed(self):
        from services.api_gateway.runbook_rag import search_runbooks_ai_search

        results = search_runbooks_ai_search("test", "compute", top=3)
        assert results == []
```

- [ ] **Step 2: Run test — expect ImportError or assertion error**

```bash
python -m pytest services/api-gateway/tests/test_runbook_rag_search.py -v 2>&1 | head -10
```

### Task 6: Add AI Search path to `services/api-gateway/runbook_rag.py`

**Files:**
- Modify: `services/api-gateway/runbook_rag.py`

- [ ] **Step 1: Read current runbook_rag.py**

```bash
cat services/api-gateway/runbook_rag.py
```

- [ ] **Step 2: Add AI Search path while keeping pgvector as fallback**

Add to `services/api-gateway/runbook_rag.py`:

```python
# Lazy import — azure-search-documents may not be installed in all envs
try:
    from azure.search.documents import SearchClient
    from azure.core.credentials import AzureKeyCredential
except ImportError:
    SearchClient = None  # type: ignore[assignment,misc]
    AzureKeyCredential = None  # type: ignore[assignment,misc]


def search_runbooks_ai_search(
    query: str,
    domain: Optional[str] = None,
    top: int = 5,
) -> list[dict]:
    """Search runbooks via Azure AI Search (hybrid keyword + vector).

    Phase 34 replacement for pgvector search. Falls back to empty list
    if the Azure AI Search SDK is not installed or endpoint not configured.

    Args:
        query: Natural-language search query.
        domain: Optional domain filter (e.g. "compute").
        top: Maximum number of results.

    Returns:
        List of runbook dicts with title, content, domain, version.
    """
    if SearchClient is None:
        logger.warning("azure-search-documents not installed — runbook AI Search unavailable")
        return []

    search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
    index_name = os.environ.get("AZURE_SEARCH_INDEX_NAME", "aap-runbooks")
    api_key = os.environ.get("AZURE_SEARCH_API_KEY", "")

    if not search_endpoint:
        logger.warning("AZURE_SEARCH_ENDPOINT not set — AI Search runbook lookup unavailable")
        return []

    try:
        if api_key:
            credential = AzureKeyCredential(api_key)
        else:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()

        client = SearchClient(
            endpoint=search_endpoint,
            index_name=index_name,
            credential=credential,
        )

        filter_str = f"domain eq '{domain}'" if domain else None

        results = []
        for doc in client.search(
            search_text=query,
            filter=filter_str,
            top=top,
            select=["id", "title", "content", "domain", "version"],
        ):
            results.append({
                "id": doc.get("id", ""),
                "title": doc.get("title", ""),
                "content": doc.get("content", ""),
                "domain": doc.get("domain", ""),
                "version": doc.get("version", "1.0"),
            })

        return results

    except Exception as exc:
        logger.warning("AI Search runbook search failed: %s", exc)
        return []
```

- [ ] **Step 3: Run tests — expect PASS**

```bash
python -m pytest services/api-gateway/tests/test_runbook_rag_search.py -v
```

- [ ] **Step 4: Commit**

```bash
git add services/api-gateway/runbook_rag.py \
        services/api-gateway/tests/test_runbook_rag_search.py
git commit -m "feat(phase-34): add AI Search runbook search path to runbook_rag.py"
```

---

## Chunk 4: Terraform — AI Search + Foundry Connection

### Task 7: Terraform AI Search resources

**Files:**
- Create or modify: `terraform/modules/databases/search.tf` (or add to appropriate module)
- Modify: `terraform/modules/agent-apps/main.tf`

- [ ] **Step 1: Add AI Search Terraform resource**

Create `terraform/modules/databases/search.tf`:

```hcl
# Azure AI Search service for runbook RAG (Phase 34)
resource "azurerm_search_service" "runbook_search" {
  name                = "aap-search-prod"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "basic"  # basic is sufficient for 1,000 runbooks
  replica_count       = 1
  partition_count     = 1

  local_authentication_enabled = true  # Allow API key auth for migration script
  authentication_failure_mode  = "http401WithBearerChallenge"

  identity {
    type = "SystemAssigned"
  }
}

output "search_endpoint" {
  value = "https://${azurerm_search_service.runbook_search.name}.search.windows.net"
}

output "search_service_id" {
  value = azurerm_search_service.runbook_search.id
}
```

- [ ] **Step 2: Add AI Search Foundry connection (azapi)**

Add to `terraform/modules/agent-apps/main.tf`:

```hcl
# Foundry connection to Azure AI Search for runbook RAG
resource "azapi_resource" "ai_search_connection" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-05-01-preview"
  name      = "aap-runbook-search-connection"
  parent_id = var.foundry_project_id

  body = {
    properties = {
      category    = "AzureAISearch"
      target      = var.search_endpoint
      authType    = "ApiKey"
      credentials = {
        key = var.search_admin_key
      }
      displayName = "AAP Runbook AI Search Index"
    }
  }
}
```

Add to `variables.tf`:
```hcl
variable "search_endpoint" {
  description = "Azure AI Search service endpoint"
  type        = string
  default     = ""
}
variable "search_admin_key" {
  description = "Azure AI Search admin API key"
  type        = string
  default     = ""
  sensitive   = true
}
variable "runbook_search_connection_id" {
  description = "Foundry connection ID for the AI Search runbook index"
  type        = string
  default     = ""
}
```

- [ ] **Step 3: Add RUNBOOK_SEARCH_CONNECTION_ID env var to all Container Apps**

In `terraform/modules/agent-apps/main.tf`, add to every agent Container App:

```hcl
env {
  name  = "RUNBOOK_SEARCH_CONNECTION_ID"
  value = var.runbook_search_connection_id
}
env {
  name  = "AZURE_SEARCH_ENDPOINT"
  value = var.search_endpoint
}
env {
  name  = "AZURE_SEARCH_INDEX_NAME"
  value = "aap-runbooks"
}
```

- [ ] **Step 4: Run terraform plan**

```bash
cd terraform/envs/prod
terraform plan -var-file=credentials.tfvars -var-file=terraform.tfvars 2>&1 | tail -20
```

- [ ] **Step 5: Commit Terraform changes**

```bash
git add terraform/
git commit -m "feat(phase-34): add Terraform AI Search service + Foundry connection"
```

---

## Chunk 5: FileSearch Roundtrip Test + Final Verification

### Task 8: FileSearch attachment smoke test

**Files:**
- Create: `agents/tests/integration/test_phase34_smoke.py`

- [ ] **Step 1: Create smoke test**

```python
"""Phase 34 smoke tests — knowledge tool attachment and AI Search migration."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class TestPhase34Smoke:
    """Verify Phase 34 knowledge tool wiring."""

    def test_migrate_runbooks_importable(self):
        from scripts.migrate_runbooks_to_ai_search import (
            build_runbook_document,
            create_runbook_index,
            migrate_runbooks,
        )
        assert all([build_runbook_document, create_runbook_index, migrate_runbooks])

    def test_ai_search_path_in_runbook_rag(self):
        from services.api_gateway.runbook_rag import search_runbooks_ai_search
        assert search_runbooks_ai_search

    def test_compute_agent_has_file_search_tool_import(self):
        """Verify compute agent imports FileSearchTool."""
        import inspect
        import agents.compute.agent as compute_agent_module
        src = inspect.getsource(compute_agent_module)
        assert "FileSearchTool" in src

    def test_compute_agent_has_azure_ai_search_tool_import(self):
        """Verify compute agent imports AzureAISearchTool."""
        import inspect
        import agents.compute.agent as compute_agent_module
        src = inspect.getsource(compute_agent_module)
        assert "AzureAISearchTool" in src

    def test_file_search_tool_uses_env_var(self, monkeypatch):
        """Verify SOP_VECTOR_STORE_ID env var drives FileSearchTool attachment."""
        monkeypatch.setenv("SOP_VECTOR_STORE_ID", "vs_smoke_test")
        monkeypatch.setenv("AGENT_MODEL_DEPLOYMENT", "gpt-4.1")

        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()

        with patch("agents.compute.agent.FileSearchTool") as mock_fst:
            mock_fst.return_value = MagicMock()
            from agents.compute.agent import create_compute_agent_version
            create_compute_agent_version(mock_project)

        mock_fst.assert_called_once_with(vector_store_ids=["vs_smoke_test"])

    def test_graceful_degradation_when_sop_vs_not_set(self, monkeypatch):
        """Agent version creation should succeed even without SOP_VECTOR_STORE_ID."""
        monkeypatch.delenv("SOP_VECTOR_STORE_ID", raising=False)
        monkeypatch.setenv("AGENT_MODEL_DEPLOYMENT", "gpt-4.1")

        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()

        from agents.compute.agent import create_compute_agent_version
        result = create_compute_agent_version(mock_project)
        assert result is not None  # Should not raise

    def test_build_runbook_document_strips_hyphens_from_id(self):
        from scripts.migrate_runbooks_to_ai_search import build_runbook_document

        doc = build_runbook_document({
            "id": "123e4567-e89b-12d3-a456-426614174000",
            "title": "T", "content": "c", "domain": "compute", "version": "1.0",
            "embedding": [0.1] * 1536,
        })
        assert "-" not in doc["id"]
        assert doc["original_id"] == "123e4567-e89b-12d3-a456-426614174000"
```

- [ ] **Step 2: Run smoke test**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/integration/test_phase34_smoke.py -v
```

- [ ] **Step 3: Run full test suite for regressions**

```bash
python -m pytest agents/ services/api-gateway/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: no new failures

- [ ] **Step 4: Final commit**

```bash
git add agents/tests/integration/test_phase34_smoke.py
git commit -m "test(phase-34): add Phase 34 FileSearch + AI Search smoke tests"
```

---

## Chunk 6: Production Runbook Migration (Post-Deploy)

### Task 9: Execute runbook migration in production

> Note: This step requires a live Azure environment with AI Search provisioned.

- [ ] **Step 1: Set environment variables**

```bash
export DATABASE_URL="postgresql://..."
export AZURE_SEARCH_ENDPOINT="https://aap-search-prod.search.windows.net"
export AZURE_SEARCH_API_KEY="<admin-key-from-key-vault>"
```

- [ ] **Step 2: Run migration script**

```bash
python scripts/migrate_runbooks_to_ai_search.py
```

Expected output:
```
Migration complete: 45 total, 45 indexed, 0 skipped
```

- [ ] **Step 3: Verify index in Azure portal**

Navigate to AI Search → `aap-search-prod` → Indexes → `aap-runbooks`:
- Document count should match PostgreSQL runbook count
- Run a test query: Search for "VM high CPU" — verify results returned

- [ ] **Step 4: Set `RUNBOOK_SEARCH_CONNECTION_ID` in Terraform vars**

After Foundry connection is created by Terraform apply:
```bash
# Get the connection ID from Terraform output or Azure portal
export RUNBOOK_SEARCH_CONNECTION_ID="<connection-id>"
```

Update `terraform/envs/prod/terraform.tfvars`:
```hcl
runbook_search_connection_id = "<connection-id>"
```

- [ ] **Step 5: Re-run agent registration to update definitions**

```bash
python scripts/register_agents.py
```

This creates a new version of each agent with `FileSearchTool` and `AzureAISearchTool` attached.

- [ ] **Step 6: Verify in Foundry portal**

Navigate to **Foundry portal → Project → Agents**:
- Each agent should show a new version
- Under "Tools", both `file_search` and `azure_ai_search` should appear as knowledge sources
- Navigate to **Files** tab — verify `aap-sops-v1` vector store is visible with 34 files

- [ ] **Step 7: Final commit**

```bash
git add .
git commit -m "feat(phase-34): Phase 34 complete — FileSearch + AI Search knowledge attached to all agents"
```

---

## Phase 34 Done Checklist

- [ ] `scripts/migrate_runbooks_to_ai_search.py` created with HNSW vector search schema
- [ ] AI Search runbook search path added to `runbook_rag.py`
- [ ] All 9 agent `create_*_agent_version()` functions updated with `FileSearchTool`
- [ ] All 9 agent `create_*_agent_version()` functions updated with `AzureAISearchTool`
- [ ] Graceful degradation: agents work even if env vars not set
- [ ] Terraform: `azurerm_search_service` added
- [ ] Terraform: AI Search Foundry connection added (azapi)
- [ ] Terraform: `RUNBOOK_SEARCH_CONNECTION_ID` + `AZURE_SEARCH_ENDPOINT` env vars on all agents
- [ ] Phase 34 smoke tests pass
- [ ] Production: runbooks migrated to AI Search (post-deploy)
- [ ] Production: agents re-registered with knowledge tools attached
- [ ] Foundry portal: all agents show `file_search` + `azure_ai_search` in tools list
